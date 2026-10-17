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

When updating an import, compare it with the recorded upstream revision, preserve
the license and deliberate local adaptations, then update these notes in the same
commit. Local adaptations are also tracked in Git history.

## Parallel deep research

- Local skill: [`skills/parallel-deep-research`](../skills/parallel-deep-research/).
- Upstream: [parallel-web/parallel-agent-skills at `92694a248ce444fb74d9bc120a9b93e69316b9f8`](https://github.com/parallel-web/parallel-agent-skills/tree/92694a248ce444fb74d9bc120a9b93e69316b9f8/skills/parallel-deep-research).
- Imported path: `skills/parallel-deep-research`; no local instruction changes.
- Root license preserved at [`skills/parallel-deep-research/LICENSE`](../skills/parallel-deep-research/LICENSE).
- Runtime: `parallel-cli >= 0.3.0`; facts project installs a pinned project-local CLI. Existing `PARALLEL_API_KEY` authentication is reused; no new account grant.
- Updates: deliberately review a new upstream commit, replace the skill, preserve the license, and update this record. CLI installations are owned by their project, not this import.
