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

The helper prefers the `claude` on PATH when it is version 2.1.200 or later.
If it is too old or unavailable, it checks existing installations at
`~/.local/bin/claude`, `/opt/homebrew/bin/claude`, and `/usr/local/bin/claude`,
printing the selected fallback. It never installs or updates Claude. This avoids
terminal-specific PATH differences selecting a CLI without resume support.

## Commands

```sh
cclaude                        # Server mode: bring back sessions, accept new chats
cclaude --worktree             # Server mode with a git worktree per new session
cclaude --continue             # Serve only the last recorded session
cclaude --session-id SESSION_URL_OR_ID   # Serve only that session
cclaude --status               # Inspect without launching Claude
cclaude --verbose              # Include native session diagnostics/log locations
cclaude --help
```

The default (`--server` is an alias) runs `claude remote-control --spawn same-dir`.
That server brings back every session the folder's previous server was serving,
for about four hours after it stopped, including a session last served by
`--continue`. It also creates a session for each new chat started with **+** or
**New** in the Claude desktop or mobile app, or at claude.ai/code, so those chats
appear as their own threads on every device. `--worktree` gives each new session
its own git worktree; the pre-created session stays in the current folder.

`--continue` and `--session-id` serve **one** session and exit when it ends. New
chats sent to that folder cannot create sessions, so they land in the served
thread. Use them only to bring back a session older than the restore window, or
an archived one; both unarchive it. They cannot be combined with `--spawn`,
`--capacity`, or pre-creation flags. The helper retains the user's
`bypassPermissions` choice in every mode.

Run at most one Remote Control process per folder. Stopping one while another
runs in the same directory can archive its sessions. Concurrent wrapper
invocations use an OS advisory lock keyed by the physical current directory,
including when reached through a symlink. Locks are stored owner-only under
`~/.agents/local/claude-remote/`, contain no launch environment, and release when
the wrapper exits. Do not unlink lock files while a wrapper might run.

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
- New chats landing in an existing thread means the folder's server runs with
  `--continue` or `--session-id`. Stop it with Ctrl+C and run `cclaude`; the
  served session comes back in server mode.
- To bring back a session older than the restore window, pass its full URL to
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
