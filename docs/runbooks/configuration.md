# Configuration ownership, installation, and recovery

Run `agents-config list` and `agents-config show ITEM` to find an item's owner,
authoritative source, installed location, and consumers. `config/inventory.json`
is the metadata index; existing configuration files own actual settings.

## Where to edit

| Item | Authoritative edit location | Installation or reload |
| --- | --- | --- |
| Shared Railway/Cloudflare MCP definitions | `config/mcp.json` | Installer, then a new agent session |
| Six managed Codex preferences | `config/codex.defaults.toml` | Installer; restart client or start a new session |
| Credential profile IDs and locations | `config/profiles.json` | Move/restore private file separately; restart affected MCP clients |
| Other Codex settings, profiles, plugin toggles, application MCP runtimes | Codex settings or the active `~/.codex/config.toml` | Follow application reload behavior; preserve managed sections |
| Global agent instructions | `rules/AGENTS.md` | Symlink already installed; new agent session |
| Claude Code Git/PR user rule | `rules/git-workflow.md` | Installer links `~/.claude/rules/git-workflow.md`; new session |
| Cursor Git/PR user rule | `rules/git-workflow.mdc` | Installer links `~/.cursor/rules/git-workflow.mdc`; new session |
| Repository agent entrypoint | `AGENTS.md` | Links repository work to the inventory and global rules |
| Agent utility PATH hook | `config/env.sh`; installer owns its `.zprofile` source hook | New login shell or explicitly source env.sh |
| Shell secrets | `~/.secrets.sh`, loaded by `~/.zshenv` (normal zsh), `~/.profile` (login Bash), and `~/.bashrc` (interactive Bash); clean noninteractive shells require injection/profile loading | New shell; restart apps that started before the change |
| Other shell settings | Your active `.zprofile`, currently backed by ignored `local/shell/zprofile` | New login shell |
| Link destinations | `config/links.json` | Installer after checking destination ownership |
| Inventory metadata | `config/inventory.json` | Regenerate `docs/INVENTORY.md` |

For native discovery, execution policies, hooks, role formats, and differences
between Cursor editor/CLI and Codex, consult the
[harness map](../agent-harnesses.md). Use the
[customization runbook](agent-customization.md) for new tooling or repeated setup
failures. Cursor account User Rules remain application-owned. The managed local
user-rule file below supplies Git/PR routing separately from Codex instructions.

The installer owns only keys present in `config/codex.defaults.toml` from its
allowlist: model, reasoning effort, verbosity, reasoning summary, web search,
and service tier. It preserves unrelated settings and comments. Removing a key
from the defaults file relinquishes ownership; it does not delete the active value.
Project configurations and runtime overrides may take precedence over user defaults.

Do not edit generated `docs/INVENTORY.md` directly. Do not store credentials in
shared defaults or MCP JSON. The complete application config remains ignored;
it can contain host-specific paths, runtime state, and sensitive settings.

## Global Git and PR routing

The policy lives in `skills/git-management/`, with `pr-management` as a short
compatibility entrypoint. The common entrypoint covers Git publishing; conditional
references cover the Codex review loop, PR maintenance, and production promotions.
Keep instructions in that owning skill rather than copying them into projects.

`rules/AGENTS.md` directs Codex through its existing global link. Claude Code's
user-level `~/.claude/rules/git-workflow.md` loads the short shared router.
Cursor's local user-level `~/.cursor/rules/git-workflow.mdc` uses
`alwaysApply: true` and points to that same router. Both links are declared in
`config/links.json` and installed by `scripts/install.py`; other user rules,
project instructions, account rules, and application settings keep their existing
owners. Do not replace a user's whole CLAUDE.md or account rules.

Inspect installer output before `--apply`; it must contain only intended changes.
Use repeatable `--only-link TARGET` selectors to install/check just these rule links
without rendering unrelated Codex/shell settings. Selecting the Cursor MCP link still
validates `config/mcp.json` as a full installation does. The installer backs up existing
destinations and supports guarded restore. Verify link targets and contents, then
check a fresh client session from another project for the routing instruction.
A link proves installation, not model selection or compliance; current sessions
and cloud agents with a different home need their own entrypoint or a new session.
A Codex override can replace its global file; client restrictions can also affect
rule loading.

Codex's GitHub integration reviews each ready PR when it opens and after every
push, so the loop never posts review-request comments. Agents open PRs ready for
review and mark a draft ready after pushing to it; drafts are left for PRs the
user parks to pause automatic review. The 30-minute limit is the longest
wait for Codex's review of the pushed head, not a mandatory delay after it
completes. Record the head and push time, handle all feedback when the review
arrives or time runs out, and repeat after functional fixes. If no review has
arrived, report it pending. `pr-context.py` reports the head Codex last reviewed
in `codex_review`; automatic-review settings live in Codex, not this repository.

Sources: [Codex global instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md),
[Claude Code user rules](https://code.claude.com/docs/en/memory#user-level-rules),
and [Cursor local user-rule files](https://prod.cursor.com/help/customization/rules#where-are-rules-stored).

## Inspect and install

```sh
python3 ~/.agents/scripts/install.py
# Review the reported changes, then apply the intended configuration:
python3 ~/.agents/scripts/install.py --apply
~/.agents/bin/agents-config check
```

Installation preserves existing configuration, creates ignored local backups, and
installs the links declared in `config/links.json`. If an application replaces a
link while saving, the check reports it. The installer can adopt current application
settings and restore the link without silently replacing unrelated settings.
Cursor JSON with other definitions needs an explicit merge before installation.
Likewise, an existing text destination such as `~/.codex/AGENTS.md` or a Git/PR
rule file whose content differs from its source is refused; merge it into the
source or move it first, so installation never silently deactivates instructions.

## Plugin and authentication state

`application.codex-plugins` records registered plugin toggles as metadata. Change
them through supported Codex settings, then update that record to reflect the intended
customization. The inventory check compares toggles; the installer does not manage them.
Application plugin caches and bundled MCP executables remain application-owned.

Use `codex login status` for Codex sign-in and the supported login flow for recovery.
The active `cli_auth_credentials_store` controls file versus OS credential storage.
Inventory does not read native authentication stores. Do not relocate OAuth databases,
copy login tokens into shared files, or assume cloning config establishes authentication.

GitHub CLI authentication is separate from an agent's GitHub connector account.
Use `gh api user --jq .login` to check the CLI identity without displaying tokens,
and select repository owner/host explicitly for operations. Use supported CLI or
connector settings to change sign-in within the current task's authorization.
Native GitHub credentials/configuration remain application-owned under the CLI's
normal store; do not copy them into shared config or print credential-store output.

`application.parallel-connectors` records the Parallel connectors in the Codex app
and claude.ai. `engineering-research` uses them only when its API script,
`scripts/parallel.py`, fails; the script needs only `PARALLEL_API_KEY` and covers
search, full-page extraction, and deep research. claude.ai connectors also load in
Claude Desktop and Claude Code sessions on that account. Add or remove connectors in
each app's connector settings; their grants stay application-owned.

## Backup and restore

Installer backup locations are returned by `--apply` and kept in ignored
`local/install-backups/`. They may include credentials and private configuration.

```sh
python3 ~/.agents/scripts/install.py --restore ~/.agents/local/install-backups/TIMESTAMP
```

Restore refuses to overwrite destinations whose link changed after installation.
New backups also retain private installed-state snapshots and refuse to restore
when an installer-rendered file (`local/codex/config.toml`, `local/shell/zprofile`)
changed after install, even when the symlink still matches. Tracked sources such
as rules and `config/mcp.json` keep their changes in Git, so updating them (for
example by a pull) does not block restore. Older backups predate this content
guard; inspect and preserve newer local edits before restoring those.
A destination that was already a symlink is recreated as that symlink. Restore
rewrites its target's saved bytes only when the target is one of the two files
install re-renders, `local/codex/config.toml` or `local/shell/zprofile`; other
targets, such as dotfiles-managed rules or other `local/` files, keep their
current contents. Backup restoration does not recover a
revoked provider token. Keep encrypted secret backups separately or use provider
replacement procedures. Update inventory records when configuration locations,
ownership, credentials, consumers, or update/recovery procedures change; update
the appropriate runbook and meaningful changelog entries in the same PR. Ordinary
skill edits are maintained directly in `skills/` without inventory registration.

References: [Codex configuration layers](https://learn.chatgpt.com/docs/config-file/config-basic),
[credential storage](https://learn.chatgpt.com/docs/auth).
