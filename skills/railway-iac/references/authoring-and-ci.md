# Railway IaC authoring and CI

Read this reference for new IaC definitions, imports, migrations, multi-repository
ownership, variables, environment differences, or CI plan/apply workflows.

## Toolchain and file ownership

TypeScript authoring uses the `railway` package and `railway/iac` entrypoint. Pin the
SDK and Railway CLI in the project rather than relying on an unrelated global version.
IaC needs Railway CLI 5.42.1 or newer; check current official requirements because the
SDK remains capable of breaking changes.

Use one `.railway/railway.ts` when one repository or monorepo owns the environment's
entire graph. Omission from that file is deletion on the next apply.

For a project whose services live in separate repositories, every repository must
export a stable named partial, for example:

```ts
export const partial = "api";
```

Each partial can delete only resources it owns. Do not mix named partial and
whole-project files in one environment. Inspect and transfer ownership with the
current CLI workflow before reorganizing repositories.

## Resource graph

The TypeScript DSL can describe persistent services, cron functions, Postgres, MySQL,
Redis, MongoDB, buckets, volumes, domains, replicas, groups, and environment variables.
Service sources can be GitHub repositories, images, templates, or empty services.
Use typed references such as a database's exported URL instead of copying credentials.
Use `ctx.shared.NAME` for shared Railway variables.

Use `preserve()` when Railway already owns a value that must remain secret or outside
source control:

```ts
import { defineRailway, preserve, project, service } from "railway/iac";

export default defineRailway((ctx) => {
  const production = ctx.isEnvironment("production");
  const web = service(production ? "web" : "web-dev", {
    source: {
      repo: "owner/repository",
      branch: production ? "production" : "main",
    },
    env: { API_KEY: preserve() },
  });

  return project(ctx.projectName ?? "project-name", { resources: [web] });
});
```

Conditional resource names are appropriate only when those distinct resources already
exist or are intentionally being created. Verify the resulting plan does not replace a
service merely because its name differs between environments.

## Import and migration

`railway config pull --json` returns raw imported graph JSON without writing files.
Plain `railway config pull` generates human-editable authoring code, omits platform
defaults and generated Railway domains, and renders existing values as `preserve()`.
Run a plan immediately after import; a faithful import should be clean.

Avoid `--include-variables`: it decrypts and writes non-sealed values into the spec.
Sealed variables remain preserved, cannot be retrieved by CLI, and are not copied to
PR environments or duplicated environments/services. Provision required sealed values
separately in every environment that needs them.

A legacy `railway.json` or `railway.toml` service must be migrated before IaC can own
it. Start with the dry-run, inspect the generated changes, then apply deliberately:

```bash
railway config migrate
railway config migrate --apply
railway config plan
```

Do not add `--force` unless replacing an existing authoring file is intentional and
reviewed. Do not simply set the dashboard Config File field to the TypeScript path.

## Saved plans and GitHub Actions

For manual CI primitives:

```bash
railway config plan --out railway-plan.json
railway config apply --plan railway-plan.json --yes --confirm-destructive
```

The saved plan binds the change set, environment `configEtag`, and `.railway/` source
tree. It must fail if the environment or reviewed tree changes.

Prefer `railwayapp/config@v1` for pull requests. Store a project token for the target
environment as a GitHub Actions secret. Plan on same-repository PRs and apply the pinned
artifact only after merge. Grant `contents: read`, `pull-requests: write`, and
`actions: read`; add `id-token: write` when using the Railway GitHub App identity.
Fork PRs do not receive repository secrets.

Use a separate environment-scoped project token and plan/apply job for each environment
that CI manages. Avoid one broad account token for convenience. Pin the CLI version in
the action so local and CI evaluation agree.

## Drift and review aids

- `railway config plan --json` produces machine-readable plan output.
- `railway config plan --detailed-exit-code` exits 0 for clean and 2 for pending drift.
- Values are redacted by default. `--show-values` can expose them; use it only for
  intentionally non-secret review.
- A stale-plan error means live state changed. Re-run and re-review the plan.
- After apply, a second plan should report no changes.

Official references:

- https://docs.railway.com/infrastructure-as-code
- https://docs.railway.com/infrastructure-as-code/reference
- https://github.com/railwayapp/config
- https://github.com/railwayapp/railway-ts-sdk
