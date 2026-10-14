---
name: use-railway
description: Operate Railway projects, services, environments, deployments, variables, domains, and diagnostics using official Railway CLI and MCP references. Use when the task targets Railway infrastructure.
---

# Use Railway

This installation vendors Railway's official reference material at the revision in
`~/.agents/config/skill-sources.json`. The entrypoint is curated for this machine;
provider updates are intentional Git changes, not automatic session-start installs.

Read `~/.agents/README.md` for installed tools and access. For this user's targets,
read `railway-iac` and its local connections reference before selecting credentials.
Use a scoped project query for workspace tokens: `whoami`/`me` may fail despite valid
access. Select the intended workspace and resource IDs before creating or deploying.
Do not treat a failed identity endpoint as proof of missing authentication.

## Route to provider references

- New projects/services/environments: [setup](references/setup.md).
- Variables, sources, networking/domains: [configure](references/configure.md).
- Source deploys and exact deployment status: [deploy](references/deploy.md).
- TypeScript IaC import/plan/apply: [IaC](references/iac.md), plus local `railway-iac`.
- Logs, health and failures: [operate](references/operate.md).
- GraphQL/API schema and request mechanics: [requests](references/request.md).
- Railway plus Cloudflare DNS: local `deploy-railway-with-cloudflare`.

Choose CLI for local repo/profile operations, hosted MCP for authenticated platform
operations, and `railway api` for missing commands. Inspect schema with `api search`
/`api describe` before constructing unfamiliar fields. MCP OAuth and CLI workspace
tokens are separate. Do not overwrite managed configs with `setup agent` or update
pinned tools incidentally. Never send secrets through command arguments or tool output.

After changes, read back the same resource. Track the exact deployment until SUCCESS;
a successful upload or CLI exit is not deployment completion. Verify application health
and any authorized functional behavior separately from infrastructure readiness.
