# Railway IaC authoring and CI

Read this reference for new IaC definitions, imports, migrations, multi-repository
ownership, variables, environment differences, or CI plan/apply workflows.

## Toolchain and file ownership

TypeScript authoring uses the `railway` package and `railway/iac` entrypoint. Pin the
SDK and Railway CLI in the project rather than relying on an unrelated global version.
IaC needs Railway CLI 5.42.1 or newer; check current official requirements because the
SDK remains capable of breaking changes.

Use the repository's package manager and `packageManager` version. The WebArts
migration used SDK 3.11.0, CLI 5.62.1 for Notes/NLP, and the existing pinned CLI
5.59.0 for Map; these are tested versions, not requirements to override future
pins. Node 24 was used for IaC CI. Evaluating IaC and building the application can
use different Node versions; do not upgrade app runtimes solely for SDK evaluation.
Run the repository's IaC type-check script and lint a changed workflow with
`actionlint` when available, then review live plans for every affected environment.

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

Read-only `railway status --json` output omits some configuration fields. A missing
key is not evidence that a live setting is empty. Use imported graph JSON or an
explicit API selection of `railwayConfigFile`, source, commands, healthcheck, root,
and watch patterns when auditing migration. Never include variable values merely
to diagnose a build setting.

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

If the legacy file has already been deleted, translate its intended settings from
the repository and live graph, then explicitly clear the custom config path.
With CLI 5.62.1's `serviceInstanceUpdate` API, `railwayConfigFile: null` was ignored;
an empty string cleared it. Verify the field after mutation and run a fresh plan.

Audit dev, production, and existing PR environments separately. In WebArts, four
app services across dev and four previews retained 20 stale paths after the files
were removed; production already had no path. Removing a repository file does not
clear these live settings. Read [local connections](local-connections.md) for the
correct project/profile and partials.

If an authorized manual recovery requires clearing one confirmed stale path, first
inspect the live schema, then update only that service instance:

```bash
railway api 'mutation($serviceId: String!, $environmentId: String!, $input: ServiceInstanceUpdateInput!) {
  serviceInstanceUpdate(serviceId: $serviceId, environmentId: $environmentId, input: $input)
}' --raw-var serviceId="$SERVICE_ID" --raw-var environmentId="$RAILWAY_ENVIRONMENT_ID" \
  --var 'input={"railwayConfigFile":""}'
```

Select the same field again to verify it is cleared. Reconcile the intended build,
start, and health settings in the owning IaC file and review its plan before apply.
Do not copy historical IDs into a bulk mutation without a fresh inventory.

Preserve each service's GitHub source and all existing variable names, even in a
named partial. Omission can disconnect the source or delete variables. Omitting
`source.branch` cleared a PR branch in a verified CLI 5.62.1 apply. Supply the
actual branch explicitly; require an input for preview branches rather than
defaulting them to `main`. Review source changes separately from build/deploy
changes. Imported platform defaults can cause perpetual drift when explicitly
declared; verify live defaults before omitting redundant fields.

Verified CLI 5.62.1 supplied `ctx.environmentId` while environment/project names
could be null. Use stable persistent-environment IDs and a known project name when
needed; confirm both dev and production plans before replacing that logic with
`ctx.isEnvironment()`. Keep a project-ID guard for files targeting similarly named
projects. WebArts preview files require `RAILWAY_IAC_BRANCH` from the existing
source; never omit it or silently choose main.

An explicit default `restartPolicyType: "ON_FAILURE"` produced recurring drift in
this import; omitting the redundant field gave a clean plan while preserving the
live default. This is a version-specific observation, not a reason to remove
intentional nondefault settings. Inspect the imported graph and verify the result.

## Saved plans and GitHub Actions

For manual CI primitives:

```bash
railway config plan --out railway-plan.json
railway config apply --plan railway-plan.json --yes
```

The saved plan binds the change set, environment `configEtag`, and `.railway/` source
tree. It must fail if the environment or reviewed tree changes.

Prefer `railwayapp/config@v1` for pull requests. Store a project token for the target
environment as a GitHub Actions secret. Plan on same-repository PRs and apply the pinned
artifact only after merge. Grant `contents: read`, `pull-requests: write`, and
`actions: read`; add `id-token: write` when using the Railway GitHub App identity.
Fork PRs do not receive repository secrets.

Keep an existing custom workflow when it correctly implements the repository's
deployment contract. WebArts/LivX use a read-only PR plan plus a **fresh saved plan
on the deployment-branch push**, then apply that saved plan in the same job. The
official action can instead apply the reviewed PR artifact at merge. Identify
which model a workflow implements; do not claim PR-artifact binding for the custom
push model or replace working automation merely to standardize it.

For push workflows, check the current branch head before applying; restrict manual
dispatch to the intended deployment branches and serialize runs per branch.
Require a nonempty matching token, pinned toolchain, explicit file/target, and a
clean post-apply plan. Watch workflow/config/toolchain paths so IaC edits actually
trigger the job. Configure both deployment branches when production uses `prod`.
If credential or etag checks fail, diagnose that job separately from a passing
Railway source build. Do not disable a guard or swap in another project's token.

Omit `--confirm-destructive` from ordinary unattended applies. A deliberate
resource/variable removal needs a specifically reviewed plan and task authorization;
the flag is not a fix for an incomplete graph or missing `preserve()` entries.

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
