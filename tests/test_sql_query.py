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


def write_registry(path, targets):
    path.write_text(json.dumps({'schema_version': 1, 'targets': targets}))
    path.chmod(0o600)


class RegistryTests(unittest.TestCase):
    def test_example_registry_is_valid_and_has_no_real_endpoints(self):
        targets = sql.load_targets(ROOT / 'config/databases.example.json')
        self.assertTrue(all(entry['host'].endswith('.invalid') for entry in targets.values()))

    def test_missing_local_registry_explains_setup(self):
        with self.assertRaisesRegex(sql.SqlError, 'local/databases.json'):
            sql.load_targets(Path('/nonexistent/databases.json'))

    def test_rejects_malformed_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'databases.json'
            for bad in [{'host': None}, {'database': 5}, {'description': ''}, {'port': '5432'}, {'port': 0},
                        {'profile': 'nodot'}, {'variable': 'lower'}, {'withold': {'users': '*'}}]:
                write_registry(path, {'t': {**TARGET, **bad}})
                with self.assertRaises(sql.SqlError, msg=bad):
                    sql.load_targets(path)
            write_registry(path, {'Bad_Name': TARGET})
            with self.assertRaises(sql.SqlError):
                sql.load_targets(path)
            write_registry(path, {'t': {**TARGET, 'docs': 'runbook'}})
            self.assertIn('t', sql.load_targets(path))

    def test_refuses_two_targets_sharing_a_credential_variable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'databases.json'
            write_registry(path, {'a': TARGET, 'b': {**TARGET, 'database': 'other'}})
            with self.assertRaises(sql.SqlError):
                sql.load_targets(path)

    def test_refuses_a_group_readable_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'databases.json'
            write_registry(path, {'t': TARGET})
            path.chmod(0o644)
            with self.assertRaisesRegex(sql.SqlError, 'mode 600'):
                sql.load_targets(path)

    def test_unknown_target(self):
        with self.assertRaisesRegex(sql.SqlError, 'Unknown database target'):
            sql.target('nope', {'t': TARGET})


class ConnectionTests(unittest.TestCase):
    def test_builds_libpq_environment_without_inherited_database_settings(self):
        with patch.dict(os.environ, {'PGHOST': 'evil', 'DATABASE_URL': 'postgres://other', 'PATH': '/bin'}):
            env = sql.libpq_environment(url(secret='p@ss', sslmode='require'), TARGET)
        self.assertEqual((env['PGHOST'], env['PGPASSWORD'], env['PGSSLMODE']), ('db.example.test', 'p@ss', 'require'))
        self.assertIn('default_transaction_read_only=on', env['PGOPTIONS'])
        self.assertNotIn('DATABASE_URL', env)

    def test_deployed_connections_require_tls(self):
        self.assertEqual(sql.libpq_environment(url(), TARGET)['PGSSLMODE'], 'require')
        for mode in ('disable', 'allow', 'prefer'):
            with self.assertRaises(sql.SqlError):
                sql.libpq_environment(url(sslmode=mode), TARGET)
        with self.assertRaisesRegex(sql.SqlError, 'sslrootcert'):
            sql.libpq_environment(url(sslmode='verify-full'), TARGET)
        local = {**TARGET, 'host': '127.0.0.1'}
        self.assertEqual(sql.libpq_environment(url(host='127.0.0.1', sslmode='disable'), local)['PGSSLMODE'], 'disable')

    def test_rejects_connections_that_do_not_match_the_target(self):
        for bad in [url(host='other.example.test'), url(port=5432), url(database='other'), url(user=None), url(user='analytics'),
                    url(application_name='x'), 'mysql://u:p@db.example.test:6543/railway', 'postgresql://[bad']:
            with self.assertRaises(sql.SqlError, msg=bad):
                sql.libpq_environment(bad, TARGET)

    def test_missing_credential_explains_the_owner_step(self):
        with self.assertRaisesRegex(sql.SqlError, 'prepare'):
            sql.connection_url(TARGET, FakeHosting)

    def test_credentials_only_come_from_declared_postgres_profile_variables(self):
        for entry in [{**TARGET, 'profile': 'railway.workspace', 'variable': 'RAILWAY_API_TOKEN'},
                      {**TARGET, 'variable': 'OTHER_URL'}, {**TARGET, 'profile': 'postgres.missing'}]:
            with self.assertRaises(sql.SqlError):
                sql.connection_url(entry, FakeHosting)


class QueryScriptTests(unittest.TestCase):
    def test_rejects_backslashes_before_connecting(self):
        for text in ['SELECT 1\n\\endif\nDELETE FROM t', '\\! env', "SELECT '\\'", '   ']:
            with patch.object(sql, 'target', return_value=TARGET), patch.object(sql, 'connection_url') as connection, \
                    patch.object(sql.subprocess, 'Popen') as popen, patch('sys.stderr', new_callable=io.StringIO):
                self.assertEqual(sql.main(['query', 'fixture', '-c', text]), 2, text)
            connection.assert_not_called()
            popen.assert_not_called()

    def test_runs_the_sql_only_inside_the_guard_and_a_read_only_transaction(self):
        script = sql.query_script('SELECT 1')
        self.assertTrue(script.startswith(sql.GUARD_SCRIPT))
        body = script[len(sql.GUARD_SCRIPT):]
        self.assertTrue(body.startswith('\\if :agents_sql_safe\n'))
        self.assertLess(body.index('BEGIN TRANSACTION READ ONLY'), body.index('SELECT 1\n'))
        self.assertTrue(body.endswith('ROLLBACK;\n\\endif\n'))

    def test_parses_the_guard_line(self):
        verified, problems, rest = sql.guard_result(
            'NOTICE: x\nAGENTS_SQL_GUARD on|false|false|false|false|false|agent_readonly|18.1\n')
        self.assertEqual((verified['user'], problems, rest), ('agent_readonly', [], 'NOTICE: x'))
        _, problems, _ = sql.guard_result('AGENTS_SQL_GUARD off|true|false|false|true|false|postgres|18.1')
        self.assertEqual(len(problems), 2)
        for bad in ['', 'AGENTS_SQL_GUARD on|true|false|false|false|false|u|18', 'AGENTS_SQL_GUARD on|false']:
            with self.assertRaises(sql.SqlError, msg=bad):
                sql.guard_result(bad)

    def test_server_statement_timeout_follows_the_timeout_option(self):
        seen = {}

        def fake_session(env, script, args=(), capture_stdout=True, timeout=120):
            seen.update(options=env['PGOPTIONS'], timeout=timeout)
            return subprocess.CompletedProcess([], 0, '', 'AGENTS_SQL_GUARD on|false|false|false|false|false|agent_readonly|18')

        with patch.object(sql, 'target', return_value=TARGET), patch.object(sql, 'connection_url', return_value=url()), \
                patch.object(sql, 'run_session', fake_session), patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(sql.main(['query', 'fixture', '--timeout', '300', '-c', 'SELECT 1']), 0)
        self.assertIn('statement_timeout=300s', seen['options'])
        self.assertEqual(seen['timeout'], 300)

    def test_timeout_interrupts_psql_so_it_cancels_the_statement(self):
        process = MagicMock()
        process.communicate.side_effect = [subprocess.TimeoutExpired('psql', 1), ('', '')]
        with patch.object(sql, 'psql_binary', return_value='psql'), patch.object(sql.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(sql.SqlError, 'cancelled the statement on the server'):
                sql.run_session({}, 'SELECT 1;', timeout=1)
        process.send_signal.assert_called_once_with(sql.signal.SIGINT)
        process.kill.assert_not_called()


def pending_url(directory):
    return (Path(directory) / 'fixture-pending.url').read_text().strip()


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        FakeHosting.credentials = Path(self.directory.name) / 'db.env'
        self.addCleanup(setattr, FakeHosting, 'credentials', None)

    def run_main(self, args, entry=TARGET, **patches):
        out = io.StringIO()
        with patch.object(sql, 'target', return_value=entry), patch.object(sql, '_hosting', return_value=FakeHosting), \
                patch('sys.stdout', out), patch('sys.stderr', new_callable=io.StringIO):
            with contextlib_patches(patches):
                return sql.main(args), out.getvalue()

    def test_prepare_keeps_the_current_credential_and_prints_nothing_secret(self):
        current = url(host='::1', port=5432)
        sql.write_profile_value(FakeHosting.credentials, 'FIXTURE_DATABASE_URL', current)
        entry = {**TARGET, 'host': '::1', 'port': 5432}
        code, out = self.run_main(['prepare', 'fixture'], entry)
        self.assertEqual(code, 0)
        self.assertIn(current, FakeHosting.credentials.read_text())
        pending = pending_url(self.directory.name)
        self.assertIn('@[::1]:5432/', pending)
        setup = Path(self.directory.name) / 'fixture-readonly-role.sql'
        for path in (setup, Path(self.directory.name) / 'fixture-pending.url'):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertIn('SCRAM-SHA-256$', setup.read_text())
        self.assertNotIn('SCRAM-SHA-256$', out)
        self.assertNotIn(urllib.parse.urlsplit(pending).password, out)

    def test_prepare_keeps_a_pinned_server_certificate(self):
        root = Path(self.directory.name) / 'root.crt'
        root.write_text('fixture')
        current = url(sslmode='verify-full', sslrootcert=str(root))
        code, _ = self.run_main(['prepare', 'fixture'], connection_url=current)
        self.assertEqual(code, 0)
        env = sql.libpq_environment(pending_url(self.directory.name), TARGET)
        self.assertEqual((env['PGSSLMODE'], env['PGSSLROOTCERT']), ('verify-full', str(root)))

    def test_concurrent_prepare_runs_keep_password_and_verifier_paired(self):
        with patch.object(sql, 'target', return_value=TARGET), patch.object(sql, '_hosting', return_value=FakeHosting), \
                patch('sys.stdout', new_callable=io.StringIO):
            threads = [threading.Thread(target=sql.main, args=(['prepare', 'fixture'],)) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        password = urllib.parse.unquote(urllib.parse.urlsplit(pending_url(self.directory.name)).password)
        verifier = re.search(r"SCRAM-SHA-256\$4096:([^$]+)\$([^:]+):(\S+?)'",
                             (Path(self.directory.name) / 'fixture-readonly-role.sql').read_text())
        self.assertEqual(sql.scram_verifier(password, base64.b64decode(verifier.group(1))), verifier.group(0)[:-1])

    def test_activate_stores_only_a_verified_pending_url(self):
        current = url()
        sql.write_profile_value(FakeHosting.credentials, 'FIXTURE_DATABASE_URL', current)
        self.assertEqual(self.run_main(['activate', 'fixture'])[0], 2)  # nothing pending
        self.run_main(['prepare', 'fixture'])
        pending = pending_url(self.directory.name)
        self.assertEqual(self.run_main(['activate', 'fixture'], guard=sql.SqlError('auth failed'))[0], 2)
        with patch('sys.stderr', new_callable=io.StringIO) as err, \
                patch.object(sql, 'target', return_value=TARGET), patch.object(sql, '_hosting', return_value=FakeHosting), \
                patch.object(sql, 'guard', side_effect=sql.SqlError("Refusing to run: role 'agent_readonly' can write")):
            self.assertEqual(sql.main(['activate', 'fixture']), 2)
        self.assertIn('new password works', err.getvalue())
        self.assertIn(current, FakeHosting.credentials.read_text())
        verified = {'user': 'agent_readonly', 'server_version': '18'}
        self.assertEqual(self.run_main(['activate', 'fixture'], guard=verified)[0], 0)
        stored = FakeHosting.credentials.read_text()
        self.assertIn(pending, stored)
        self.assertNotIn(current, stored)
        self.assertEqual(sorted(p.name for p in Path(self.directory.name).iterdir() if not p.name.startswith('.')),
                         ['db.env'])


class contextlib_patches:
    """Patch sql.<name> with a return value, or a side effect when it is an exception."""

    def __init__(self, patches):
        self.patchers = [patch.object(sql, name, side_effect=value) if isinstance(value, Exception)
                         else patch.object(sql, name, return_value=value) for name, value in patches.items()]

    def __enter__(self):
        for patcher in self.patchers:
            patcher.start()

    def __exit__(self, *exc):
        for patcher in self.patchers:
            patcher.stop()


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
            self.assertEqual(sorted(path.read_text().splitlines()),
                             sorted(f"URL_{i}='postgresql://{i}'" for i in range(24)))

    def test_replaces_one_assignment_atomically_with_mode_600(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'creds' / 'db.env'
            sql.write_profile_value(path, 'A_URL', 'postgresql://a')
            sql.write_profile_value(path, 'B_URL', 'postgresql://b')
            sql.write_profile_value(path, 'A_URL', 'postgresql://a2')
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertEqual(path.read_text(), "B_URL='postgresql://b'\nA_URL='postgresql://a2'\n")

    def test_leaves_an_existing_directory_mode_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory).chmod(0o755)
            sql.write_profile_value(Path(directory) / 'db.env', 'A_URL', 'postgresql://a')
            self.assertEqual(stat.S_IMODE(Path(directory).stat().st_mode), 0o755)

    def test_refuses_unsafe_files_and_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db.env'
            for value in ['postgresql://u:p$(x)@h/d', 'postgresql://u:p${x}@h/d', 'postgresql://u:p`x`@h/d', "a'b"]:
                with self.assertRaises(sql.SqlError, msg=value):
                    sql.write_profile_value(path, 'A_URL', value)
            path.write_text('')
            path.chmod(0o644)
            with self.assertRaisesRegex(sql.SqlError, 'mode 600'):
                sql.write_profile_value(path, 'A_URL', 'postgresql://a')


ADMIN_URL = os.environ.get('AGENTS_SQL_TEST_ADMIN_URL')


def admin_env():
    """libpq variables for the admin URL, so its password never appears in argv."""
    parts = urllib.parse.urlsplit(ADMIN_URL)
    return {**os.environ, 'PGHOST': parts.hostname, 'PGPORT': str(parts.port or 5432),
            'PGDATABASE': urllib.parse.unquote(parts.path.lstrip('/')), 'PGUSER': urllib.parse.unquote(parts.username),
            'PGPASSWORD': urllib.parse.unquote(parts.password or ''), 'PGSSLMODE': 'disable'}


def admin_psql(*args, **kwargs):
    return subprocess.run(['psql', '-X', *args], env=admin_env(), capture_output=True, text=True, **kwargs)


@unittest.skipUnless(ADMIN_URL and shutil.which('psql'), 'set AGENTS_SQL_TEST_ADMIN_URL to a disposable localhost database')
class LiveRoleTests(unittest.TestCase):
    """Applies the role SQL to a disposable local database with password auth."""

    @classmethod
    def setUpClass(cls):
        cls.parts = urllib.parse.urlsplit(ADMIN_URL)
        if cls.parts.hostname not in ('127.0.0.1', 'localhost'):
            raise unittest.SkipTest('live role tests only run against localhost')
        cls.target = {**TARGET, 'host': cls.parts.hostname, 'port': cls.parts.port or 5432,
                      'database': cls.parts.path.lstrip('/')}
        cls.admin("""
          CREATE TABLE IF NOT EXISTS public.users (id bigint PRIMARY KEY, email text, password text, api_token text);
          CREATE TABLE IF NOT EXISTS public.user_auth_tokens (id bigint PRIMARY KEY, token text);
          INSERT INTO public.users VALUES (1, 'member@example.invalid', 'hash', 'tok') ON CONFLICT DO NOTHING;
        """)
        cls.secret = 'fixture' + os.urandom(8).hex()
        assert cls.run_role_sql().returncode == 0
        cls.readonly_url = cls.role_url('agent_readonly', cls.secret)

    @classmethod
    def admin(cls, statement):
        result = admin_psql('-v', 'ON_ERROR_STOP=1', '-q', '-c', statement)
        if result.returncode:
            raise AssertionError(f'admin statement failed: {result.stderr.strip()[:300]}')

    @classmethod
    def run_role_sql(cls, secret=None, prefix=''):
        role_sql = sql.ROLE_SQL.read_text().replace('REPLACE_WITH_SCRAM_VERIFIER', sql.scram_verifier(secret or cls.secret))
        return admin_psql('-v', 'ON_ERROR_STOP=1', '-q', input=prefix + role_sql)

    @classmethod
    def role_url(cls, user, secret):
        return url(host=cls.parts.hostname, port=cls.parts.port or 5432, database=cls.parts.path.lstrip('/'),
                   user=user, secret=secret, sslmode='disable')

    def env(self, connection):
        return sql.libpq_environment(connection, self.target)

    def granted(self, grant, undo):
        """Temporarily give agent_readonly an extra privilege it must never hold."""
        self.admin(grant)
        self.addCleanup(self.admin, undo)

    def query(self, text):
        result = sql.run_session(self.env(self.readonly_url), sql.query_script(text), ['-At'])
        verified, problems, rest = sql.guard_result(result.stderr)
        self.assertEqual(problems, [])
        return result.returncode, result.stdout.strip(), rest

    def test_verifies_the_read_only_role_and_refuses_other_logins(self):
        self.assertEqual(sql.guard(self.env(self.readonly_url))['user'], 'agent_readonly')
        for other in [ADMIN_URL + '?sslmode=disable', self.role_url('analytics', 'x')]:
            with self.assertRaisesRegex(sql.SqlError, 'agent_readonly role'):
                self.env(other)

    def test_refuses_the_role_when_it_could_write(self):
        safe = 'agent_probe_safe_' + os.urandom(3).hex()
        schema = 'agent_probe_s_' + os.urandom(3).hex()
        cases = [('GRANT INSERT ON public.users TO agent_readonly', 'REVOKE INSERT ON public.users FROM agent_readonly',
                  'can write'),
                 ('GRANT UPDATE (email) ON public.users TO agent_readonly',
                  'REVOKE UPDATE (email) ON public.users FROM agent_readonly', 'can write'),
                 ('CREATE SEQUENCE IF NOT EXISTS public.agent_probe_seq; GRANT USAGE ON public.agent_probe_seq TO agent_readonly',
                  'DROP SEQUENCE public.agent_probe_seq', 'can write'),
                 ('GRANT pg_write_all_data TO agent_readonly', 'REVOKE pg_write_all_data FROM agent_readonly', 'member'),
                 (f'CREATE SCHEMA {schema} AUTHORIZATION agent_readonly', f'DROP SCHEMA {schema}', 'owns'),
                 ('GRANT CREATE ON SCHEMA public TO agent_readonly', 'REVOKE CREATE ON SCHEMA public FROM agent_readonly',
                  'create'),
                 (f'CREATE ROLE {safe} NOLOGIN; GRANT {safe} TO agent_readonly; ALTER ROLE agent_readonly SET role = {safe}',
                  f'ALTER ROLE agent_readonly RESET role; DROP ROLE {safe}', 'agent_readonly login')]
        for grant, undo, message in cases:
            with self.subTest(grant=grant):
                self.admin(grant)
                try:
                    with self.assertRaisesRegex(sql.SqlError, message):
                        sql.guard(self.env(self.readonly_url))
                finally:
                    self.admin(undo)
        sql.guard(self.env(self.readonly_url))

    def test_reads_allowed_columns_but_not_secrets(self):
        self.assertEqual(self.query('SELECT email FROM users WHERE id = 1')[:2], (0, 'member@example.invalid'))
        for text in ['SELECT password FROM users', 'SELECT token FROM user_auth_tokens', 'SELECT * FROM users']:
            code, _, rest = self.query(text)
            self.assertNotEqual(code, 0, text)
            self.assertIn('permission denied', rest)

    def test_writes_fail_inside_the_tool(self):
        for text in ["UPDATE users SET email = 'x'", "SELECT set_config('transaction_read_only', 'off', true)",
                     'SELECT lo_create(0)', 'CREATE TEMP TABLE t (i int)']:
            self.assertNotEqual(self.query(text)[0], 0, text)

    def test_refused_role_never_runs_the_query(self):
        self.granted('GRANT INSERT ON public.users TO agent_readonly', 'REVOKE INSERT ON public.users FROM agent_readonly')
        started = time.monotonic()
        with patch.object(sql, 'target', return_value=self.target), \
                patch.object(sql, 'connection_url', return_value=self.readonly_url), \
                patch('sys.stderr', new_callable=io.StringIO) as err:
            self.assertEqual(sql.main(['query', 'fixture', '-c', 'SELECT pg_sleep(5)']), 2)
        self.assertLess(time.monotonic() - started, 4)
        self.assertIn('can write', err.getvalue())

    def test_timeout_cancels_a_query_that_raises_its_own_statement_timeout(self):
        with patch.object(sql, 'target', return_value=self.target), \
                patch.object(sql, 'connection_url', return_value=self.readonly_url), \
                patch('sys.stderr', new_callable=io.StringIO) as err:
            code = sql.main(['query', 'fixture', '--timeout', '3', '-c',
                             "SELECT set_config('statement_timeout', '0', true), pg_sleep(60)"])
        self.assertEqual(code, 2)
        self.assertIn('cancelled the statement on the server', err.getvalue())
        running = ''
        for _ in range(20):
            running = admin_psql('-At', '-c',
                                 "SELECT count(*) FROM pg_stat_activity WHERE usename = 'agent_readonly' "
                                 "AND query LIKE '%pg_sleep(60)%' AND state = 'active'").stdout.strip()
            if running == '0':
                break
            time.sleep(0.25)
        self.assertEqual(running, '0')

    def test_role_sql_requires_a_verifier_and_clears_role_settings(self):
        template = admin_psql('-v', 'ON_ERROR_STOP=1', '-q', input=sql.ROLE_SQL.read_text())
        self.assertNotEqual(template.returncode, 0)
        self.admin('ALTER ROLE agent_readonly SET work_mem = 1234')
        self.assertEqual(self.run_role_sql().returncode, 0)
        settings = admin_psql('-At', '-c', "SELECT array_to_string(setconfig, ',') FROM pg_db_role_setting "
                                           "WHERE setrole = 'agent_readonly'::regrole").stdout
        self.assertNotIn('work_mem', settings)
        self.assertIn('default_transaction_read_only=on', settings)
        sql.guard(self.env(self.readonly_url))

    def test_prepare_then_activate_rotates_the_password(self):
        self.addCleanup(lambda: self.assertEqual(self.run_role_sql().returncode, 0))  # restore the class password
        with tempfile.TemporaryDirectory() as directory:
            FakeHosting.credentials = Path(directory) / 'db.env'
            self.addCleanup(setattr, FakeHosting, 'credentials', None)
            with patch.object(sql, 'target', return_value=self.target), patch.object(sql, '_hosting', return_value=FakeHosting), \
                    patch('sys.stdout', new_callable=io.StringIO), patch('sys.stderr', new_callable=io.StringIO):
                self.assertEqual(sql.main(['prepare', 'fixture']), 0)
                password = urllib.parse.unquote(urllib.parse.urlsplit(pending_url(directory)).password)
                sql.guard(self.env(self.readonly_url))  # the old password works until the owner step
                self.assertEqual(sql.main(['activate', 'fixture']), 2)
                setup = Path(directory) / 'fixture-readonly-role.sql'
                self.assertEqual(admin_psql('-v', 'ON_ERROR_STOP=1', '-q', '-f', str(setup)).returncode, 0)
                self.assertEqual(sql.main(['activate', 'fixture']), 0)
            stored = FakeHosting.credentials.read_text().strip().split('=', 1)[1].strip("'")
            self.assertEqual(urllib.parse.unquote(urllib.parse.urlsplit(stored).password), password)
            self.assertFalse(setup.exists())


    def test_role_sql_stops_on_layouts_that_would_expose_secrets(self):
        other = 'other' + os.urandom(8).hex()
        schema = 'agent_probe_x_' + os.urandom(3).hex()
        cases = [('GRANT SELECT ON public.users TO PUBLIC', 'REVOKE SELECT ON public.users FROM PUBLIC', 'can still read'),
                 ('GRANT SELECT (password) ON public.users TO PUBLIC', 'REVOKE SELECT (password) ON public.users FROM PUBLIC',
                  'can still read'),
                 ('CREATE VIEW public.agent_probe_inner AS SELECT password FROM public.users; '
                  'CREATE VIEW public.agent_probe_outer AS SELECT * FROM public.agent_probe_inner; '
                  'GRANT SELECT ON public.agent_probe_outer TO PUBLIC',
                  'DROP VIEW public.agent_probe_outer; DROP VIEW public.agent_probe_inner', 'can read views'),
                 (f'CREATE SCHEMA {schema}; CREATE TABLE {schema}.notes (id int); '
                  f'GRANT USAGE ON SCHEMA {schema} TO PUBLIC; GRANT SELECT ON {schema}.notes TO PUBLIC',
                  f'DROP SCHEMA {schema} CASCADE', 'outside public'),
                 ('CREATE FUNCTION public.agent_probe_definer() RETURNS text LANGUAGE sql SECURITY DEFINER '
                  'AS $$ SELECT password FROM public.users LIMIT 1 $$',
                  'DROP FUNCTION public.agent_probe_definer()', 'SECURITY DEFINER'),
                 ('CREATE TABLE public.agent_probe_child () INHERITS (public.user_auth_tokens)',
                  'DROP TABLE public.agent_probe_child', 'inheritance'),
                 ('GRANT CREATE ON SCHEMA public TO PUBLIC', 'REVOKE CREATE ON SCHEMA public FROM PUBLIC', 'PUBLIC can create'),
                 ]
        for change, undo, message in cases:
            with self.subTest(change=change):
                self.admin(change)
                try:
                    result = self.run_role_sql(secret=other)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(message, result.stderr)
                finally:
                    self.admin(undo)
                sql.guard(self.env(self.readonly_url))  # nothing changed: the old password still works

    def test_role_sql_clears_stale_and_derived_access(self):
        schema = 'agent_probe_o_' + os.urandom(3).hex()
        self.admin(f'CREATE SCHEMA {schema}; CREATE TABLE {schema}.notes (id int); '
                   f'GRANT USAGE ON SCHEMA {schema} TO agent_readonly; GRANT SELECT ON {schema}.notes TO agent_readonly; '
                   'GRANT SELECT (password) ON public.users TO agent_readonly; '
                   'ALTER TABLE public.users ADD COLUMN password_copy text GENERATED ALWAYS AS (password) STORED')
        self.addCleanup(self.admin, f'DROP SCHEMA {schema} CASCADE; ALTER TABLE public.users DROP COLUMN password_copy')
        self.assertEqual(self.run_role_sql().returncode, 0)
        for text in ['SELECT password FROM users', 'SELECT password_copy FROM users', f'SELECT * FROM {schema}.notes']:
            self.assertNotEqual(self.query(text)[0], 0, text)
        self.assertEqual(self.query('SELECT email FROM users WHERE id = 1')[:2], (0, 'member@example.invalid'))


if __name__ == '__main__':
    unittest.main()
