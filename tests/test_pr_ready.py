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
           'url': URL, 'head': {'sha': HEAD}},
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

    def __init__(self, state='open'):
        self.state = state

    def api(self, path):
        return {'state': self.state, 'head': {'sha': HEAD}, 'html_url': URL}

    def pages(self, path):
        return [{'context': 'agent/ready', 'state': 'pending', 'description': 'old', 'updated_at': '1', 'id': 1},
                {'context': 'agent/ready', 'state': 'success', 'description': 'new', 'updated_at': '2', 'id': 2}]


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
        self.assertEqual(fields[0]['description'], 'Ready to merge: Codex clean on aaaaaaa; 182 tests pass')

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
