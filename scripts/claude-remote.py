#!/usr/bin/env python3
"""Run one Claude Remote Control server per folder (macOS).

The server brings back the sessions the folder's previous server was serving and
creates a new session for each new chat started from the Claude apps or claude.ai.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys


def pointer_path(cwd):
    # Claude Code 2.1.316's short project-directory encoding. For long paths,
    # let the native --continue implementation handle its hashed key instead.
    key = re.sub(r"[^a-zA-Z0-9]", "-", str(cwd))
    if len(key) > 200:
        return None
    root = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    return root / "projects" / key / "bridge-pointer.json"


def read_pointer(path):
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def show_link(pointer):
    session = pointer.get("sessionId", "")
    environment = pointer.get("environmentId", "")
    if isinstance(session, str) and re.fullmatch(r"session_[A-Za-z0-9]+", session):
        print(f"https://claude.ai/code/{session}", flush=True)
    elif isinstance(environment, str) and re.fullmatch(r"env_[A-Za-z0-9]+", environment):
        print(f"https://claude.ai/code?environment={environment}", flush=True)


def active_servers(cwd):
    """Find old-alias servers as well as servers started through this wrapper."""
    rows = subprocess.check_output(["ps", "-axo", "uid=,pid=,args="], text=True)
    found = []
    for row in rows.splitlines():
        fields = row.split(None, 2)
        if len(fields) != 3 or fields[0] != str(os.getuid()):
            continue
        if not re.search(r" (?:remote-control|rc)(?: |$)", fields[2]):
            continue
        pid = int(fields[1])
        executable = subprocess.run(["ps", "-p", str(pid), "-o", "comm="],
                                    text=True, capture_output=True).stdout.strip()
        if Path(executable).name not in ("claude", "claude.exe"):
            continue
        probe = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                               text=True, capture_output=True)
        directories = [line[1:] for line in probe.stdout.splitlines() if line.startswith("n")]
        if not directories:
            # It may have exited between ps and lsof. An uninspectable live
            # server is uncertainty, not permission to start another one.
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            raise RuntimeError(f"Cannot verify working directory of Remote Control PID {pid}.")
        if Path(directories[0]).resolve() == cwd:
            found.append(pid)
    return found


def claude_args(args):
    base = ["remote-control", "--permission-mode", "bypassPermissions"]
    if args.session_id:
        session = args.session_id.removeprefix("https://claude.ai/code/").split("?", 1)[0]
        if not re.fullmatch(r"session_[A-Za-z0-9]+", session):
            raise ValueError("--session-id needs a session_ ID or its claude.ai/code URL.")
        base += ["--session-id", session]
    elif args.continue_one:
        # Single-session mode: serves only the recorded session; new chats
        # started from the apps cannot create sessions in this mode.
        base += ["--continue"]
    else:
        # Server mode restores every session the folder's previous server was
        # serving (about four hours) and spawns a session for each new chat.
        base += ["--spawn", "worktree" if args.worktree else "same-dir"]
    if args.verbose:
        base.append("--verbose")
    if args.name:
        base += ["--name", args.name]
    return base


def select_claude(candidates=None):
    if candidates is None:
        candidates = [shutil.which("claude"), str(Path.home() / ".local/bin/claude"),
                      "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]
    seen = set()
    for candidate in candidates:
        if not candidate or not os.access(candidate, os.X_OK):
            continue
        resolved = str(Path(candidate).resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        version = subprocess.run([candidate, "--version"], capture_output=True,
                                 text=True, timeout=10)
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)\b", version.stdout.strip())
        if version.returncode == 0 and match and tuple(map(int, match.groups())) >= (2, 1, 200):
            return candidate
    raise RuntimeError("No compatible Claude CLI found. Remote Control resume requires Claude Code 2.1.200 or later.")


def run_child(command):
    # Keep the Mac awake for exactly this invocation. No detached server or
    # automatic restart: Claude keeps the real terminal's stdin/stdout/stderr.
    awake = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
    child = None
    previous = {}

    def forward(signum, _frame):
        if child is not None and child.poll() is None:
            child.send_signal(signum)

    try:
        for sig in (signal.SIGTERM, signal.SIGHUP):
            previous[sig] = signal.signal(sig, forward)
        # Ctrl+C already reaches Claude through the foreground process group.
        # Forwarding it again could turn one keypress into a forced shutdown.
        previous[signal.SIGINT] = signal.signal(signal.SIGINT, lambda _sig, _frame: None)
        child = subprocess.Popen(command)
        return child.wait()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        awake.terminate()
        awake.wait()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--server", action="store_true", help="Server mode (the default): restore sessions and accept new chats.")
    mode.add_argument("--worktree", action="store_true", help="Server mode with a git worktree for each new chat's session.")
    mode.add_argument("--continue", dest="continue_one", action="store_true",
                      help="Serve only the last recorded session; new chats cannot create sessions.")
    mode.add_argument("--session-id", help="Serve only one specific session ID or claude.ai/code session URL.")
    parser.add_argument("--status", action="store_true", help="Show local server and saved-session status without starting anything.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show native session diagnostics, including child log locations.")
    parser.add_argument("--name", help="Name passed through to Claude Remote Control.")
    args = parser.parse_args(argv)
    cwd = Path.cwd().resolve()
    path = pointer_path(cwd)
    for tool in ("caffeinate", "lsof", "ps"):
        if not shutil.which(tool):
            raise RuntimeError(f"Required command is unavailable: {tool}")

    state = Path.home() / ".agents" / "local" / "claude-remote"
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = hashlib.sha256(str(cwd).encode()).hexdigest()
    # Never unlink the lock file: a waiter could otherwise lock an old inode.
    with (state / f"{key}.lock").open("a+") as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("cclaude is already running in this folder. Use its terminal or the saved link.", flush=True)
            show_link(read_pointer(path))
            return 0
        active = active_servers(cwd)
        if active:
            print("Remote Control is already running in this folder (PID " + ", ".join(map(str, active)) + ").", flush=True)
            print("Use its terminal or the saved link; no competing server was started.", flush=True)
            show_link(read_pointer(path))
            return 0
        if args.status:
            print("No running Remote Control server in this folder.", flush=True)
            print("Saved record present." if path and path.exists() else "No directly located saved record.", flush=True)
            show_link(read_pointer(path))
            return 0
        command = claude_args(args)
        executable = select_claude()
        if executable != shutil.which("claude"):
            print(f"Using compatible Claude CLI: {executable}", flush=True)
        if args.continue_one or args.session_id:
            print("Serving one saved session; new chats from the apps cannot create sessions here.", flush=True)
        else:
            print("Starting the Remote Control server: sessions from this folder's last server come back\n"
                  "(if it stopped within about four hours), and each new chat gets its own session.", flush=True)
        result = run_child([executable, *command])
        if result:
            print("Remote Control exited with an error. Retry cclaude --verbose for diagnostics,\n"
                  "or use --session-id with a session URL to bring back one older session.",
                  file=sys.stderr)
        return result if result >= 0 else 128 - result


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"cclaude: {error}", file=sys.stderr)
        sys.exit(1)
