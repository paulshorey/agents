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

    def test_first_start_and_saved_resume_use_compatible_flags(self):
        self.assertEqual(self.run_cli()[0], 0)
        self.saved_record()
        self.assertEqual(self.run_cli()[0], 0)
        first, resumed = self.invocations()
        self.assertIn("--spawn", first)
        self.assertIn("--continue", resumed)
        self.assertNotIn("--spawn", resumed)
        self.assertEqual(resumed[-2:], ["bypassPermissions", "--continue"])

    def test_failed_resume_never_creates_a_replacement(self):
        self.saved_record()
        self.env["TEST_EXIT"] = "7"
        code, _, err = self.run_cli()
        self.assertEqual(code, 7)
        self.assertIn("no replacement session was created", err)
        self.assertEqual(len(self.invocations()), 1)
        self.assertIn("--continue", self.invocations()[0])

    def test_pointer_deleted_by_native_failure_does_not_make_next_retry_create(self):
        path = self.saved_record()
        self.env["TEST_EXIT"] = "7"
        self.assertEqual(self.run_cli()[0], 7)
        path.unlink()  # Native Claude clears invalid/expired pointer records.
        self.assertEqual(self.run_cli()[0], 7)
        self.assertEqual(len(self.invocations()), 2)
        for invocation in self.invocations():
            self.assertIn("--continue", invocation)
            self.assertNotIn("--spawn", invocation)

    def test_exact_url_and_explicit_server(self):
        self.saved_record()
        self.assertEqual(self.run_cli("--session-id", "https://claude.ai/code/session_exact123?from=cli")[0], 0)
        self.assertEqual(self.run_cli("--server")[0], 0)
        exact, server = self.invocations()
        self.assertEqual(exact[-2:], ["--session-id", "session_exact123"])
        self.assertNotIn("--spawn", exact)
        self.assertIn("--spawn", server)

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
if '-axo' in sys.argv:
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
if '-axo' in sys.argv:
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
if '-axo' in sys.argv:
    print('{os.getuid()} {os.getpid()} claude remote-control')
else:
    print('/opt/bin/claude')
""")
        code, _, err = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("Cannot verify working directory", err)
        self.assertEqual(self.invocations(), [])

    def test_bad_session_id_and_invalid_pointer_fail_safely(self):
        self.assertEqual(self.run_cli("--session-id", "not-a-session")[0], 1)
        path = self.saved_record()
        path.write_text("invalid json")
        self.assertEqual(self.run_cli()[0], 0)
        self.assertIn("--continue", self.invocations()[0])
        self.assertEqual(path.read_text(), "invalid json")


if __name__ == "__main__":
    unittest.main()
