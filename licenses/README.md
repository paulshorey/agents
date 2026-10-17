# Imported skill provenance

These notes preserve the upstream revisions and local adaptations of vendored
provider material so updates can be reviewed against the original source. They
are needed only when updating those imports. Skills are discovered directly from
`skills/`; local skills need no registration or separate source record.

## Cloudflare CLI

- Local skill: [`skills/cf-cli`](../skills/cf-cli/).
- Upstream: [cloudflare/skills at `53395984c3ea1925d00fce03b266112302f050e6`](https://github.com/cloudflare/skills/tree/53395984c3ea1925d00fce03b266112302f050e6/skills/cf-cli).
- Imported path: `skills/cf-cli`.
- Local adaptations: managed pinned CLI setup and anonymous discovery guidance in
  `SKILL.md`.
- Preserved license: [cf-cli/LICENSE](cf-cli/LICENSE).

## Railway

- Local skill: [`skills/use-railway`](../skills/use-railway/).
- Upstream: [railwayapp/railway-skills at `526e95524e964ed326689cbac4464d97a58ab81c`](https://github.com/railwayapp/railway-skills/tree/526e95524e964ed326689cbac4464d97a58ab81c/plugins/railway/skills/use-railway).
- Imported path: `plugins/railway/skills/use-railway`.
- Local adaptations: curated local entrypoint; official references and scripts
  preserved.
- Preserved license: [use-railway/LICENSE](use-railway/LICENSE).

## Last 30 Days

- Local skill: [`skills/last30days`](../skills/last30days/).
- Upstream: [mvanhorn/last30days-skill at `0341304f8ecb307ca0a939e48ecd002761ef23b2`](https://github.com/mvanhorn/last30days-skill/tree/0341304f8ecb307ca0a939e48ecd002761ef23b2/skills/last30days), version 3.28.0.
- Imported path: `skills/last30days`, including its scripts, references,
  and native agent metadata. Upstream's archive export excludes example media
  under `assets/`. The upstream root MIT license is included as
  [`skills/last30days/LICENSE`](../skills/last30days/LICENSE); the vendored
  bird-search client retains its own license.
- Local adaptations: hosted API v1 rejects unsupported retrieval/output constraints
  before submitting; watchlist polling honors numeric UTC cron schedules and avoids
  repeating a scheduled minute, validates finite nonnegative budgets, and marks
  schema/storage processing errors failed. Imported trailing whitespace is removed.
  Offline regression coverage lives in `tests/test_last30days_review.py`; operation
  details are in the skill's [local adaptations](../skills/last30days/references/local-adaptations.md).
  No setup wizard, browser-cookie access, provider credential changes, extra CLI
  installation, or hosted publishing was performed.
- Runtime: Python 3.12 or newer. Use the skill's runtime preflight and source
  health/setup instructions before research; a successful local CLI check does
  not establish authentication or live access to every source.
- Updates: deliberately select a new upstream commit, review the skill and
  scripts, replace the imported tree while preserving licenses, and update this
  provenance entry. Do not automatically track upstream HEAD.

When updating an import, compare it with the recorded upstream revision, preserve
the license and deliberate local adaptations, then update these notes in the same
commit. Local adaptations are also tracked in Git history.

## Parallel deep research

- Local skill: [`skills/parallel-deep-research`](../skills/parallel-deep-research/).
- Upstream: [parallel-web/parallel-agent-skills at `92694a248ce444fb74d9bc120a9b93e69316b9f8`](https://github.com/parallel-web/parallel-agent-skills/tree/92694a248ce444fb74d9bc120a9b93e69316b9f8/skills/parallel-deep-research).
- Imported path: `skills/parallel-deep-research`.
- Local adaptations: standalone setup replaces the unavailable upstream plugin
  command with project-owned installation and authentication instructions; normal
  lookups route to available web tools without requiring an absent companion skill.
  Authentication guidance covers active legacy logins and environment-key precedence.
- Root license preserved at [`skills/parallel-deep-research/LICENSE`](../skills/parallel-deep-research/LICENSE).
- Runtime: commands verified with `parallel-cli 0.9.3`; facts owns its pinned project-local CLI. Other projects reuse their own managed installation or deliberately provision an isolated environment. Existing authentication can be reused; no new account grant was made by this import.
- Updates: deliberately review a new upstream commit, replace the skill, preserve the license, and update this record. CLI installations are owned by their project, not this import.
