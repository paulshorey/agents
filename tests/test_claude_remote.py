import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/claude-remote.py"
SPEC = importlib.util.spec_from_file_location("claude_remote", SCRIPT)
REMOTE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REMOTE)


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cwd = self.root / "project"
        self.cwd.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls.jsonl"
        self.env = dict(os.environ, HOME=str(self.root),
                        CLAUDE_CONFIG_DIR=str(self.root / "claude-config"),
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        TEST_CALLS=str(self.calls), TEST_WAIT="0", TEST_EXIT="0")
        self.children = []
        self.fake("ps", "pass")
        self.fake("lsof", "pass")
        self.fake("caffeinate", "import time; time.sleep(60)")
        self.fake("claude", """import json, os, sys, time
if sys.argv[1:] == ['--version']:
    print('2.1.316 (Claude Code)')
    sys.exit(0)
with open(os.environ['TEST_CALLS'], 'a') as output:
    output.write(json.dumps(sys.argv[1:]) + '\\n')
time.sleep(float(os.environ['TEST_WAIT']))
sys.exit(int(os.environ['TEST_EXIT']))
""")

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=5)
        self.temp.cleanup()

    def fake(self, name, body):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + body + "\n")
        path.chmod(0o700)

    def launch(self, *args, cwd=None):
        child = subprocess.Popen([sys.executable, str(SCRIPT), *args], cwd=cwd or self.cwd,
                                 env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.children.append(child)
        return child

    def run_cli(self, *args):
        child = self.launch(*args)
        out, err = child.communicate(timeout=5)
        return child.returncode, out, err

    def saved_record(self):
        with patch.dict(os.environ, self.env):
            path = REMOTE.pointer_path(self.cwd.resolve())
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"sessionId": "session_saved123", "environmentId": "env_saved123"}))
        return path

    def invocations(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def test_default_is_server_mode_with_or_without_a_saved_record(self):
        self.assertEqual(self.run_cli()[0], 0)
        self.saved_record()
        self.assertEqual(self.run_cli()[0], 0)
        self.assertEqual(self.run_cli("--server")[0], 0)
        for invocation in self.invocations():
            self.assertEqual(invocation, ["remote-control", "--permission-mode", "bypassPermissions",
                                          "--spawn", "same-dir"])

    def test_worktree_server_mode(self):
        self.assertEqual(self.run_cli("--worktree")[0], 0)
        self.assertEqual(self.invocations()[0][-2:], ["--spawn", "worktree"])

    def test_failed_server_start_does_not_switch_later_runs_to_single_session(self):
        self.saved_record()
        self.env["TEST_EXIT"] = "7"
        code, _, err = self.run_cli()
        self.assertEqual(code, 7)
        self.assertIn("cclaude --verbose", err)
        self.env["TEST_EXIT"] = "0"
        self.assertEqual(self.run_cli()[0], 0)
        for invocation in self.invocations():
            self.assertIn("--spawn", invocation)
            self.assertNotIn("--continue", invocation)

    def test_single_session_modes_are_explicit(self):
        self.saved_record()
        self.assertEqual(self.run_cli("--continue")[0], 0)
        self.assertEqual(self.run_cli("--session-id", "https://claude.ai/code/session_exact123?from=cli")[0], 0)
        resumed, exact = self.invocations()
        self.assertEqual(resumed[-1], "--continue")
        self.assertEqual(exact[-2:], ["--session-id", "session_exact123"])
        for invocation in (resumed, exact):
            self.assertNotIn("--spawn", invocation)

    def test_modes_are_mutually_exclusive(self):
        code, _, err = self.run_cli("--continue", "--worktree")
        self.assertEqual(code, 2)
        self.assertIn("not allowed with", err)
        self.assertEqual(self.invocations(), [])

    def test_status_does_not_start_claude(self):
        self.saved_record()
        code, out, _ = self.run_cli("--status")
        self.assertEqual(code, 0)
        self.assertIn("https://claude.ai/code/session_saved123", out)
        self.assertEqual(self.invocations(), [])

    def test_concurrent_calls_and_symlinks_share_lock(self):
        self.saved_record()
        self.env["TEST_WAIT"] = "60"
        first = self.launch()
        deadline = time.monotonic() + 5
        while not self.invocations() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(len(self.invocations()), 1)
        alias = self.root / "project-link"
        alias.symlink_to(self.cwd, target_is_directory=True)
        second = self.launch(cwd=alias)
        out, err = second.communicate(timeout=5)
        self.assertEqual(second.returncode, 0, err)
        self.assertIn("already running", out)
        self.assertEqual(len(self.invocations()), 1)
        first.terminate()
        first.communicate(timeout=5)
        # A retained lock file must not block the next invocation.
        self.env["TEST_WAIT"] = "0"
        self.assertEqual(self.run_cli()[0], 0)
        self.assertEqual(len(self.invocations()), 2)

    def test_old_alias_server_blocks_launch(self):
        self.saved_record()
        self.fake("ps", f"""import sys
if '-wwaxo' in sys.argv:
    print('{os.getuid()} 12345 claude remote-control --spawn same-dir')
else:
    print('/opt/bin/claude')
""")
        self.fake("lsof", f"print('p12345\\nn{self.cwd.resolve()}')")
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("PID 12345", out)
        self.assertEqual(self.invocations(), [])

    def test_other_folder_and_shell_command_do_not_block(self):
        self.fake("ps", f"""import sys
if '-wwaxo' in sys.argv:
    print('{os.getuid()} 12345 claude remote-control --spawn same-dir')
    print('{os.getuid()} 12346 zsh -c claude remote-control')
else:
    print('/opt/bin/claude' if '12345' in sys.argv else '/bin/zsh')
""")
        self.fake("lsof", f"print('p12345\\nn{self.root}')")
        self.assertEqual(self.run_cli()[0], 0)
        self.assertEqual(len(self.invocations()), 1)

    def test_uninspectable_live_server_does_not_allow_duplicate(self):
        self.fake("ps", f"""import sys
if '-wwaxo' in sys.argv:
    print('{os.getuid()} {os.getpid()} claude remote-control')
else:
    print('/opt/bin/claude')
""")
        code, _, err = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("Cannot verify working directory", err)
        self.assertEqual(self.invocations(), [])

    def test_npm_server_blocks_launch(self):
        for invocation in (
            'node /usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js remote-control --continue',
            '/opt/homebrew/bin/node /usr/local/bin/claude rc',
            'node --max-old-space-size=8192 /usr/local/bin/claude remote-control',
            'claude remote-control --name "Bob\'s project"',
        ):
            with self.subTest(invocation=invocation):
                self.fake('ps', f"print({f'{os.getuid()} 12345 {invocation}'!r})")
                self.fake('lsof', f"print('p12345\\nn{self.cwd.resolve()}')")
                code, out, err = self.run_cli()
                self.assertEqual(code, 0, err)
                self.assertIn('PID 12345', out)
                self.assertEqual(self.invocations(), [])

    def test_unrelated_commands_do_not_count_as_servers(self):
        for command in (
            'zsh -c "claude remote-control"',
            'node /tmp/unrelated.js remote-control',
            'node -e "claude remote-control"',
            'claude -p "explain remote-control"',
            'claude --name remote-control',
            'claude --model remote-control',
            'claude --debug-file remote-control',
            'claude --verbose -p remote-control',
            'claude --model sonnet -p remote-control',
            'claude --model= remote-control',
            'claude --model --verbose remote-control',
        ):
            with self.subTest(command=command):
                self.assertFalse(REMOTE.is_remote_command(command))

    def test_servers_with_global_options_block_launch(self):
        for invocation in (
            'claude --verbose remote-control',
            'claude --model sonnet remote-control',
            'claude --model=sonnet --verbose rc',
            'claude --verbose --debug=api --debug-file /tmp/debug.log --model sonnet remote-control',
            'node /usr/local/bin/claude --verbose --model sonnet remote-control',
        ):
            with self.subTest(invocation=invocation):
                self.fake('ps', f"print({f'{os.getuid()} 12345 {invocation}'!r})")
                self.fake('lsof', f"print('p12345\\nn{self.cwd.resolve()}')")
                code, out, err = self.run_cli()
                self.assertEqual(code, 0, err)
                self.assertIn('PID 12345', out)
                self.assertEqual(self.invocations(), [])

    def test_bad_session_id_and_invalid_pointer_fail_safely(self):
        self.assertEqual(self.run_cli("--session-id", "not-a-session")[0], 1)
        path = self.saved_record()
        path.write_text("invalid json")
        self.assertEqual(self.run_cli()[0], 0)
        self.assertEqual(self.invocations()[0][-2:], ["--spawn", "same-dir"])
        self.assertEqual(path.read_text(), "invalid json")

    def test_existing_compatible_install_is_used_when_path_version_is_old(self):
        self.fake("claude-old", "print('2.1.83 (Claude Code)')")
        newer = str(self.bin / "claude")
        self.assertEqual(REMOTE.select_claude([str(self.bin / "claude-old"), newer]), newer)
        self.assertEqual(self.invocations(), [])
        with self.assertRaisesRegex(RuntimeError, "2.1.200"):
            REMOTE.select_claude([str(self.bin / "claude-old")])

    def test_unlaunchable_install_does_not_hide_compatible_fallback(self):
        broken = self.bin / 'claude-broken'
        broken.write_text('#!/nonexistent/claude-test-interpreter\n')
        broken.chmod(0o700)
        newer = str(self.bin / 'claude')
        self.assertEqual(REMOTE.select_claude([str(broken), newer]), newer)
        with self.assertRaisesRegex(RuntimeError, 'No compatible Claude CLI'):
            REMOTE.select_claude([str(broken)])

    def test_timed_out_probe_does_not_hide_compatible_fallback(self):
        candidates = [str(self.bin / 'claude'), str(self.bin / 'second-claude')]
        self.fake('second-claude', "print('2.1.316 (Claude Code)')")
        with patch.object(REMOTE.subprocess, 'run', side_effect=[
            subprocess.TimeoutExpired([candidates[0], '--version'], 10),
            subprocess.CompletedProcess([], 0, '2.1.316 (Claude Code)\\n', ''),
        ]) as probe:
            self.assertEqual(REMOTE.select_claude(candidates), candidates[1])
        self.assertEqual([call.args[0] for call in probe.call_args_list],
                         [[candidate, '--version'] for candidate in candidates])


if __name__ == "__main__":
    unittest.main()
