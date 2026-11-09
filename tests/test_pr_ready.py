import copy
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('pr_ready', ROOT / 'scripts/pr-ready.py')
pr_ready = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pr_ready)
HEAD = 'a' * 40
URL = 'https://github.com/example/project/pull/7'
READY = {
    'pr': {'state': 'open', 'merged': False, 'draft': False, 'mergeable': True, 'mergeable_state': 'clean',
           'url': URL, 'head': {'sha': HEAD}, 'base': {'sha': 'b' * 40}, 'reviewDecision': None},
    'codex_review': {'covers_head': True, 'outcome': 'clean'},
    'threads': [{'isResolved': True}],
    'checks': [{'name': 'validate', 'status': 'completed', 'conclusion': 'success'}],
    'statuses': [{'context': 'agent/ready', 'state': 'pending'}, {'context': 'GitGuardian', 'state': 'success'}],
}


def changed(**updates):
    context = copy.deepcopy(READY)
    for path, value in updates.items():
        target = context
        *parents, key = path.split('__')
        for parent in parents:
            target = target[parent]
        target[key] = value
    return context


class ReadinessTests(unittest.TestCase):
    def test_ready_when_every_condition_holds(self):
        self.assertEqual(pr_ready.readiness(READY), [])

    def test_reports_each_unmet_condition(self):
        cases = [
            (changed(pr__state='closed'), 'not open'),
            (changed(pr__draft=True), 'draft'),
            (changed(pr__mergeable_state='dirty'), 'conflicts'),
            (changed(pr__mergeable=None), 'still computing mergeability'),
            (changed(pr__reviewDecision='CHANGES_REQUESTED'), 'requested changes'),
            (changed(codex_review={'covers_head': False, 'outcome': 'clean'}), 'waiting for Codex review of aaaaaaa'),
            (changed(codex_review=None), 'waiting for Codex review'),
            (changed(codex_review={'covers_head': True, 'outcome': 'findings'}), 'is findings'),
            (changed(codex_review={'covers_head': True, 'outcome': 'ambiguous'}), 'is ambiguous'),
            (changed(threads=[{'isResolved': False}, {'isResolved': False}]), '2 unresolved'),
            (changed(checks=[{'name': 'validate', 'status': 'in_progress'}]), 'validate is in_progress'),
            (changed(checks=[{'name': 'validate', 'status': 'completed', 'conclusion': 'failure'}]), 'validate failure'),
            (changed(statuses=[{'context': 'GitGuardian', 'state': 'failure'}]), 'GitGuardian is failure'),
        ]
        for context, expected in cases:
            with self.subTest(expected=expected):
                self.assertTrue(any(expected in reason for reason in pr_ready.readiness(context)),
                                pr_ready.readiness(context))

    def test_ignores_its_own_previous_status(self):
        self.assertEqual(pr_ready.readiness(changed(statuses=[{'context': 'agent/ready', 'state': 'failure'}])), [])


class FakeApi:
    host, prefix, pull = 'github.com', 'repos/example/project', 'repos/example/project/pulls/7'

    def __init__(self, state='open', head=HEAD, checks=None):
        self.state, self.head = state, head
        self.checks = checks if checks is not None else [{'name': 'validate', 'status': 'completed', 'conclusion': 'success'}]

    def api(self, path):
        return {'state': self.state, 'head': {'sha': self.head}, 'html_url': URL}

    def pages(self, path, key=None):
        if key == 'check_runs':
            return self.checks
        return [{'context': 'agent/ready', 'state': 'pending', 'description': 'old', 'updated_at': '1', 'id': 1},
                {'context': 'agent/ready', 'state': 'success', 'description': 'new', 'updated_at': '2', 'id': 2}]


GATE_STATUS = {'context': 'PR checks finished', 'state': 'pending',
               'creator': {'login': 'github-actions[bot]'}}
OBSERVER_CHECK = {'name': 'Observe PR check completion', 'status': 'in_progress',
                  'app': {'slug': 'github-actions'}}


class CompletionApi(FakeApi):
    def __init__(self):
        super().__init__()
        self.merge = 'm' * 40
        self.calls = []
        self.by_ref = {
            HEAD: {'checks': [copy.deepcopy(OBSERVER_CHECK)], 'statuses': [copy.deepcopy(GATE_STATUS)]},
            self.merge: {'checks': [{'name': 'test merge', 'status': 'completed', 'conclusion': 'success'}],
                         'statuses': []},
        }
        self.runs = [{'name': 'PR completion', 'path': pr_ready.COMPLETION_WORKFLOW,
                      'status': 'in_progress'}]

    def api(self, path):
        return {**super().api(path), 'merge_commit_sha': self.merge}

    def pages(self, path, key=None):
        self.calls.append(path)
        if key == 'workflow_runs':
            return self.runs
        ref = path.split('/commits/')[1].split('/')[0]
        return self.by_ref[ref]['checks' if key == 'check_runs' else 'statuses']


class CompletionObserverTests(unittest.TestCase):
    def test_completion_observer_does_not_wait_on_agent_ready(self):
        for state, conclusion in [('in_progress', None), ('completed', 'failure'), ('completed', 'cancelled')]:
            checks = [{**OBSERVER_CHECK, 'status': state, 'conclusion': conclusion}]
            self.assertEqual(pr_ready.readiness(changed(checks=checks, statuses=[GATE_STATUS])), [])
        api = CompletionApi()
        self.assertEqual(pr_ready.recheck(api, READY), [])
        self.assertTrue(any(api.merge in path for path in api.calls))
        self.assertEqual(sum('actions/runs?' in path for path in api.calls), 2)

    def test_completion_names_alone_cannot_bypass_checks(self):
        for creator in [None, {'login': 'other-app[bot]'}]:
            self.assertTrue(pr_ready.readiness(changed(checks=[OBSERVER_CHECK], statuses=[
                {**GATE_STATUS, 'creator': creator}])))
        self.assertTrue(pr_ready.readiness(changed(checks=[
            {**OBSERVER_CHECK, 'app': {'slug': 'another-app'}}], statuses=[GATE_STATUS])))
        self.assertTrue(pr_ready.readiness(changed(checks=[
            {'name': 'CI', 'status': 'completed', 'conclusion': 'failure'}], statuses=[GATE_STATUS])))

    def test_pending_and_failed_test_merge_signals_still_block(self):
        for state, conclusion in [('in_progress', None), ('completed', 'failure')]:
            api = CompletionApi()
            api.by_ref[api.merge]['checks'][0].update(status=state, conclusion=conclusion)
            self.assertTrue(pr_ready.recheck(api, READY))
        api = CompletionApi()
        api.by_ref[api.merge]['statuses'] = [{'context': 'Railway', 'state': 'failure'}]
        self.assertTrue(pr_ready.recheck(api, READY))

    def test_queued_workflow_blocks_before_check_registration(self):
        api = CompletionApi()
        api.runs.append({'name': 'CI', 'path': '.github/workflows/ci.yml', 'status': 'queued'})
        self.assertTrue(any('workflow CI' in r for r in pr_ready.recheck(api, READY)))

    def test_absent_or_changed_test_merge_cannot_pass(self):
        api = CompletionApi()
        api.merge = None
        self.assertTrue(pr_ready.recheck(api, READY))
        api = CompletionApi()
        original = api.api
        calls = []
        def change_merge(path):
            calls.append(path)
            result = original(path)
            if len(calls) > 1:
                result['merge_commit_sha'] = 'new-merge'
            return result
        api.api = change_merge
        self.assertIn('the test-merge revision changed', pr_ready.recheck(api, READY))


class CommandTests(unittest.TestCase):
    def run_main(self, argv, api=None, context=READY):
        posted = []
        with patch.object(pr_ready, 'resolve', return_value=api or FakeApi()), \
                patch.object(pr_ready.pr_context, 'fetch_context', return_value=copy.deepcopy(context)), \
                patch.object(pr_ready.pr_context, 'gh', side_effect=lambda *a: posted.append(a) or {}), \
                patch('sys.stdout', new_callable=io.StringIO) as out, patch('sys.stderr', new_callable=io.StringIO) as err:
            code = pr_ready.main(argv)
        fields = [dict(arg.split('=', 1) for arg in call[call.index('-f') + 1::2]) for call in posted]
        return code, fields, posted, out.getvalue() + err.getvalue()

    def test_ready_posts_success_on_the_head(self):
        code, fields, posted, _ = self.run_main(['ready', '7', '--note', '182 tests pass'])
        self.assertEqual(code, 0)
        self.assertIn(f'repos/example/project/statuses/{HEAD}', posted[0])
        self.assertEqual(fields[0]['state'], 'success')
        self.assertEqual(fields[0]['context'], 'agent/ready')
        self.assertEqual(fields[0]['description'], 'Ready to merge: Codex clean on aaaaaaa (base bbbbbbb); 182 tests pass')

    def test_ready_rechecks_before_posting(self):
        rerun = FakeApi(checks=[{'name': 'validate', 'status': 'in_progress'}])
        code, fields, _, _ = self.run_main(['ready', '7'], api=rerun)
        self.assertEqual((code, fields[0]['state']), (1, 'pending'))
        self.assertIn('validate is in_progress', fields[0]['description'])
        code, fields, _, _ = self.run_main(['ready', '7'], api=FakeApi(head='c' * 40))
        self.assertEqual(code, 1)
        self.assertIn('head changed', fields[0]['description'])

    def test_reports_missing_status_permission_distinctly(self):
        def refuse(*args):
            raise pr_ready.pr_context.FetchError('gh api failed (exit 1; HTTP 403).')
        with patch.object(pr_ready, 'resolve', return_value=FakeApi()), \
                patch.object(pr_ready.pr_context, 'fetch_context', return_value=copy.deepcopy(READY)), \
                patch.object(pr_ready.pr_context, 'gh', side_effect=refuse), \
                patch('sys.stderr', new_callable=io.StringIO) as err:
            self.assertEqual(pr_ready.main(['ready', '7']), 3)
        self.assertIn('PR conversation', err.getvalue())

    def test_ready_refuses_and_marks_pending_when_unmet(self):
        code, fields, _, output = self.run_main(['ready', '7'], context=changed(threads=[{'isResolved': False}]))
        self.assertEqual(code, 1)
        self.assertEqual(fields[0]['state'], 'pending')
        self.assertIn('unresolved', fields[0]['description'])
        self.assertIn('not ready', output)

    def test_ready_posts_nothing_on_a_closed_pr(self):
        code, fields, _, _ = self.run_main(['ready', '7'], context=changed(pr__state='closed'))
        self.assertEqual((code, fields), (1, []))

    def test_working_and_blocked_set_pending_and_failure(self):
        _, fields, _, _ = self.run_main(['working', '7', 'fixing 4 Codex findings'])
        self.assertEqual((fields[0]['state'], fields[0]['description']), ('pending', 'Agent working: fixing 4 Codex findings'))
        _, fields, _, _ = self.run_main(['blocked', '7', 'keep or drop the cache?'])
        self.assertEqual((fields[0]['state'], fields[0]['description']), ('failure', 'Needs your decision: keep or drop the cache?'))

    def test_working_requires_a_message_and_an_open_pr(self):
        with self.assertRaises(SystemExit), patch('sys.stderr', new_callable=io.StringIO):
            pr_ready.main(['working', '7'])
        code, fields, _, _ = self.run_main(['working', '7', 'x'], api=FakeApi(state='closed'))
        self.assertEqual((code, fields), (1, []))

    def test_status_prints_the_latest_agent_status(self):
        code, _, posted, output = self.run_main(['status', '7'])
        self.assertEqual((code, posted), (0, []))
        self.assertIn('"state": "success"', output)

    def test_descriptions_fit_github_limit(self):
        self.assertEqual(len(pr_ready.describe('x ' * 200)), 140)


if __name__ == '__main__':
    unittest.main()
