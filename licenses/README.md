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
- Local adaptations: none. No setup wizard, browser-cookie access, provider
  credential changes, extra CLI installation, or hosted publishing was performed.
- Runtime: Python 3.12 or newer. Use the skill's runtime preflight and source
  health/setup instructions before research; a successful local CLI check does
  not establish authentication or live access to every source.
- Updates: deliberately select a new upstream commit, review the skill and
  scripts, replace the imported tree while preserving licenses, and update this
  provenance entry. Do not automatically track upstream HEAD.

When updating an import, compare it with the recorded upstream revision, preserve
the license and deliberate local adaptations, then update these notes in the same
commit. Local adaptations are also tracked in Git history.
