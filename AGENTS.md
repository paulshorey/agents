# Agent configuration repository

This public repository manages shared AI-agent skills, configuration, and provider
tooling. Before changes, read [README.md](README.md), the
[configuration inventory](docs/INVENTORY.md), and [global rules](rules/AGENTS.md).

- Put skills in `skills/`; keep shared configuration and utilities in this repository.
- Preserve application-owned settings. Use `scripts/install.py` for configuration links.
- Keep secret values, OAuth state, backups, and rendered settings in ignored local
  storage. Never commit or print secrets, fragments, or hashes.
- Update `config/inventory.json` when configuration locations, ownership, credentials,
  consumers, or update/recovery procedures change. Update the relevant runbook and
  record meaningful changes in `CHANGELOG.md`. Reference existing manifests.
  Maintain skills directly in `skills/`; skill edits need no inventory registration.
- Before committing, run `bin/agents-config validate`, `bin/agents-config docs`,
  `bin/agents-config docs --check`, and `git diff --check`.
- Verify actual provider access and resulting state. Configuration grants capability;
  the current user request determines which external changes are authorized.
