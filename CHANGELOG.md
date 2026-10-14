# Configuration changes

Git history records tracked-file diffs. This log records meaningful configuration,
credential-reference, provider-grant, and ownership changes without secret values.
Verification dates describe historical observations, not current readiness.

## 2026-10-14 — Configuration inventory

- Added `config/inventory.json`, its schema, generated `docs/INVENTORY.md`, and
  `agents-config` lookup/validation/check commands. Registered credential profiles,
  environment variables, installed links, MCP integrations, tools, skills, runtime
  ownership, and plugin toggles. Secret values remain outside Git.
- Captured the six existing non-secret Codex preferences in
  `config/codex.defaults.toml`. The installer manages those keys while preserving
  other application settings; the captured values match the existing machine setup.
- Added credential/configuration update and recovery instructions, explicit live
  checks, sanitized ignored verification reports, and CI documentation validation.
- No provider grants, token values, DNS records, deployments, or tool pins changed
  as part of the inventory implementation. Git/PR history links this entry to its
  implementation and validation results.

## 2026-10-14 — Cloudflare all-domains identity permission

- `cloudflare.dns-token`: the user approved and saved User Details Read on
  **Agent DNS — all domains**, preserving DNS Edit and Zone Read for all zones.
  The original token value remained in the same ignored owner-only profile.
- Verification: token active, user read succeeded, all 12 current zones reported
  DNS Edit, and the official hosted MCP initialized and executed a zone read.
- Permission edits and secret rotation are different operations. No DNS changes
  were used to test access. Documentation was originally published in PR #4;
  the inventory PR includes that update for one review.

## 2026-10-14 — Shared hosting toolkit

- Established shared MCP definitions, configuration links, explicit credential
  loading, pinned cf CLI, imported provider skills, and Railway/Cloudflare hosting
  helpers. Kept application state, credentials, backups, plans, and journals ignored.
- Registered all-domains DNS/zone access instead of a single-zone token. Preserved
  the existing WebArts Railway workspace profile and working deployment tool pins.
- Delivered through [PR #3](https://github.com/paulshorey/agents/pull/3).
