# Claude Remote Control shortcut

`~/.shortcuts.sh` defines `cclaude`, delegating to
`~/.agents/scripts/claude-remote.py` with Python 3. The rest of the shortcuts file
is external, user-owned shell configuration. It is not an installer-managed
symlink. Keep changes to its cclaude block narrow and back it up under ignored
`local/shell-backups/` before editing. The installed block is:

```sh
unalias cclaude 2>/dev/null || true
function cclaude() {
    command python3 "$HOME/.agents/scripts/claude-remote.py" "$@"
}
```

After installing/editing that block, existing terminals need
`source ~/.shortcuts.sh`. The unalias line permits reloading a shell that still
has the old alias. New terminals load it through their normal shell profiles.
No full installer apply is necessary for this external file. Check the existing
managed links with `python3 scripts/install.py`; unrelated reported drift is a
separate maintenance task, not permission to overwrite settings.

## Commands

```sh
cclaude                        # Resume the saved conversation, if a record exists
cclaude --status               # Inspect without launching Claude
cclaude --session-id SESSION_URL_OR_ID
cclaude --verbose              # Include native session diagnostics/log locations
cclaude --server               # Explicitly use same-dir multi-session server mode
cclaude --help
```

The default uses `claude remote-control --continue` when the current folder has
a bridge pointer or the helper has previously attempted a launch. With no
directly located record on the first invocation, it starts the original
same-dir server mode, which can create a conversation. For paths whose encoded
project key exceeds 200 characters, it always tries native `--continue` rather
than guessing Claude's hashed key. Native Claude owns record validity, expiration,
worktree lookup, account access, and unarchiving. A failed resume stops with the
original error; it never falls back to creating a conversation. If the wrapper
cannot locate a record but another worktree has one, invoke
`claude remote-control --continue` directly or use `cclaude --session-id`.

`--continue` and `--session-id` resume **one** conversation and exit when it ends.
They cannot be combined with `--spawn`, `--capacity`, or pre-creation flags.
`--server` preserves the original `--spawn same-dir` behavior and native restoration
of the environment's sessions; it is not a guarantee of a fresh environment.
The helper retains the user's `bypassPermissions` choice in both modes.

Concurrent wrapper invocations use an OS advisory lock keyed by the physical
current directory, including when reached through a symlink. Locks are stored
owner-only under `~/.agents/local/claude-remote/`, contain no launch environment,
and release when the wrapper exits. Lock files remain intentionally and retain
only a `resume` marker after a launch attempt. If Claude deletes an expired or
invalid pointer, this marker makes later retries keep trying `--continue`
instead of creating a replacement conversation. Use `--server` explicitly to
allow server mode again. Do not unlink lock files while a wrapper might run.

The helper also checks same-user native Remote Control processes and their CWD
with `ps`/`lsof`, including launches from the old alias. If one exists, it prints
its PID and the saved link rather than starting a competitor. This reuses the
browser connection, not the other terminal's UI. Stop the original terminal with
Ctrl+C before moving ownership to another terminal. A live process is not proof
that its web connection is healthy. Launches that bypass this helper cannot be
serialized by its lock.

Claude inherits the real terminal, including keyboard/QR interaction. A separate
`caffeinate -i -w` assertion keeps the Mac awake for the wrapper's lifetime and is
stopped when Claude exits. Closing the terminal still stops the invocation;
this is not a detached service. No process takeover, automatic restart, native
auth edit, pointer rewrite, or session deletion occurs.

## Diagnostics and recovery

The implementation was checked against Claude Code 2.1.316. See the current
[official Remote Control documentation](https://code.claude.com/docs/en/remote-control#resume-sessions-after-stopping-the-server)
and `claude remote-control --help` before changing flags. Native resumption is
available for roughly four hours after server shutdown. `caffeinate` prevents
idle system sleep, not child-process crashes or provider rejection.

- Repeated terminal status redraws with the same environment ID do not establish
  that multiple servers exist. `Capacity: 0/32` means no active child sessions;
  the server can still be connected.
- `Session failed: Process exited with error` is a child failure. Run
  `cclaude --verbose` to see the native per-session log path. Logs may contain
  private prompts, paths, or credentials: inspect locally and share only the
  minimal sanitized error, never entire logs.
- A terminal's `Connected` status is insufficient acceptance. Check the exact
  session URL from the phone/browser and confirm a message reaches the session.
- `Bridge environments are not available for this organization` is a provider
  eligibility/organization rejection, not an absent caffeine assertion. Check
  `claude auth status` privately, confirm the intended account/subscription and
  organization policy, and consult official Remote Control troubleshooting.
  Do not log out, change account grants, or replace credentials automatically.
- To select an older disconnected browser conversation, pass its full URL to
  `--session-id`. Do not infer the desired conversation from the web list order.

## Validation

```sh
python3 -m unittest discover -s tests -p 'test_claude_remote.py' -v
bin/agents-config validate
bin/agents-config docs
bin/agents-config docs --check
git diff --check
```

Tests use temporary homes, fake Claude/caffeinate/process inspection, and real
advisory locks. They do not launch live conversations. Live CLI reconnection and
browser/mobile acceptance must be reported separately.
