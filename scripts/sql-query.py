#!/usr/bin/env python3
"""Run read-only SQL against registered databases without exposing credentials.

Targets live in local/databases.json (ignored; format in
config/databases.example.json). Each target names a credential profile and
variable holding a connection URL for a read-only role, plus the expected host,
port and database so a stored URL cannot silently point somewhere else.
The URL is read from the owner-only profile file, never from arguments, and is
passed to psql through libpq environment variables so it never appears in a
process listing or in output.

Every query runs in one psql session that first checks the role (it must not be
a superuser or own, create or write anything) and runs the SQL only if the check
passes, inside a read-only transaction. The database role's grants are the real
boundary: the client-side SQL rules only stop mistakes, since anything that can
read the credential file can connect without this tool. Writes and migrations
are out of scope; use the project's runbook.
"""
import argparse
import base64
import contextlib
import fcntl
import getpass
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / 'local/databases.json'
EXAMPLE_REGISTRY = ROOT / 'config/databases.example.json'
TARGET_NAME = re.compile(r'^[a-z][a-z0-9-]*$')
IDENTIFIER = re.compile(r'^[a-z_][a-z0-9_]*$')
RELATION = re.compile(r'^(?:[a-z_][a-z0-9_]*\.)?[a-z_][a-z0-9_]*$')  # table or schema.table
# Full routine identity as regprocedure prints it with search_path pinned to pg_catalog,
# e.g. public.digest(text,text). Overloads must each be listed.
ROUTINE = re.compile(r'^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*\([a-z0-9_ ,.\[\]]*\)$')
DATABASE_NAME = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.-]*$')
GUARD_MARK = 'AGENTS_SQL_GUARD '
LOOPBACK = {'127.0.0.1', 'localhost', '::1'}
# Railway's public TCP proxy serves a self-signed certificate, so `require`
# (encrypted, unauthenticated) is the default; verify-ca/verify-full need a
# pinned sslrootcert. Weaker modes are allowed only for loopback test databases.
STRONG_SSL_MODES = {'require', 'verify-ca', 'verify-full'}
SESSION_OPTIONS = '-c default_transaction_read_only=on -c statement_timeout=30s -c idle_in_transaction_session_timeout=60s'
# Built-in routines with effects a read-only transaction and rollback cannot undo.
SIDE_EFFECT_ROUTINES = ('pg_logical_emit_message',)
# Statement types a query may start with; everything else (transaction
# control, SET, DO, CALL, LOCK, PREPARE TRANSACTION...) is rejected.
READ_STATEMENTS = {'select', 'with', 'table', 'values', 'show', 'explain'}
# schema.name(argument types), always schema-qualified even for pg_catalog routines.
ROUTINE_IDENTITY = r"(n.nspname||'.'||p.proname||substring(p.oid::regprocedure::text from '\(.*\)$'))"
# Session temp schemas are exactly pg_temp_N / pg_toast_temp_N ('_' is a LIKE
# wildcard, so a LIKE filter would also skip persistent schemas such as pgxtemp_x).
# One row of named fields; guard_script() joins them into the AGENTS_SQL_GUARD line.
# Checks use effective privileges (direct, PUBLIC and inherited), so a grant at
# table, column, sequence, server or large-object level is caught. Ownership
# comes from pg_shdepend, which records owners of every object type.
GUARD_SQL = rf"""
SELECT (r.rolsuper OR r.rolcreaterole OR r.rolcreatedb OR r.rolbypassrls OR r.rolreplication)::text AS elevated,
  EXISTS(SELECT 1 FROM pg_shdepend d WHERE d.refclassid='pg_authid'::regclass
    AND d.refobjid=r.oid AND d.deptype='o')::text AS owns,
  (EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    -- Every persistent schema, catalogs included: system catalogs are writable tables.
    -- pg_settings is exempt: PostgreSQL grants PUBLIC UPDATE on it by default, and its
    -- update rule only calls set_config() for the current session, like SET.
    WHERE n.nspname !~ '^pg_(toast_)?temp_[0-9]+$'
      AND c.oid <> 'pg_catalog.pg_settings'::regclass
      AND ((c.relkind IN ('r','p','v','m','f')
          AND (has_table_privilege(current_user, c.oid, 'INSERT, UPDATE, DELETE, TRUNCATE, TRIGGER')
            OR has_any_column_privilege(current_user, c.oid, 'INSERT, UPDATE')))
        OR (c.relkind='S' AND has_sequence_privilege(current_user, c.oid, 'USAGE, UPDATE'))))
   OR EXISTS(SELECT 1 FROM pg_foreign_server s WHERE has_server_privilege(current_user, s.oid, 'USAGE'))
   -- Large objects cannot be withheld individually, so any SELECT or UPDATE grant fails.
   OR EXISTS(SELECT 1 FROM pg_largeobject_metadata l, aclexplode(l.lomacl) a
     WHERE a.grantee IN (r.oid, 0) AND a.privilege_type IN ('SELECT', 'UPDATE'))
   OR current_setting('lo_compat_privileges')='on')::text AS writes,
  (has_database_privilege(current_user, current_database(), 'CREATE')
    OR EXISTS(SELECT 1 FROM pg_namespace n
      WHERE n.nspname !~ '^pg_(toast_)?temp_[0-9]+$'
      AND has_schema_privilege(current_user, n.oid, 'CREATE'))
    OR EXISTS(SELECT 1 FROM pg_foreign_data_wrapper w
      WHERE has_foreign_data_wrapper_privilege(current_user, w.oid, 'USAGE')))::text AS creates,
  coalesce((SELECT string_agg(g.rolname, ',' ORDER BY g.rolname) FROM pg_auth_members m
    JOIN pg_roles g ON g.oid=m.roleid WHERE m.member=r.oid), '') AS memberships,
  -- Grant options, plus default ACLs (any creator, any schema or global) that would
  -- give this role or PUBLIC privileges on future objects.
  (EXISTS(SELECT 1 FROM pg_default_acl d, aclexplode(d.defaclacl) a WHERE a.grantee IN (r.oid, 0))
   OR EXISTS(SELECT 1 FROM (
      SELECT relacl AS acl FROM pg_class UNION ALL SELECT attacl FROM pg_attribute
      UNION ALL SELECT nspacl FROM pg_namespace UNION ALL SELECT proacl FROM pg_proc
      UNION ALL SELECT typacl FROM pg_type UNION ALL SELECT lomacl FROM pg_largeobject_metadata
      UNION ALL SELECT srvacl FROM pg_foreign_server UNION ALL SELECT lanacl FROM pg_language
      UNION ALL SELECT datacl FROM pg_database WHERE datname=current_database()
    ) acls, aclexplode(acls.acl) a WHERE a.grantee=r.oid AND a.is_grantable))::text AS grantable,
  coalesce((SELECT string_agg(name, ',') FROM (SELECT {ROUTINE_IDENTITY} AS name
    FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang
    WHERE (p.prosecdef OR (n.nspname='pg_catalog' AND p.proname = ANY(ARRAY{list(SIDE_EFFECT_ROUTINES)!r}))
        OR (NOT l.lanpltrusted AND l.lanname NOT IN ('c', 'internal'))
        -- Built-ins PostgreSQL restricts by default (pg_read_file, pg_ls_dir, ...) carry an ACL.
        OR (n.nspname='pg_catalog' AND p.proacl IS NOT NULL)
        -- Compiled extension routines (dblink_exec, aliases of restricted built-ins) can act
        -- outside the transaction; only a target's explicit allowed_routines may pass.
        -- OIDs from 16384 (FirstNormalObjectId) were created after initdb, so a compiled
        -- routine there is never a core built-in, whatever its schema or extension.
        OR (l.lanname IN ('c', 'internal') AND (n.nspname<>'pg_catalog' OR p.oid >= 16384)
          AND NOT ({ROUTINE_IDENTITY} = ANY(__ALLOWED_ROUTINES__::text[]))))
      AND has_function_privilege(current_user, p.oid, 'EXECUTE')
    ORDER BY 1 LIMIT 5) routines), '') AS routines,
  -- Roles are cluster-wide and PUBLIC may connect to every database by default; the
  -- other databases' grants are not audited here, so each must be listed by the target.
  coalesce((SELECT string_agg(d.datname, ',' ORDER BY d.datname) FROM pg_database d
    WHERE d.datname<>current_database() AND d.datallowconn
      AND has_database_privilege(current_user, d.oid, 'CONNECT')
      AND NOT (d.datname = ANY(__OTHER_DATABASES__::text[]))), '') AS other_databases,
  current_user AS usr, current_setting('server_version') AS version
FROM pg_roles r WHERE r.rolname=current_user
"""
# Version-specific privileges that older servers cannot even parse.
MAINTAIN_SQL = """SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname !~ '^pg_(toast_)?temp_[0-9]+$' AND c.relkind IN ('r','p','m')
    AND has_table_privilege(current_user, c.oid, 'MAINTAIN'))::text"""
PARAMETER_SQL = """SELECT EXISTS(SELECT 1 FROM pg_parameter_acl p, aclexplode(p.paracl) a
  WHERE a.grantee IN ((SELECT oid FROM pg_roles WHERE rolname=current_user), 0))::text"""


class SqlError(Exception):
    pass


def _hosting():
    spec = importlib.util.spec_from_file_location('hosting', ROOT / 'scripts/hosting.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_targets(path=None):
    path = REGISTRY if path is None else path
    if not Path(path).exists():
        raise SqlError('No database targets are registered on this machine; copy config/databases.example.json '
                       'to local/databases.json and fill in the targets (docs/runbooks/databases.md)')
    if Path(path).resolve() != EXAMPLE_REGISTRY.resolve():
        info = Path(path).stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise SqlError(f'Target registry must be owned by you and mode 600 (chmod 600 {path})')
    try:
        data = json.loads(Path(path).read_text())
        if data.get('schema_version') != 1 or not isinstance(data.get('targets'), dict):
            raise ValueError()
        for name, target in data['targets'].items():
            if (not TARGET_NAME.fullmatch(name) or not isinstance(target, dict)
                    or not {'description', 'profile', 'variable', 'host', 'port', 'database'} <= set(target)
                    or not all(isinstance(target[k], str) and target[k] for k in ('description', 'host', 'database'))
                    or not isinstance(target['profile'], str) or not isinstance(target['variable'], str)
                    or not re.fullmatch(r'[a-z][a-z0-9_-]*\.[a-z][a-z0-9_-]*', target['profile'])
                    or not re.fullmatch(r'[A-Z][A-Z0-9_]*', target['variable'])
                    or not isinstance(target['port'], int) or not 1 <= target['port'] <= 65535):
                raise ValueError()
            for key, pattern in (('allowed_routines', ROUTINE), ('other_databases', DATABASE_NAME)):
                values = target.get(key, [])
                if not isinstance(values, list) or not all(isinstance(v, str) and pattern.fullmatch(v) for v in values):
                    raise ValueError()
            withheld = target.get('withheld', {})
            if not isinstance(withheld, dict) or not all(
                    isinstance(t, str) and RELATION.fullmatch(t) and (cols == '*' or (isinstance(cols, list) and cols
                                                               and all(isinstance(c, str) and IDENTIFIER.fullmatch(c) for c in cols)))
                    for t, cols in withheld.items()):
                raise ValueError()
    except (OSError, ValueError, TypeError, KeyError):
        raise SqlError(f'Database target registry is malformed; inspect {path}') from None
    return data['targets']


def target(name, targets=None):
    targets = load_targets() if targets is None else targets
    if name not in targets:
        raise SqlError(f'Unknown database target {name!r}; run `agents-sql targets`')
    return targets[name]


def check_profile(entry, hosting):
    """Credentials may only come from (and be written to) a declared postgres profile variable."""
    try:
        profiles = hosting.credential_profiles()
    except hosting.HostingError as error:
        raise SqlError(str(error)) from None
    profile = profiles.get(entry['profile'])
    if (not profile or profile.get('provider') != 'postgres'
            or entry['variable'] not in (profile.get('variables') or [])):
        raise SqlError(f"Target credential must be a variable declared by a postgres.* profile in config/profiles.json "
                       f"(got {entry['profile']} / {entry['variable']})")


def connection_url(entry, hosting=None):
    hosting = hosting or _hosting()
    check_profile(entry, hosting)
    try:
        env = hosting.profile_environment(entry['profile'], base={}, variables=[entry['variable']])
    except hosting.HostingError as error:
        raise SqlError(str(error)) from None
    url = env.get(entry['variable'])
    if not url:
        raise SqlError(
            f"No read-only credential is stored for this target ({entry['variable']} in profile {entry['profile']}). "
            'Ask the owner to create the read-only role and store it with `agents-sql set-url TARGET`; '
            'see docs/runbooks/databases.md.')
    return url


def libpq_environment(url, entry):
    """Split a URL into libpq variables, validating it matches the registered target."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ('postgres', 'postgresql'):
        raise SqlError('Stored connection is not a PostgreSQL URL')
    try:
        port = parts.port or 5432
    except ValueError:
        raise SqlError('Stored connection has an invalid port') from None
    database = urllib.parse.unquote(parts.path.lstrip('/'))
    if (parts.hostname, port, database) != (entry['host'], entry['port'], entry['database']):
        raise SqlError('Stored connection does not match the registered host, port and database for this target')
    if not parts.username or parts.password is None:
        raise SqlError('Stored connection must include the read-only role name and password')
    query = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
    if set(query) - {'sslmode', 'sslrootcert'} or any(len(v) != 1 for v in query.values()):
        raise SqlError('Only sslmode and sslrootcert options are allowed in the stored connection')
    sslmode = query.get('sslmode', ['prefer' if parts.hostname in LOOPBACK else 'require'])[0]
    if parts.hostname not in LOOPBACK and sslmode not in STRONG_SSL_MODES:
        raise SqlError('Deployed databases require sslmode=require, verify-ca or verify-full')
    rootcert = query.get('sslrootcert', [None])[0]
    if sslmode in ('verify-ca', 'verify-full') and not (rootcert and Path(rootcert).expanduser().is_file()):
        raise SqlError(f'sslmode={sslmode} needs sslrootcert pointing to the pinned root certificate file')
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TERM') if k in os.environ}
    env.update(
        PGHOST=parts.hostname, PGPORT=str(port), PGDATABASE=database,
        PGUSER=urllib.parse.unquote(parts.username), PGPASSWORD=urllib.parse.unquote(parts.password),
        PGAPPNAME='agents-sql', PGCONNECT_TIMEOUT='10', PGOPTIONS=SESSION_OPTIONS,
    )
    env['PGSSLMODE'] = sslmode
    if rootcert:
        env['PGSSLROOTCERT'] = str(Path(rootcert).expanduser())
    return env


def psql_binary():
    found = shutil.which('psql')
    if not found:
        raise SqlError('psql is not installed or not on PATH')
    return found


def run_session(env, script, args=(), capture_stdout=True, timeout=120):
    """Run one psql session reading the script on stdin. On timeout psql gets
    SIGINT, which makes it send a cancel request so the server stops the
    statement (a query can raise its own statement_timeout with set_config, so
    only this cancel bounds it); it is killed only if it does not exit."""
    process = subprocess.Popen([psql_binary(), '-X', '-v', 'ON_ERROR_STOP=1', '-P', 'pager=off', '-q', *args, '-f', '-'],
                               env=env, text=True, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                               stdout=subprocess.PIPE if capture_stdout else None)
    try:
        stdout, stderr = process.communicate(script, timeout=timeout)
    except subprocess.TimeoutExpired:
        process.send_signal(signal.SIGINT)
        try:
            process.communicate(timeout=10)
            cancelled = 'psql cancelled the statement on the server'
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            cancelled = 'psql did not exit after a cancel request and was killed'
        raise SqlError(f'Query timed out after {timeout}s; {cancelled}') from None
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


def withheld_sql(withheld):
    """One row 'readable|missing'. readable: withheld relations/columns the role can
    still read, directly, through inheritance or partition descendants, or through a
    view or materialized view built on them (views run with their owner's privileges
    unless security_invoker). missing: withheld entries that do not exist, which
    fail closed so a typo or rename cannot silently disable protection. Relations
    default to schema public. Identifiers are pre-validated by load_targets."""
    rows = []
    for relation, columns in sorted(withheld.items()):
        schema, _, table = relation.rpartition('.')
        for column in (columns if isinstance(columns, list) else [None]):
            rows.append(f"('{schema or 'public'}', '{table}', {'NULL' if column is None else repr(column)}::text)")
    if not rows:
        return ''
    return f"""
WITH RECURSIVE secrets(sch, tbl, col) AS (VALUES {', '.join(rows)}),
base AS (
  SELECT s.sch, s.tbl, s.col, c.oid AS relid FROM secrets s
    LEFT JOIN pg_namespace n ON n.nspname=s.sch
    LEFT JOIN pg_class c ON c.relnamespace=n.oid AND c.relname=s.tbl
),
missing AS (
  SELECT b.sch||'.'||b.tbl||coalesce('.'||b.col, '') AS name FROM base b
  WHERE b.relid IS NULL OR (b.col IS NOT NULL AND NOT EXISTS(SELECT 1 FROM pg_attribute a
    WHERE a.attrelid=b.relid AND a.attname=b.col AND NOT a.attisdropped))
),
-- Descendants have their own grants; ancestors return a child's rows when queried.
down AS (
  SELECT b.col, b.relid FROM base b WHERE b.relid IS NOT NULL
  UNION SELECT t.col, i.inhrelid FROM down t JOIN pg_inherits i ON i.inhparent=t.relid
),
up AS (
  SELECT b.col, b.relid FROM base b WHERE b.relid IS NOT NULL
  UNION SELECT t.col, i.inhparent FROM up t JOIN pg_inherits i ON i.inhrelid=t.relid
),
inherited AS (SELECT col, relid FROM down UNION SELECT col, relid FROM up),
-- Generated columns computed from a withheld column carry its value.
tree AS (
  SELECT col, relid FROM inherited
  UNION SELECT g.attname::text, t.relid FROM inherited t
    JOIN pg_attribute src ON src.attrelid=t.relid AND src.attname=t.col
    JOIN pg_depend d ON d.classid='pg_attrdef'::regclass
      AND d.refclassid='pg_class'::regclass AND d.refobjid=t.relid AND d.refobjsubid=src.attnum
    JOIN pg_attrdef ad ON ad.oid=d.objid AND ad.adrelid=t.relid
    JOIN pg_attribute g ON g.attrelid=t.relid AND g.attnum=ad.adnum AND g.attgenerated<>''
),
readable AS (
  SELECT t.relid::regclass::text || coalesce('.'||t.col, '') AS name FROM tree t
  WHERE CASE WHEN t.col IS NULL THEN has_any_column_privilege(current_user, t.relid, 'SELECT')
    WHEN NOT EXISTS(SELECT 1 FROM pg_attribute a WHERE a.attrelid=t.relid AND a.attname=t.col AND NOT a.attisdropped) THEN false
    ELSE has_column_privilege(current_user, t.relid, t.col, 'SELECT') END
),
views(relid) AS (
  SELECT r.ev_class FROM tree t
    JOIN pg_depend d ON d.refclassid='pg_class'::regclass AND d.refobjid=t.relid
      -- refobjsubid 0 is a whole-row reference (SELECT u FROM users u), which exposes every column.
      AND (t.col IS NULL OR d.refobjsubid IN (0, (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid=t.relid AND a.attname=t.col)))
    JOIN pg_rewrite r ON d.classid='pg_rewrite'::regclass AND d.objid=r.oid
  WHERE r.ev_class<>t.relid
  UNION SELECT r.ev_class FROM views v
    JOIN pg_depend d ON d.refclassid='pg_class'::regclass AND d.refobjid=v.relid
    JOIN pg_rewrite r ON d.classid='pg_rewrite'::regclass AND d.objid=r.oid
  WHERE r.ev_class<>v.relid
),
exposed AS (
  SELECT DISTINCT c.oid::regclass::text || ' (view)' AS name FROM views v JOIN pg_class c ON c.oid=v.relid
  WHERE has_any_column_privilege(current_user, c.oid, 'SELECT')
    AND NOT (c.relkind='v' AND coalesce(array_to_string(c.reloptions, ',') ~* 'security_invoker=(true|on|yes|1)', false))
)
SELECT concat_ws(',', (SELECT string_agg(name, ',' ORDER BY name) FROM readable),
    (SELECT string_agg(name, ',' ORDER BY name) FROM exposed))
  || '|' || coalesce((SELECT string_agg(name, ',' ORDER BY name) FROM missing), '')"""


def _sql_array(values):
    """Text array literal of values pre-validated by load_targets (no quotes)."""
    return 'ARRAY[' + ', '.join(f"'{v}'" for v in values) + ']'


def guard_script(entry):
    """psql commands that verify the role and set :agents_sql_safe to on or off.
    Verification runs with search_path pinned to pg_catalog, so a role-level
    search_path cannot shadow catalog relations, functions or operators. The
    result goes to stderr as one AGENTS_SQL_GUARD line for guard_result()."""
    withheld = withheld_sql(entry.get('withheld') or {}) or "SELECT '|'"
    guard_sql = (GUARD_SQL.replace('__ALLOWED_ROUTINES__', _sql_array(entry.get('allowed_routines', [])))
                 .replace('__OTHER_DATABASES__', _sql_array(entry.get('other_databases', []))))
    return f"""SET search_path TO pg_catalog, pg_temp;
SELECT CASE WHEN current_setting('server_version_num')::int >= 170000 THEN 'on' ELSE 'off' END AS agents_sql_pg17,
  CASE WHEN current_setting('server_version_num')::int >= 150000 THEN 'on' ELSE 'off' END AS agents_sql_pg15 \\gset
\\if :agents_sql_pg17
{MAINTAIN_SQL} AS agents_sql_maintain \\gset
\\else
SELECT 'false' AS agents_sql_maintain \\gset
\\endif
\\if :agents_sql_pg15
{PARAMETER_SQL} AS agents_sql_parameter \\gset
\\else
SELECT 'false' AS agents_sql_parameter \\gset
\\endif
{withheld} AS agents_sql_withheld \\gset
WITH g AS ({guard_sql})
SELECT CASE WHEN g.elevated='false' AND g.owns='false' AND g.writes='false' AND g.creates='false'
    AND g.memberships='' AND g.grantable='false' AND g.routines='' AND g.other_databases=''
    AND :'agents_sql_maintain'='false' AND :'agents_sql_parameter'='false' AND :'agents_sql_withheld'='|'
    THEN 'on' ELSE 'off' END AS agents_sql_safe FROM g \\gset
WITH g AS ({guard_sql})
SELECT concat_ws('|', :'agents_sql_safe', g.elevated, g.owns, g.writes, g.creates, g.memberships, g.grantable,
    g.routines, g.other_databases, :'agents_sql_maintain', :'agents_sql_parameter', :'agents_sql_withheld',
    g.usr, g.version) AS agents_sql_guard FROM g \\gset
\\warn {GUARD_MARK}:agents_sql_guard
"""


def guard_result(stderr):
    """Parse the AGENTS_SQL_GUARD line. Returns (verified, problems, other stderr)."""
    lines = (stderr or '').splitlines()
    marks = [line[len(GUARD_MARK):] for line in lines if line.startswith(GUARD_MARK)]
    # Line numbers refer to the generated script, not the agent's SQL.
    rest = '\n'.join(re.sub(r'^psql:<stdin>:\d+: ', '', line) for line in lines if not line.startswith(GUARD_MARK))
    if len(marks) != 1:
        raise SqlError('Could not connect or verify the role: ' + rest.strip()[:500])
    fields = marks[0].split('|')
    if len(fields) != 15:
        raise SqlError('Unexpected role verification result')
    (safe, elevated, owns, writes, creates, memberships, grantable, routines, others,
     maintain, parameter, exposed, missing, user, version) = fields
    problems = [label for label, flag in (
        ('has elevated role attributes', elevated), ('owns database objects', owns),
        ('can write to tables, columns, sequences, foreign servers or large objects', writes),
        ('can create objects or foreign servers', creates),
        ('holds grant options or default privileges on future objects', grantable),
        ('has MAINTAIN on tables', maintain), ('has configuration parameter privileges', parameter)) if flag != 'false']
    # Any membership can confer reads or writes beyond the audited grants
    # (pg_read_all_data reads every secret column), so none are allowed.
    if memberships:
        problems.append('is a member of other roles (' + memberships.replace(',', ', ') + ')')
    if routines:
        problems.append('can execute restricted built-in, SECURITY DEFINER, WAL-writing, untrusted-language or '
                        'unlisted compiled extension routines (' + routines
                        + '); revoke their EXECUTE from PUBLIC and this role')
    if others:
        problems.append('can connect to other databases whose grants are not audited (' + others
                        + '); revoke CONNECT on them from PUBLIC, or list audited ones in the target\'s other_databases')
    if exposed:
        problems.append('can read withheld secrets (' + exposed + ')')
    if missing:
        problems.append('has withheld entries that do not exist (' + missing + '); update the target in local/databases.json')
    if (safe == 'on') == bool(problems):
        raise SqlError('Role verification was inconsistent; treat the role as unverified and report this bug')
    return {'user': user, 'server_version': version}, problems, rest


def refusal(verified, problems):
    return SqlError(f"Refusing to run: role {verified['user']!r} " + '; '.join(problems)
                    + '. Store a dedicated read-only role instead (docs/runbooks/databases.md).')


def guard(env, entry):
    """Refuse any role able to write, own or create objects, reach unaudited
    databases, or read withheld secrets."""
    result = run_session(env, guard_script(entry))
    verified, problems, _ = guard_result(result.stderr)
    if problems:
        raise refusal(verified, problems)
    return verified


def summary(name, entry, verified):
    return (f"target={name} host={entry['host']} port={entry['port']} database={entry['database']} "
            f"role={verified['user']} server={verified['server_version']} read_only=verified")


def command_targets(args):
    hosting = _hosting()
    for name, entry in load_targets().items():
        try:
            connection_url(entry, hosting)
            stored = 'stored'
        except SqlError:
            stored = 'missing'
        print(f"{name}\t{entry['host']}:{entry['port']}/{entry['database']}\tcredential={stored}\t{entry['description']}")
    return 0


def command_check(args):
    entry = target(args.target)
    env = libpq_environment(connection_url(entry), entry)
    print(summary(args.target, entry, guard(env, entry)))
    return 0


def statement_count(text):
    """Count statements in backslash-free SQL, skipping quotes, dollar quotes and
    comments the way psql's lexer does. Unterminated constructs are rejected."""
    i, n, count, has_content = 0, len(text), 0, False
    while i < n:
        ch = text[i]
        if ch in "'\"":
            close = text.find(ch, i + 1)
            while close != -1 and close + 1 < n and text[close + 1] == ch:
                close = text.find(ch, close + 2)
            if close == -1:
                raise SqlError('SQL has an unterminated quote')
            i, has_content = close + 1, True
        elif ch == '$' and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] in '_$')) \
                and (tag := re.match(r'\$([A-Za-z_][A-Za-z0-9_]*)?\$', text[i:])):
            close = text.find(tag.group(0), i + len(tag.group(0)))
            if close == -1:
                raise SqlError('SQL has an unterminated dollar quote')
            i, has_content = close + len(tag.group(0)), True
        elif text.startswith('--', i):
            newline = text.find('\n', i)
            i = n if newline == -1 else newline + 1
        elif text.startswith('/*', i):
            depth, i = 1, i + 2
            while depth and i < n:
                if text.startswith('/*', i):
                    depth, i = depth + 1, i + 2
                elif text.startswith('*/', i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            if depth:
                raise SqlError('SQL has an unterminated comment')
        elif ch == ';':
            count += has_content
            has_content, i = False, i + 1
        else:
            has_content = has_content or not ch.isspace()
            i += 1
    return count + has_content


def first_keyword(text):
    """First word of backslash-free SQL after leading whitespace, comments and '('."""
    i, n = 0, len(text)
    while i < n:
        if text[i].isspace() or text[i] == '(':
            i += 1
        elif text.startswith('--', i):
            newline = text.find('\n', i)
            i = n if newline == -1 else newline + 1
        elif text.startswith('/*', i):
            depth, i = 1, i + 2
            while depth and i < n:
                if text.startswith('/*', i):
                    depth, i = depth + 1, i + 2
                elif text.startswith('*/', i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
        else:
            match = re.match(r'[A-Za-z]+', text[i:])
            return match.group(0).lower() if match else ''
    return ''


def wrapped_sql(text):
    """Run exactly one statement inside a READ ONLY transaction that has already
    taken a snapshot: PostgreSQL then refuses to switch it to read-write, and the
    single statement cannot start another transaction. Writes, nextval, large
    object creation and DDL fail regardless of the role's grants."""
    if statement_count(text) != 1:
        raise SqlError('Provide exactly one SQL statement per query')
    if first_keyword(text) not in READ_STATEMENTS:
        raise SqlError('Only ' + ', '.join(sorted(k.upper() for k in READ_STATEMENTS)) + ' statements are allowed')
    # Unqualified names resolve in public only, never a schema another role controls.
    return ('SET search_path TO public;\n'
            'BEGIN TRANSACTION READ ONLY;\n'
            'SELECT 1 AS agents_sql_snapshot \\gset\n'
            + text.strip() + '\n;\nROLLBACK;\n')


def checked_sql(text):
    """psql meta-commands (\\!, \\o |cmd, \\copy ... program, \\i) all start with a
    backslash and can run local programs that inherit the password, so no SQL
    containing a backslash is passed to psql. Use chr(92) for a literal backslash."""
    if '\\' in text:
        raise SqlError('SQL may not contain backslashes: psql meta-commands are disabled. '
                       'Use chr(92) for a literal backslash.')
    if not text.strip():
        raise SqlError('No SQL was provided')
    # PostgreSQL ends a -- comment at CR as well as LF; normalize so the scanner
    # and psql see the same lines.
    return text.replace('\r\n', '\n').replace('\r', '\n')


def command_query(args):
    entry = target(args.target)
    if args.command is not None:
        sql_text = args.command
    elif args.file:
        try:
            sql_text = Path(args.file).expanduser().read_text()
        except OSError as error:
            raise SqlError(f'Could not read SQL file: {error.strerror}') from None
    else:
        if sys.stdin.isatty():
            raise SqlError('Provide SQL with -c, -f, or on stdin')
        sql_text = sys.stdin.read()
    sql_text = wrapped_sql(checked_sql(sql_text))
    env = libpq_environment(connection_url(entry), entry)
    # One session: the SQL runs only if the role check in the same connection passed.
    script = guard_script(entry) + '\\if :agents_sql_safe\n' + sql_text + '\\endif\n'
    result = run_session(env, script, ['--csv'] if args.csv else [], capture_stdout=False, timeout=args.timeout)
    verified, problems, rest = guard_result(result.stderr)
    if problems:
        raise refusal(verified, problems)
    print('-- ' + summary(args.target, entry, verified), file=sys.stderr)
    if rest.strip():
        print(rest, file=sys.stderr)
    return result.returncode


def _private_parent(path):
    """Create a missing parent directory as mode 700; leave an existing one as it is
    (a profile such as ~/.secrets.sh lives in a directory other programs own)."""
    try:
        path.parent.mkdir(parents=True, mode=0o700)
    except FileExistsError:
        return
    os.chmod(path.parent, 0o700)  # mkdir's mode is masked by the umask


@contextlib.contextmanager
def profile_lock(path):
    """Exclusive lock for an owner-only credential file and files written with it."""
    path = Path(path).expanduser()
    _private_parent(path)
    lock_fd = os.open(path.parent / f'.{path.name}.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield path
    finally:
        os.close(lock_fd)


def write_profile_value(path, variable, value):
    """Atomically replace one literal assignment in an owner-only dotenv file,
    holding an exclusive lock so concurrent writers cannot lose an update."""
    with profile_lock(path) as locked:
        _replace_assignment(locked, variable, value)


def _replace_assignment(path, variable, value):
    lines = []
    if path.exists():
        info = path.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise SqlError(f'Credential file must be owned by you and mode 600: {path}')
        lines = [line for line in path.read_text().splitlines()
                 if not re.match(rf'^(?:export\s+)?{re.escape(variable)}=', line.strip())]
    # Mirror hosting.profile_environment, which refuses these even inside quotes.
    if any(c in value for c in ("'", '\n', '\r', '`', '$(', '${')):
        raise SqlError("Connection value contains characters the credential file cannot hold (' ` $( ${ or a newline); "
                       'use a password without them')
    lines.append(f"{variable}='{value}'")
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write('\n'.join(lines) + '\n')
        os.replace(temp, path)
    except BaseException:
        if os.path.exists(temp):
            os.unlink(temp)
        raise


def command_set_url(args):
    entry = target(args.target)
    value = (getpass.getpass('Read-only connection URL (input hidden): ') if sys.stdin.isatty()
             else sys.stdin.readline()).strip()
    if not value:
        raise SqlError('No connection URL was provided')
    hosting = _hosting()
    check_profile(entry, hosting)  # never overwrite an unrelated credential
    env = libpq_environment(value, entry)
    verified = guard(env, entry)  # never store a role that can write
    write_profile_value(hosting.resolve_profile(entry['profile']), entry['variable'], value)
    print('Stored. ' + summary(args.target, entry, verified))
    return 0


def scram_verifier(password, salt=None, iterations=4096):
    """SCRAM-SHA-256 verifier PostgreSQL stores for a password (RFC 7677). The owner
    sets the role with it, so the cleartext password never appears in SQL or logs.
    Generated passwords are ASCII alphanumerics, which SASLprep leaves unchanged."""
    salt = salt if salt is not None else os.urandom(16)
    salted = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, iterations)
    client_key = hmac.new(salted, b'Client Key', 'sha256').digest()
    server_key = hmac.new(salted, b'Server Key', 'sha256').digest()
    b64 = lambda data: base64.b64encode(data).decode()
    return f'SCRAM-SHA-256${iterations}:{b64(salt)}${b64(hashlib.sha256(client_key).digest())}:{b64(server_key)}'


def pending_paths(name, entry, hosting):
    credentials = Path(hosting.resolve_profile(entry['profile'])).expanduser()
    return credentials, credentials.parent / f'{name}-readonly-role.sql', credentials.parent / f'{name}-pending.url'


def command_prepare(args):
    """Generate a password and keep its URL pending, so the current credential
    keeps working until the owner applies the new role SQL and `activate` swaps
    it in. The SCRAM verifier is never printed: it goes into an owner-only,
    ready-to-run copy of readonly-role.sql."""
    entry = target(args.target)
    hosting = _hosting()
    check_profile(entry, hosting)
    password = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789') for _ in range(32))
    host = f"[{entry['host']}]" if ':' in entry['host'] else entry['host']
    query = '' if entry['host'] in LOOPBACK else '?sslmode=require'
    url = (f"postgresql://agent_readonly:{password}@{host}:{entry['port']}/"
           f"{urllib.parse.quote(entry['database'])}{query}")
    libpq_environment(url, entry)  # same validation as a stored URL
    credentials, setup, pending = pending_paths(args.target, entry, hosting)
    role_sql = (ROOT / 'skills/database-query/references/readonly-role.sql').read_text()
    # One lock covers both files, so the pending password and the prepared verifier always pair.
    with profile_lock(credentials):
        _write_private(setup, role_sql.replace('REPLACE_WITH_SCRAM_VERIFIER', scram_verifier(password)))
        _write_private(pending, url + '\n')
    print(f'Prepared a new password for {args.target}; the current credential stays active until you activate it.\n'
          f'As a superuser or CREATEROLE role, run the prepared setup (it contains a password verifier; keep it private):\n'
          f'  pbcopy < {setup}   # then paste into the database SQL console, or: psql OWNER_URL -f {setup}\n'
          f'Then run: agents-sql activate {args.target}  (verifies the new role, stores it, deletes both files).')
    return 0


def command_activate(args):
    """Verify the pending URL from `prepare` and make it the stored credential."""
    entry = target(args.target)
    hosting = _hosting()
    check_profile(entry, hosting)
    credentials, setup, pending = pending_paths(args.target, entry, hosting)
    with profile_lock(credentials):
        if not pending.exists():
            raise SqlError(f'No pending credential for {args.target}; run `agents-sql prepare {args.target}` first')
        info = pending.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise SqlError(f'Pending credential must be owned by you and mode 600: {pending}')
        url = pending.read_text().strip()
        try:
            verified = guard(libpq_environment(url, entry), entry)
        except SqlError as error:
            raise SqlError(f'{error} The new password is not active yet; run the prepared role SQL as the owner, '
                           f'then activate again. The current credential is unchanged.') from None
        _replace_assignment(credentials, entry['variable'], url)
        for path in (pending, setup):
            path.unlink(missing_ok=True)
    print('Activated. ' + summary(args.target, entry, verified))
    return 0


def _write_private(path, text):
    _private_parent(path)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write(text)
        os.replace(temp, path)
    except BaseException:
        if os.path.exists(temp):
            os.unlink(temp)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(prog='agents-sql', description='Read-only SQL for registered databases.')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('targets', help='List registered targets and whether a credential is stored')
    check = sub.add_parser('check', help='Connect and verify the stored role is read-only')
    check.add_argument('target')
    query = sub.add_parser('query', help='Run read-only SQL (-c, -f, or stdin)')
    query.add_argument('target')
    group = query.add_mutually_exclusive_group()
    group.add_argument('-c', '--command')
    group.add_argument('-f', '--file')
    query.add_argument('--csv', action='store_true')
    query.add_argument('--timeout', type=int, default=120,
                       help='Seconds before the statement is cancelled on the server (default 120)')
    store = sub.add_parser('set-url', help='Verify and store a read-only connection URL from hidden input/stdin')
    store.add_argument('target')
    prepare = sub.add_parser('prepare', help='Generate a pending password and write the owner role SQL privately')
    prepare.add_argument('target')
    activate = sub.add_parser('activate', help='Verify the pending password from prepare and store it')
    activate.add_argument('target')
    args = parser.parse_args(argv)
    try:
        return {'targets': command_targets, 'check': command_check, 'query': command_query,
                'set-url': command_set_url, 'prepare': command_prepare, 'activate': command_activate}[args.action](args)
    except SqlError as error:
        print(f'agents-sql: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
