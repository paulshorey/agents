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
                            {'ok': {**TARGET, 'withheld': {'a.b.c': '*'}}},
                            {'ok': {**TARGET, 'withheld': {'Auth.tokens': '*'}}},
                            {'ok': {**TARGET, 'profile': '/tmp/creds.env'}}]:
                path.write_text(json.dumps({'schema_version': 1, 'targets': targets}))
                path.chmod(0o600)
                with self.assertRaises(sql.SqlError, msg=targets):
                    sql.load_targets(path)

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
WITHHELD = {'users': ['password', 'api_token'], 'user_auth_tokens': '*'}


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
                    sql.guard(self.env(self.readonly_url), WITHHELD)
                self.assertIn(exposed, str(raised.exception))
                self.admin(grants.replace('GRANT SELECT', 'REVOKE ALL').replace(' TO ', ' FROM '))
        sql.guard(self.env(self.readonly_url), WITHHELD)

    def test_fails_closed_on_missing_withheld_entries(self):
        for withheld, missing in [({'no_such_table': '*'}, 'public.no_such_table'),
                                  ({'users': ['no_such_column']}, 'public.users.no_such_column')]:
            with self.subTest(missing), self.assertRaises(sql.SqlError) as raised:
                sql.guard(self.env(self.readonly_url), {**WITHHELD, **withheld})
            self.assertIn(missing, str(raised.exception))

    def test_checks_withheld_relations_outside_public(self):
        self.admin('CREATE SCHEMA IF NOT EXISTS agent_probe_auth; CREATE TABLE agent_probe_auth.tokens (token text); '
                   'GRANT USAGE ON SCHEMA agent_probe_auth TO agent_readonly; GRANT SELECT ON agent_probe_auth.tokens TO agent_readonly')
        self.addCleanup(self.admin, 'DROP SCHEMA agent_probe_auth CASCADE')
        with self.assertRaises(sql.SqlError) as raised:
            sql.guard(self.env(self.readonly_url), {**WITHHELD, 'agent_probe_auth.tokens': '*'})
        self.assertIn('agent_probe_auth.tokens', str(raised.exception))

    def test_refuses_security_definer_routines_in_system_schemas(self):
        self.admin('CREATE FUNCTION information_schema.agent_probe_definer() RETURNS int LANGUAGE sql SECURITY DEFINER AS $$ SELECT 1 $$')
        self.addCleanup(self.admin, 'DROP FUNCTION information_schema.agent_probe_definer()')
        with self.assertRaises(sql.SqlError) as raised:
            sql.guard(self.env(self.readonly_url), WITHHELD)
        self.assertIn('agent_probe_definer', str(raised.exception))

    def test_refuses_untrusted_language_routines(self):
        # A language created without TRUSTED is untrusted; reuse plpgsql's handler.
        self.admin('CREATE LANGUAGE agent_probe_lang HANDLER plpgsql_call_handler; '
                   'CREATE FUNCTION public.agent_probe_untrusted() RETURNS int LANGUAGE agent_probe_lang '
                   'AS $$ BEGIN RETURN 1; END $$')
        self.addCleanup(self.admin, 'DROP LANGUAGE agent_probe_lang CASCADE')
        with self.assertRaises(sql.SqlError) as raised:
            sql.guard(self.env(self.readonly_url), WITHHELD)
        self.assertIn('agent_probe_untrusted', str(raised.exception))

    def test_refuses_foreign_data_wrapper_usage(self):
        self.admin('CREATE FOREIGN DATA WRAPPER agent_probe_fdw')
        self.addCleanup(self.admin, 'DROP FOREIGN DATA WRAPPER agent_probe_fdw CASCADE')
        role = self.scratch_role('GRANT USAGE ON FOREIGN DATA WRAPPER agent_probe_fdw TO {role};')
        with self.assertRaises(sql.SqlError) as raised:
            sql.guard(self.env(role))
        self.assertIn('foreign servers', str(raised.exception))

    def test_role_sql_refuses_the_placeholder_password(self):
        role_sql = (ROOT / 'skills/database-query/references/readonly-role.sql').read_text()
        for unsafe in [role_sql, role_sql.replace('REPLACE_WITH_GENERATED_PASSWORD', 'short')]:
            failed = subprocess.run(['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-q', ADMIN_URL], input=unsafe, text=True,
                                    capture_output=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn('at least 20 characters', failed.stderr)
        sql.guard(self.env(self.readonly_url), WITHHELD)  # the existing password still works

    def test_refuses_granted_file_reading_built_ins(self):
        role = self.scratch_role('GRANT EXECUTE ON FUNCTION pg_read_file(text) TO {role};')
        with self.assertRaises(sql.SqlError) as raised:
            sql.guard(self.env(role))
        self.assertIn('pg_read_file', str(raised.exception))

    def test_refuses_whole_row_views_over_withheld_columns(self):
        self.admin('CREATE VIEW public.agent_probe_rows AS SELECT u FROM public.users u; '
                   'CREATE VIEW public.agent_probe_safe AS SELECT id, email FROM public.users; '
                   'GRANT SELECT ON public.agent_probe_safe TO agent_readonly')
        self.addCleanup(self.admin, 'DROP VIEW IF EXISTS public.agent_probe_rows, public.agent_probe_safe')
        sql.guard(self.env(self.readonly_url), WITHHELD)  # a column-only view is fine
        self.admin('GRANT SELECT ON public.agent_probe_rows TO agent_readonly')
        with self.assertRaises(sql.SqlError) as raised:
            sql.guard(self.env(self.readonly_url), WITHHELD)
        self.assertIn('agent_probe_rows', str(raised.exception))

    def test_role_search_path_cannot_shadow_the_catalogs(self):
        role = self.scratch_role('CREATE SCHEMA agent_probe_shadow_{role} AUTHORIZATION {role}; '
                                 'CREATE VIEW agent_probe_shadow_{role}.pg_shdepend AS SELECT * FROM pg_catalog.pg_shdepend WHERE false; '
                                 'ALTER VIEW agent_probe_shadow_{role}.pg_shdepend OWNER TO {role}; '
                                 'ALTER ROLE {role} SET search_path = agent_probe_shadow_{role}, pg_catalog;')
        name = urllib.parse.urlsplit(role).username
        self.addCleanup(self.admin, f'DROP SCHEMA IF EXISTS agent_probe_shadow_{name} CASCADE')
        with self.assertRaises(sql.SqlError) as raised:
            sql.guard(self.env(role))
        self.assertIn('owns database objects', str(raised.exception))

    def test_role_sql_handles_tables_with_only_secret_columns(self):
        self.admin('CREATE TABLE IF NOT EXISTS public.device_push_tokens (token text)')
        self.addCleanup(self.admin, 'DROP TABLE IF EXISTS public.device_push_tokens')
        role_sql = (ROOT / 'skills/database-query/references/readonly-role.sql').read_text()
        subprocess.run(['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-q', ADMIN_URL],
                       input=role_sql.replace('REPLACE_WITH_GENERATED_PASSWORD', self.secret), text=True,
                       check=True, capture_output=True)
        sql.guard(self.env(self.readonly_url), {**WITHHELD, 'device_push_tokens': ['token']})

    def test_role_sql_withholds_secrets_on_child_tables(self):
        self.admin('CREATE TABLE public.agent_probe_child2 () INHERITS (public.user_auth_tokens)')
        self.addCleanup(self.admin, 'DROP TABLE IF EXISTS public.agent_probe_child2')
        role_sql = (ROOT / 'skills/database-query/references/readonly-role.sql').read_text()
        subprocess.run(['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-q', ADMIN_URL],
                       input=role_sql.replace('REPLACE_WITH_GENERATED_PASSWORD', self.secret), text=True,
                       check=True, capture_output=True)
        sql.guard(self.env(self.readonly_url), WITHHELD)

    def test_refuses_wal_writing_routines(self):
        role = self.scratch_role("DO $$ DECLARE f regprocedure; BEGIN FOR f IN SELECT oid::regprocedure FROM pg_proc "
                                 "WHERE proname='pg_logical_emit_message' LOOP EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO {role}', f); "
                                 "END LOOP; END $$;")
        with self.assertRaises(sql.SqlError) as raised:
            sql.guard(self.env(role))
        self.assertIn('pg_logical_emit_message', str(raised.exception))

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
