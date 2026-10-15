---
name: agent-customization
description: Maintain Paul's shared agent skills, configuration, and tool integrations; diagnose capability gaps and add persistent customizations with documented ownership and verification. Use for agent setup changes, not ordinary application development.
---

# Agent customization

Read `~/.agents/README.md`, `docs/INVENTORY.md`, and `rules/AGENTS.md` before
changing persistent setup. Use the [maintenance runbook](../../docs/runbooks/agent-customization.md)
for contribution, secret-edit, and validation procedures. Consult the
[harness map and plan](../../docs/agent-harnesses.md) when native discovery or
Codex/Cursor differences matter; refresh official sources for changed behavior.

1. Reproduce the specific missing capability. Separate skill/rule discovery,
   config, PATH/runtime access, authentication/grants, and workflow errors.
   Inspect actual client version, instruction overrides, and intended account.
2. Improve the existing owning skill/helper when possible. Put portable skills
   in `~/.agents/skills`; store shared config/scripts in this repo. Keep native
   auth, state, backups, and secret values in registered ignored/native locations.
3. Use the harness's documented entrypoint. `~/.agents/skills` is shared discovery;
   the rest of this repository needs explicit instructions, references, or links.
   Codex global instructions do not configure Cursor User Rules. Their hooks,
   execution policies, role formats, and computer tools are not interchangeable.
4. Preserve unrelated application settings through `scripts/install.py`. For new
   managed files, establish ownership and test merge/restore before installing.
   Use existing provider profile/hosting manifests and local service managers.
5. Update inventory records when configuration locations, ownership, credentials,
   consumers, or update/recovery procedures change; update the relevant runbook
   and meaningful changelog entries. Skills live directly in `skills/` without
   inventory registration; imported provenance belongs in `licenses/README.md`.
   Never record secret values, fragments, or hashes.
6. Validate and regenerate inventory docs; test changed mechanics and fresh-client
   behavior. Verify exact account/resource access separately from local setup.
   Publish through the Git management workflow and identify remaining gaps.

Choose changes within the current request. A capability goal or documented token
location does not authorize unrelated infrastructure or account mutations. When a
task asks for a plan, keep proposed policy/connection changes clearly unapplied.
