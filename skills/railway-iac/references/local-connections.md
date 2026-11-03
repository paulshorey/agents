# Local Railway connections and project map

Read this for work on this user's Railway projects. URLs, live API state, and the
current deployment branch are the authority when they disagree with this map.
IDs below identify targets; they are not credentials or authorization.

## Profiles and authentication

| Context | Credential source | Use |
| --- | --- | --- |
| Local workspace access | `~/.secrets.sh` exports `RAILWAY_API_TOKEN` | Source explicitly inside `bash --noprofile --norc -c`; verify access to the requested project |
| CI or cloud agent for one environment | Secret manager injects `RAILWAY_TOKEN` | Project token scoped to the intended project/environment; do not replace it with the broader local token |

The local token belongs to workspace `c64d0999-e00c-4c52-bbd4-2614210e3758`,
displayed as **my workspace** (scoped project reads rechecked October 31, 2026),
in the Railway account in Wavebox group
**web@artspaces.net**. It can access Notes, Experimental, Map, Livx (`80a86bab…`),
Paul, Facts, Events, and HCI.

Never read profiles into tool output, use shell tracing, print environment dumps,
or copy token values into a skill, repository, prompt, plan comment, or artifact.
Source a profile inside a subshell to avoid carrying one workspace's token into
another operation. When using `RAILWAY_API_TOKEN`, unset `RAILWAY_TOKEN`; when
using a project token, unset `RAILWAY_API_TOKEN`. Fail when the selected token is
empty rather than falling back to a stored CLI login. Project/environment selector variables
do not broaden a token's scope.

Workspace tokens can query authorized projects while account identity endpoints
such as `me`, CLI `whoami`, account-wide `list`, or `link` return Unauthorized.
Use the scoped project query in `SKILL.md`, or this inventory query:

```bash
railway api 'query { projects(first: 50) { edges { node { id name } } } }'
```

To list what is deployed, add `pageInfo { hasNextPage }` beside `edges` and select
`environments { edges { node { id name } } }` and `services { edges { node { id name
serviceInstances { edges { node { environmentId latestDeployment { status createdAt
} } } } } } }` on each project node, without variables. Some service instances
reference environment IDs absent from the project's environment list; report them
rather than guessing a name.

Paginate when necessary; do not infer a project's absence from one page. Direct
workspace/account API requests use `Authorization: Bearer <token>` at
`https://backboard.railway.com/graphql/v2`. Project tokens use
`Project-Access-Token` instead; let the CLI choose headers when possible.
`railway api` already returns JSON; it does not accept a `--json` flag.
Inspect unfamiliar fields with `railway api search` and `railway api describe`.

For a CI project token, inspect its scope without printing the token:

```bash
railway api 'query { projectToken { projectId environmentId } }'
```

Match both IDs before installing/using a CI secret. The same query is not an
account-token identity check; choose the query for the token type.

If a scoped query is unauthorized, recheck the profile, token precedence, and exact
project ID before asking for another token. Do not repeatedly retry account-wide
endpoints or reuse another project's CI secret. Python `urllib`'s default client
received Cloudflare 1010 here; distinguish an HTTP client block from Railway auth
by using the CLI or another supported HTTP client.

## Notes

Project **Notes** `7c451bd1-350a-4fb3-a08f-5295863269ce`, repository `~/git/notes`,
file `.railway/railway.ts`, named partial `notes`.

| Environment | ID | Branch | Domain |
| --- | --- | --- | --- |
| dev | `8cbb1415-ac2b-46c3-ae8c-144265017189` | `main` | `dev.jot.new` |
| production | `f65d1bcb-a786-4678-a431-e9f6c3ff154f` | `prod` | `jot.new` |

The partial owns service `apps/notes-next` (`38f9a93c-4d6c-4559-8ae5-dc297c878239`)
and the `media` bucket. Postgres, `postgres-volume`, and the `Postgres-PITR` bucket
are dashboard-owned; never declare them in the partial. Readiness is `/api/health`.
`.github/workflows/railway-iac.yml` uses `NOTES_RAILWAY_TOKEN_DEV` and
`NOTES_RAILWAY_TOKEN_PRODUCTION`. The repository's `.railway/README.md` owns variables,
preview handling, and the apply procedure.

## Experimental

Project **Experimental** `c6260c51-8b01-4934-8ccb-9cf32456744c` hosts the NLP and
`apps/map` services and their databases.

| Environment | ID |
| --- | --- |
| dev | `4e7d33aa-1de0-441f-a105-352bbe3b6697` |
| production | `46907359-520d-41a3-adf3-6ed23379b418` |

| Repository at `~/git/` | IaC file | Named partial | Owned services (dev) |
| --- | --- | --- | --- |
| `nlp` | `.railway/railway.ts` | `nlp` | `apps/be` (`7d9de107…`, `/health`), `apps/fe` (`87a13310…`, `/api/health`) |
| `map` | **`.railway/webarts.ts`** | `map` | `apps/map` (`8bc68702…`, `/api/health`) |

Map's default `.railway/railway.ts` targets the **Map** project; always pass
`--file .railway/webarts.ts` for Experimental. Both repositories' CI uses
`.github/workflows/railway-webarts.yml` with `WEBARTS_RAILWAY_TOKEN_DEV`.

Experimental still contains an `apps/notes-next` service, a `notes-pr-109`
environment, `NOTES_DB`, and `notes` partial ownership records. They do not serve
Notes; never plan the Notes file against Experimental.

App partials preserve variable values and leave databases, volumes, buckets, and
domains under existing ownership. Inspect `railway config partials list` before
ownership changes. Repository concurrency does not serialize repositories sharing
one project; an environment-etag conflict should fail, so regenerate and review the
plan before rerunning an authorized apply.

## Map, Livx, and Paul

| Project | ID | Environments | Repository / authoring shape |
| --- | --- | --- | --- |
| Map | `d25b93f2-bea9-4f05-a6c0-4a045e8b18ac` | dev `01e37c22-5804-4b63-80a3-5d00255951e4`, production `a77c64bc-8e82-46b7-8634-7b72453ebfd8` | `~/git/map`, `.railway/railway.ts`; inspect live `map`/`DB_MAP` and the full plan before applying; CI `railway-config.yml` uses dev-only `RAILWAY_TOKEN` |
| Livx | `80a86bab-aca8-422b-8487-b17bb36768eb` | dev `e68dfed4-2931-4833-8779-65ff582f7e9a`, production `87986a21-933a-447b-bf7e-6e726347e080` | `~/git/livx`, `.railway/migration-dev.ts` and `migration-production.ts`; services include `apps/backend`, `apps/admin`, `apps/client` |
| Paul | `0147ed48-9a17-4d6f-a17f-43e989df9adf` | dev `79b60708-8a5e-41d1-9853-4336136ed0e7`, production `9019f433-ea50-40eb-9239-c1e697353491` | `~/git/paul`, `.railway/railway.ts`; service `paul`; CI uses `RAILWAY_TOKEN_DEV` / `RAILWAY_TOKEN_PRODUCTION` |

`~/git/livx/.railway/railway.ts` targets project `4acaad07-06dc-4766-9bf3-6144e9c1ca90`,
which the default workspace token cannot access (scoped read rechecked October 31,
2026); its `railway-iac.yml` uses `RAILWAY_TOKEN_DEV` and
`RAILWAY_TOKEN_PRODUCTION`. Keep that serving project separate from destination
validation copies. For authorized work, supply an explicitly selected credential
for the serving project; do not source `~/.secrets.sh` afterward or reactivate a
commented-out token. Continue independent work when access is unavailable.

## Events, Facts, and HCI

| Project | ID | Environments | Owning instructions and CI credentials |
| --- | --- | --- | --- |
| Events | `a0315029-9b64-41a0-9c83-e4367366947d` | dev `fb0a7dbd-2f66-4183-b3c3-7b1e7a7afe24`, production `cf2c1bdd-7938-4b8a-b752-3c3bb6826b9e` | `~/git/events/.railway/project.json` and README; whole-environment `.railway/railway.ts`; no Railway credential in Actions |
| Facts | `f463753e-8db6-4d2b-b8d1-127e9ab5d59d` | dev `bd4378a5-dd88-44c3-957f-57877e8ca905` | `~/git/facts/.railway/project.json` and README; storage only, no application deployment or Railway Actions credential |
| HCI | `114d34ca-984f-43a0-b9ac-6e0d72ee489e` | dev `5603e862-49cb-498b-a036-136264957f66`, production `9b8cb8a9-31f2-4913-8fa4-75eafd25f0da` | `~/git/hci/docs/deployment.md`; `hci` partial; GitHub environments `development` and `production` each supply their own `RAILWAY_TOKEN` |

HCI authoring also needs its exact `HCI_RAILWAY_PROJECT_ID`,
`HCI_RAILWAY_ENVIRONMENT_ID`, `HCI_RAILWAY_TARGET` (`development`/`production`),
`HCI_BUCKET_REGION=iad`, and `HCI_STORAGE_PROVIDER=railway`. These are selectors,
not credentials. Map’s repository skill must use the same local/CI distinction
as this skill. Map’s cloud runtime bootstrap must not persist control-plane tokens.

Railway CI credentials belong to each repository/environment’s secret store.
An invalid-token check does not prove expiry; inspect its exact log and token type.
When a task authorizes repair, mint a project token for the verified environment,
check `projectToken { projectId environmentId }`, save it through hidden stdin to
the existing GitHub secret name, and verify a PR plan. Never substitute a workspace
token or rerun a push/apply workflow merely to test authentication.

## Planning blockers

Read-only plans checked October 31, 2026 authenticated successfully. The default
Map/dev whole graph proposes replacing the app and deleting `DB_MAP` and
`Postgres-PITR`; do not merge/apply it before ownership and service reconciliation.
The Map Experimental partial proposes an app creation. Livx destination definitions
retain live RSVP variables but still propose URL/reference and dev upload-volume
changes; they are not no-op connection checks. Authentication does not approve
infrastructure changes, service cutover, or database replacement.

## Shared workflow rules

- Same-repository PRs plan only against their target persistent environment.
- Most CLI workflows plan/apply on `main` pushes or manual dispatch, with `prod`
  mapping to production where configured. Verify that exact branch’s workflow.
- Those CLI apply jobs create their saved plan in the same run, check the branch
  head, and require a clean follow-up plan, with destructive confirmation disabled.
- Map’s default `railwayapp/config` workflow instead plans PRs and applies the
  reviewed artifact after merge. Its apply also disables destructive confirmation;
  do not enable it to bypass the current graph’s destructive plan.

Do not infer workflow availability from a successful source deployment. Verify the
current branch's workflow file and GitHub Actions **config job**, separately from
Railway's application build. Verify both deployment branches carry the workflow.

For an existing preview, inspect the service's live GitHub source branch, then set
`RAILWAY_ENVIRONMENT_ID` and **`RAILWAY_IAC_BRANCH`** before planning the owning
partial. Discover preview domains from the current service. Verify important custom
domains as well as Railway-provided domains.

## Other access paths

`~/git/dbs` contains a Railway management app using `RAILWAY_API_TOKEN` in
`lib/railway.ts`; read its `AGENTS.md` before work there. Avoid exposing variable
values when inspecting projects through it.

If dashboard access is necessary, use the user's specified Wavebox group and the
`wavebox-browser` skill when available; verify the account and cookie space.
Browser login and CLI token access are independent. Do not extract browser
credentials as a substitute for scoped API access. Honor computer-use credential
and clipboard restrictions; if a newly authorized token cannot be stored through
the available tools, have the user save it locally without pasting it into chat.

Railway's hosted MCP uses OAuth or a `railway login` session. For a configured
agent connection, `railway mcp install --agent <agent> --oauth` lets the user
choose the workspace during consent; CLI 5.62.1 accepts `codex`, `claude-code`,
`cursor`, and other agents (an unknown value prints the list). MCP is optional:
the CLI with the workspace token covers project, service, and deployment reads in
any harness. Recheck current MCP documentation before setup, and use an existing
connector when it supports the task. Workspace API tokens remain useful for
`railway api` and direct GraphQL access.

Official references:

- https://docs.railway.com/integrations/api
- https://docs.railway.com/cli/login
