---
name: railway-iac
description: Configure, migrate, plan, apply, deploy, and troubleshoot Railway projects with the Railway CLI and .railway/railway.ts Infrastructure as Code. Use for Railway services, environments, variables, databases, domains, monorepos, CI plans, preview environments, deployment failures, or configuration drift.
---

# Railway Infrastructure as Code

Manage Railway as reviewed desired state while preserving the repository's own
deployment conventions. Projects are commonly under `~/git`; start in the requested
repository and read its `AGENTS.md`, README, `.railway/README.md`, package scripts,
and existing workflow files before choosing commands.

## Choose the control path

- Use the Railway CLI for `.railway/railway.ts`, local repository context, exact
  command output, `railway run`, deployments from the working tree, and logs.
- Use a Railway MCP connector when it is already available and the task is a
  platform-state read or a supported bounded operation. Pass explicit project,
  environment, and service IDs; MCP and CLI may not share local link state.
- Use the dashboard for inspection or an authorized recovery when CLI credentials
  are unavailable. Mirror recovery changes in IaC and reconcile them later.
- Use official Railway documentation when CLI flags or SDK types may have changed.
  The TypeScript SDK evolves independently from the CLI, so inspect installed
  versions and pin compatible versions in the repository and CI.

## Keep Railway configuration systems distinct

Infrastructure as Code describes a whole project/environment in
`.railway/railway.ts` and is evaluated only by `railway config plan` or
`railway config apply`. A source push uses the configuration already applied to
Railway; it does not evaluate the TypeScript file.

`railway.json` and `railway.toml` are the deprecated per-service Config as Code
system. The dashboard's **Railway Config File** field selects those legacy files.
Do not point it at `.railway/railway.ts`, and do not manage one service with both
systems.

## Resolve identity before mutation

Prefer IDs from a supplied Railway URL or repository documentation. A service URL has
the useful identifiers in this shape:

```text
https://railway.com/project/<PROJECT_ID>/service/<SERVICE_ID>?environmentId=<ENVIRONMENT_ID>
```

Extract those IDs before using a possibly unrelated local link. When no URL or local
documentation identifies the target, inspect the authenticated context:

```bash
railway --version
railway whoami --json
railway status --json
railway environment list --json
railway service list --json
```

Confirm workspace, project, environment, service, source repository, branch, domains,
variables, databases, buckets, volumes, and current deployment. A service name or
branch can differ by environment; encode intentional differences with
`ctx.isEnvironment(name)` after confirming the existing resources.

Interactive developers use `railway login`; truly headless sessions may use
`railway login --browserless`. CI and unattended agents should use a project token in
`RAILWAY_TOKEN`, scoped to one project/environment. Reserve the broader
`RAILWAY_API_TOKEN` for account/workspace operations. Do not set both, print tokens,
or write credentials or decrypted variable values into the repository.

## Inspect and author safely

For an existing project, inspect raw imported state without overwriting source:

```bash
railway config pull --json
```

`railway config pull` writes an authoring file. If one already exists it requires
`--force`; preserve and review the current file before any intentional replacement.
Avoid `--include-variables` unless decrypted non-sealed values are explicitly needed
and can be handled securely. Imported variable names should normally remain
`preserve()` entries.

Treat a non-partial definition as the complete desired graph for the selected
environment. Omitted owned services, variables, databases, volumes, buckets, or
domains can be deleted. Use named partials when separate repositories own different
slices of one environment. Read [authoring and CI](references/authoring-and-ci.md)
before creating resources, importing live infrastructure, migrating legacy config,
or setting up automated plans.

Read [deployment operations](references/deployment-operations.md) when configuring
build/start behavior, monorepos, variables, health checks, networking, volumes,
preview environments, production readiness, or troubleshooting a failed deploy.

## Plan, apply, and verify

Validate the repository's authoring file with its pinned toolchain, then plan:

```bash
railway config plan --file .railway/railway.ts
```

Read the whole plan. Confirm the environment and every add/change/destroy. Stop on
an unexpected deletion, renamed resource, wrong target, missing preserved variable,
or unresolved drift. Use `--json` for machine parsing, `--detailed-exit-code` for a
drift gate, and `--show-values` only when disclosure is appropriate.

Apply an approved plan through the repository's normal CI workflow. For a deliberate
interactive apply:

```bash
railway config apply --file .railway/railway.ts
railway config plan --file .railway/railway.ts
```

Non-interactive applies use `--yes`; destructive changes additionally require
`--confirm-destructive`. Never add that flag merely to make an unexplained plan pass.
Concurrent dashboard or IaC changes invalidate saved plans; re-plan and review rather
than bypassing the stale-state guard.

After any mutation, verify the exact affected deployment reaches a terminal successful
state. Inspect build and deploy logs, confirm the configured start command ran, and
call the readiness endpoint through the Railway domain and any important custom domain.
Railway health checks run during deployment, not continuously, so an `Active` state is
not a substitute for ongoing monitoring.

## Stop conditions

Stop and preserve evidence when the target is ambiguous, a plan contains an
unexplained destroy, a database or volume would be replaced, credentials lack the
required scope, the live environment changes during review, or a deployment fails.
Diagnose the first failure before retrying; repeated rebuilds do not fix configuration,
provider, migration, or application errors.

Official references:

- https://docs.railway.com/infrastructure-as-code
- https://docs.railway.com/infrastructure-as-code/reference
- https://docs.railway.com/cli
- https://github.com/railwayapp/railway-ts-sdk
- https://github.com/railwayapp/config
