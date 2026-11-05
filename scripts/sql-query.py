#!/usr/bin/env python3
"""Run read-only SQL against registered databases without exposing credentials.

Targets live in local/databases.json (ignored; format in
config/databases.example.json). Each target names a credential profile and
variable holding a connection URL for a read-only role, plus the expected host,
port and database so a stored URL cannot silently point somewhere else.
The URL is read from the owner-only profile file, never from arguments, and is
passed to psql through libpq environment variables so it never appears in a
process listing or in output.

Before every query the role is checked: it must not be a superuser or own,
create or write anything. Sessions also default to read-only with a statement
timeout. Writes and migrations are out of scope; use the project's runbook.
"""
import argparse
import getpass
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
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
LOOPBACK = {'127.0.0.1', 'localhost', '::1'}
# Railway's public TCP proxy serves a self-signed certificate, so `require`
# (encrypted, unauthenticated) is the default; verify-ca/verify-full need a
# pinned sslrootcert. Weaker modes are allowed only for loopback test databases.
STRONG_SSL_MODES = {'require', 'verify-ca', 'verify-full'}
SESSION_OPTIONS = '-c default_transaction_read_only=on -c statement_timeout=30s -c idle_in_transaction_session_timeout=60s'
# One row: elevated|owns_objects|can_write|can_create|memberships|current_user|server_version
# Write checks use effective privileges (direct, PUBLIC and inherited; table,
# column and sequence level), not just catalog rows granted to this role.
GUARD_SQL = r"""
SELECT (r.rolsuper OR r.rolcreaterole OR r.rolcreatedb OR r.rolbypassrls OR r.rolreplication)::text,
  EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE c.relowner=r.oid AND n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_temp%' AND n.nspname NOT LIKE 'pg_toast%')::text,
  EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_temp%' AND n.nspname NOT LIKE 'pg_toast%'
      AND ((c.relkind IN ('r','p','v','m','f')
          AND (has_table_privilege(current_user, c.oid, 'INSERT, UPDATE, DELETE, TRUNCATE, TRIGGER')
            OR has_any_column_privilege(current_user, c.oid, 'INSERT, UPDATE')))
        OR (c.relkind='S' AND has_sequence_privilege(current_user, c.oid, 'UPDATE'))))::text,
  (has_database_privilege(current_user, current_database(), 'CREATE')
    OR EXISTS(SELECT 1 FROM pg_namespace n WHERE n.nspname NOT IN ('pg_catalog','information_schema')
      AND n.nspname NOT LIKE 'pg_temp%' AND n.nspname NOT LIKE 'pg_toast%'
      AND has_schema_privilege(current_user, n.oid, 'CREATE')))::text,
  coalesce((SELECT string_agg(g.rolname, ',' ORDER BY g.rolname) FROM pg_auth_members m
    JOIN pg_roles g ON g.oid=m.roleid WHERE m.member=r.oid), ''),
  current_user, current_setting('server_version')
FROM pg_roles r WHERE r.rolname=current_user
"""


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
    try:
        data = json.loads(Path(path).read_text())
        if data.get('schema_version') != 1 or not isinstance(data.get('targets'), dict):
            raise ValueError()
        for name, target in data['targets'].items():
            if (not TARGET_NAME.fullmatch(name) or not isinstance(target, dict)
                    or not {'description', 'profile', 'variable', 'host', 'port', 'database'} <= set(target)
                    or not re.fullmatch(r'[a-z][a-z0-9_-]*\.[a-z][a-z0-9_-]*', target['profile'])
                    or not re.fullmatch(r'[A-Z][A-Z0-9_]*', target['variable'])
                    or not isinstance(target['port'], int) or not 1 <= target['port'] <= 65535):
                raise ValueError()
            withheld = target.get('withheld', {})
            if not isinstance(withheld, dict) or not all(
                    IDENTIFIER.fullmatch(t) and (cols == '*' or (isinstance(cols, list) and cols
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


def run_psql(env, args, capture=True, timeout=120):
    try:
        return subprocess.run([psql_binary(), '-X', '-v', 'ON_ERROR_STOP=1', '-P', 'pager=off', *args],
                              env=env, capture_output=capture, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SqlError('psql timed out') from None


def withheld_sql(withheld):
    """Names of withheld tables/columns the role can still read (identifiers pre-validated).
    CASE branches run in order, so privilege functions never see a missing relation."""
    checks = []
    for table, columns in sorted(withheld.items()):
        rel = f"'public.{table}'"
        if columns == '*':
            checks.append(f"CASE WHEN to_regclass({rel}) IS NULL THEN NULL "
                          f"WHEN has_any_column_privilege(current_user, {rel}, 'SELECT') THEN '{table}' END")
        else:
            for column in columns:
                checks.append(
                    f"CASE WHEN NOT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
                    f"AND table_name='{table}' AND column_name='{column}') THEN NULL "
                    f"WHEN has_column_privilege(current_user, {rel}, '{column}', 'SELECT') THEN '{table}.{column}' END")
    return "SELECT concat_ws(',', " + ', '.join(checks) + ')' if checks else ''


def guard(env, withheld=None):
    """Refuse any role able to write, own or create objects, or read withheld secrets."""
    result = run_psql(env, ['-At', '-F', '|', '-c', GUARD_SQL])
    if result.returncode:
        raise SqlError('Could not connect or verify the role: ' + (result.stderr or result.stdout).strip()[:500])
    fields = result.stdout.strip().split('|')
    if len(fields) != 7:
        raise SqlError('Unexpected role verification result')
    elevated, owns, writes, creates, memberships, user, version = fields
    # Any membership can confer reads or writes beyond the audited grants
    # (pg_read_all_data reads every secret column), so none are allowed.
    unsafe = [m for m in memberships.split(',') if m]
    problems = [label for label, flag in (('has elevated role attributes', elevated), ('owns database objects', owns),
                                          ('can write to tables, columns or sequences', writes), ('can create objects', creates))
                if flag == 'true']
    if unsafe:
        problems.append('is a member of other roles (' + ', '.join(unsafe) + ')')
    if not problems and withheld:
        readable = run_psql(env, ['-At', '-c', withheld_sql(withheld)])
        if readable.returncode:
            raise SqlError('Could not verify withheld columns: ' + (readable.stderr or readable.stdout).strip()[:500])
        if readable.stdout.strip():
            problems.append('can read withheld secrets (' + readable.stdout.strip() + ')')
    if problems:
        raise SqlError(f'Refusing to run: role {user!r} ' + '; '.join(problems)
                       + '. Store a dedicated read-only role instead (docs/runbooks/databases.md).')
    return {'user': user, 'server_version': version}


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
    print(summary(args.target, entry, guard(env, entry.get('withheld'))))
    return 0


def checked_sql(text):
    """psql meta-commands (\\!, \\o |cmd, \\copy ... program, \\i) all start with a
    backslash and can run local programs that inherit the password, so no SQL
    containing a backslash is passed to psql. Use chr(92) for a literal backslash."""
    if '\\' in text:
        raise SqlError('SQL may not contain backslashes: psql meta-commands are disabled. '
                       'Use chr(92) for a literal backslash.')
    if not text.strip():
        raise SqlError('No SQL was provided')
    return text


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
    sql_text = checked_sql(sql_text)
    env = libpq_environment(connection_url(entry), entry)
    verified = guard(env, entry.get('withheld'))
    print('-- ' + summary(args.target, entry, verified), file=sys.stderr)
    psql_args = (['--csv'] if args.csv else []) + ['-f', '-']
    try:
        result = subprocess.run([psql_binary(), '-X', '-v', 'ON_ERROR_STOP=1', '-P', 'pager=off', *psql_args],
                                env=env, input=sql_text, text=True, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        raise SqlError('psql timed out') from None
    return result.returncode


def write_profile_value(path, variable, value):
    """Atomically replace one literal assignment in an owner-only dotenv file."""
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    lines = []
    if path.exists():
        info = path.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise SqlError(f'Credential file must be owned by you and mode 600: {path}')
        lines = [line for line in path.read_text().splitlines()
                 if not re.match(rf'^(?:export\s+)?{re.escape(variable)}=', line.strip())]
    if any(c in value for c in "'\n\r"):
        raise SqlError('Connection value contains unsupported characters')
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
    verified = guard(env, entry.get('withheld'))  # never store a role that can write
    write_profile_value(hosting.resolve_profile(entry['profile']), entry['variable'], value)
    print('Stored. ' + summary(args.target, entry, verified))
    return 0


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
    query.add_argument('--timeout', type=int, default=120, help='Seconds before psql is stopped (default 120)')
    store = sub.add_parser('set-url', help='Verify and store a read-only connection URL from hidden input/stdin')
    store.add_argument('target')
    args = parser.parse_args(argv)
    try:
        return {'targets': command_targets, 'check': command_check, 'query': command_query,
                'set-url': command_set_url}[args.action](args)
    except SqlError as error:
        print(f'agents-sql: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
