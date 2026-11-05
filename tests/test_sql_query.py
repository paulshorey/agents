import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'scripts' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


sql = module('sql-query')
TARGET = {'description': 'Fixture', 'profile': 'postgres.fixture', 'variable': 'FIXTURE_DATABASE_URL',
          'host': 'db.example.test', 'port': 6543, 'database': 'railway'}


def url(host='db.example.test', port=6543, database='railway', user='agent_readonly', secret=None, **query):
    """Build fixture URLs at runtime so no credential-shaped literal is committed."""
    secret = secret if secret is not None else 'x' + os.urandom(6).hex()
    netloc = f'{urllib.parse.quote(user)}:{urllib.parse.quote(secret, safe="")}@{host}:{port}' if user else f'{host}:{port}'
    return urllib.parse.urlunsplit(('postgresql', netloc, '/' + database, urllib.parse.urlencode(query), ''))


class FakeHosting:
    credentials = None

    class HostingError(Exception):
        pass

    profiles = {'postgres.fixture': {'provider': 'postgres', 'path': '~/x', 'variables': ['FIXTURE_DATABASE_URL']},
                'railway.workspace': {'provider': 'railway', 'path': '~/y', 'variables': ['RAILWAY_API_TOKEN']}}

    @classmethod
    def credential_profiles(cls):
        return cls.profiles

    @staticmethod
    def profile_environment(profile, base=None, variables=None):
        return {}

    @classmethod
    def resolve_profile(cls, profile):
        return cls.credentials


class RegistryTests(unittest.TestCase):
    def test_example_registry_is_valid_and_has_no_real_endpoints(self):
        targets = sql.load_targets(sql.EXAMPLE_REGISTRY)
        text = sql.EXAMPLE_REGISTRY.read_text()
        self.assertNotIn('postgresql://', text)
        self.assertNotIn('rlwy.net', text)
        profiles = json.loads((ROOT / 'config/profiles.json').read_text())['profiles']
        for entry in targets.values():
            self.assertTrue(entry['host'].endswith('.invalid'))
            self.assertIn(entry['variable'], profiles[entry['profile']]['variables'])

    def test_missing_local_registry_explains_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(sql.SqlError) as raised:
                sql.load_targets(Path(directory) / 'databases.json')
        self.assertIn('databases.example.json', str(raised.exception))

    def test_rejects_malformed_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'databases.json'
            for targets in [{'Bad Name': TARGET}, {'ok': {**TARGET, 'port': 'x'}},
                            {'ok': {**TARGET, 'withheld': {'users; drop': '*'}}},
                            {'ok': {**TARGET, 'withheld': {'users': ["pass'word"]}}},
                            {'ok': {**TARGET, 'withheld': {'a.b.c': '*'}}},
                            {'ok': {**TARGET, 'withheld': {'Auth.tokens': '*'}}},
                            {'ok': {**TARGET, 'allowed_routines': ['no_schema']}},
                            {'ok': {**TARGET, 'allowed_routines': ['public.digest']}},
                            {'ok': {**TARGET, 'allowed_routines': ["public.x'y"]}},
                            {'ok': {**TARGET, 'profile': '/tmp/creds.env'}}]:
                path.write_text(json.dumps({'schema_version': 1, 'targets': targets}))
                path.chmod(0o600)
                with self.assertRaises(sql.SqlError, msg=targets):
                    sql.load_targets(path)

    def test_rejects_non_string_registry_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'databases.json'
            for bad in [{'host': None}, {'database': 5}, {'description': ''}, {'other_databases': ["x'y"]},
                        {'other_databases': 'postgres'}]:
                path.write_text(json.dumps({'schema_version': 1, 'targets': {'t': {**TARGET, **bad}}}))
                path.chmod(0o600)
                with self.assertRaises(sql.SqlError, msg=bad):
                    sql.load_targets(path)
            path.write_text(json.dumps({'schema_version': 1, 'targets': {'t': {**TARGET, 'other_databases': ['postgres']}}}))
            self.assertIn('t', sql.load_targets(path))

    def test_accepts_schema_qualified_withheld_relations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'databases.json'
            path.write_text(json.dumps({'schema_version': 1, 'targets': {'ok': {**TARGET, 'withheld': {'auth.tokens': '*'}}}}))
            path.chmod(0o600)
            self.assertIn('ok', sql.load_targets(path))
            path.chmod(0o644)
            with self.assertRaises(sql.SqlError):
                sql.load_targets(path)
        self.assertIn("('auth', 'tokens', NULL::text)", sql.withheld_sql({'auth.tokens': '*'}))
        self.assertIn("('public', 'users', 'password'::text)", sql.withheld_sql({'users': ['password']}))
            # routine identities include argument types
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'databases.json'
            path.write_text(json.dumps({'schema_version': 1, 'targets': {'ok': {**TARGET, 'allowed_routines': ['public.digest(text,text)']}}}))
            path.chmod(0o600)
            self.assertIn('ok', sql.load_targets(path))

    def test_unknown_target(self):
        with self.assertRaises(sql.SqlError):
            sql.target('missing', {'fixture': TARGET})


class ConnectionTests(unittest.TestCase):
    def test_builds_libpq_environment_without_inherited_database_settings(self):
        secret = 'p@' + os.urandom(4).hex()
        with patch.dict(os.environ, {'PGHOST': 'evil', 'DATABASE_URL': 'postgres://other', 'PATH': '/bin'}):
            env = sql.libpq_environment(url(secret=secret, sslmode='require'), TARGET)
        self.assertEqual(env['PGHOST'], 'db.example.test')
        self.assertEqual(env['PGPASSWORD'], secret)
        self.assertEqual(env['PGSSLMODE'], 'require')
        self.assertIn('default_transaction_read_only=on', env['PGOPTIONS'])
        self.assertNotIn('DATABASE_URL', env)

    def test_deployed_connections_require_tls(self):
        self.assertEqual(sql.libpq_environment(url(), TARGET)['PGSSLMODE'], 'require')
        for mode in ['disable', 'allow', 'prefer']:
            with self.assertRaises(sql.SqlError, msg=mode):
                sql.libpq_environment(url(sslmode=mode), TARGET)
        with self.assertRaises(sql.SqlError):
            sql.libpq_environment(url(sslmode='verify-full'), TARGET)
        with tempfile.NamedTemporaryFile() as cert:
            env = sql.libpq_environment(url(sslmode='verify-ca', sslrootcert=cert.name), TARGET)
            self.assertEqual((env['PGSSLMODE'], env['PGSSLROOTCERT']), ('verify-ca', cert.name))
        local = {**TARGET, 'host': '127.0.0.1'}
        self.assertEqual(sql.libpq_environment(url(host='127.0.0.1', sslmode='disable'), local)['PGSSLMODE'], 'disable')

    def test_rejects_connections_that_do_not_match_the_target(self):
        for candidate in [url(host='other.test'), url(port=5432), url(database='other'),
                          url().replace('postgresql', 'mysql', 1), url(user=None),
                          url(host='elsewhere'), url() + '&host=elsewhere', url(options='-c x=y')]:
            with self.assertRaises(sql.SqlError, msg=candidate):
                sql.libpq_environment(candidate, TARGET)

    def test_missing_credential_explains_the_owner_step(self):
        with self.assertRaises(sql.SqlError) as raised:
            sql.connection_url(TARGET, FakeHosting)
        self.assertIn('set-url', str(raised.exception))

    def test_credentials_only_come_from_declared_postgres_profile_variables(self):
        for entry in [{**TARGET, 'profile': 'railway.workspace', 'variable': 'RAILWAY_API_TOKEN'},
                      {**TARGET, 'variable': 'OTHER_URL'}, {**TARGET, 'profile': 'postgres.missing'}]:
            with self.assertRaises(sql.SqlError, msg=entry):
                sql.check_profile(entry, FakeHosting)
        sql.check_profile(TARGET, FakeHosting)

    def test_set_url_refuses_an_unrelated_credential_before_connecting_or_writing(self):
        entry = {**TARGET, 'profile': 'railway.workspace', 'variable': 'RAILWAY_API_TOKEN'}
        with patch.object(sql, 'target', return_value=entry), patch.object(sql, '_hosting', return_value=FakeHosting), \
                patch.object(sql, 'guard') as guard, patch.object(sql, 'write_profile_value') as write, \
                patch('sys.stdin', io.StringIO(url() + '\n')), patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(sql.main(['set-url', 'fixture']), 2)
        guard.assert_not_called()
        write.assert_not_called()


class MetaCommandTests(unittest.TestCase):
    def test_rejects_any_backslash_before_connecting(self):
        for text in ['SELECT 1; \\! env', '\\o |cat', "SELECT '\\'", '\\copy t to program \'env\'', '   ']:
            with self.assertRaises(sql.SqlError, msg=text):
                sql.checked_sql(text)
        self.assertEqual(sql.checked_sql('SELECT chr(92)'), 'SELECT chr(92)')

    def test_rejects_more_than_one_statement_before_connecting(self):
        for text in ['SELECT 1; SELECT 2', 'SET transaction_read_only=off; UPDATE t SET a=1', 'COMMIT; DELETE FROM t',
                     "SELECT 'x", '-- nothing']:
            with patch.object(sql, 'target', return_value=TARGET), \
                    patch.object(sql, 'connection_url') as connection, \
                    patch.object(sql.subprocess, 'Popen') as run, patch('sys.stderr', new_callable=io.StringIO):
                self.assertEqual(sql.main(['query', 'fixture', '-c', text]), 2, text)
            connection.assert_not_called()
            run.assert_not_called()
        for text, count in [('SELECT $$a;b$$', 1), ("SELECT ';' -- x;", 1), ('/* ; */ SELECT 1;', 1), ('SELECT 1; SELECT 2', 2)]:
            self.assertEqual(sql.statement_count(text), count, text)

    def test_carriage_return_ends_a_line_comment(self):
        text = 'SELECT 1 --x\r; ROLLBACK; SET default_transaction_read_only=off; SELECT lo_create(0)'
        with patch.object(sql, 'target', return_value=TARGET), patch.object(sql, 'connection_url') as connection, \
                patch.object(sql.subprocess, 'Popen') as run, patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(sql.main(['query', 'fixture', '-c', text]), 2)
        connection.assert_not_called()
        run.assert_not_called()
        self.assertNotIn('\r', sql.checked_sql('SELECT 1 --x\r\n'))

    def test_allows_only_read_statement_types(self):
        for text in ['/* c */ (SELECT 1)', 'WITH x AS (SELECT 1) SELECT * FROM x', 'EXPLAIN SELECT 1', 'show work_mem',
                     'TABLE users', 'VALUES (1)']:
            self.assertIn('BEGIN TRANSACTION READ ONLY', sql.wrapped_sql(text))
        for text in ["PREPARE TRANSACTION 'g'", 'COMMIT', 'SET transaction_read_only = off', 'DO $$ BEGIN END $$',
                     'CALL p()', 'LOCK users', "-- c\nprepare transaction 'x'", 'CREATE TEMP TABLE t (i int)']:
            with self.assertRaises(sql.SqlError, msg=text):
                sql.wrapped_sql(text)

    def test_query_command_never_starts_psql_for_meta_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'q.sql'
            script.write_text('SELECT 1;\n\\! env\n')
            for args in [['-c', '\\! env'], ['-f', str(script)]]:
                with patch.object(sql, 'target', return_value=TARGET), \
                        patch.object(sql, 'connection_url') as connection, \
                        patch.object(sql.subprocess, 'Popen') as run, patch('sys.stderr', new_callable=io.StringIO):
                    self.assertEqual(sql.main(['query', 'fixture', *args]), 2)
                connection.assert_not_called()
                run.assert_not_called()


def pending_url(directory):
    return (Path(directory) / 'fixture-pending.url').read_text().strip()


class PrepareTests(unittest.TestCase):
    def test_prepare_keeps_the_current_credential_and_never_prints_the_verifier(self):
        with tempfile.TemporaryDirectory() as directory:
            FakeHosting.credentials = Path(directory) / 'db.env'
            self.addCleanup(setattr, FakeHosting, 'credentials', None)
            current = url(host='::1', port=5432)
            sql.write_profile_value(FakeHosting.credentials, 'FIXTURE_DATABASE_URL', current)
            entry = {**TARGET, 'host': '::1', 'port': 5432}
            out = io.StringIO()
            with patch.object(sql, 'target', return_value=entry), patch.object(sql, '_hosting', return_value=FakeHosting), \
                    patch('sys.stdout', out):
                self.assertEqual(sql.main(['prepare', 'fixture']), 0)
            self.assertIn(current, FakeHosting.credentials.read_text())  # rotation does not break the working URL
            pending = pending_url(directory)
            self.assertIn('@[::1]:5432/', pending)
            self.assertEqual(sql.libpq_environment(pending, entry)['PGHOST'], '::1')
            for name in ('fixture-readonly-role.sql', 'fixture-pending.url'):
                self.assertEqual(stat.S_IMODE((Path(directory) / name).stat().st_mode), 0o600)
            self.assertIn('SCRAM-SHA-256$', (Path(directory) / 'fixture-readonly-role.sql').read_text())
            self.assertNotIn('SCRAM-SHA-256$', out.getvalue())
            self.assertNotIn(urllib.parse.urlsplit(pending).password, out.getvalue())

    def test_activate_stores_only_a_verified_pending_url(self):
        with tempfile.TemporaryDirectory() as directory:
            FakeHosting.credentials = Path(directory) / 'db.env'
            self.addCleanup(setattr, FakeHosting, 'credentials', None)
            current = url()
            sql.write_profile_value(FakeHosting.credentials, 'FIXTURE_DATABASE_URL', current)
            with patch.object(sql, 'target', return_value=TARGET), patch.object(sql, '_hosting', return_value=FakeHosting), \
                    patch('sys.stdout', new_callable=io.StringIO), patch('sys.stderr', new_callable=io.StringIO):
                self.assertEqual(sql.main(['activate', 'fixture']), 2)  # nothing pending
                sql.main(['prepare', 'fixture'])
                pending = pending_url(directory)
                with patch.object(sql, 'guard', side_effect=sql.SqlError('password authentication failed')):
                    self.assertEqual(sql.main(['activate', 'fixture']), 2)
                self.assertIn(current, FakeHosting.credentials.read_text())
                with patch.object(sql, 'guard', return_value={'user': 'agent_readonly', 'server_version': '18'}):
                    self.assertEqual(sql.main(['activate', 'fixture']), 0)
            self.assertIn(pending, FakeHosting.credentials.read_text())
            self.assertNotIn(current, FakeHosting.credentials.read_text())
            self.assertEqual(sorted(path.name for path in Path(directory).iterdir() if not path.name.startswith('.')),
                             ['db.env'])

    def test_concurrent_prepare_runs_keep_password_and_verifier_paired(self):
        with tempfile.TemporaryDirectory() as directory:
            FakeHosting.credentials = Path(directory) / 'db.env'
            self.addCleanup(setattr, FakeHosting, 'credentials', None)
            with patch.object(sql, 'target', return_value=TARGET), patch.object(sql, '_hosting', return_value=FakeHosting), \
                    patch('sys.stdout', new_callable=io.StringIO):
                threads = [threading.Thread(target=sql.main, args=(['prepare', 'fixture'],)) for _ in range(8)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
            password = urllib.parse.unquote(urllib.parse.urlsplit(pending_url(directory)).password)
            verifier = re.search(r"SCRAM-SHA-256\$4096:([^$]+)\$([^:]+):(\S+?)'", (Path(directory) / 'fixture-readonly-role.sql').read_text())
            salt = base64.b64decode(verifier.group(1))
            self.assertEqual(sql.scram_verifier(password, salt), verifier.group(0)[:-1])


class TimeoutTests(unittest.TestCase):
    def test_timeout_interrupts_psql_so_it_cancels_the_statement(self):
        process = MagicMock()
        process.communicate.side_effect = [subprocess.TimeoutExpired('psql', 1), ('', '')]
        with patch.object(sql, 'psql_binary', return_value='psql'), patch.object(sql.subprocess, 'Popen', return_value=process):
            with self.assertRaises(sql.SqlError) as raised:
                sql.run_session({}, 'SELECT 1;', timeout=1)
        process.send_signal.assert_called_once_with(sql.signal.SIGINT)
        process.kill.assert_not_called()
        self.assertIn('cancelled the statement on the server', str(raised.exception))


class CredentialFileTests(unittest.TestCase):
    def test_concurrent_writers_do_not_lose_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db.env'
            threads = [threading.Thread(target=sql.write_profile_value, args=(path, f'URL_{i}', f'postgresql://{i}'))
                       for i in range(24)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            text = path.read_text()
            self.assertEqual(sorted(text.splitlines()), sorted(f"URL_{i}='postgresql://{i}'" for i in range(24)))

    def test_replaces_one_assignment_atomically_and_keeps_mode_600(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'creds' / 'db.env'
            sql.write_profile_value(path, 'A_URL', 'postgresql://a')
            sql.write_profile_value(path, 'B_URL', 'postgresql://b')
            sql.write_profile_value(path, 'A_URL', 'postgresql://a2')
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.read_text(), "B_URL='postgresql://b'\nA_URL='postgresql://a2'\n")

    def test_refuses_values_the_profile_loader_cannot_read(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in ['postgresql://u:p$(x)@h/d', 'postgresql://u:p${x}@h/d', 'postgresql://u:p`x`@h/d']:
                with self.assertRaises(sql.SqlError, msg=value):
                    sql.write_profile_value(Path(directory) / 'db.env', 'A_URL', value)

    def test_leaves_an_existing_directory_mode_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory).chmod(0o755)
            sql.write_profile_value(Path(directory) / 'db.env', 'A_URL', 'postgresql://a')
            self.assertEqual(stat.S_IMODE(Path(directory).stat().st_mode), 0o755)
            nested = Path(directory) / 'new' / 'db.env'
            sql.write_profile_value(nested, 'A_URL', 'postgresql://a')
            self.assertEqual(stat.S_IMODE(nested.parent.stat().st_mode), 0o700)

    def test_refuses_a_group_readable_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db.env'
            path.write_text('')
            path.chmod(0o644)
            with self.assertRaises(sql.SqlError):
                sql.write_profile_value(path, 'A_URL', 'postgresql://a')


ADMIN_URL = os.environ.get('AGENTS_SQL_TEST_ADMIN_URL')
WITHHELD = {'users': ['password', 'api_token'], 'user_auth_tokens': '*'}


def guard(env, withheld=None, allowed_routines=(), other_databases=()):
    return sql.guard(env, {'withheld': withheld or {}, 'allowed_routines': list(allowed_routines),
                           'other_databases': list(other_databases)})


def run_session_text(env, script):
    return subprocess.run(['psql', '-X', '-At', '-q', '-v', 'ON_ERROR_STOP=1', '-f', '-'], env=env, input=script,
                          capture_output=True, text=True, timeout=60, check=True).stdout


def run_psql(env, args):
    return subprocess.run(['psql', '-X', '-v', 'ON_ERROR_STOP=1', *args], env=env, capture_output=True, text=True,
                          timeout=60)


@unittest.skipUnless(ADMIN_URL and shutil.which('psql'), 'set AGENTS_SQL_TEST_ADMIN_URL to a disposable localhost database')
class LiveRoleTests(unittest.TestCase):
    """Applies the reference role SQL to a disposable local database."""

    @classmethod
    def setUpClass(cls):
        parts = urllib.parse.urlsplit(ADMIN_URL)
        if parts.hostname not in ('127.0.0.1', 'localhost'):
            raise unittest.SkipTest('live role tests only run against localhost')
        cls.parts = parts
        cls.target = {**TARGET, 'host': parts.hostname, 'port': parts.port or 5432,
                      'database': parts.path.lstrip('/'), 'withheld': WITHHELD}
        role_sql = (ROOT / 'skills/database-query/references/readonly-role.sql').read_text()
        cls.secret = 'fixture' + os.urandom(8).hex()
        # Roles are cluster-wide; keep PUBLIC from connecting to the cluster's other databases.
        others = subprocess.run(['psql', '-X', '-At', ADMIN_URL, '-c',
                                 "SELECT string_agg(format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC;', datname), ' ') "
                                 'FROM pg_database WHERE datallowconn AND datname <> current_database()'],
                                check=True, capture_output=True, text=True).stdout.strip()
        if others:
            cls.admin(others)
        cls.admin("""
          CREATE TABLE IF NOT EXISTS public.users (id bigint PRIMARY KEY, email text, password text, api_token text);
          CREATE TABLE IF NOT EXISTS public.user_auth_tokens (id bigint PRIMARY KEY, token text);
          INSERT INTO public.users VALUES (1, 'member@example.invalid', 'hash', 'tok') ON CONFLICT DO NOTHING;
        """)
        subprocess.run(['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-q', ADMIN_URL],
                       input=role_sql.replace('REPLACE_WITH_SCRAM_VERIFIER', sql.scram_verifier(cls.secret)), text=True,
                       check=True, capture_output=True)
        cls.readonly_url = cls.role_url('agent_readonly', cls.secret)

    @classmethod
    def admin(cls, statement):
        subprocess.run(['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-q', ADMIN_URL, '-c', statement], check=True,
                       capture_output=True)

    @classmethod
    def role_url(cls, user, secret):
        return url(host=cls.parts.hostname, port=cls.parts.port or 5432, database=cls.parts.path.lstrip('/'),
                   user=user, secret=secret, sslmode='disable')

    def env(self, connection):
        return sql.libpq_environment(connection, self.target)

    def scratch_role(self, grants):
        name = 'agent_probe_' + os.urandom(3).hex()
        secret = 'probe' + os.urandom(6).hex()
        self.admin(f"CREATE ROLE {name} LOGIN PASSWORD '{secret}'; GRANT USAGE ON SCHEMA public TO {name}; {grants.format(role=name)}")
        self.addCleanup(self.admin, f'DROP OWNED BY {name}; DROP ROLE {name}')
        return self.role_url(name, secret)

    def test_verifies_the_read_only_role_and_refuses_the_owner(self):
        self.assertEqual(guard(self.env(self.readonly_url), WITHHELD)['user'], 'agent_readonly')
        owner = self.role_url(self.parts.username, urllib.parse.unquote(self.parts.password or 'x'))
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(owner))
        self.assertIn('Refusing to run', str(raised.exception))

    def test_refuses_column_level_write_grants(self):
        role = self.scratch_role('GRANT SELECT (id, email) ON public.users TO {role}; GRANT UPDATE (email) ON public.users TO {role};')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(role))
        self.assertIn('write', str(raised.exception))

    def test_refuses_inherited_read_all_data(self):
        role = self.scratch_role('GRANT pg_read_all_data TO {role};')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(role), WITHHELD)
        self.assertIn('pg_read_all_data', str(raised.exception))

    def test_refuses_a_role_that_can_read_withheld_secrets(self):
        role = self.scratch_role('GRANT SELECT ON public.users TO {role};')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(role), WITHHELD)
        self.assertIn('users.password', str(raised.exception))

    def test_refuses_other_write_paths(self):
        cases = {
            'sequence usage': 'CREATE SEQUENCE IF NOT EXISTS public.probe_seq; GRANT USAGE ON SEQUENCE public.probe_seq TO {role};',
            'owned type': "CREATE TYPE public.probe_type_{role} AS ENUM ('a'); ALTER TYPE public.probe_type_{role} OWNER TO {role};",
            'grant option': 'GRANT SELECT (id, email) ON public.users TO {role} WITH GRANT OPTION;',
            'maintain': 'GRANT MAINTAIN ON public.users TO {role};',
            'parameter': 'GRANT SET ON PARAMETER work_mem TO {role};',
        }
        version = int(subprocess.run(['psql', '-X', '-At', ADMIN_URL, '-c', 'SHOW server_version_num'],
                                     capture_output=True, text=True, check=True).stdout)
        for label, grants in cases.items():
            if label == 'maintain' and version < 170000 or label == 'parameter' and version < 150000:
                continue
            with self.subTest(label):
                role = self.scratch_role(grants)
                with self.assertRaises(sql.SqlError, msg=label):
                    guard(self.env(role))

    def test_refuses_executable_security_definer_routines(self):
        self.admin('CREATE FUNCTION public.agent_probe_definer() RETURNS int LANGUAGE sql SECURITY DEFINER AS $$ SELECT 1 $$')
        self.addCleanup(self.admin, 'DROP FUNCTION public.agent_probe_definer()')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(self.readonly_url), WITHHELD)
        self.assertIn('agent_probe_definer', str(raised.exception))

    def test_tool_queries_run_in_an_enforced_read_only_transaction(self):
        self.admin('CREATE SEQUENCE IF NOT EXISTS public.probe_ro_seq')
        self.addCleanup(self.admin, 'DROP SEQUENCE IF EXISTS public.probe_ro_seq')
        before = subprocess.run(['psql', '-X', '-At', ADMIN_URL, '-c', 'SELECT count(*) FROM pg_largeobject_metadata'],
                                capture_output=True, text=True, check=True).stdout
        # Writes reachable from read statement types fail in the server-side read-only transaction.
        for statement in ["SELECT set_config('transaction_read_only', 'off', true)", "SELECT lo_from_bytea(0, 'x')",
                          "WITH gone AS (DELETE FROM public.users RETURNING 1) SELECT count(*) FROM gone",
                          "SELECT pg_logical_emit_message(false, 'agents', 'probe')"]:
            with patch.object(sql, 'target', return_value=self.target), \
                    patch.object(sql, 'connection_url', return_value=self.readonly_url), \
                    patch('sys.stderr', new_callable=io.StringIO):
                self.assertNotEqual(sql.main(['query', 'fixture', '-c', statement]), 0, statement)
        after = subprocess.run(['psql', '-X', '-At', ADMIN_URL, '-c', 'SELECT count(*) FROM pg_largeobject_metadata'],
                               capture_output=True, text=True, check=True).stdout
        self.assertEqual(before, after, 'no large object was created')

    def test_refuses_views_and_child_tables_that_expose_withheld_secrets(self):
        self.admin('CREATE VIEW public.agent_probe_view AS SELECT id, password FROM public.users; '
                   'CREATE VIEW public.agent_probe_view2 AS SELECT id FROM public.agent_probe_view; '
                   'CREATE TABLE public.agent_probe_child () INHERITS (public.user_auth_tokens)')
        self.addCleanup(self.admin, 'DROP VIEW IF EXISTS public.agent_probe_view2, public.agent_probe_view; '
                                    'DROP TABLE IF EXISTS public.agent_probe_child')
        for grants, exposed in [('GRANT SELECT ON public.agent_probe_view TO agent_readonly', 'agent_probe_view'),
                                ('GRANT SELECT ON public.agent_probe_view2 TO agent_readonly', 'agent_probe_view2'),
                                ('GRANT SELECT ON public.agent_probe_child TO agent_readonly', 'agent_probe_child')]:
            with self.subTest(exposed):
                self.admin(grants)
                with self.assertRaises(sql.SqlError) as raised:
                    guard(self.env(self.readonly_url), WITHHELD)
                self.assertIn(exposed, str(raised.exception))
                self.admin(grants.replace('GRANT SELECT', 'REVOKE ALL').replace(' TO ', ' FROM '))
        guard(self.env(self.readonly_url), WITHHELD)

    def test_fails_closed_on_missing_withheld_entries(self):
        for withheld, missing in [({'no_such_table': '*'}, 'public.no_such_table'),
                                  ({'users': ['no_such_column']}, 'public.users.no_such_column')]:
            with self.subTest(missing), self.assertRaises(sql.SqlError) as raised:
                guard(self.env(self.readonly_url), {**WITHHELD, **withheld})
            self.assertIn(missing, str(raised.exception))

    def test_checks_withheld_relations_outside_public(self):
        self.admin('CREATE SCHEMA IF NOT EXISTS agent_probe_auth; CREATE TABLE agent_probe_auth.tokens (token text); '
                   'GRANT USAGE ON SCHEMA agent_probe_auth TO agent_readonly; GRANT SELECT ON agent_probe_auth.tokens TO agent_readonly')
        self.addCleanup(self.admin, 'DROP SCHEMA agent_probe_auth CASCADE')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(self.readonly_url), {**WITHHELD, 'agent_probe_auth.tokens': '*'})
        self.assertIn('agent_probe_auth.tokens', str(raised.exception))

    def test_refuses_security_definer_routines_in_system_schemas(self):
        self.admin('CREATE FUNCTION information_schema.agent_probe_definer() RETURNS int LANGUAGE sql SECURITY DEFINER AS $$ SELECT 1 $$')
        self.addCleanup(self.admin, 'DROP FUNCTION information_schema.agent_probe_definer()')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(self.readonly_url), WITHHELD)
        self.assertIn('agent_probe_definer', str(raised.exception))

    def test_refuses_untrusted_language_routines(self):
        # A language created without TRUSTED is untrusted; reuse plpgsql's handler.
        self.admin('CREATE LANGUAGE agent_probe_lang HANDLER plpgsql_call_handler; '
                   'CREATE FUNCTION public.agent_probe_untrusted() RETURNS int LANGUAGE agent_probe_lang '
                   'AS $$ BEGIN RETURN 1; END $$')
        self.addCleanup(self.admin, 'DROP LANGUAGE agent_probe_lang CASCADE')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(self.readonly_url), WITHHELD)
        self.assertIn('agent_probe_untrusted', str(raised.exception))

    def test_refuses_foreign_data_wrapper_usage(self):
        self.admin('CREATE FOREIGN DATA WRAPPER agent_probe_fdw')
        self.addCleanup(self.admin, 'DROP FOREIGN DATA WRAPPER agent_probe_fdw CASCADE')
        role = self.scratch_role('GRANT USAGE ON FOREIGN DATA WRAPPER agent_probe_fdw TO {role};')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(role))
        self.assertIn('foreign servers', str(raised.exception))

    def test_role_sql_accepts_only_a_scram_verifier(self):
        role_sql = (ROOT / 'skills/database-query/references/readonly-role.sql').read_text()
        for unsafe in [role_sql, role_sql.replace('REPLACE_WITH_SCRAM_VERIFIER', 'a-cleartext-password-0123456789')]:
            failed = subprocess.run(['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-q', ADMIN_URL], input=unsafe, text=True,
                                    capture_output=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn('SCRAM-SHA-256 verifier', failed.stderr)
        guard(self.env(self.readonly_url), WITHHELD)  # the existing password still works

    def test_refuses_granted_file_reading_built_ins(self):
        role = self.scratch_role('GRANT EXECUTE ON FUNCTION pg_read_file(text) TO {role};')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(role))
        self.assertIn('pg_read_file', str(raised.exception))

    def test_refuses_whole_row_views_over_withheld_columns(self):
        self.admin('CREATE VIEW public.agent_probe_rows AS SELECT u FROM public.users u; '
                   'CREATE VIEW public.agent_probe_safe AS SELECT id, email FROM public.users; '
                   'GRANT SELECT ON public.agent_probe_safe TO agent_readonly')
        self.addCleanup(self.admin, 'DROP VIEW IF EXISTS public.agent_probe_rows, public.agent_probe_safe')
        guard(self.env(self.readonly_url), WITHHELD)  # a column-only view is fine
        self.admin('GRANT SELECT ON public.agent_probe_rows TO agent_readonly')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(self.readonly_url), WITHHELD)
        self.assertIn('agent_probe_rows', str(raised.exception))

    def test_role_search_path_cannot_shadow_the_catalogs(self):
        role = self.scratch_role('CREATE SCHEMA agent_probe_shadow_{role} AUTHORIZATION {role}; '
                                 'CREATE VIEW agent_probe_shadow_{role}.pg_shdepend AS SELECT * FROM pg_catalog.pg_shdepend WHERE false; '
                                 'ALTER VIEW agent_probe_shadow_{role}.pg_shdepend OWNER TO {role}; '
                                 'ALTER ROLE {role} SET search_path = agent_probe_shadow_{role}, pg_catalog;')
        name = urllib.parse.urlsplit(role).username
        self.addCleanup(self.admin, f'DROP SCHEMA IF EXISTS agent_probe_shadow_{name} CASCADE')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(role))
        self.assertIn('owns database objects', str(raised.exception))

    def run_role_sql(self):
        role_sql = (ROOT / 'skills/database-query/references/readonly-role.sql').read_text()
        return subprocess.run(['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-q', ADMIN_URL],
                              input=role_sql.replace('REPLACE_WITH_SCRAM_VERIFIER', sql.scram_verifier(self.secret)), text=True,
                              capture_output=True)

    def test_catalog_write_grants_are_not_effective_for_non_superusers(self):
        # PostgreSQL denies catalog writes to non-superusers even with an explicit grant,
        # and the guard scans effective privileges in every schema, catalogs included.
        role = self.scratch_role('GRANT UPDATE ON pg_catalog.pg_description TO {role};')
        guard(self.env(role))
        denied = run_psql(self.env(role), ['-At', '-c',
            "SET transaction_read_only = off; UPDATE pg_catalog.pg_description SET description = description WHERE false"])
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('permission denied', denied.stderr)

    def test_role_sql_removes_stale_write_grants(self):
        self.admin('GRANT INSERT, UPDATE (email) ON public.users TO agent_readonly')
        with self.assertRaises(sql.SqlError):
            guard(self.env(self.readonly_url), WITHHELD)
        self.assertEqual(self.run_role_sql().returncode, 0)
        guard(self.env(self.readonly_url), WITHHELD)

    def test_role_sql_stops_instead_of_changing_public_create(self):
        self.admin('GRANT CREATE ON SCHEMA public TO PUBLIC')
        self.addCleanup(self.admin, 'REVOKE CREATE ON SCHEMA public FROM PUBLIC')
        failed = self.run_role_sql()
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn('PUBLIC can create objects in schema public', failed.stderr)
        has_create = subprocess.run(['psql', '-X', '-At', ADMIN_URL, '-c',
                                     "SELECT has_schema_privilege('public', 'public', 'CREATE')"],
                                    capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(has_create, 't', 'the database-wide grant was left for the owner to change')

    def test_withholds_generated_columns_derived_from_secrets(self):
        self.admin('ALTER TABLE public.users ADD COLUMN password_copy text GENERATED ALWAYS AS (password) STORED')
        self.addCleanup(self.admin, 'ALTER TABLE public.users DROP COLUMN IF EXISTS password_copy')
        self.assertEqual(self.run_role_sql().returncode, 0)
        guard(self.env(self.readonly_url), WITHHELD)  # setup skipped the derived column
        self.admin('GRANT SELECT (password_copy) ON public.users TO agent_readonly')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(self.readonly_url), WITHHELD)
        self.assertIn('password_copy', str(raised.exception))

    def test_refuses_create_on_any_persistent_schema(self):
        role = self.scratch_role('GRANT CREATE ON SCHEMA information_schema TO {role};')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(role))
        self.assertIn('can create', str(raised.exception))

    def test_default_privileges_for_any_creator_are_refused_and_cleared(self):
        self.admin('CREATE ROLE agent_probe_migrator; '
                   'ALTER DEFAULT PRIVILEGES FOR ROLE agent_probe_migrator IN SCHEMA public GRANT SELECT ON TABLES TO agent_readonly; '
                   'ALTER DEFAULT PRIVILEGES FOR ROLE postgres GRANT SELECT ON TABLES TO agent_readonly')
        self.addCleanup(self.admin, 'ALTER DEFAULT PRIVILEGES FOR ROLE postgres REVOKE ALL ON TABLES FROM agent_readonly; '
                                    'DROP OWNED BY agent_probe_migrator; DROP ROLE agent_probe_migrator')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(self.readonly_url), WITHHELD)
        self.assertIn('default privileges', str(raised.exception))
        self.assertEqual(self.run_role_sql().returncode, 0)
        guard(self.env(self.readonly_url), WITHHELD)

    def test_readable_parent_exposes_a_withheld_child(self):
        self.admin('CREATE TABLE public.agent_probe_parent (token text); '
                   'CREATE TABLE public.agent_probe_kid () INHERITS (public.agent_probe_parent); '
                   'GRANT SELECT ON public.agent_probe_parent TO agent_readonly')
        self.addCleanup(self.admin, 'DROP TABLE IF EXISTS public.agent_probe_kid, public.agent_probe_parent')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(self.readonly_url), {**WITHHELD, 'agent_probe_kid': '*'})
        self.assertIn('agent_probe_parent', str(raised.exception))

    def test_refuses_unlisted_compiled_extension_routines(self):
        self.admin("CREATE FUNCTION public.agent_probe_lower(text) RETURNS text LANGUAGE internal IMMUTABLE STRICT AS 'lower'")
        self.addCleanup(self.admin, 'DROP FUNCTION IF EXISTS public.agent_probe_lower(text), public.agent_probe_lower(text, text)')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(self.readonly_url), WITHHELD)
        self.assertIn('agent_probe_lower', str(raised.exception))
        guard(self.env(self.readonly_url), WITHHELD, ['public.agent_probe_lower(text)'])
        # An unaudited overload is not covered by the allowlisted identity.
        self.admin("CREATE FUNCTION public.agent_probe_lower(text, text) RETURNS text LANGUAGE internal IMMUTABLE STRICT AS 'textcat'")
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(self.readonly_url), WITHHELD, ['public.agent_probe_lower(text)'])
        self.assertIn('public.agent_probe_lower(text,text)', str(raised.exception))

    def test_refuses_custom_compiled_routines_created_in_pg_catalog(self):
        self.admin("CREATE FUNCTION pg_catalog.agent_probe_catalog(text) RETURNS text LANGUAGE internal IMMUTABLE STRICT AS 'lower'")
        self.addCleanup(self.admin, 'DROP FUNCTION pg_catalog.agent_probe_catalog(text)')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(self.readonly_url), WITHHELD)
        self.assertIn('pg_catalog.agent_probe_catalog(text)', str(raised.exception))

    def test_refuses_compiled_extension_routines_installed_in_pg_catalog(self):
        # Stock PostgreSQL blocks installing dblink into pg_catalog, so move one member there.
        self.admin('CREATE EXTENSION dblink; ALTER FUNCTION public.dblink_exec(text,text) SET SCHEMA pg_catalog')
        self.addCleanup(self.admin, 'DROP EXTENSION dblink')
        others = subprocess.run(['psql', '-X', '-At', ADMIN_URL, '-c',
            "SET search_path TO pg_catalog; SELECT 'public.'||p.proname||substring(p.oid::regprocedure::text from '\\(.*\\)$') "
            "FROM pg_proc p WHERE p.pronamespace='public'::regnamespace AND p.proname LIKE 'dblink%'"],
            capture_output=True, text=True, check=True).stdout.split()
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(self.readonly_url), WITHHELD, others)
        self.assertIn('pg_catalog.dblink_exec(text,text)', str(raised.exception))

    def test_refuses_large_object_reads_and_role_sql_revokes_them(self):
        lo = subprocess.run(['psql', '-X', '-At', ADMIN_URL, '-c', "SELECT lo_from_bytea(0, 'secret')"],
                            capture_output=True, text=True, check=True).stdout.strip()
        self.addCleanup(self.admin, f'SELECT lo_unlink({lo})')
        self.admin(f'GRANT SELECT ON LARGE OBJECT {lo} TO agent_readonly')
        with self.assertRaises(sql.SqlError):
            guard(self.env(self.readonly_url), WITHHELD)
        self.assertEqual(self.run_role_sql().returncode, 0)
        guard(self.env(self.readonly_url), WITHHELD)
        self.admin(f'GRANT SELECT ON LARGE OBJECT {lo} TO PUBLIC')
        with self.assertRaises(sql.SqlError):
            guard(self.env(self.readonly_url), WITHHELD)

    def test_role_sql_keeps_existing_roles_wal_message_access(self):
        self.admin("CREATE ROLE agent_probe_app; DO $$ DECLARE f regprocedure; BEGIN FOR f IN SELECT oid::regprocedure "
                   "FROM pg_proc WHERE proname='pg_logical_emit_message' LOOP EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO PUBLIC', f); "
                   "END LOOP; END $$;")
        self.addCleanup(self.admin, 'DROP OWNED BY agent_probe_app; DROP ROLE agent_probe_app')
        self.assertEqual(self.run_role_sql().returncode, 0)
        check = subprocess.run(['psql', '-X', '-At', ADMIN_URL, '-c',
            "SELECT bool_and(has_function_privilege('agent_probe_app', oid, 'EXECUTE')), "
            "bool_or(has_function_privilege('agent_readonly', oid, 'EXECUTE')), "
            "bool_or(has_function_privilege('public', oid, 'EXECUTE')) FROM pg_proc WHERE proname='pg_logical_emit_message'"],
            capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(check, 't|f|f')

    def test_default_acl_cleanup_requires_authority_over_each_creator(self):
        secret = 'x' + os.urandom(8).hex()
        self.admin(f"CREATE ROLE agent_probe_migrator2; CREATE ROLE agent_probe_exec LOGIN PASSWORD '{secret}'; "
                   'ALTER DEFAULT PRIVILEGES FOR ROLE agent_probe_migrator2 GRANT SELECT ON TABLES TO agent_readonly')
        self.addCleanup(self.admin, 'DROP OWNED BY agent_probe_migrator2; DROP ROLE agent_probe_migrator2; DROP ROLE agent_probe_exec')
        role_sql = (ROOT / 'skills/database-query/references/readonly-role.sql').read_text()
        start = role_sql.index('-- Clear default privileges naming this role')
        block = role_sql[start:role_sql.index('END $$;', start) + len('END $$;')]
        failed = subprocess.run(['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-q', self.role_url('agent_probe_exec', secret)],
                                input=block, text=True, capture_output=True)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn('created by agent_probe_migrator2', failed.stderr)

    def test_refuses_maintain_on_catalogs(self):
        version = int(subprocess.run(['psql', '-X', '-At', ADMIN_URL, '-c', 'SHOW server_version_num'],
                                     capture_output=True, text=True, check=True).stdout)
        if version < 170000:
            self.skipTest('MAINTAIN needs PostgreSQL 17+')
        role = self.scratch_role('GRANT MAINTAIN ON pg_catalog.pg_description TO {role};')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(role))
        self.assertIn('MAINTAIN', str(raised.exception))

    def test_prepare_then_activate_rotates_the_password(self):
        self.addCleanup(lambda: self.assertEqual(self.run_role_sql().returncode, 0))  # restore the class password
        with tempfile.TemporaryDirectory() as directory:
            FakeHosting.credentials = Path(directory) / 'db.env'
            self.addCleanup(setattr, FakeHosting, 'credentials', None)
            fixture = {**self.target, 'profile': 'postgres.fixture', 'variable': 'FIXTURE_DATABASE_URL'}
            out = io.StringIO()
            with patch.object(sql, 'target', return_value=fixture), patch.object(sql, '_hosting', return_value=FakeHosting), \
                    patch('sys.stdout', out), patch('sys.stderr', new_callable=io.StringIO):
                self.assertEqual(sql.main(['prepare', 'fixture']), 0)
                password = urllib.parse.unquote(urllib.parse.urlsplit(pending_url(directory)).password)
                self.assertNotIn(password, out.getvalue())
                self.assertNotIn('SCRAM-SHA-256$', out.getvalue())
                guard(self.env(self.readonly_url), WITHHELD)  # the old password still works before the owner step
                self.assertEqual(sql.main(['activate', 'fixture']), 2)  # new password not applied yet
                setup = Path(directory) / 'fixture-readonly-role.sql'
                subprocess.run(['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-q', ADMIN_URL, '-f', str(setup)],
                               check=True, capture_output=True)
                self.assertEqual(sql.main(['activate', 'fixture']), 0)
            stored = FakeHosting.credentials.read_text().strip().split('=', 1)[1].strip("'")
            self.assertEqual(urllib.parse.unquote(urllib.parse.urlsplit(stored).password), password)
            self.assertEqual(stat.S_IMODE(FakeHosting.credentials.stat().st_mode), 0o600)
            self.assertFalse(setup.exists())

    def test_refuses_connect_on_unlisted_databases(self):
        name = 'agent_probe_db_' + os.urandom(3).hex()
        self.admin(f'CREATE DATABASE {name}')
        self.addCleanup(self.admin, f'DROP DATABASE {name}')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(self.readonly_url), WITHHELD)
        self.assertIn(name, str(raised.exception))
        guard(self.env(self.readonly_url), WITHHELD, other_databases=[name])  # audited and listed

    def test_schemas_resembling_temp_names_are_still_audited(self):
        schema = 'pgxtemp_' + os.urandom(3).hex()
        self.admin(f'CREATE SCHEMA {schema}; CREATE TABLE {schema}.payload (id int)')
        self.addCleanup(self.admin, f'DROP SCHEMA {schema} CASCADE')
        role = self.scratch_role(f'GRANT USAGE ON SCHEMA {schema} TO {{role}}; GRANT UPDATE ON {schema}.payload TO {{role}};')
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(role))
        self.assertIn('can write', str(raised.exception))

    def test_role_sql_ignores_the_invokers_search_path(self):
        schema = 'agent_probe_evil_' + os.urandom(3).hex()
        self.admin(f"CREATE SCHEMA {schema}; CREATE FUNCTION {schema}.current_setting(text) RETURNS text "
                   f"LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'shadowed'; END $$")
        self.addCleanup(self.admin, f'DROP SCHEMA {schema} CASCADE')
        role_sql = (ROOT / 'skills/database-query/references/readonly-role.sql').read_text()
        result = subprocess.run(['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-q', ADMIN_URL],
                                input=f'SET search_path = {schema}, pg_catalog;\n'
                                + role_sql.replace('REPLACE_WITH_SCRAM_VERIFIER', sql.scram_verifier(self.secret)),
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('shadowed', result.stderr)

    def test_refused_role_never_runs_the_query_in_the_same_session(self):
        role = self.scratch_role('GRANT INSERT ON public.users TO {role};')
        started = time.monotonic()
        with patch.object(sql, 'target', return_value=self.target), patch.object(sql, 'connection_url', return_value=role), \
                patch('sys.stderr', new_callable=io.StringIO) as err:
            self.assertEqual(sql.main(['query', 'fixture', '-c', 'SELECT pg_sleep(5)']), 2)
        self.assertLess(time.monotonic() - started, 4)  # the query part was skipped
        self.assertIn('can write', err.getvalue())

    def test_query_search_path_is_pinned_to_public(self):
        self.admin('ALTER ROLE agent_readonly SET search_path = agent_probe_nowhere')
        self.addCleanup(self.admin, 'ALTER ROLE agent_readonly RESET search_path')
        env = self.env(self.readonly_url)
        self.assertIn('agent_probe_nowhere', run_psql(env, ['-At', '-c', 'SHOW search_path']).stdout)
        session = run_session_text(env, sql.wrapped_sql('SHOW search_path'))
        self.assertEqual(session.strip(), 'public')
        guard(env, WITHHELD)  # verification pins pg_catalog regardless

    def test_timeout_cancels_a_query_that_raises_its_own_statement_timeout(self):
        with patch.object(sql, 'target', return_value=self.target), \
                patch.object(sql, 'connection_url', return_value=self.readonly_url), \
                patch('sys.stderr', new_callable=io.StringIO) as err, patch('sys.stdout', new_callable=io.StringIO):
            code = sql.main(['query', 'fixture', '--timeout', '3', '-c',
                             "SELECT set_config('statement_timeout', '0', true), pg_sleep(60)"])
        self.assertEqual(code, 2)
        self.assertIn('cancelled the statement on the server', err.getvalue())
        for _ in range(20):
            running = subprocess.run(['psql', '-X', '-At', ADMIN_URL, '-c',
                                      "SELECT count(*) FROM pg_stat_activity WHERE usename='agent_readonly' "
                                      "AND query LIKE '%pg_sleep(60)%' AND state='active'"],
                                     capture_output=True, text=True).stdout.strip()
            if running == '0':
                break
            subprocess.run(['sleep', '0.25'])
        self.assertEqual(running, '0')

    def test_role_sql_handles_tables_with_only_secret_columns(self):
        self.admin('CREATE TABLE IF NOT EXISTS public.device_push_tokens (token text)')
        self.addCleanup(self.admin, 'DROP TABLE IF EXISTS public.device_push_tokens')
        role_sql = (ROOT / 'skills/database-query/references/readonly-role.sql').read_text()
        subprocess.run(['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-q', ADMIN_URL],
                       input=role_sql.replace('REPLACE_WITH_SCRAM_VERIFIER', sql.scram_verifier(self.secret)), text=True,
                       check=True, capture_output=True)
        guard(self.env(self.readonly_url), {**WITHHELD, 'device_push_tokens': ['token']})

    def test_role_sql_withholds_secrets_on_child_tables(self):
        self.admin('CREATE TABLE public.agent_probe_child2 () INHERITS (public.user_auth_tokens)')
        self.addCleanup(self.admin, 'DROP TABLE IF EXISTS public.agent_probe_child2')
        role_sql = (ROOT / 'skills/database-query/references/readonly-role.sql').read_text()
        subprocess.run(['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-q', ADMIN_URL],
                       input=role_sql.replace('REPLACE_WITH_SCRAM_VERIFIER', sql.scram_verifier(self.secret)), text=True,
                       check=True, capture_output=True)
        guard(self.env(self.readonly_url), WITHHELD)

    def test_refuses_wal_writing_routines(self):
        role = self.scratch_role("DO $$ DECLARE f regprocedure; BEGIN FOR f IN SELECT oid::regprocedure FROM pg_proc "
                                 "WHERE proname='pg_logical_emit_message' LOOP EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO {role}', f); "
                                 "END LOOP; END $$;")
        with self.assertRaises(sql.SqlError) as raised:
            guard(self.env(role))
        self.assertIn('pg_logical_emit_message', str(raised.exception))

    def test_reads_allowed_columns_but_never_writes_or_reads_secrets(self):
        env = self.env(self.readonly_url)
        ok = run_psql(env, ['-At', '-c', 'SELECT email FROM public.users WHERE id=1'])
        self.assertEqual(ok.stdout.strip(), 'member@example.invalid')
        for statement in ['SELECT password FROM public.users', 'SELECT token FROM public.user_auth_tokens',
                          "SET transaction_read_only=off; UPDATE public.users SET email='x'",
                          'BEGIN READ WRITE; DELETE FROM public.users; COMMIT',
                          'CREATE TABLE public.agent_probe(id int)']:
            denied = run_psql(env, ['-At', '-c', statement])
            self.assertNotEqual(denied.returncode, 0, statement)

    def test_query_command_runs_sql_through_the_guard(self):
        with patch.object(sql, 'target', return_value=self.target), \
                patch.object(sql, 'connection_url', return_value=self.readonly_url), \
                patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(sql.main(['check', 'fixture']), 0)
        with patch.object(sql, 'target', return_value=self.target), \
                patch.object(sql, 'connection_url', return_value=self.readonly_url), \
                patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(sql.main(['query', 'fixture', '-c', 'SELECT count(*) FROM public.users']), 0)


if __name__ == '__main__':
    unittest.main()
