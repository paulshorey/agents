"""Durable native task ownership for a caller-selected local GitHub project.

Codex owns schedules and coordinator model settings. This module never starts an
agent, writes automation settings or supplies human messaging authorization.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess
from datetime import datetime, timezone
from uuid import uuid4

SKILL = Path(__file__).resolve().parent.parent
# Coding preference is independent of the model selected for a scheduled run.
DEFAULT_CODING_MODEL = "gpt-6.1-sol"
DEFAULT_CODING_REASONING = "high"
UUID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.I)
SHA = re.compile(r"^[0-9a-f]{40}$")
ORIGIN = re.compile(r"(?:git@github\.com:|https://github\.com/)([^/]+/[^/]+?)(?:\.git)?/?")

class Project:
    def __init__(self, cwd, expected_repository=None):
        self.path = Path(git(cwd, "rev-parse", "--show-toplevel")).resolve()
        origin = ORIGIN.fullmatch(git(self.path, "remote", "get-url", "origin"))
        if not origin:
            raise ValueError("Review the GitHub origin before coordinating this project")
        self.repository = origin.group(1)
        if expected_repository and self.repository.lower() != expected_repository.lower():
            raise ValueError("Checkout origin does not match the requested project")
        self.common = git(self.path, "rev-parse", "--path-format=absolute", "--git-common-dir")
        # Git lists the main worktree first. Linked coding worktrees must share
        # its ledger, even though their own ignored files are separate.
        first = git(self.path, "worktree", "list", "--porcelain", "-z").split("\0", 1)[0]
        if not first.startswith("worktree "):
            raise ValueError("Cannot identify the project's primary checkout")
        self.primary = Path(first.removeprefix("worktree ")).resolve()
        if (git(self.primary, "rev-parse", "--is-bare-repository") == "true"
                or git(self.primary, "rev-parse", "--path-format=absolute", "--git-common-dir") != self.common):
            raise ValueError("Project state requires the primary non-bare checkout")
        self.state_path = self.primary / ".codex/project-coordinator"


def project(context):
    return {"path": str(context.path), "repository": context.repository}

def now():
    return datetime.now(timezone.utc).isoformat()

def identifier(value):
    if not isinstance(value, str) or not UUID.fullmatch(value):
        raise ValueError("An actual native thread/run UUID is required")
    return value

def read_json(path):
    return json.loads(Path(path).read_text())

def private_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Private state cannot be symlinked")
    temporary = path.with_name(path.name + "." + str(uuid4()) + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

def git(cwd, *arguments):
    result = subprocess.run(["git", "-C", str(cwd), *arguments], capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise ValueError("Git verification failed: " + " ".join(arguments[:2]))
    return result.stdout.strip()

def verify_repository(context, cwd=None):
    item = project(context)
    path = Path(cwd or item["path"]).resolve()
    origin = git(path, "remote", "get-url", "origin")
    match = re.fullmatch(r"(?:git@github\.com:|https://github\.com/)([^/]+/[^/]+?)(?:\.git)?/?", origin)
    if not match or match.group(1).lower() != item["repository"].lower():
        raise ValueError("Checkout origin does not match the requested repository")
    return {"path": str(path), "repository": item["repository"], "head": git(path, "rev-parse", "HEAD")}

def state(context):
    project(context)
    path = context.state_path
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Private project state cannot be symlinked")
    try:
        git(context.primary, "check-ignore", "--no-index", str(path / "tasks.sqlite3"))
    except ValueError as exc:
        raise ValueError("Ignore /.codex/project-coordinator/ in the project before writing private state") from exc
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path

def connection(context):
    path = state(context) / "tasks.sqlite3"
    if path.is_symlink():
        raise ValueError("Private task ledger cannot be symlinked")
    db = sqlite3.connect(path, timeout=15, isolation_level=None)
    os.chmod(path, 0o600)
    db.row_factory = sqlite3.Row
    db.executescript("""
      CREATE TABLE IF NOT EXISTS passes (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, started_at TEXT NOT NULL,
        state TEXT NOT NULL, finished_at TEXT, evidence TEXT);
      CREATE UNIQUE INDEX IF NOT EXISTS one_pass ON passes(state) WHERE state='active';
      CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY, scope TEXT NOT NULL UNIQUE, base TEXT NOT NULL,
        state TEXT NOT NULL, prompt_path TEXT NOT NULL, authority TEXT NOT NULL,
        acceptance TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        pass_id TEXT, thread_id TEXT UNIQUE, host_id TEXT, cwd TEXT, observed_status TEXT,
        observed_at TEXT, evidence TEXT);
    """)
    db.execute("BEGIN IMMEDIATE")
    if "admission" not in {row["name"] for row in db.execute("PRAGMA table_info(tasks)")}:
        db.execute("ALTER TABLE tasks ADD COLUMN admission TEXT")
    db.commit()
    return db

def begin(context, owner):
    identifier(owner)
    db = connection(context)
    try:
        db.execute("BEGIN IMMEDIATE")
        active = db.execute("SELECT * FROM passes WHERE state='active'").fetchone()
        if active:
            db.rollback()
            return {"status": "already_owned" if active["owner"] == owner else "blocked", "pass": dict(active),
                    "instruction": "Read the actual owner task before recovery; never reclaim on elapsed time alone."}
        value = {"id": str(uuid4()), "owner": owner, "started_at": now(), "state": "active"}
        db.execute("INSERT INTO passes(id,owner,started_at,state) VALUES (:id,:owner,:started_at,:state)", value)
        db.commit()
        return {"status": "claimed", "pass": value}
    finally:
        db.close()

def end(context, pass_id, evidence, recovered=False):
    identifier(pass_id)
    if not evidence.strip():
        raise ValueError("A result/recovery evidence reference is required")
    db = connection(context)
    try:
        cursor = db.execute("UPDATE passes SET state=?,finished_at=?,evidence=? WHERE id=? AND state='active'",
                            ("recovered" if recovered else "finished", now(), evidence, pass_id))
        if cursor.rowcount != 1:
            raise ValueError("No matching active pass")
    finally:
        db.close()

def prepare_task(context, scope, base, prompt_path, authority, acceptance):
    verify_repository(context)
    if not scope.strip() or not authority.strip() or not acceptance.strip() or not SHA.fullmatch(base):
        raise ValueError("Stable scope, reviewed full base SHA, authority and acceptance checks required")
    item = project(context)
    if git(item["path"], "rev-parse", base + "^{commit}") != base:
        raise ValueError("Reviewed base is not a local commit")
    source = Path(prompt_path).resolve()
    if not source.is_relative_to(state(context).resolve()) or not source.is_file():
        raise ValueError("Task prompt must be in this project's private state")
    text = source.read_text()
    if not text.strip() or len(text.encode()) > 65536:
        raise ValueError("Task prompt must be nonempty and at most 64 KiB")
    db = connection(context)
    try:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT * FROM tasks WHERE scope=?", (scope,)).fetchone()
        if existing:
            db.rollback()
            return {"status": "existing", "task": dict(existing)}
        task_id = str(uuid4())
        frozen = state(context) / "prompts" / (task_id + ".txt")
        frozen.parent.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(frozen, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
        row = {"id": task_id, "scope": scope, "base": base, "state": "prepared", "prompt_path": str(frozen),
               "authority": authority, "acceptance": acceptance, "created_at": now(), "updated_at": now()}
        db.execute("""INSERT INTO tasks(id,scope,base,state,prompt_path,authority,acceptance,created_at,updated_at)
                      VALUES(:id,:scope,:base,:state,:prompt_path,:authority,:acceptance,:created_at,:updated_at)""", row)
        db.commit()
        return {"status": "prepared", "task": row}
    finally:
        db.close()

def task(context, task_id):
    identifier(task_id)
    db = connection(context)
    try:
        row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown project task")
        return dict(row)
    finally:
        db.close()

def claim_task(context, task_id, pass_id):
    identifier(task_id)
    identifier(pass_id)
    binding = read_json(state(context) / "desktop.json")
    if binding.get("path") != project(context)["path"] or binding.get("host_id") != "local":
        raise ValueError("Refresh the native project binding before dispatch")
    db = connection(context)
    try:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM passes WHERE id=? AND state='active'", (pass_id,)).fetchone():
            raise ValueError("Dispatch needs the current active coordination pass")
        changed = db.execute("UPDATE tasks SET state='dispatching',pass_id=?,updated_at=? WHERE id=? AND state='prepared'",
                             (pass_id, now(), task_id))
        if changed.rowcount != 1:
            raise ValueError("Task already claimed/started; ambiguous dispatch must never be retried automatically")
        db.commit()
    finally:
        db.close()
    return task(context, task_id)

def bind_project(context, project_id):
    verify_repository(context)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", project_id):
        raise ValueError("Use an actual project ID returned by native list_projects")
    private_json(state(context) / "desktop.json", {"project_id": project_id, "path": project(context)["path"], "host_id": "local", "updated_at": now()})

def dispatch_plan(context, task_id):
    row = task(context, task_id)
    if row["state"] != "dispatching":
        raise ValueError("Claim the task once before obtaining creation arguments")
    settings = {"model": DEFAULT_CODING_MODEL, "reasoning_effort": DEFAULT_CODING_REASONING}
    binding = read_json(state(context) / "desktop.json")
    if binding["path"] != project(context)["path"] or binding["host_id"] != "local":
        raise ValueError("Refresh the native project binding")
    command = shlex.join(["python3", str(SKILL / "scripts/tasks.py"), "--cwd", str(context.path), "--repository", context.repository])
    instructions = (
        f"Implement only this recorded authorized scope in a separate native worktree. Intent {task_id}; "
        f"authority: {row['authority']}; reviewed base: {row['base']}. "
        f"Before editing run {command} task-start --task {task_id} --actual-cwd YOUR_ACTUAL_CWD. "
        "Stop on a base/origin/worktree/cleanliness mismatch. Preserve the primary checkout and user changes. "
        "Read applicable project AGENTS.md. Product/release decisions outside this scope belong to the human. "
        f"Acceptance: {row['acceptance']}. Complete relevant checks and create/update any PR required by the scoped task and project. "
        "Return the actual base, diff/check results, remaining decisions and PR URL. "
        "Use the project environment runner at the actual worktree/app path when credentials are needed; map uses --shell-only.\n\n"
        + Path(row["prompt_path"]).read_text()
    )
    return {"model": settings["model"], "thinking": settings["reasoning_effort"],
            "title": f"{context.repository.split('/')[-1]}: {row['scope'][:80]}", "prompt": instructions,
            "target": {"type": "project", "projectId": binding["project_id"], "environment": {"type": "worktree"}}}

def attach_task(context, task_id, thread_id, host_id):
    identifier(thread_id)
    if host_id != "local":
        raise ValueError("Attach only the exact ready local thread; resolve pending/unknown outcomes first")
    db = connection(context)
    try:
        cursor = db.execute("""UPDATE tasks SET state='started',thread_id=?,host_id=?,updated_at=?
          WHERE id=? AND state IN ('dispatching','started') AND (thread_id IS NULL OR thread_id=?)""",
          (thread_id, host_id, now(), task_id, thread_id))
        if cursor.rowcount != 1:
            raise ValueError("Task is not admitted or belongs to a different thread")
    finally:
        db.close()
    return {"task": task(context, task_id), "url": f"codex://threads/{thread_id}"}

def start_task(context, task_id, cwd, thread_id):
    identifier(thread_id)
    row = task(context, task_id)
    if row["state"] not in {"dispatching", "started"} or (row["thread_id"] and row["thread_id"] != thread_id):
        raise ValueError("Task is not admitted or is owned by another native thread")
    primary = Path(project(context)["path"]).resolve()
    cwd = Path(cwd).resolve()
    # Save the actual identity first, including if worktree admission fails. The creator
    # may have received only a pending client ID; the ledger is its discovery path.
    db = connection(context)
    try:
        cursor = db.execute("""UPDATE tasks SET state='started',thread_id=?,host_id='local',cwd=?,updated_at=?
          WHERE id=? AND state IN ('dispatching','started') AND (thread_id IS NULL OR thread_id=?)""",
          (thread_id, str(cwd), now(), task_id, thread_id))
        if cursor.rowcount != 1:
            raise ValueError("Task admission changed; stop before editing")
    finally:
        db.close()
    try:
        verify_repository(context, cwd)
        if cwd == primary or git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir") != git(primary, "rev-parse", "--path-format=absolute", "--git-common-dir"):
            raise ValueError("Coding must use a linked worktree of this project, never the primary checkout")
        if git(cwd, "rev-parse", "HEAD") != row["base"] or git(cwd, "status", "--porcelain"):
            raise ValueError("Native worktree must start clean at the reviewed base")
    except (ValueError, OSError, subprocess.TimeoutExpired):
        db = connection(context)
        try:
            db.execute("UPDATE tasks SET admission='blocked',updated_at=? WHERE id=? AND thread_id=?", (now(), task_id, thread_id))
        finally:
            db.close()
        raise
    db = connection(context)
    try:
        db.execute("UPDATE tasks SET admission='verified',updated_at=? WHERE id=? AND thread_id=?", (now(), task_id, thread_id))
    finally:
        db.close()
    return {"task": task(context, task_id), "admission": "verified", "instruction": "Read project instructions, then implement only the authorized scope."}

def observe_task(context, task_id, observed_status, evidence, close=False):
    row = task(context, task_id)
    if not row["thread_id"] or not evidence.strip():
        raise ValueError("Exact native thread and fresh observation evidence required")
    db = connection(context)
    try:
        db.execute("""UPDATE tasks SET observed_status=?,observed_at=?,evidence=?,
          state=CASE WHEN ? THEN 'closed' ELSE state END,updated_at=? WHERE id=?""",
          (observed_status, now(), evidence, close, now(), task_id))
    finally:
        db.close()
    return task(context, task_id)
