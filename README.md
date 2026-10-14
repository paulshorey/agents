# Paul’s agent configuration

This is the Git repository for shared skills, provider tooling, and agent
configuration: https://github.com/paulshorey/agents. The checkout is `~/.agents`.
It is **public**. Credentials, OAuth state, application-maintained settings,
installation backups, DNS plans, and runtime journals stay out of Git.

## Start here

For work on Railway and Cloudflare, read
[`deploy-railway-with-cloudflare`](skills/deploy-railway-with-cloudflare/SKILL.md)
and [`railway-iac`](skills/railway-iac/SKILL.md). The latter documents this machine’s
workspace profiles and existing resource ownership. Use scoped resource checks:
a valid workspace token can fail account identity commands.

```sh
source ~/.agents/config/env.sh
agents-hosting doctor
agents-hosting verify
```

Commands use [`config/hosting/paul.json`](config/hosting/paul.json) by default.
Pass `--manifest PATH` for another project. The doctor checks installed tools,
Railway project/workspace/environment/source-branch identities, and Cloudflare
zone access. It exits nonzero when a prerequisite is missing. Verification checks
validated HTTPS and the deployed commit against the remote branch head for Paul.
It does not send contact-form messages or modify infrastructure.

## What is version controlled

| Location | Purpose |
| --- | --- |
| `skills/` | Local skills and selected official provider reference material |
| `config/mcp.json` | Shared, secret-free Railway MCP launcher and Cloudflare endpoint |
| `config/links.json` | Application symlink destinations and source ownership |
| `config/env.sh` | Tool PATH setup, without credentials |
| `config/hosting/*.json` | Non-secret project IDs, branches, domains, and profile references |
| `config/skill-sources.json`, `licenses/` | Upstream revisions, local adaptations, provider licenses |
| `tools/package.json`, `tools/package-lock.json` | Exact Cloudflare CLI dependency versions |
| `scripts/`, `bin/`, `tests/` | Installation, credential loading, DNS reconciliation, and verification |
| `rules/AGENTS.md` | Global agent context, linked into Codex |

Ignored `local/` contains owner-only credential files, rendered Codex/shell config,
installation backups, saved plans, and execution journals. `tools/node_modules/`
is restored from the lockfile. Application credential stores such as Codex OAuth,
Railway login, and Cloudflare login remain in the application’s normal locations.
Do not copy their contents into this repository or symlink an authentication database.

## Install and maintain configuration links

```sh
npm ci --prefix ~/.agents/tools --ignore-scripts
python3 ~/.agents/scripts/install.py          # inspect; exits 1 if installation is needed
python3 ~/.agents/scripts/install.py --apply  # back up existing files, merge managed config, install links
python3 ~/.agents/scripts/install.py          # should report status: current
```

The installer establishes these links:

| Application path | Source inside `~/.agents` |
| --- | --- |
| `~/.cursor/mcp.json` | `config/mcp.json` |
| `~/.codex/config.toml` | `local/codex/config.toml` |
| `~/.codex/AGENTS.md` | `rules/AGENTS.md` |
| `~/.zprofile` | `local/shell/zprofile` |

Codex uses TOML rather than `mcp.json`. The installer renders only the shared
Railway/Cloudflare MCP sections into the active Codex configuration and preserves
all other settings, servers, plugins, and comments. The complete application config
is kept local because Codex maintains host paths, preferences, and runtime values.
Shared MCP configuration remains version controlled. Existing nonempty Cursor
configuration must be merged into the shared JSON before installation; it is never
silently overwritten.

`~/.local/bin` is root-owned on this Mac, so these tools use `~/.agents/bin` directly.
The shell config preserves existing content and adds a source hook for `config/env.sh`.
New login shells receive `~/.agents/bin` on PATH. An existing terminal or desktop
agent process may need explicit `source ~/.agents/config/env.sh`, or can use
`~/.agents/bin/cf` and `~/.agents/bin/agents-hosting` directly. The PATH hook does not
select a Railway workspace or inject credentials globally.

Some apps replace symlinks when saving. Run the installer’s check after configuration
changes. If a link is replaced, `--apply` adopts the current application settings,
re-renders the managed sections, saves a backup, and restores the link. To restore
a reported installation backup:

```sh
python3 ~/.agents/scripts/install.py --restore ~/.agents/local/install-backups/TIMESTAMP
```

Restore refuses to overwrite a destination whose link changed after installation.
Review app configuration before restoring if it was edited while still symlinked.
Edit `config/mcp.json` for shared endpoint changes, then rerun installation. New
agent sessions normally load new skills and MCP connections; this does not retrofit
tools into a running conversation.

## Provider tools and authentication

The installed Cloudflare CLI is **`cf@1.0.0-beta.16`**, pinned in `tools/`. It requires
Node 22.18 or newer; Node 24 is suitable for CI. This setup uses the CLI for API
operations, not a migration of Railway applications to Workers. Installation skips
npm lifecycle scripts; check build-specific prerequisites separately for future
Workers development. Use `cf cli search "create a DNS record"`, inspect the discovered
command with `--help`/`cf schema`, and use `--dry-run` to preview a request. Discovery
queries should describe operations without account IDs, domains, emails, or tokens.
A request preview is not a state-aware deployment plan.

Railway’s existing native CLI is 5.62.1. Repositories retain their own CLI and SDK
pins. Paul uses SDK 3.15.0 and downloads the official native CLI in CI. Do not add
the npm Railway CLI installer to application dependencies or change working pins
incidentally.

Official skills `cf-cli` and `use-railway` are imported at commits recorded in
`config/skill-sources.json`. `use-railway` has a narrower local entrypoint and preserves
the official reference material. Update provider skills/tools deliberately, review
local adaptations, validate behavior, and commit the change. Do not run automatic
latest-version setup commands from a normal deployment task.

### Environment variables and profiles

| Variable | Purpose and source |
| --- | --- |
| `RAILWAY_API_TOKEN` | Workspace/account access. For WebArts and Paul, source `~/.config/railway/webarts.env` explicitly. The generic token in `~/.secrets.sh` accesses another workspace. |
| `RAILWAY_TOKEN` | Environment-scoped project token for CI. Unset when selecting a workspace profile; never reuse another project’s CI secret. |
| `RAILWAY_PROJECT_ID`, `RAILWAY_ENVIRONMENT_ID`, `RAILWAY_SERVICE_ID` | Non-secret target selectors, where supported. Prefer explicit CLI IDs. These do not broaden credential scope. |
| `RAILWAY_IAC_BRANCH` | Required by some existing preview IaC definitions; inspect the actual source branch. |
| `CLOUDFLARE_API_TOKEN` | Scoped API token for unattended DNS/CLI/API use. Store in `local/credentials/cloudflare.env`, mode 600, or inject through an external secret manager. |
| `CLOUDFLARE_ACCOUNT_ID` | Non-secret expected account ID; prevents ambiguous account selection. |
| `CLOUDFLARE_ZONE_ID` | Optional non-secret zone ID. With it, the helper reads that exact zone; otherwise it looks up the configured zone name. |
| `PATH` | `config/env.sh` adds `~/.agents/bin`; desktop processes may have a different inherited environment. |

The helper parses literal `KEY=value` or `export KEY=value` assignments from owner-only
profiles; it does not execute shell commands. Quote literal values if needed. It rejects
command substitution and group/world-readable credential files. The explicit Railway
profile replaces inherited Railway tokens. The Cloudflare wrapper/profile supplies
its configured credentials to the pinned CLI. Avoid shell tracing, environment dumps,
token-bearing command arguments, and printing full API variable values.

The active Cloudflare token is named **Agent DNS — all domains** and grants
**Zone DNS Edit and Zone Read for All zones**, plus **User Details: Read**, as
explicitly authorized by the user. The dashboard summary and live API access were
verified on October 14, 2026 (UTC): the stored token is active, profile reads work,
and all 12 current zones report DNS Edit access. The token remains in ignored
`local/credentials/cloudflare.env`, mode 600. Editing its permissions preserves
the existing token value; rolling a token is a separate operation. No new value
needs to be copied after a permission edit.
The default account is `c54cc4d7f6317b833f5cc02d7172f245`. Confirm the intended account
and zone against live state for each operation; broad credential access is not
authorization to modify unrelated domains. The profile deliberately omits
`CLOUDFLARE_ZONE_ID` so future projects are not accidentally pinned to Paul’s zone.
Use a manifest-specific zone ID/name, or `cf --zone`, to select the target.
For a separate credential, choose the scope authorized for that task. Never paste
token values into chat, documentation, or Git.

```sh
mkdir -p ~/.agents/local/credentials
chmod 700 ~/.agents/local/credentials
python3 ~/.agents/scripts/set-cloudflare-token.py
```

The credential setup command prompts invisibly, validates access to the manifest’s
zone, and saves only to ignored owner-only storage. It prints resource IDs, never the
token. It sets the account default and leaves the zone unbound; `--pin-zone` explicitly
adds a global zone default for a deliberately single-zone profile. Run the doctor to
verify current access rather than relying on this recorded setup state.

For an ad hoc Railway operation, keep profile selection local:

```sh
(
  source "$HOME/.config/railway/webarts.env"
  unset RAILWAY_TOKEN
  railway api 'query($id:String!){project(id:$id){id name workspaceId}}' \
    --raw-var id=0147ed48-9a17-4d6f-a17f-43e989df9adf
)
```

### MCP connections

Railway uses the official `railway mcp local` server with the existing WebArts
workspace profile, launched through `bin/railway-mcp`. No new account OAuth grant is
needed for that existing access. Pass another explicit profile to the launcher when
that workspace is intended. Cloudflare uses `https://mcp.cloudflare.com/mcp`.
Codex can use Cloudflare OAuth when a scoped API token is not configured:

```sh
codex mcp login cloudflare
codex mcp list
```

OAuth login requires one-time provider consent; a configured URL alone is not an
authenticated connection. For optional hosted Railway MCP, add a separate server at `https://mcp.railway.com`
and complete its OAuth connection. That access is independent of local workspace
tokens; choose the intended account/workspace during consent. Cursor has
its own OAuth connection state and may require its own sign-in.

For Cloudflare, Codex also reads an injected `CLOUDFLARE_API_TOKEN` and has an internal
header helper that reads the owner-only profile. This avoids requiring the desktop
app to inherit a shell variable. `scripts/mcp-headers.py` writes credentials only to
Codex’s internal auth pipe: **never run it manually to display or log its output**.
OAuth remains an alternative when no API token is supplied. Verify a real provider
read in a new agent session before claiming the MCP connection works.

The hosted Cloudflare MCP also requires an identity-read permission for API-token
authentication. A DNS/Zone-only token returned HTTP 403 with
`Token lacks required user:read or account:read scope` during verification. For user
tokens, **User Details: Read** supplies that identity permission; for account tokens,
the provider documents Account Resources: Read. This is additional data access and
must be authorized before expanding an existing token. DNS CLI/API access works
without it. Do not confuse successful REST DNS access with authenticated hosted MCP.

The user approved and saved User Details: Read for the active all-domains token.
On October 14, 2026 (UTC), the configured header helper supplied the existing token
to the hosted MCP server: initialization and tool discovery succeeded, and an
`execute` call to GET `/zones` returned all 12 zones with DNS Edit permission.
This verified the provider connection directly; existing agent conversations still
need a new session to discover newly configured MCP tools. For direct HTTP checks,
identify the client with `User-Agent: paul-agents-hosting/1`; Cloudflare rejected
Python's default urllib user agent with error 1010 during verification.

## Deploying Railway plus Cloudflare

The skill orchestrates project/environment/service creation, source branches,
secrets, IaC, domain registration, DNS, and verification. Read its bootstrap reference
for workspace-token project creation, deployment-trigger queries, default normalization,
native CLI installation, and DNS/certificate propagation.

The `agents-hosting` helper’s **plan/apply covers DNS** after Railway domain registration.
It obtains current Railway DNS requirements, checks target identities and branch
sources, compares the specified names with Cloudflare records, and saves a reviewable
plan. It does not own an entire zone, create projects, apply Railway IaC, or delete DNS
records. Native Railway CLI/IaC handles those separate stages under task authorization.

```sh
agents-hosting plan --plan-file ~/.agents/local/hosting/paul.plan.json
# Review the JSON plan and the authorized scope before applying.
agents-hosting apply --plan-file ~/.agents/local/hosting/paul.plan.json
agents-hosting verify
```

Use `--environment dev`, `production`, or `all`. A changed manifest, changed Railway
requirements, or changed relevant DNS state invalidates the saved plan. Regenerate
it rather than bypassing the check. Completed changes become no-ops on a subsequent
plan. Runtime journals retain changed record IDs in `local/hosting/`.

The helper can update one existing A/AAAA/CNAME route record in place, create missing
records, and reconcile Railway verification TXT values. Multiple competing route
records or NS conflicts stop the plan before any write. Other TXT, MX, unrelated
subdomains, record comments, and tags are preserved. Existing matching records are
left unchanged; new/changed routing records use DNS-only and TTL Auto. Unsupported
record types need inspected native API operations rather than a guessed conversion.

For another project, copy `config/hosting/example.json`, replace all placeholder
IDs with returned provider identities, and specify the repository, branches, domains,
port, profile references, and readiness schema. `commit_field`/`require_commit` enable
exact commit verification when the app exposes it. Establish ownership of existing
resources before applying any whole-project IaC graph.

## Validation and scope

```sh
python3 -m unittest discover -s ~/.agents/tests -v
npm audit --prefix ~/.agents/tools --omit=dev
~/.agents/bin/cf --version
python3 ~/.agents/scripts/install.py
~/.agents/bin/agents-hosting doctor
~/.agents/bin/agents-hosting verify
```

Tests cover wrong credentials/workspace, DNS conflicts, preserving unrelated records,
stale-plan rejection, partial failure/resume, a no-op second apply, and installation
backup/restore. Live verification is read-only. Paid-resource creation and a full
end-to-end bootstrap pilot need an authorized target; SMS tests need an authorized
message. Working health/DNS does not establish payments, persistent storage, or other
application-specific behavior.

Read `~/git/AGENTS.md` before working on the user’s repositories or local services.
Preserve their existing ports, process ownership, private routing, and unrelated work.
Configuration establishes capability; the current user request establishes mutation
scope. Do not reset provider resources or grant broader access merely to simplify setup.

## Primary references

- [Railway agent integrations](https://github.com/railwayapp/railway-skills)
- [Railway CLI MCP](https://docs.railway.com/cli/mcp)
- [Railway IaC](https://docs.railway.com/infrastructure-as-code)
- [Cloudflare CLI](https://developers.cloudflare.com/cf/get-started/)
- [Cloudflare API MCP](https://developers.cloudflare.com/agents/model-context-protocol/cloudflare/servers-for-cloudflare/)
- [Cloudflare token permissions](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/)
- [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
