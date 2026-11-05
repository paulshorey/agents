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
            path.write_text(json.dumps({'schema_version': 1, 'targets': {'Bad Name': TARGET}}))
            with self.assertRaises(sql.SqlError):
                sql.load_targets(path)
            path.write_text(json.dumps({'schema_version': 1, 'targets': {'ok': {**TARGET, 'port': 'x'}}}))
            with self.assertRaises(sql.SqlError):
                sql.load_targets(path)

    def test_unknown_target(self):
        with self.assertRaises(sql.SqlError):
            sql.target('missing', {'fixture': TARGET})


class ConnectionTests(unittest.TestCase):
    def test_builds_libpq_environment_without_inherited_database_settings(self):
        url = 'postgresql://agent_readonly:p%40ss@db.example.test:6543/railway?sslmode=require'
        with patch.dict(os.environ, {'PGHOST': 'evil', 'DATABASE_URL': 'postgres://other', 'PATH': '/bin'}):
            env = sql.libpq_environment(url, TARGET)
        self.assertEqual(env['PGHOST'], 'db.example.test')
        self.assertEqual(env['PGPASSWORD'], 'p@ss')
        self.assertEqual(env['PGSSLMODE'], 'require')
        self.assertIn('default_transaction_read_only=on', env['PGOPTIONS'])
        self.assertNotIn('DATABASE_URL', env)

    def test_rejects_connections_that_do_not_match_the_target(self):
        for url in ['postgresql://u:p@other.test:6543/railway', 'postgresql://u:p@db.example.test:5432/railway',
                    'postgresql://u:p@db.example.test:6543/other', 'mysql://u:p@db.example.test:6543/railway',
                    'postgresql://u@db.example.test:6543/railway',
                    'postgresql://u:p@db.example.test:6543/railway?host=elsewhere']:
            with self.assertRaises(sql.SqlError, msg=url):
                sql.libpq_environment(url, TARGET)

    def test_missing_credential_explains_the_owner_step(self):
        class Hosting:
            class HostingError(Exception):
                pass

            @staticmethod
            def profile_environment(profile, base=None, variables=None):
                return {}
        with self.assertRaises(sql.SqlError) as raised:
            sql.connection_url(TARGET, Hosting)
        self.assertIn('set-url', str(raised.exception))


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


@unittest.skipUnless(ADMIN_URL and shutil.which('psql'), 'set AGENTS_SQL_TEST_ADMIN_URL to a disposable localhost database')
class LiveRoleTests(unittest.TestCase):
    """Applies the reference role SQL to a disposable local database."""

    @classmethod
    def setUpClass(cls):
        parts = urllib.parse.urlsplit(ADMIN_URL)
        if parts.hostname not in ('127.0.0.1', 'localhost'):
            raise unittest.SkipTest('live role tests only run against localhost')
        cls.target = {**TARGET, 'host': parts.hostname, 'port': parts.port or 5432,
                      'database': parts.path.lstrip('/')}
        role_sql = (ROOT / 'skills/database-query/references/readonly-role.sql').read_text()
        cls.password = 'fixture-' + os.urandom(8).hex()
        fixture = """
          CREATE TABLE IF NOT EXISTS public.users (id bigint PRIMARY KEY, email text, password text, api_token text);
          CREATE TABLE IF NOT EXISTS public.user_auth_tokens (id bigint PRIMARY KEY, token text);
          INSERT INTO public.users VALUES (1, 'member@example.invalid', 'hash', 'tok') ON CONFLICT DO NOTHING;
        """
        subprocess.run(['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-q', ADMIN_URL, '-c', fixture], check=True,
                       capture_output=True)
        subprocess.run(['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-q', ADMIN_URL],
                       input=role_sql.replace('REPLACE_WITH_GENERATED_PASSWORD', cls.password), text=True,
                       check=True, capture_output=True)
        cls.readonly_url = urllib.parse.urlunsplit(
            ('postgresql', f'agent_readonly:{cls.password}@{parts.hostname}:{parts.port or 5432}',
             parts.path, '', ''))

    def env(self, url):
        return sql.libpq_environment(url, self.target)

    def test_verifies_the_read_only_role_and_refuses_the_owner(self):
        verified = sql.guard(self.env(self.readonly_url))
        self.assertEqual(verified['user'], 'agent_readonly')
        owner = urllib.parse.urlsplit(ADMIN_URL)
        owner_url = urllib.parse.urlunsplit(('postgresql', f'{owner.username}:{owner.password or "x"}@{owner.hostname}:{owner.port or 5432}', owner.path, '', ''))
        with self.assertRaises(sql.SqlError) as raised:
            sql.guard(self.env(owner_url))
        self.assertIn('Refusing to run', str(raised.exception))

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
        with tempfile.TemporaryDirectory() as directory:
            creds = Path(directory) / 'db.env'
            with patch.object(sql, 'target', return_value=self.target), \
                    patch.object(sql, 'connection_url', return_value=self.readonly_url), \
                    patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(sql.main(['check', 'fixture']), 0)
            with patch.object(sql, 'target', return_value=self.target), \
                    patch.object(sql, 'connection_url', return_value=self.readonly_url):
                self.assertEqual(sql.main(['query', 'fixture', '-c', 'SELECT count(*) FROM public.users']), 0)
            self.assertFalse(creds.exists())


if __name__ == '__main__':
    unittest.main()
