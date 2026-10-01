# Local Railway connections and project map

Read this for work on this user's Railway projects. The map records verified
configuration from September 2026; URLs, live API state, and the current deployment
branch are the authority if a project, branch, domain, or credential has changed.
IDs below identify targets; they are not credentials or authorization.

## Profiles and authentication

| Context | Credential source | Use |
| --- | --- | --- |
| Default local workspace access | `~/.secrets.sh` exports `RAILWAY_API_TOKEN` | Source explicitly in a non-login command shell; verify access to the requested project |
| WebArts local access | `~/.config/railway/webarts.env` exports `RAILWAY_API_TOKEN` | Source explicitly even when the global variable exists; keep file owner-only (`600`) |
| CI or cloud agent for one environment | Secret manager injects `RAILWAY_TOKEN` | Project token scoped to the intended project/environment; do not replace it with the broader local token |

Never read profiles into tool output, use shell tracing, print environment dumps,
or copy token values into a skill, repository, prompt, plan comment, or artifact.
Source a profile inside a subshell to avoid carrying one workspace's token into
another operation. When using `RAILWAY_API_TOKEN`, unset `RAILWAY_TOKEN`; when
using a project token, avoid setting both. Project/environment selector variables
do not broaden a token's scope.

The WebArts token belongs to workspace `c64d0999-e00c-4c52-bbd4-2614210e3758`,
displayed as **my workspace**, in the Railway account in Wavebox group
**web@artspaces.net**. **WebArts is the project name**, not the workspace name.
The global token was not authorized for WebArts during the migration.

Workspace tokens can query authorized projects while account identity endpoints
such as `me`, CLI `whoami`, account-wide `list`, or `link` return Unauthorized.
Use the scoped project query in `SKILL.md`, or this inventory query:

```bash
railway api 'query { projects(first: 20) { edges { node { id name } } } }'
```

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

## WebArts ownership and targets

Project ID: `c6260c51-8b01-4934-8ccb-9cf32456744c`.

| Environment | ID | Persistent source branches |
| --- | --- | --- |
| dev | `4e7d33aa-1de0-441f-a105-352bbe3b6697` | `main` |
| production | `46907359-520d-41a3-adf3-6ed23379b418` | Notes `prod` |
| PR previews | Discover current environment ID from URL/API | Preserve the actual PR branch; never assume `main` |

| Repository at `~/git/` | IaC file | Named partial | Existing services |
| --- | --- | --- | --- |
| `notes` | `.railway/railway.ts` | `notes` | `apps/notes-next` in dev/previews; `notes` in production |
| `nlp` | `.railway/railway.ts` | `nlp` | `apps/be`, `apps/fe` in dev/previews |
| `map` | **`.railway/webarts.ts`** | `map` | `apps/map` in dev/previews |

Map's default `.railway/railway.ts` targets **World**, a different project. Always
pass `--file .railway/webarts.ts` or use its `railway:webarts:*` scripts for WebArts.
Notes/NLP use `railway:config:*` scripts. Read the current root `package.json` and
`.railway/README.md` for commands and pinned versions before executing.

At migration time, production contained only Notes and NOTES_DB. Do not apply
the dev-only Map/NLP partials there to create additional services incidentally.
App partials preserve variable values and leave databases, volumes, buckets, and
domains under existing ownership. Do not replace this with a Notes-only
whole-project graph. Inspect `railway config partials list` before ownership changes.

Useful stable service IDs (confirm live identity before mutation):

| Service | ID | Readiness path |
| --- | --- | --- |
| apps/notes-next | `f2e255ea-c0af-43e5-a97c-affb75868d7b` | `/api/health` |
| production notes | `23fdd041-aa00-443a-8ef8-a1bd6157b070` | `/api/health` |
| apps/be | `7d9de107-a073-4d61-b303-61e30daef20a` | `/health` |
| apps/fe | `87a13310-699c-4ece-a895-d70680247143` | `/api/health` |
| apps/map | `8bc68702-594f-4f73-a98b-a99ad8ca6aab` | `/api/health` |

Known Notes public readiness URLs: `https://dev.jot.new/api/health` and
`https://jot.new/api/health`. Discover preview domains from the current service;
preview environments and their domains are temporary. Verify important custom
domains as well as Railway-provided domains.

For an existing preview, inspect the service's live GitHub source branch, then set
`RAILWAY_ENVIRONMENT_ID` and **`RAILWAY_IAC_BRANCH`** before planning the owning
partial. The authored files intentionally require this input outside persistent
environments. A historical `notes-pr-84` used `redesign`; this is not a default
for other previews. See deployment operations for inheritance and skipped services.

## CI currently used by these projects

WebArts repositories use `.github/workflows/railway-webarts.yml`:

- Same-repository PRs plan only against their target persistent environment.
- Pushes/manual dispatch on `main` plan and apply to dev; Notes `prod` targets
  production. The workflow must exist on the branch being deployed.
- `WEBARTS_RAILWAY_TOKEN_DEV` is a dev-scoped project token in each repository.
  Notes additionally uses `WEBARTS_RAILWAY_TOKEN_PRODUCTION` for production.
- The non-PR job creates and applies a saved plan in that run, checks the latest
  branch head, then requires a clean follow-up plan. It does **not** apply a saved
  artifact from the earlier PR job. Destructive confirmation is disabled.
- Repository concurrency does not serialize all repositories sharing WebArts.
  An environment-etag conflict should fail; regenerate/review the plan before
  rerunning an authorized apply. Do not bypass the guard.

Do not infer workflow availability from a successful source deployment. Verify the
current branch's workflow file and GitHub Actions **config job**, separately from
Railway's application build. Dev and production workflows may be installed in
separate PRs; verify both deployment branches rather than assuming one merge
installed automation everywhere.

## LivX and World are separate targets

| Project | ID | Repository / authoring shape |
| --- | --- | --- |
| `livx` currently served by this repository | `4acaad07-06dc-4766-9bf3-6144e9c1ca90` | `~/git/livx`, `.railway/railway.ts`, whole-project graph |
| Older `Livx` project | `80a86bab-aca8-422b-8487-b17bb36768eb` | Similar repository, different live names/resources; import separately |
| World | `d25b93f2-bea9-4f05-a6c0-4a045e8b18ac` | `~/git/map`, `.railway/railway.ts`; never use the WebArts file/token by assumption |

Current `livx` dev ID is `b0700040-e04d-4ebc-a4f1-e23b4dcd45a9`; production ID is
`656678f7-3260-4cfc-8f6c-c71c2c53f809`. Its whole-project file includes the three
apps, database, volume, bucket, and domains; retain the complete graph. Its
`.github/workflows/railway-iac.yml` uses `RAILWAY_TOKEN_DEV` and
`RAILWAY_TOKEN_PRODUCTION`, mapping main/dev and prod/production.

World's dev ID is `01e37c22-5804-4b63-80a3-5d00255951e4`; production ID is
`a77c64bc-8e82-46b7-8634-7b72453ebfd8`. Its separate
`.github/workflows/railway-config.yml` uses the official action with repository
secret `RAILWAY_TOKEN`. This secret was empty during the WebArts migration:
verify its current state/scope if that job fails, rather than replacing it with
a WebArts credential. Read the World runbook for its reviewed-plan apply policy.

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
Codex agent connection, `railway mcp install --agent codex --oauth` lets the user
choose the workspace during consent. Recheck current MCP documentation before
setup, and use an existing connector when it supports the task. Workspace API
tokens remain useful for `railway api` and direct GraphQL access.

Official references:

- https://docs.railway.com/integrations/api
- https://docs.railway.com/cli/login
