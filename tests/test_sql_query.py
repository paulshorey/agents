import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
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
                            {'ok': {**TARGET, 'profile': '/tmp/creds.env'}}]:
                path.write_text(json.dumps({'schema_version': 1, 'targets': targets}))
                with self.assertRaises(sql.SqlError, msg=targets):
                    sql.load_targets(path)

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
                    patch.object(sql.subprocess, 'run') as run, patch('sys.stderr', new_callable=io.StringIO):
                self.assertEqual(sql.main(['query', 'fixture', '-c', text]), 2, text)
            connection.assert_not_called()
            run.assert_not_called()
        for text, count in [('SELECT $$a;b$$', 1), ("SELECT ';' -- x;", 1), ('/* ; */ SELECT 1;', 1), ('SELECT 1; SELECT 2', 2)]:
            self.assertEqual(sql.statement_count(text), count, text)

    def test_query_command_never_starts_psql_for_meta_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'q.sql'
            script.write_text('SELECT 1;\n\\! env\n')
            for args in [['-c', '\\! env'], ['-f', str(script)]]:
                with patch.object(sql, 'target', return_value=TARGET), \
                        patch.object(sql, 'connection_url') as connection, \
                        patch.object(sql.subprocess, 'run') as run, patch('sys.stderr', new_callable=io.StringIO):
                    self.assertEqual(sql.main(['query', 'fixture', *args]), 2)
                connection.assert_not_called()
                run.assert_not_called()


class CredentialFileTests(unittest.TestCase):
    def test_replaces_one_assignment_atomically_and_keeps_mode_600(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'creds' / 'db.env'
            sql.write_profile_value(path, 'A_URL', 'postgresql://a')
            sql.write_profile_value(path, 'B_URL', 'postgresql://b')
            sql.write_profile_value(path, 'A_URL', 'postgresql://a2')
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.read_text(), "B_URL='postgresql://b'\nA_URL='postgresql://a2'\n")

    def test_refuses_a_group_readable_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db.env'
            path.write_text('')
            path.chmod(0o644)
            with self.assertRaises(sql.SqlError):
                sql.write_profile_value(path, 'A_URL', 'postgresql://a')


ADMIN_URL = os.environ.get('AGENTS_SQL_TEST_ADMIN_URL')
WITHHELD = {'users': ['password', 'api_token'], 'user_auth_tokens': '*', 'missing_table': '*',
            'users_missing': ['token']}


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
        cls.admin("""
          CREATE TABLE IF NOT EXISTS public.users (id bigint PRIMARY KEY, email text, password text, api_token text);
          CREATE TABLE IF NOT EXISTS public.user_auth_tokens (id bigint PRIMARY KEY, token text);
          INSERT INTO public.users VALUES (1, 'member@example.invalid', 'hash', 'tok') ON CONFLICT DO NOTHING;
        """)
        subprocess.run(['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-q', ADMIN_URL],
                       input=role_sql.replace('REPLACE_WITH_GENERATED_PASSWORD', cls.secret), text=True,
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
        self.assertEqual(sql.guard(self.env(self.readonly_url), WITHHELD)['user'], 'agent_readonly')
        owner = self.role_url(self.parts.username, urllib.parse.unquote(self.parts.password or 'x'))
        with self.assertRaises(sql.SqlError) as raised:
            sql.guard(self.env(owner))
        self.assertIn('Refusing to run', str(raised.exception))

    def test_refuses_column_level_write_grants(self):
        role = self.scratch_role('GRANT SELECT (id, email) ON public.users TO {role}; GRANT UPDATE (email) ON public.users TO {role};')
        with self.assertRaises(sql.SqlError) as raised:
            sql.guard(self.env(role))
        self.assertIn('write', str(raised.exception))

    def test_refuses_inherited_read_all_data(self):
        role = self.scratch_role('GRANT pg_read_all_data TO {role};')
        with self.assertRaises(sql.SqlError) as raised:
            sql.guard(self.env(role), WITHHELD)
        self.assertIn('pg_read_all_data', str(raised.exception))

    def test_refuses_a_role_that_can_read_withheld_secrets(self):
        role = self.scratch_role('GRANT SELECT ON public.users TO {role};')
        with self.assertRaises(sql.SqlError) as raised:
            sql.guard(self.env(role), WITHHELD)
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
                    sql.guard(self.env(role))

    def test_refuses_executable_security_definer_routines(self):
        self.admin('CREATE FUNCTION public.agent_probe_definer() RETURNS int LANGUAGE sql SECURITY DEFINER AS $$ SELECT 1 $$')
        self.addCleanup(self.admin, 'DROP FUNCTION public.agent_probe_definer()')
        with self.assertRaises(sql.SqlError) as raised:
            sql.guard(self.env(self.readonly_url), WITHHELD)
        self.assertIn('agent_probe_definer', str(raised.exception))

    def test_tool_queries_run_in_an_enforced_read_only_transaction(self):
        self.admin('CREATE SEQUENCE IF NOT EXISTS public.probe_ro_seq')
        self.addCleanup(self.admin, 'DROP SEQUENCE IF EXISTS public.probe_ro_seq')
        before = subprocess.run(['psql', '-X', '-At', ADMIN_URL, '-c', 'SELECT count(*) FROM pg_largeobject_metadata'],
                                capture_output=True, text=True, check=True).stdout
        for statement in ['SET transaction_read_only = off', "SELECT lo_from_bytea(0, 'x')",
                          'CREATE TEMP TABLE agent_probe_temp (id int)', "UPDATE public.users SET email='x'"]:
            with patch.object(sql, 'target', return_value=self.target), \
                    patch.object(sql, 'connection_url', return_value=self.readonly_url), \
                    patch('sys.stderr', new_callable=io.StringIO):
                self.assertNotEqual(sql.main(['query', 'fixture', '-c', statement]), 0, statement)
        with patch.object(sql, 'target', return_value=self.target), \
                patch.object(sql, 'connection_url', return_value=self.readonly_url), \
                patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(sql.main(['query', 'fixture', '-c', 'COMMIT']), 0)
        after = subprocess.run(['psql', '-X', '-At', ADMIN_URL, '-c', 'SELECT count(*) FROM pg_largeobject_metadata'],
                               capture_output=True, text=True, check=True).stdout
        self.assertEqual(before, after, 'no large object was created')

    def test_reads_allowed_columns_but_never_writes_or_reads_secrets(self):
        env = self.env(self.readonly_url)
        ok = sql.run_psql(env, ['-At', '-c', 'SELECT email FROM public.users WHERE id=1'])
        self.assertEqual(ok.stdout.strip(), 'member@example.invalid')
        for statement in ['SELECT password FROM public.users', 'SELECT token FROM public.user_auth_tokens',
                          "SET transaction_read_only=off; UPDATE public.users SET email='x'",
                          'BEGIN READ WRITE; DELETE FROM public.users; COMMIT',
                          'CREATE TABLE public.agent_probe(id int)']:
            denied = sql.run_psql(env, ['-At', '-c', statement])
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
