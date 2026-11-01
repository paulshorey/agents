---
name: railway-iac
description: Connect to Railway, troubleshoot deployments, and configure or apply TypeScript Infrastructure as Code with the Railway CLI. Use for Railway services, environments, monorepos, preview deployments, CI plan/apply workflows, legacy config migration, and configuration drift.
---

# Railway Infrastructure as Code

Manage Railway as reviewed desired state while preserving the repository's own
deployment conventions. Projects are commonly under `~/git`; start in the requested
repository and read its `AGENTS.md`, README, `.railway/README.md`, package scripts,
and existing workflow files before choosing commands.

## Start here

1. Extract project, environment, service, and deployment IDs from the user's URL.
   Select the matching credential profile and confirm access to that exact project.
2. Read [local connections and project map](references/local-connections.md) for
   this machine's profile, project and partial ownership, environment IDs,
   and CI secret names.
3. For a failed deployment, read [deployment operations](references/deployment-operations.md)
   and identify the first failing stage before changing anything.
4. For IaC changes, imports, or CI, read [authoring and CI](references/authoring-and-ci.md).
   Review the complete plan, apply the intended file, require a clean follow-up plan,
   and verify the resulting deployment and public readiness endpoint.
5. For new projects with Cloudflare DNS, use `deploy-railway-with-cloudflare` and
   its bootstrap reference. `~/.agents/README.md` documents the shared toolchain,
   credential profiles, and managed configuration links.

Read the current deployment branch, not just a local feature checkout. Check
`git status --short` and preserve unrelated changes. A merged runbook or workflow
may not yet exist in the local checkout; inspect the remote branch or use an
isolated worktree rather than overwriting user work.

For authorized production promotions, follow [Git management](../git-management/SKILL.md)
for the full `main` to `prod` merge and the [deployment workflow](../deploy-railway-with-cloudflare/SKILL.md)
for production database migrations and release validation alongside IaC verification.

## Local access on this machine

The local workspace credential is `RAILWAY_API_TOKEN` in `~/.secrets.sh`, selected
by profile `railway.workspace` in `~/.agents/config/profiles.json`. On this Mac,
normal zsh and login/interactive Bash load that file; children inherit exported
values. A clean noninteractive Bash process does not load it automatically.
`~/.shortcuts.sh` defines aliases and directory helpers, not Railway credentials;
its `*-prod` directory hook does not select a Railway project or environment.
Use an inherited token, explicitly load the trusted file in a Bash subshell as below,
or use the registered profile loader for clients without shell startup.

Unset `RAILWAY_TOKEN` and fail if `RAILWAY_API_TOKEN` is absent before local workspace
commands. In CI/cloud tasks, use only the intended environment’s project token in
`RAILWAY_TOKEN`, with `RAILWAY_API_TOKEN` unset. Never copy the local workspace
credential into GitHub Actions to repair a failed project-token job. Pass the Homebrew CLI path
(`/opt/homebrew/bin/railway`) when a repository's npm CLI binary was not installed.

For a read-only check of Notes dev:

```bash
bash --noprofile --norc -c '
  set -e
  source "$HOME/.secrets.sh" >/dev/null 2>&1
  unset RAILWAY_TOKEN
  test -n "${RAILWAY_API_TOKEN:-}" || exit 1
  export RAILWAY_PROJECT_ID=7c451bd1-350a-4fb3-a08f-5295863269ce
  export RAILWAY_ENVIRONMENT_ID=8cbb1415-ac2b-46c3-ae8c-144265017189
  railway api "query(\$id: String!) { project(id: \$id) { id name } }" \
    --raw-var id="$RAILWAY_PROJECT_ID"
'
```

Run repository plans in a shell with the same profile and explicit target, using
its pinned CLI. A valid workspace token may return Unauthorized for `whoami`,
account-wide `list`, or `link`; test a scoped project query before concluding the
credential is invalid. IDs and token scope must agree before mutation.

Never print credentials or returned secret values. Run secret-handling snippets
under `bash --noprofile --norc -c '...'`, not the default zsh: zsh prints
`name=value` when `local`/`typeset` re-declares an already-set variable, so a
`local v` inside a copy loop leaks the previous secret. Copy values between
services with `railway variable set KEY --stdin --skip-deploys`, never via
arguments or echo. Credential profiles and local
skills are not automatically copied to cloud agents: supply this skill and inject
the intended scoped token through that agent's secret manager. A credential profile
or skill does not grant authorization for additional actions.

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

The dashboard's build/start/healthcheck fields show the **applied live state**.
Populated values are expected after IaC apply; do not clear them merely because
TypeScript also declares them. Keep only the legacy **Railway Config File** field
empty after migration.

## Resolve identity before mutation

Prefer IDs from a supplied Railway URL or repository documentation. A service URL has
the useful identifiers in this shape:

```text
https://railway.com/project/<PROJECT_ID>/service/<SERVICE_ID>?environmentId=<ENVIRONMENT_ID>
```

Extract those IDs before using a possibly unrelated local link. Clear inherited service selectors when they
do not belong to the target. When no URL or local
documentation identifies the target, inspect the authenticated context. With a
workspace-scoped token, use `railway api` to discover projects first; the identity
commands below can require broader scope:

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
the IaC context after confirming the existing resources and the context fields
actually populated by the installed CLI.

Interactive developers use `railway login`; truly headless sessions may use
`railway login --browserless`. CI and unattended agents should use a project token in
`RAILWAY_TOKEN`, scoped to one project/environment, and verify both IDs with
`railway api 'query{projectToken{projectId environmentId}}'`. Reserve the broader
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

A clean IaC plan proves configuration alignment, not application health. An apply
may not start a new deployment, and a source build can pass while the IaC job fails.
Check the separate config job and the source commit of the active release. After a
configuration change that requires deployment, verify the exact affected deployment
reaches a terminal successful state. Inspect build and deploy logs, confirm the
configured start command ran, and call the readiness endpoint through the Railway
domain and any important custom domain.
Railway health checks run during deployment, not continuously, so an `Active` state is
not a substitute for ongoing monitoring.

## Stop conditions

Stop and preserve evidence when the target is ambiguous, a plan contains an
unexplained destroy, a database or volume would be replaced, credentials lack the
required scope, or the live environment changes during review. When a deployment
fails, continue diagnosis within the authorized task and retry after correcting the
first failure; repeated rebuilds do not fix configuration, provider, migration,
or application errors.

Official references:

- https://docs.railway.com/infrastructure-as-code
- https://docs.railway.com/infrastructure-as-code/reference
- https://docs.railway.com/cli
- https://github.com/railwayapp/railway-ts-sdk
- https://github.com/railwayapp/config

---

**Self-reflection and improvement:**
Consider these instructions with your current use case. Can anything be done do to make your job easier? Can we improve these instructions to help make the task easier next time? Edit this skill `skills/railway-iac` with any improvements you can think of for next time or suggest possible improvements.
