# Configuration changes

Git history records tracked-file diffs. This log records meaningful configuration,
credential-reference, provider-grant, and ownership changes without secret values.
Verification dates describe historical observations, not current readiness.

## 2026-10-14 — Codex/Cursor discovery and lifecycle plan

- Researched native skill/instruction/configuration loading, command policies,
  hooks, subagents, local project opening, and desktop-control scope. Saved a
  source-linked harness map and prioritized acceptance plan in `docs/agent-harnesses.md`.
- Added the portable `agent-customization` skill and a maintenance runbook for
  diagnosing discovery, execution, account, and workflow gaps and contributing
  persistent improvements through the owning sources.
- Registered previously unlisted native policy/settings/context locations and
  project-secret conventions as references. Extended the global shell-source notes
  without reading its secret values or sourcing it for discovery.
- Confirmed Codex global rules/shared skill discovery using captured prompt-input
  metadata. Cursor effective User Rules, editor policy, and native MCP calls remain
  explicit verification work in the plan.
- No native permissions, active client configuration, provider grants, credential
  values, processes, DNS, deployments, or tool pins were changed. The new shared
  skill is available to local discovery; further setup changes remain proposed.

## 2026-10-14 — Implementation review and account consistency

- Centralized credential locations in `config/profiles.json`. CLI/MCP launchers,
  hosting helpers, token setup, and inventory now resolve the same profile IDs;
  no credential files or values were moved or rotated.
- Replaced line-based TOML rewriting with hash-pinned TOML Kit, restored only in
  ignored local Python packages. Valid quoted/dotted/inline tables and multiline
  strings are preserved; already-matching application config is not rewritten.
- Static validation now detects unsupported defaults, unregistered shared config or
  MCP definitions, invalid link sources/targets, and malformed profile metadata.
  Local checks flag added/removed plugins or application MCP runtimes and tool drift.
- Removed the deprecated zone-membership field as DNS Edit evidence. Live checks
  verify real DNS reads and explicitly mark write permissions untested; recorded
  permission scope comes from the dashboard grant.
- Live checks accept an explicit manifest and bind Cloudflare MCP verification to
  its account and zone. Added native GitHub authentication context and editor schema
  association without exposing native credential stores.
- New install backups retain private installed-state snapshots; restore refuses to
  overwrite subsequent file edits. Historical backups retain their original guard.
- Review evidence and scope limits are recorded in `docs/reviews/2026-10-14.md`.

## 2026-10-14 — Configuration inventory

- Added a concise root `AGENTS.md` linking repository work to the inventory,
  global rules, and required maintenance commands.
- Plugin checks now report malformed application settings as a failed result and
  continue other checks; regression coverage includes root and per-plugin formats.
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
- Verification: token active, user read succeeded, all 12 current zones were readable,
  the dashboard declared DNS Edit for all zones, and the official hosted MCP
  initialized and executed a zone read. Legacy zone membership fields are not
  evidence of API-token grants.
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
