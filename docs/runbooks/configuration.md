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
| Repository agent entrypoint | `AGENTS.md` | Links repository work to the inventory and global rules |
| Agent utility PATH hook | `config/env.sh`; installer owns its `.zprofile` source hook | New login shell or explicitly source env.sh |
| Other shell settings | Your active `.zprofile`, currently backed by ignored `local/shell/zprofile` | New login shell |
| Link destinations | `config/links.json` | Installer after checking destination ownership |
| Inventory metadata | `config/inventory.json` | Regenerate `docs/INVENTORY.md` |

The installer owns only keys present in `config/codex.defaults.toml` from its
allowlist: model, reasoning effort, verbosity, reasoning summary, web search,
and service tier. It preserves unrelated settings and comments. Removing a key
from the defaults file relinquishes ownership; it does not delete the active value.
Project configurations and runtime overrides may take precedence over user defaults.

Do not edit generated `docs/INVENTORY.md` directly. Do not store credentials in
shared defaults or MCP JSON. The complete application config remains ignored;
it can contain host-specific paths, runtime state, and sensitive settings.

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

## Backup and restore

Installer backup locations are returned by `--apply` and kept in ignored
`local/install-backups/`. They may include credentials and private configuration.

```sh
python3 ~/.agents/scripts/install.py --restore ~/.agents/local/install-backups/TIMESTAMP
```

Restore refuses to overwrite destinations whose link changed after installation.
New backups also retain private installed-state snapshots and refuse to overwrite
later file edits even when the symlink still matches. Older backups predate this
content guard; inspect and preserve newer local edits before restoring those.
Backup restoration does not recover a
revoked provider token. Keep encrypted secret backups separately or use provider
replacement procedures. Record persistent customization changes in the inventory,
appropriate runbook, and changelog in the same PR.

References: [Codex configuration layers](https://learn.chatgpt.com/docs/config-file/config-basic),
[credential storage](https://learn.chatgpt.com/docs/auth).
