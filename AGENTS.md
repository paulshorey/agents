# Project: Shared agent configuration

Public source for shared skills, configuration, and provider tools. The active
checkout is `~/.agents`; `~/prs/agents` is for contributions and review. The human
developer pulls merged changes into `~/.agents` to make them available locally.

## Ownership and maintenance

Read [README.md](README.md), [the inventory](docs/INVENTORY.md), and
[global rules](rules/AGENTS.md) before changes.

- Maintain skills in `skills/`; skill edits need no inventory registration.
- Preserve application-owned settings; use `scripts/install.py` for links.
- Keep credentials, OAuth state, backups, and rendered settings in ignored local
  storage. Never commit or print secrets, fragments, or hashes.
- When configuration ownership, locations, credentials, consumers, or recovery
  procedures change, update `config/inventory.json`, the owning runbook, and
  `CHANGELOG.md`. Reference existing manifests instead of copying settings.
- Verify actual provider access and resulting state. Configuration alone does
  not establish authentication or authorize external changes.

## Validation

Before committing, run `bin/agents-config validate`, `bin/agents-config docs`,
`bin/agents-config docs --check`, and `git diff --check`.

# Research and report

If something went wrong, stop and report back. Include all info, data, and logs.
If unsure about something, research, search the web, find latest techniques and best practices.

# Next steps

Consider what was recently done, what's in progress, and how it contributes to the goal.
Decide and recommend what to do next.

# Goal: Reliable, reusable agent workflows across projects
