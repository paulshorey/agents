#!/usr/bin/env python3
"""Run read-only SQL against registered databases without exposing credentials.

Targets live in local/databases.json (ignored; format in
config/databases.example.json). Each names a credential profile variable and the
expected host, port and database, so a stored URL cannot point somewhere else and
dev and production are always chosen by name.

The database role is the security boundary: `agent_readonly` can only SELECT
(skills/database-query/references/readonly-role.sql). This tool adds guardrails
against mistakes: it keeps the URL out of arguments and output, refuses a stored
URL for a role that is elevated or can write (an owner URL saved by accident), runs
each query in a read-only transaction, and cancels it on the server on timeout.
"""
import argparse
import base64
import contextlib
import fcntl
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
ROLE_SQL = ROOT / 'skills/database-query/references/readonly-role.sql'
TARGET_NAME = re.compile(r'^[a-z][a-z0-9-]*$')
REQUIRED_KEYS = {'description', 'profile', 'variable', 'host', 'port', 'database'}
# An unknown key is usually a typo; refuse it rather than silently ignore it.
TARGET_KEYS = REQUIRED_KEYS | {'docs'}
LOOPBACK = {'127.0.0.1', 'localhost', '::1'}
# Railway's public TCP proxy serves a self-signed certificate, so `require`
# (encrypted, unauthenticated) is the default; verify-ca/verify-full need a
# pinned sslrootcert. Weaker modes are allowed only for loopback test databases.
STRONG_SSL_MODES = {'require', 'verify-ca', 'verify-full'}
SESSION_OPTIONS = '-c default_transaction_read_only=on -c statement_timeout=30s -c idle_in_transaction_session_timeout=60s'
GUARD_MARK = 'AGENTS_SQL_GUARD '
# One psql session: check the role, set :agents_sql_safe, report on stderr.
GUARD_SCRIPT = r"""SET search_path TO pg_catalog, pg_temp;
SELECT g.safe AS agents_sql_safe,
  concat_ws('|', g.safe, g.elevated::text, g.member::text, g.owns::text, g.writes::text, g.creates::text,
    g.usr, g.version) AS agents_sql_guard
FROM (SELECT f.*, CASE WHEN f.elevated OR f.member OR f.owns OR f.writes OR f.creates THEN 'off' ELSE 'on' END AS safe
  FROM (SELECT
    -- Only the dedicated login, which readonly-role.sql grants and withholds for; a
    -- persistent `SET role` would make this check a different role than the login.
    (r.rolsuper OR r.rolcreaterole OR r.rolcreatedb OR r.rolbypassrls OR r.rolreplication
      OR session_user <> current_user OR current_user <> 'agent_readonly') AS elevated,
    -- Membership can confer any privilege (pg_read_all_data, pg_write_all_data, an owner role).
    EXISTS(SELECT 1 FROM pg_auth_members m WHERE m.member = r.oid) AS member,
    EXISTS(SELECT 1 FROM pg_shdepend d WHERE d.refclassid = 'pg_authid'::regclass
      AND d.refobjid = r.oid AND d.deptype = 'o') AS owns,
    EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname !~ '^pg_(toast_)?temp_[0-9]+$'
        AND ((c.relkind IN ('r', 'p', 'v', 'm', 'f')
            AND (has_table_privilege(c.oid, 'INSERT, UPDATE, DELETE, TRUNCATE')
              OR has_any_column_privilege(c.oid, 'INSERT, UPDATE')))
          OR (c.relkind = 'S' AND has_sequence_privilege(c.oid, 'USAGE, UPDATE')))) AS writes,  -- USAGE allows nextval
    (has_database_privilege(current_database(), 'CREATE')
      OR EXISTS(SELECT 1 FROM pg_namespace n WHERE n.nspname !~ '^pg_(toast_)?temp_[0-9]+$'
        AND has_schema_privilege(n.oid, 'CREATE'))) AS creates,
    current_user::text AS usr, current_setting('server_version') AS version
  FROM pg_roles r WHERE r.rolname = current_user) f) g \gset
\warn AGENTS_SQL_GUARD :agents_sql_guard
"""
PROBLEMS = ('is not the dedicated agent_readonly login, or has elevated role attributes',
            'is a member of other roles', 'owns database objects',
            'can write to tables or sequences', 'can create objects')
PASSWORD_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'


class SqlError(Exception):
    pass


def _hosting():
    spec = importlib.util.spec_from_file_location('hosting', ROOT / 'scripts/hosting.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_targets(path=None):
    path = Path(REGISTRY if path is None else path)
    if not path.exists():
        raise SqlError('No database targets are registered on this machine; copy config/databases.example.json '
                       'to local/databases.json and fill in the targets (docs/runbooks/databases.md)')
    if path.resolve() != EXAMPLE_REGISTRY.resolve():
        info = path.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise SqlError(f'Target registry must be owned by you and mode 600 (chmod 600 {path})')
    try:
        data = json.loads(path.read_text())
        if data.get('schema_version') != 1 or not isinstance(data.get('targets'), dict):
            raise ValueError()
        for name, entry in data['targets'].items():
            if (not TARGET_NAME.fullmatch(name) or not isinstance(entry, dict)
                    or not REQUIRED_KEYS <= set(entry) or set(entry) - TARGET_KEYS
                    or not all(isinstance(entry[k], str) and entry[k] for k in REQUIRED_KEYS - {'port'})
                    or not re.fullmatch(r'[a-z][a-z0-9_-]*\.[a-z][a-z0-9_-]*', entry['profile'])
                    or not re.fullmatch(r'[A-Z][A-Z0-9_]*', entry['variable'])
                    or not isinstance(entry['port'], int) or not 1 <= entry['port'] <= 65535):
                raise ValueError()
        # One dotenv variable holds one URL, so two targets cannot share it.
        slots = [(entry['profile'], entry['variable']) for entry in data['targets'].values()]
        if len(slots) != len(set(slots)):
            raise ValueError()
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
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
        raise SqlError(f"No read-only credential is stored for this target ({entry['variable']} in profile "
                       f"{entry['profile']}). Ask the owner to run `agents-sql prepare` and `activate` "
                       '(docs/runbooks/databases.md).')
    return url


def libpq_environment(url, entry):
    """Split a URL into libpq variables, validating it matches the registered target."""
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port or 5432
        host, user, password = parts.hostname, parts.username, parts.password
    except ValueError:
        raise SqlError('Stored connection is not a valid URL') from None
    if parts.scheme not in ('postgres', 'postgresql'):
        raise SqlError('Stored connection is not a PostgreSQL URL')
    database = urllib.parse.unquote(parts.path.lstrip('/'))
    if (host, port, database) != (entry['host'], entry['port'], entry['database']):
        raise SqlError('Stored connection does not match the registered host, port and database for this target')
    if urllib.parse.unquote(user or '') != 'agent_readonly' or password is None:
        raise SqlError('Stored connection must be for the agent_readonly role, with its password')
    query = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
    if set(query) - {'sslmode', 'sslrootcert'} or any(len(v) != 1 for v in query.values()):
        raise SqlError('Only sslmode and sslrootcert options are allowed in the stored connection')
    sslmode = query.get('sslmode', ['prefer' if host in LOOPBACK else 'require'])[0]
    if host not in LOOPBACK and sslmode not in STRONG_SSL_MODES:
        raise SqlError('Deployed databases require sslmode=require, verify-ca or verify-full')
    rootcert = query.get('sslrootcert', [None])[0]
    if sslmode in ('verify-ca', 'verify-full') and not (rootcert and Path(rootcert).expanduser().is_file()):
        raise SqlError(f'sslmode={sslmode} needs sslrootcert pointing to the pinned root certificate file')
    # Start from a clean environment so inherited PG*/DATABASE_URL settings never apply.
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TERM') if k in os.environ}
    env.update(PGHOST=host, PGPORT=str(port), PGDATABASE=database, PGUSER=urllib.parse.unquote(user),
               PGPASSWORD=urllib.parse.unquote(password), PGAPPNAME='agents-sql', PGCONNECT_TIMEOUT='10',
               PGOPTIONS=SESSION_OPTIONS, PGSSLMODE=sslmode)
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
    SIGINT, which sends a cancel request so the server stops the statement (a
    query can raise its own statement_timeout); it is killed only if it hangs."""
    process = subprocess.Popen([psql_binary(), '-X', '-v', 'ON_ERROR_STOP=1', '-P', 'pager=off', '-q', *args, '-f', '-'],
                               env=env, text=True, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                               stdout=subprocess.PIPE if capture_stdout else None)
    try:
        stdout, stderr = process.communicate(script, timeout=timeout)
    except subprocess.TimeoutExpired:
        process.send_signal(signal.SIGINT)
        try:
            process.communicate(timeout=10)
            outcome = 'psql cancelled the statement on the server'
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            outcome = 'psql did not exit after a cancel request and was killed'
        raise SqlError(f'Query timed out after {timeout}s; {outcome}') from None
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


def guard_result(stderr):
    """Parse the AGENTS_SQL_GUARD line. Returns (verified, problems, other stderr)."""
    lines = (stderr or '').splitlines()
    marks = [line[len(GUARD_MARK):] for line in lines if line.startswith(GUARD_MARK)]
    # Line numbers refer to the generated script, not the agent's SQL.
    rest = '\n'.join(re.sub(r'^psql:<stdin>:\d+: ', '', line) for line in lines if not line.startswith(GUARD_MARK))
    if len(marks) != 1:
        raise SqlError('Could not connect or verify the role: ' + rest.strip()[:500])
    fields = marks[0].split('|')
    if len(fields) != 8:
        raise SqlError('Unexpected role verification result')
    safe, flags, user, version = fields[0], fields[1:6], fields[6], fields[7]
    problems = [label for label, flag in zip(PROBLEMS, flags) if flag != 'false']
    if (safe == 'on') == bool(problems):
        raise SqlError('Role verification was inconsistent; treat the role as unverified')
    return {'user': user, 'server_version': version}, problems, rest


def refusal(verified, problems):
    return SqlError(f"Refusing to run: role {verified['user']!r} " + '; '.join(problems)
                    + '. Store the dedicated read-only role instead (docs/runbooks/databases.md).')


def guard(env):
    """Refuse a stored URL whose role is elevated, a member of other roles, or can
    own, write or create anything: that is an owner or app URL saved by mistake."""
    verified, problems, _ = guard_result(run_session(env, GUARD_SCRIPT).stderr)
    if problems:
        raise refusal(verified, problems)
    return verified


def checked_sql(text):
    """The query runs inside a psql script with \\if around it; a backslash
    (psql meta-command such as \\endif or \\!) could step outside that, so none
    are allowed. Use chr(92) for a literal backslash."""
    if '\\' in text:
        raise SqlError('SQL may not contain backslashes (psql meta-commands are disabled); use chr(92) for one.')
    if not text.strip():
        raise SqlError('No SQL was provided')
    return text


def query_script(text):
    """Run the SQL only if the role check in the same session passed, inside a
    READ ONLY transaction that has already taken a snapshot (so it cannot be
    switched to read-write), with unqualified names resolved in public only."""
    return (GUARD_SCRIPT + '\\if :agents_sql_safe\n'
            'SET search_path TO public;\n'
            'BEGIN TRANSACTION READ ONLY;\n'
            'SELECT 1 AS agents_sql_snapshot \\gset\n'
            + checked_sql(text).strip() + '\n;\nROLLBACK;\n\\endif\n')


def summary(name, entry, verified):
    return (f"target={name} host={entry['host']} port={entry['port']} database={entry['database']} "
            f"role={verified['user']} server={verified['server_version']} role_check=passed")


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
    print(summary(args.target, entry, guard(libpq_environment(connection_url(entry), entry))))
    return 0


def command_query(args):
    entry = target(args.target)
    if args.command is not None:
        text = args.command
    elif args.file:
        try:
            text = Path(args.file).expanduser().read_text()
        except OSError as error:
            raise SqlError(f'Could not read SQL file: {error.strerror}') from None
    else:
        if sys.stdin.isatty():
            raise SqlError('Provide SQL with -c, -f, or on stdin')
        text = sys.stdin.read()
    script = query_script(text)
    env = libpq_environment(connection_url(entry), entry)
    # The server-side limit matches --timeout (the role's 30 s is only a default).
    env['PGOPTIONS'] = SESSION_OPTIONS.replace('statement_timeout=30s', f'statement_timeout={args.timeout}s')
    result = run_session(env, script, ['--csv'] if args.csv else [], capture_stdout=False, timeout=args.timeout)
    verified, problems, rest = guard_result(result.stderr)
    if problems:
        raise refusal(verified, problems)
    print('-- ' + summary(args.target, entry, verified), file=sys.stderr)
    if rest.strip():
        print(rest, file=sys.stderr)
    return result.returncode


def _private_parent(path):
    """Create a missing parent as mode 700; leave an existing directory alone."""
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


def _replace_assignment(path, variable, value):
    """Atomically replace one literal assignment in an owner-only dotenv file.
    Callers hold profile_lock."""
    # Mirror hosting.profile_environment, which refuses these even inside quotes.
    if any(c in value for c in ("'", '\n', '\r', '`', '$(', '${')):
        raise SqlError("Connection value contains characters the credential file cannot hold (' ` $( ${ or a newline)")
    lines = []
    if path.exists():
        info = path.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise SqlError(f'Credential file must be owned by you and mode 600: {path}')
        lines = [line for line in path.read_text().splitlines()
                 if not re.match(rf'^(?:export\s+)?{re.escape(variable)}=', line.strip())]
    lines.append(f"{variable}='{value}'")
    _write_private(path, '\n'.join(lines) + '\n')


def write_profile_value(path, variable, value):
    with profile_lock(path) as locked:
        _replace_assignment(locked, variable, value)


def scram_verifier(password, salt=None, iterations=4096):
    """SCRAM-SHA-256 verifier PostgreSQL stores for a password (RFC 7677), so the
    cleartext password never appears in SQL or server logs. Generated passwords
    are ASCII alphanumerics, which SASLprep leaves unchanged."""
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
    """Generate a password, keep its URL pending (the current credential keeps
    working) and write a private, ready-to-run copy of the role SQL containing
    only the password's SCRAM verifier. Nothing secret is printed."""
    entry = target(args.target)
    hosting = _hosting()
    check_profile(entry, hosting)
    password = ''.join(secrets.choice(PASSWORD_CHARS) for _ in range(32))
    host = f"[{entry['host']}]" if ':' in entry['host'] else entry['host']
    credentials, setup, pending = pending_paths(args.target, entry, hosting)
    with profile_lock(credentials):
        query = '' if entry['host'] in LOOPBACK else '?sslmode=require'
        # Keep a pinned server certificate: rotation must not fall back to unauthenticated TLS.
        try:
            current = urllib.parse.parse_qs(urllib.parse.urlsplit(connection_url(entry, hosting)).query)
        except (SqlError, ValueError):
            current = {}
        if current.get('sslmode', [''])[0] in ('verify-ca', 'verify-full') and current.get('sslrootcert'):
            query = '?' + urllib.parse.urlencode({'sslmode': current['sslmode'][0],
                                                  'sslrootcert': current['sslrootcert'][0]})
        url = f"postgresql://agent_readonly:{password}@{host}:{entry['port']}/{urllib.parse.quote(entry['database'])}{query}"
        libpq_environment(url, entry)  # same validation as a stored URL
        _write_private(setup, ROLE_SQL.read_text().replace('REPLACE_WITH_SCRAM_VERIFIER', scram_verifier(password)))
        _write_private(pending, url + '\n')
    print(f'Prepared a new password for {args.target}; any current credential stays active until you activate.\n'
          f'Run the prepared role SQL as a superuser (Railway: the postgres user); it contains a password verifier, '
          f'keep it private:\n'
          f'  pbcopy < {setup}   # then paste into the database SQL console (Railway: Data tab), or\n'
          f"  psql 'host=HOST port=PORT dbname={entry['database']} user=postgres sslmode=require' -f {setup}"
          f'   # prompts for the password\n'
          f'Then run: agents-sql activate {args.target}  (verifies the role, stores it, deletes both files).')
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
            verified = guard(libpq_environment(url, entry))
        except SqlError as error:
            if str(error).startswith('Refusing'):
                raise SqlError(f'{error} The new password works, so the prepared SQL has run, but the role failed '
                               f'the check: fix the reported grants, then activate again. The stored URL was not '
                               f'changed and its old password no longer works.') from None
            raise SqlError(f'{error} If the new password was rejected, run the prepared role SQL as a superuser, '
                           f'then activate again. The stored URL was not changed.') from None
        _replace_assignment(credentials, entry['variable'], url)
        for path in (pending, setup):
            path.unlink(missing_ok=True)
    print('Activated. ' + summary(args.target, entry, verified))
    return 0


def positive_int(value):
    number = int(value)
    if not 1 <= number <= 3600:
        raise argparse.ArgumentTypeError('must be 1-3600 seconds')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(prog='agents-sql', description='Read-only SQL for registered databases.')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('targets', help='List registered targets and whether a credential is stored')
    sub.add_parser('check', help='Connect and verify the stored role is read-only').add_argument('target')
    query = sub.add_parser('query', help='Run read-only SQL (-c, -f, or stdin)')
    query.add_argument('target')
    source = query.add_mutually_exclusive_group()
    source.add_argument('-c', '--command')
    source.add_argument('-f', '--file')
    query.add_argument('--csv', action='store_true')
    query.add_argument('--timeout', type=positive_int, default=120,
                       help='Seconds before the statement is cancelled on the server (default 120)')
    sub.add_parser('prepare', help='Generate a pending password and write the role SQL privately').add_argument('target')
    sub.add_parser('activate', help='Verify the pending password from prepare and store it').add_argument('target')
    args = parser.parse_args(argv)
    commands = {'targets': command_targets, 'check': command_check, 'query': command_query,
                'prepare': command_prepare, 'activate': command_activate}
    try:
        return commands[args.action](args)
    except SqlError as error:
        print(f'agents-sql: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
