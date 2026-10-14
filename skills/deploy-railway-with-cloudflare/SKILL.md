---
name: deploy-railway-with-cloudflare
description: Deploy GitHub applications to Railway with dev and production environments and Cloudflare DNS, including project bootstrap, branch sources, secrets, custom domains, and deployment verification. Use for this combined hosting workflow or its recovery.
---

# Railway hosting with Cloudflare DNS

Read `~/.agents/README.md` for tool paths and credential profiles. Use `railway-iac`
for workspace identity, resource ownership, and IaC. Use `cf-cli` for Cloudflare
command discovery and `use-railway` for provider reference material.

## Complete the authorized deployment

1. Inspect repository instructions, remote, branches, current changes, and deployment
   runbook. Establish the requested project/workspace, environment-to-branch mapping,
   domains, port, and secret requirements. Preserve unrelated work.
2. Select the workspace credential explicitly. Check scoped project access;
   `whoami` can fail for valid workspace tokens. For new projects, read
   [bootstrap and recovery](references/bootstrap.md). Create only the requested
   resources. Record returned IDs in a non-secret manifest using
   `~/.agents/config/hosting/example.json` as the shape.
3. Configure GitHub sources, build/start/health settings, and secrets per environment
   with Railway CLI/API and the owning IaC file. Verify branch triggers directly.
   Preserve secrets in IaC, supply sealed values separately, and require a clean
   plan after an authorized apply.
4. Register custom domains with `railway domain` and explicit port/project/
   environment/service. Inspect existing registrations instead of duplicating them.
   Adopt registered domains in IaC and read required DNS records from domain status.
5. Run `~/.agents/bin/agents-hosting doctor --manifest PATH`, then
   `plan --manifest PATH --plan-file ~/.agents/local/hosting/NAME.plan.json`.
   The helper's plan/apply manages **DNS only**; Railway provisioning and IaC
   remain native operations. Review record changes within the authorized scope,
   then apply the current saved plan when authorized. Regenerate stale plans.
6. Verify record read-back, domain ownership/certificate state, the exact deployment's
   SUCCESS status, HTTPS health, source branch/commit, and the config workflow.
   `verify` checks HTTPS/branch/commit when configured in the manifest. A healthy
   page alone does not establish application-specific behavior; run authorized
   functional tests when needed.

When access is missing, finish independent work and identify the specific one-time
authorization needed. Do not bypass consent, paste tokens into chat, or reuse another
project's CI token. MCP URL configuration and local workspace tokens are separate;
new MCP tools normally require authentication and a new agent session.

## Waiting and recovery

DNS and TLS converge independently. Check at reasonable intervals within a bounded
window, keep progress visible, and report pending state when needed. Actual DNS
answers and validated HTTPS are evidence; a lagging advisory alone is not a reason
to rewrite records. Retry certificates only after a reported retryable failure.
Never disable certificate validation to make a test pass.

After an interrupted DNS apply, regenerate a plan: completed records become no-ops.
The helper refuses ambiguous route records, stale plans, and mismatched workspace,
zone, project, environment, source branch, or domain port. It preserves other TXT,
MX, and subdomain records. Use native provider operations for unsupported record
types/project shapes, following the same identity and read-back checks.
