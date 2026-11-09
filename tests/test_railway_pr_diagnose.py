import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
SPEC = importlib.util.spec_from_file_location('railway_pr_diagnose', ROOT / 'scripts/railway-pr-diagnose.py')
diagnose = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnose)


def service(name='app', status='SUCCESS', volumes=(), variables=(), step=None):
    deployment = {'id': 'd1', 'status': status, 'step': step} if status else None
    return {'name': name, 'deployment': deployment, 'volumes': list(volumes), 'variables': list(variables)}


class ClassifyTests(unittest.TestCase):
    def test_whole_value_reference_exposes_only_its_target(self):
        self.assertEqual(diagnose.classify('${{Postgres.DATABASE_URL}}'), ('reference', 'Postgres.DATABASE_URL'))
        self.assertEqual(diagnose.classify('${{ Postgres.DATABASE_URL }}'), ('reference', 'Postgres.DATABASE_URL'))

    def test_partial_reference_and_literal_expose_nothing(self):
        self.assertEqual(diagnose.classify('postgres://a:b@${{Postgres.HOST}}/d'), ('mixed', None))
        self.assertEqual(diagnose.classify('postgres://user:pw@host/db'), ('literal', None))
        self.assertEqual(diagnose.classify(''), ('empty', None))

    def test_report_never_contains_values_and_hides_railway_names(self):
        shown, hidden = diagnose.variable_report({'API_KEY': 'hunter2-secret', 'RAILWAY_PUBLIC_DOMAIN': 'x.up'})
        self.assertEqual(hidden, 1)
        self.assertNotIn('hunter2', repr(shown))
        self.assertEqual(shown, [{'name': 'API_KEY', 'kind': 'literal', 'target': None}])


class RedactTests(unittest.TestCase):
    def test_known_values_and_credential_shapes_are_masked(self):
        line = 'connect postgres://app:pw123@db/x token=abc123 Bearer zzz using hunter2-secret'
        result = diagnose.redact(line, ['hunter2-secret'])
        for secret in ('pw123', 'abc123', 'zzz', 'hunter2-secret'):
            self.assertNotIn(secret, result)
        self.assertIn('connect postgres://app:', result)

    def test_short_masks_do_not_erase_ordinary_text(self):
        self.assertEqual(diagnose.redact('build failed', ['a', 'true']), 'build failed')
        self.assertEqual(diagnose.redact('abcdef is true', ['abc', 'true']), 'abcdef is true')

    def test_short_values_are_masked_as_whole_words(self):
        self.assertEqual(diagnose.redact('code abcde here', ['abcde']), f'code {diagnose.MASK} here')

    def test_jwt_and_long_tokens_are_masked(self):
        jwt = 'eyJhbGciOiJ.eyJzdWIiOiIx.c2lnbmF0dXJl'
        self.assertNotIn(jwt, diagnose.redact(f'value {jwt}'))
        self.assertNotIn('a' * 40, diagnose.redact('sha ' + 'a' * 40))


class StepTests(unittest.TestCase):
    def test_pre_deploy_error_beats_a_build_success(self):
        events = [
            {'step': 'BUILD_IMAGE', 'createdAt': '1', 'completedAt': '2', 'payload': {}},
            {'step': 'PRE_DEPLOY_COMMAND', 'createdAt': '3', 'completedAt': '4',
             'payload': {'error': 'exited with 1'}},
        ]
        self.assertEqual(diagnose.failing_step(events), ('PRE_DEPLOY_COMMAND', 'exited with 1'))

    def test_unfinished_step_is_reported_when_no_error_exists(self):
        events = [
            {'step': 'BUILD_IMAGE', 'createdAt': '1', 'completedAt': '2', 'payload': None},
            {'step': 'HEALTHCHECK', 'createdAt': '3', 'completedAt': None, 'payload': None},
        ]
        self.assertEqual(diagnose.failing_step(events), ('HEALTHCHECK', None))

    def test_reason_identifies_a_completed_failed_step(self):
        events = [{'step': 'HEALTHCHECK', 'createdAt': '1', 'completedAt': '2', 'payload': {'reason': 'timed out'}}]
        self.assertEqual(diagnose.failing_step(events), ('HEALTHCHECK', 'timed out'))
        self.assertEqual(diagnose.failing_step(events, failed=False), (None, None))

    def test_no_events_has_no_step(self):
        self.assertEqual(diagnose.failing_step([]), (None, None))


class LogTests(unittest.TestCase):
    def test_error_lines_come_first_and_are_distinct(self):
        logs = [{'message': 'installing'}, {'message': 'getaddrinfo ENOTFOUND postgres.railway.internal'},
                {'message': 'getaddrinfo ENOTFOUND postgres.railway.internal'}, {'message': 'done', 'severity': 'error'}]
        self.assertEqual(diagnose.error_lines(logs, 5), ['getaddrinfo ENOTFOUND postgres.railway.internal', 'done'])

    def test_final_lines_are_used_when_nothing_looks_like_an_error(self):
        logs = [{'message': 'one'}, {'message': 'two'}, {'message': 'three'}]
        self.assertEqual(diagnose.error_lines(logs, 2), ['two', 'three'])


class EnvironmentTests(unittest.TestCase):
    ENVIRONMENTS = [{'id': 'e1', 'name': 'dev'}, {'id': 'e2', 'name': 'notes-pr-119'}, {'id': 'e3', 'name': 'notes-pr-11'}]

    def test_pr_number_matches_the_exact_suffix(self):
        self.assertEqual(diagnose.find_environment(self.ENVIRONMENTS, '11')['id'], 'e3')
        self.assertEqual(diagnose.find_environment(self.ENVIRONMENTS, '119')['id'], 'e2')

    def test_ambiguous_pr_number_is_rejected(self):
        environments = [{'id': 'a', 'name': 'web-pr-7'}, {'id': 'b', 'name': 'api-pr-7'}]
        with self.assertRaises(diagnose.DiagnosisError):
            diagnose.find_environment(environments, '7')

    def test_names_and_ids_match_exactly(self):
        self.assertEqual(diagnose.find_environment(self.ENVIRONMENTS, 'dev')['id'], 'e1')
        self.assertEqual(diagnose.find_environment(self.ENVIRONMENTS, 'e2')['name'], 'notes-pr-119')
        self.assertIsNone(diagnose.find_environment(self.ENVIRONMENTS, '120'))


class ProblemTests(unittest.TestCase):
    def test_healthy_service_has_no_problems(self):
        self.assertEqual(diagnose.service_problems(service(), {'app': 'SUCCESS'}), [])

    def test_missing_and_skipped_deployments_are_reported(self):
        self.assertIn('no deployment ran', diagnose.service_problems(service(status=None), {})[0])
        self.assertIn('no deployment ran', diagnose.service_problems(service(status='SKIPPED'), {})[0])

    def test_failed_deployment_names_its_step(self):
        result = diagnose.service_problems(service(status='FAILED', step='PRE_DEPLOY_COMMAND'), {})
        self.assertEqual(result, ['app: FAILED at PRE_DEPLOY_COMMAND.'])

    def test_database_without_volume_is_reported(self):
        result = diagnose.service_problems(service(name='Postgres'), {'Postgres': 'SUCCESS'})
        self.assertEqual(result, ['Postgres: database service has no volume in this environment.'])

    def test_only_unambiguous_names_count_as_databases(self):
        self.assertEqual(diagnose.service_problems(service(name='postgres-exporter'), {'postgres-exporter': 'SUCCESS'}), [])

    def test_sleeping_dependency_is_available(self):
        variables = [{'name': 'CACHE_URL', 'kind': 'reference', 'target': 'cache.URL'}]
        self.assertEqual(diagnose.service_problems(service(variables=variables), {'app': 'SUCCESS', 'cache': 'SLEEPING'}), [])

    def test_literal_database_url_is_reported(self):
        variables = [{'name': 'DB_NOTES_URL', 'kind': 'literal', 'target': None}]
        self.assertIn('must be a reference', diagnose.service_problems(service(variables=variables), {})[0])

    def test_reference_to_undeployed_or_absent_service_is_reported(self):
        variables = [{'name': 'DB_NOTES_URL', 'kind': 'reference', 'target': 'Postgres.DATABASE_URL'}]
        skipped = diagnose.service_problems(service(variables=variables), {'app': 'SUCCESS', 'Postgres': 'SKIPPED'})
        self.assertIn('whose latest deployment is SKIPPED', skipped[0])
        absent = diagnose.service_problems(service(variables=variables), {'app': 'SUCCESS'})
        self.assertIn('not in this environment', absent[0])

    def test_bucket_references_are_not_service_references(self):
        variables = [{'name': 'MEDIA_BUCKET_NAME', 'kind': 'reference', 'target': 'media.BUCKET'}]
        self.assertEqual(diagnose.service_problems(service(variables=variables), {'app': 'SUCCESS'}, {'media'}), [])

    def test_shared_references_are_not_service_references(self):
        variables = [{'name': 'KEY', 'kind': 'reference', 'target': 'shared.KEY'}]
        self.assertEqual(diagnose.service_problems(service(variables=variables), {'app': 'SUCCESS'}), [])


if __name__ == '__main__':
    unittest.main()
