#!/usr/bin/env python3
"""Resume Claude Remote Control without launching competing servers (macOS)."""

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


def claude_args(args, path, previously_started=False):
    base = ["remote-control", "--permission-mode", "bypassPermissions"]
    if args.server:
        base += ["--spawn", "same-dir"]
    elif args.session_id:
        session = args.session_id.removeprefix("https://claude.ai/code/").split("?", 1)[0]
        if not re.fullmatch(r"session_[A-Za-z0-9]+", session):
            raise ValueError("--session-id needs a session_ ID or its claude.ai/code URL.")
        base += ["--session-id", session]
    elif previously_started or path is None or path.exists():
        # Do not guess whether a saved record is expired or valid. Claude owns
        # validation, worktree lookup, unarchiving and reconnection.
        base += ["--continue"]
    else:
        base += ["--spawn", "same-dir"]
    if args.verbose:
        base.append("--verbose")
    if args.name:
        base += ["--name", args.name]
    return base


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
    mode.add_argument("--server", action="store_true", help="Use same-dir multi-session server mode (may create sessions).")
    mode.add_argument("--session-id", help="Resume one specific session ID or claude.ai/code session URL.")
    parser.add_argument("--status", action="store_true", help="Show local server and saved-session status without starting anything.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show native session diagnostics, including child log locations.")
    parser.add_argument("--name", help="Name passed through to Claude Remote Control.")
    args = parser.parse_args(argv)
    cwd = Path.cwd().resolve()
    path = pointer_path(cwd)
    for tool in ("claude", "caffeinate", "lsof", "ps"):
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
        lock.seek(0)
        command = claude_args(args, path, previously_started=bool(lock.read()))
        # Native Claude may clear an invalid/expired pointer on a failed resume.
        # Remember the attempt so a second retry cannot silently create a new
        # conversation merely because that record disappeared.
        lock.seek(0)
        lock.truncate()
        lock.write("resume\n")
        lock.flush()
        print("Resuming saved Remote Control session." if "--continue" in command or args.session_id
              else "Starting same-dir Remote Control server.", flush=True)
        result = run_child([shutil.which("claude"), *command])
        if result:
            print("Remote Control exited with an error; no replacement session was created.\n"
                  "Retry cclaude --verbose for diagnostics, or use --session-id with the wanted session URL.\n"
                  "If Claude says the saved session expired, use cclaude --server to start server mode explicitly.",
                  file=sys.stderr)
        return result if result >= 0 else 128 - result


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"cclaude: {error}", file=sys.stderr)
        sys.exit(1)
