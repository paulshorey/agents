#!/usr/bin/env python3
"""Run a command with login-shell and project-scoped dotenv variables.

Only variable names and presence are printed in --check mode. Values stay in
the child process environment and are never written to a report.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values


ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MARKER = b"\0__COORDINATOR_LOGIN_ENV__\0"


def login_environment() -> dict[str, str]:
    probe = subprocess.run(
        ["/bin/zsh", "-lc", 'printf "\\0__COORDINATOR_LOGIN_ENV__\\0"; /usr/bin/env -0'],
        capture_output=True,
        timeout=20,
        check=True,
    )
    if MARKER not in probe.stdout:
        raise RuntimeError("login shell environment marker was not returned")
    result: dict[str, str] = {}
    for entry in probe.stdout.split(MARKER, 1)[1].split(b"\0"):
        if b"=" not in entry:
            continue
        raw_key, raw_value = entry.split(b"=", 1)
        key = raw_key.decode(errors="surrogateescape")
        if ENV_NAME.fullmatch(key):
            result[key] = raw_value.decode(errors="surrogateescape")
    return result


def project_root(cwd: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return Path(result.stdout.strip()).resolve()
    git_home = Path.home() / "git"
    try:
        relative = cwd.relative_to(git_home)
        return git_home / relative.parts[0]
    except (ValueError, IndexError):
        return cwd


def scope_directories(root: Path, cwd: Path) -> list[Path]:
    try:
        relative = cwd.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"working directory is outside project root: {cwd}") from exc
    directories = [root]
    current = root
    for part in relative.parts:
        current = current / part
        directories.append(current)
    return directories


def build_environment(cwd: Path, extra_required: set[str], shell_only: bool = False) -> tuple[dict[str, str], list[Path], set[str]]:
    root = project_root(cwd)
    directories = scope_directories(root, cwd)
    env_files = [] if shell_only else [directory / name for directory in directories for name in (".env", ".env.local") if (directory / name).is_file()]
    example_files = [directory / name for directory in directories for name in (".env.example", ".env.local.example") if (directory / name).is_file()]

    declared = set(extra_required)
    for path in (*env_files, *example_files):
        declared.update(dotenv_values(path, interpolate=False).keys())
    declared = {key for key in declared if ENV_NAME.fullmatch(key)}

    parent = os.environ.copy()
    shell = login_environment()
    working = parent.copy()
    working.update({key: value for key, value in shell.items() if key not in working or not working[key]})
    try:
        for path in env_files:
            # python-dotenv expands ${NAME} against the values accumulated so far.
            os.environ.clear()
            os.environ.update(working)
            parsed = dotenv_values(path)
            working.update({key: value for key, value in parsed.items() if value is not None and value != ""})
    finally:
        os.environ.clear()
        os.environ.update(parent)

    final = parent.copy()
    final.update({key: working[key] for key in declared if key in working and working[key]})
    return final, env_files, declared


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", required=True, type=Path, help="project working directory")
    parser.add_argument("--require", action="append", default=[], metavar="NAME", help="required variable; refuse to execute if absent or empty")
    parser.add_argument("--check", action="store_true", help="print names and missing variables only")
    parser.add_argument("--shell-only", action="store_true", help="use injected/login-shell variables and example declarations; do not read dotenv files")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    cwd = args.cwd.expanduser().resolve()
    if not cwd.is_dir():
        parser.error(f"working directory does not exist: {cwd}")
    required = set(args.require)
    if any(not ENV_NAME.fullmatch(key) for key in required):
        parser.error("--require accepts environment variable names only")

    try:
        env, files, declared = build_environment(cwd, required, args.shell_only)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, RuntimeError) as exc:
        print(f"Project environment could not be prepared: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 78

    missing_required = sorted(key for key in required if not env.get(key))
    if args.check:
        missing = sorted(key for key in declared if not env.get(key))
        print(f"Project: {cwd}")
        print("Dotenv files: " + (", ".join(str(path) for path in files) if files else "none"))
        print(f"Declared names: {len(declared)}; available: {len(declared) - len(missing)}; missing: {len(missing)}")
        if missing:
            print("Missing names: " + ", ".join(missing))
        if missing_required:
            print("Missing required names: " + ", ".join(missing_required))
        return 1 if missing_required else 0

    if missing_required:
        print("Blocked: missing required environment names: " + ", ".join(missing_required), file=sys.stderr)
        return 78

    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not command:
        parser.error("provide a command after -- or use --check")
    os.chdir(cwd)
    os.execvpe(command[0], command, env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
