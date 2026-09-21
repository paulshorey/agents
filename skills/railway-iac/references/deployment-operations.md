# Railway deployment operations

Read this reference for service configuration, deployments, monorepos, health checks,
networking, storage, previews, production review, and failure diagnosis.

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

## Production review

Consider region proximity, private networking, restart policy, at least two replicas for
high availability, capacity, database HA, backups, notifications/webhooks, wait-for-CI
checks, rollback procedures, and multi-region disaster recovery. Apply each according to
the service's reliability and cost requirements; they are review points rather than
universal settings.

## Failure patterns

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
