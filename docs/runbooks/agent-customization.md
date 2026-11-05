# Maintain agent capabilities and native configuration

Use this when a tool is missing, an agent repeatedly gets stuck, or a persistent
skill/configuration change is requested. The [harness research and plan](../agent-harnesses.md)
maps native paths and known gaps; refresh official documentation for the specific
installed version before relying on a new convention.

## Identify the failing layer

Read the root README, generated inventory, global rules, and applicable project
instructions. Inspect the working tree and exact target/account. Then distinguish:

| Layer | Useful evidence | Appropriate correction |
| --- | --- | --- |
| Discovery | Skill selector/rendered context, loaded instruction sources, overrides. | Correct path/description or instruction bridge; new session where required. |
| Configuration | Native config parse, owned manifest/link status, client version. | Update the authoritative source and preserve application-owned fields. |
| Local execution | Tool availability/PATH, sandbox paths/network, process owner. | Fix launcher or intended native policy, not unrelated global permissions. |
| Authentication/authorization | Account identity plus exact resource read or required operation. | Restore the intended profile/sign-in or obtain the specific missing grant. |
| Workflow | Actual error, provider operation, state read-back and expected result. | Improve the relevant runbook/helper/skill and verify the result. |

Inventory presence, an MCP URL, and a successful parser check prove different
things from actual authenticated access. Capture small sanitized evidence rather
than native auth files, raw prompt dumps, or full environment/config output.

## Choose the owning source

- Put portable workflows in `skills/`. Keep the entrypoint short; use references
  for conditional detail. Check existing skills before adding another. Imported
  skills retain source revisions and adaptation notes in `licenses/README.md`,
  alongside their preserved licenses. Skills need no inventory registration.
- Use repository `AGENTS.md` for project context and `rules/AGENTS.md` for the
  managed Codex global instructions. Cursor User Rules are application/account
  settings; creating a similarly named home file does not prove it loads.
- Shared MCP definitions belong in `config/mcp.json`; private profile locations in
  `config/profiles.json`; provider project selectors in the relevant hosting manifest.
  Keep actual credentials in their registered ignored/native locations.
- Other settings, hooks, native command rules, and roles need harness-specific
  sources. Extend `scripts/install.py` with preservation/restore coverage before
  adding managed destinations to `config/links.json`. Do not copy native auth,
  project databases, plugin executables, or whole settings directories into Git.
- Native Codex command rules currently live in `~/.codex/rules/default.rules`.
  Cursor's CLI settings live in `~/.cursor/cli-config.json`; editor sandbox and
  Auto-review files have separate schemas. Record intended ownership before edits.

## Secrets and local services

The global shell source is `~/.secrets.sh`; normal zsh and login/interactive Bash
load it (inventory `shell.secrets`), and child processes inherit exports. Clean
noninteractive shells need explicit injection/profile loading. `~/.shortcuts.sh`
contains shell helpers, not provider credentials. Provider-specific profiles are listed in `config/profiles.json`;
a profile with `variables` reads only those literal assignments from the file
without executing it. Application `.env*` files remain in their project.
Inspect the project's actual loader and precedence before choosing a file. Do not
load another workspace's token as an authentication fallback.

When the task authorizes secret edits, use the registered private destination,
preserve unrelated assignments and owner-only permissions, and update atomically.
Suppress value-bearing logs/diffs and verify names/presence or authenticated
behavior without printing values. A shell source can execute commands; do not
source arbitrary contents just to discover variable names. Never print lines from a
secret file, even through a mask: commented lines can hold full old credentials.
Derive only assignment key names, and run secret-handling snippets under bash, since
zsh prints a variable's value when `local` re-declares it. Record only paths,
names, consumers, reload steps, and grants in Git.

For process/service work, start with `~/git/AGENTS.md` and the actual project's
instructions. Existing web services use `~/git/local-dev`; read its runbook and
registry before selecting a manager command. Check PID/CWD/ownership before killing
anything. Do not create a competing supervisor to solve a configuration problem.

## Contribute and prove the change

Use the Git management workflow, respecting the user's branch choice. Update
`config/inventory.json` when configuration locations, ownership, credentials,
consumers, or update/recovery procedures change; update the relevant runbook and
record meaningful changes in `CHANGELOG.md`. Reference actual manifests rather
than copying their settings into notes. Ordinary skill edits are maintained in
`skills/` without inventory changes.

```sh
~/.agents/bin/agents-config validate
~/.agents/bin/agents-config docs
~/.agents/bin/agents-config docs --check
git diff --check
```

For mechanics changes, run focused regression tests and installation/restore in a
temporary home. Test a new skill with realistic requests and available tools; its
frontmatter validator alone does not prove behavior. For provider work, select the
intended manifest/profile and use an explicit read or authorized bounded operation.
Restart/reopen the target client when required and verify actual skill/rule/MCP
discovery. A passing Codex call does not establish a passing Cursor call.

Record observed versions, target IDs and sanitized checks in ignored local status
when useful. Publish the PR with validation and remaining gaps, and leave active
application configuration intact unless this task authorizes changing it. A proposed
policy or connection is not an installed capability.

## Claude Code auto mode and PR writes

Claude Code's auto-mode classifier reviews shell commands after permission rules.
Its built-in `External System Writes` rule (`claude auto-mode defaults --label
'External System Writes'`) allows two writes on a PR the user asked the agent to
work on, or one the agent opened in the session: new comments (including inline
replies) and title/body edits. It soft-blocks everything else on GitHub PRs:
resolving review threads, reactions, editing or deleting comments, comments on
other PRs, and bodies the classifier can't see, such as `--body-file` or `-F
body=@file` naming a file the session didn't write, or a pipe from another
command. A compound command that includes one blocked write is refused whole.
Codex is unaffected because its local policy allows `gh` (`~/.codex/rules`).

The [review loop](../../skills/git-management/references/review-loop.md) gives
commands that stay within those rules. To let agents resolve threads and post
review-loop comments without per-action approval, add personal entries to
`autoMode` in `~/.claude/settings.json` (application-owned; edit only with the
user's consent). Always keep `"$defaults"`, because a list without it replaces
every built-in rule in that section:

```json
{
  "autoMode": {
    "environment": [
      "$defaults",
      "Source control: GitHub account paulshorey; all repositories under github.com/paulshorey are the user's own"
    ],
    "allow": [
      "$defaults",
      "PR review loop: on a pull request in a github.com/paulshorey repository that the agent is working on, replying to review comments, posting PR comments, and resolving review threads is the user's standing workflow, unless the text contains a bot or ChatOps command"
    ]
  }
}
```

Paul approved and applied this block on 2026-11-05. Check the result with
`claude auto-mode config`; remove the `autoMode` key to undo it. Without this, a user can
approve one refused action under `/permissions` → **Recently blocked**, or name
the exact action in a message (for example, "reply to the three findings on
PR 31 and resolve their threads"), which the classifier treats as explicit intent.
