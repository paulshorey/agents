# Railway deployment operations

Read this reference for service configuration, deployments, monorepos, health checks,
networking, storage, previews, production review, and failure diagnosis.

## Diagnose the failing stage first

Record the exact project/environment/service/deployment IDs, source repository,
branch, commit, failed stage, and the first useful error. The deployment ID is
often the `id=` parameter in the user's URL. Compare the failed deployment with
the active one; an Online service may still be serving an older successful commit.

| Stage or symptom | Inspect | Likely next action |
| --- | --- | --- |
| Initialization / Snapshot code | Deployment details, source/ref access, live `railwayConfigFile` | Missing legacy file: migrate/clear the stale path and apply the owning IaC; compilation has not begun |
| Build | Exact deployment's build logs, builder, root, dependency installation, command | Fix the first dependency/compiler/build-context error; use the repository's narrow checks |
| Pre-deploy | Migration/release logs and exit status | Correct the release step or connectivity; preserve migration history and avoid database reset/seed |
| Deploy / startup | Deploy logs, executed command, runtime files, PORT, required variables | Correct start/runtime configuration and verify readiness |
| Healthcheck / routing | Readiness response, dependencies, allowed Host, target port, DNS/TLS | Verify Railway domain first, then important custom domains |
| No deployment / skipped | Watch patterns, changed files, branch, focused-preview policy | Establish whether skipping is intended; include shared build inputs where needed |
| IaC job fails while app builds pass | GitHub config job logs, secret scope, file, IDs, stale plan | Fix the config job; a source deployment does not evaluate TypeScript IaC |

When initialization fails, build logs can be absent. Inspect the deployment's
failure message/stage in the dashboard or API rather than searching older successful
build logs or triggering repeated rebuilds. `service config at '.../railway.json'
not found` is a stale Config as Code reference; changing the start command alone
will not resolve it. See [authoring and CI](authoring-and-ci.md) for migration.

For an API audit, query explicit setting fields. `status --json` can omit them;
absence there does not prove `railwayConfigFile` is cleared. Inspect the project's
`environments` and each environment's `serviceInstances`, selecting `serviceId`,
`serviceName`, `railwayConfigFile`, `source`, build/start/pre-deploy commands,
`rootDirectory`, healthcheck, and `watchPatterns`. Use current schema inspection
when field shapes differ. Keep variable values out of diagnostic output.

## Build and start configuration

Choose Railpack for conventional source builds and a Dockerfile when the application
needs explicit system packages, build stages, or image behavior. A detected Dockerfile
can take precedence, so inspect the actual build logs and builder selection.

Railway injects `PORT`; web applications should bind to it and listen on `0.0.0.0`.
Declare a start command when automatic detection cannot find the process. In shared
monorepos, build from the repository root when workspace dependencies require it and
use service-specific commands such as:

```text
pnpm --filter <workspace> build
pnpm --filter <workspace> start
```

For isolated monorepo applications, a service root directory can reduce context. For
shared monorepos, keep the shared root and include the app, shared libraries, lockfile,
and workspace manifests in watch patterns. Watch patterns are gitignore-style and also
control which services Focused PR Environments deploy.

Use a pre-deploy command for migrations or other release work that must succeed before
new containers start. Make migrations backward compatible with the old deployment
during rollout and safe to retry. Volumes are not mounted during pre-deploy.

## Variables and local commands

Keep secrets in Railway variables. Prefer typed IaC references or Railway reference
variables over duplicated values. Variable changes normally redeploy the service.

`railway run --service <service> --environment <environment> <command>` injects the
selected service variables into a local process. It can expose secrets to that process;
verify the target and command first. Sealed values are not returned by `railway run`.

## Health and deployment lifecycle

A readiness endpoint should return a fast `2xx` only when the process can serve normal
traffic. Avoid destructive writes and expensive external calls. Railway checks against
the injected `PORT` and sends the host `healthcheck.railway.app`; allow that host when
the framework validates hostnames.

Health checks gate rollout but are not continuous monitoring. Independently call the
endpoint after deployment and configure alerts or an uptime monitor for continued
coverage. A service with an attached volume can have brief redeploy downtime because
Railway cannot mount the same volume to overlapping deployments.

Verify the exact deployment ID and state. A detached upload or exit code 0 does not
prove the release is active:

```bash
railway deployment list --service <service> --environment <environment> --json
railway logs --build <deployment-id> --service <service> --environment <environment> --lines 200 --json
railway logs --deployment <deployment-id> --service <service> --environment <environment> --lines 200 --json
```

Inspect build logs for dependency/build failures and deploy logs for start, bind,
healthcheck, crash, signal, and migration failures. Supplying the deployment ID avoids
accidentally reading the latest successful release while investigating a newer failure.

The CLI defaults to the most recent **successful** deployment when one exists.
Pass the exact failed ID, or use `--latest` deliberately. `--build` and
`--deployment` choose log type; the deployment ID is a positional argument.
Use bounded `--lines`/`--since` while investigating instead of leaving a stream
running. Sanitize application log output before sharing it: log messages may
contain credentials even when the CLI's plan output is redacted.

After a fix, confirm the intended source branch/commit remains selected, the first
failure is gone, the resulting deployment reaches SUCCESS, and public readiness
returns a successful response with required dependencies connected. A clean
post-apply plan and a passing app deployment are separate checks. If the config
change does not trigger a rollout, use the existing repository deployment mechanism
when a new deployment is part of the authorized task; do not upload unrelated local
feature changes just to test infrastructure.

## Networking and storage

Use private networking for service-to-service traffic in the same environment:

```text
http://SERVICE_NAME.railway.internal:PORT
```

Each environment has an isolated private network. Give public domains only to services
that need ingress. Confirm custom-domain DNS/TLS and its target port separately from the
Railway-provided domain.

Runtime container storage is ephemeral. Attach a volume for persistent filesystem data
and use an absolute mount path; application-relative `./data` normally maps to
`/app/data`. Volumes are mounted at runtime, not build or pre-deploy time. Plan backups,
restore tests, and capacity monitoring before production use. A bucket is usually a
better fit for shared object storage or horizontally scaled services. Bucket regions
cannot currently be changed after creation through IaC.

## Environments and previews

Use persistent environments for development/staging/production isolation and explicit
branch mappings. Duplicating an environment copies ordinary configuration and variables,
but sealed variables are excluded. Review the staged deployment after duplication.

PR Environments clone a configured base and are removed when the PR closes. Proposed
IaC changes are planned by CI; a source push does not apply those changes to an already
created preview. Sync or recreate the preview after base configuration changes. Enable
bot PR environments only when their build cost and permissions are intended.

Applying to the base does not retroactively update existing previews. Discover
current previews and reconcile each affected owning partial only when required by
the task. Preserve each repository's preview source branch; branches can differ
between services. Do not infer a preview branch from the environment's name.
For WebArts, read [local connections](local-connections.md) and supply the actual
`RAILWAY_IAC_BRANCH` before planning. If a partial's services unexpectedly use
different branches, resolve that discrepancy rather than applying one branch to all.

Focused previews may intentionally deploy only services whose watched paths changed.
An inherited service's skipped deployment is not itself a failure. Verify the
affected service actually built and that required dependencies are available.
Include app files, shared libraries/config, lockfile, workspace manifest, and root
build inputs in watch patterns where those inputs affect the service. Fixing IaC
alone does not guarantee the source integration starts a new deployment.

## Production review

Consider region proximity, private networking, restart policy, at least two replicas for
high availability, capacity, database HA, backups, notifications/webhooks, wait-for-CI
checks, rollback procedures, and multi-region disaster recovery. Apply each according to
the service's reliability and cost requirements; they are review points rather than
universal settings.

## Failure patterns

- **Initialization says config file not found:** the live service still points to
  removed `railway.json`/`railway.toml`; audit and clear the reference in affected
  persistent environments and existing previews, then apply IaC and verify.
- **Online but newest commit never deployed:** compare active release commit/time
  with the latest source push, watch-path skip, and failing initialization stage.
- **Unauthorized identity commands:** with a workspace token, test the exact
  project query before treating the token as invalid; recheck profile/precedence.
- **IaC file changes but settings do not:** inspect the config workflow's branch,
  trigger paths, credentials, selected file, and apply result; ordinary source
  builds use already-applied settings.
- **No start command detected:** inspect build context and package scripts; configure an
  explicit service start command, especially in monorepos.
- **Build succeeds, deploy crashes:** inspect deploy logs, `PORT` binding, required
  variables, runtime paths, signals, and memory use.
- **Healthcheck fails:** call the endpoint inside the running process context; check
  hostname restrictions, target port, readiness dependencies, and timeout.
- **Unexpected IaC deletes:** wrong environment, renamed resource, incomplete graph, or
  missing/incorrect partial ownership. Do not apply until explained.
- **Saved plan rejected:** the environment etag or `.railway/` tree changed. Re-plan.
- **Private DNS failure:** confirm both services are deployed in the same environment and
  use the service's Railway internal DNS name and port.
- **Volume-dependent rollout downtime:** overlapping deployments are intentionally
  prevented; design the service and maintenance window accordingly.

Official references:

- https://docs.railway.com/deployments/monorepo
- https://docs.railway.com/deployments/healthchecks
- https://docs.railway.com/networking/private-networking
- https://docs.railway.com/volumes
- https://docs.railway.com/environments
- https://docs.railway.com/overview/production-readiness-checklist
