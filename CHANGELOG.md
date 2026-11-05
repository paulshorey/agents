# Configuration changes

Git history records tracked-file diffs. This log records meaningful configuration,
credential-reference, provider-grant, and ownership changes without secret values.
Verification dates describe historical observations, not current readiness.

## 2026-11-05 — Installer owns Claude Code's per-skill links

- Claude Code finds shared skills only through per-skill links in
  `~/.claude/skills`. The 18 existing links were made by hand, so a fresh checkout
  or restored machine had to recreate them with `ln -s`.
- `config/links.json` gains a `skills` link kind, `skills` → `~/.claude/skills`
  (inventory `configuration.claude-skills`). `scripts/install.py` derives the
  skill list from `skills/`, creates the directory when missing, reports missing,
  other-target, and stale links, and with `--apply` backs up, fixes, and restores
  them. It leaves unrelated entries alone, including Claude's own `synced/` folder.
  `--only-link ~/.claude/skills` checks or installs just these links.
- `bin/agents-config check` reports the skill links' state. On this machine the
  existing hand-made links already match, so installation changes nothing.

## 2026-11-05 — Read-only deployed database queries

- Added `agents-sql` (`bin/agents-sql`, `scripts/sql-query.py`) and the
  `database-query` skill so Claude Code, Codex and Cursor can query deployed
  databases by target name. Targets live in ignored `local/databases.json` (format in
  `config/databases.example.json`) so private endpoints stay out of this public
  repository. Registered credential profile `postgres.livx-readonly`
  (`~/.agents/local/credentials/livx-db-readonly.env`, variables
  `LIVX_DEV_READONLY_DATABASE_URL` and `LIVX_PRODUCTION_READONLY_DATABASE_URL`).
- The security boundary is the `agent_readonly` role (SELECT on base tables in
  `public`, credential and bearer-code tables and columns withheld), created by
  `skills/database-query/references/readonly-role.sql` as a superuser from a SCRAM
  verifier that `agents-sql prepare` writes privately; `agents-sql activate`
  verifies and stores the new URL. The tool adds guardrails against mistakes: the
  role check refuses an owner or app URL, each query runs in a read-only transaction
  in the same session, and timeouts cancel the statement on the server.
- An earlier revision of this change audited PostgreSQL catalogs for every way a role
  could be misconfigured; it was cut back because a role created by this script on a
  fresh database cannot have those grants, and the audit kept growing.
- No deployed role or credential exists yet; the owner runs the setup in
  `docs/runbooks/databases.md` per database. Observed on 2026-11-05: the
  `railway.workspace` token reads projects in my workspace but not the LivX serving
  project, which is in another Railway workspace. Tests pass against disposable local
  PostgreSQL 18.6.

## 2026-11-05 — Claude Code auto mode trusts the PR review loop

- Claude Code agents kept failing to reply to review comments and resolve threads.
  The cause was the auto-mode classifier's built-in `External System Writes` rule,
  not `gh` or the GitHub API: it refuses resolving threads, and bodies it can't see.
- With Paul's approval, added `autoMode.environment` and `autoMode.allow` entries
  to the application-owned `~/.claude/settings.json`. They trust repositories under
  `github.com/paulshorey` and allow replies, PR comments, and thread resolution on
  PRs the agent is working on, unless the text carries a bot or ChatOps command.
  Both lists keep `"$defaults"`, so every built-in rule still applies (verified with
  `claude auto-mode config`). `permissions.defaultMode` and allow rules are unchanged.
- The review loop now gives exact reply and resolve commands; the
  [agent-customization runbook](docs/runbooks/agent-customization.md#claude-code-auto-mode-and-pr-writes)
  records the setting and how to undo it.

## 2026-11-04 — API-first engineering research for Codex and Claude Code

- Replaced `engineering-research`'s search-only helper with `scripts/parallel.py`,
  a stdlib client for Parallel's v1 Search, v1 Extract (full-page markdown saved to
  files), and Task API (asynchronous cited reports with resumable results). It
  reads `PARALLEL_API_KEY` from the environment or parses (never executes) its
  literal assignment in `~/.secrets.sh`, retries rate limits, server errors, and
  network failures twice without retrying deep-run creation or waiting past a
  60-second `Retry-After`, refuses to overwrite reports, and returns distinct exit codes. Live-tested search, extract (with a
  failing URL), a `lite` deep run, and missing, invalid, and rejected keys.
- Chose the API over `parallel-cli`: the CLI wraps the same APIs through the Python
  SDK and needs installation and upgrades in each environment, while the script
  works unchanged in Codex and Claude Code. The CLI's extras (OAuth login,
  enrichment, FindAll, Monitor) are outside this skill.
- The skill uses the script by default, requires agents to report any script
  failure with its command, exit code, and error, and mentions connectors or
  built-in search only as a fallback. `parallel-deep-research` now falls back to the
  script's `deep` command when `parallel-cli` is not installed.
- Registered the existing `PARALLEL_API_KEY` assignment in `~/.secrets.sh` as
  `parallel.api-key` (profile `parallel.api`) and listed it under `shell.secrets`.
  The key itself was not changed or rotated.
- Registered `application.parallel-connectors` for the Codex Parallel app and the
  claude.ai Parallel connector Paul added. claude.ai offered no sign-in step, so its
  authentication and limits are undetermined. The full Parallel Claude Code plugin
  was not installed because it duplicates `parallel-deep-research` and needs
  `parallel-cli`.

## 2026-11-04 — Guarded Claude Remote Control shortcut

- Replaced the external `~/.shortcuts.sh` cclaude alias with a function delegating
  to `scripts/claude-remote.py`. It runs Remote Control in server mode, which
  brings back the sessions the folder's previous server was serving and creates a
  session for each new chat from the Claude apps. `--continue` and `--session-id`
  explicitly serve one session.
- Added per-directory advisory locks and detection of servers started by the old
  alias. Repeated invocations report the running server and saved link rather
  than starting competitors. Claude retains terminal access and a scoped
  caffeinate assertion. Verified with Claude Code 2.1.316: a restarted server and a
  server started after a `--continue` run both reattached the same session.
- Prefer a compatible CLI already installed on the machine when a terminal's
  PATH selects an old version without resume support. No CLI update is performed.
- Detect npm-installed servers as well as native ones, while excluding shell
  wrappers and unrelated Node commands. Recognize global model and diagnostic
  options before the Remote Control subcommand. Skip failed or timed-out version
  probes when selecting a compatible installed CLI. Regression tests cover both fixes.
- Corrected recovery guidance: single-session flags do not bypass the documented
  roughly four-hour restore window; unarchiving requires Claude Code 2.1.228+.
- Registered ownership and documented installation, reload, diagnostics, native
  resume limits, and recovery. Authentication and provider permissions unchanged.

## 2026-11-03 — One Git/PR workflow and iterative Codex review

- Consolidated Git publishing and PR maintenance under `git-management`, with
  conditional references and a short `pr-management` compatibility entrypoint.
  Existing invocations and both PR-context script symlinks remain available.
- Added the loop for every created PR and functional PR contributions: record
  each pushed head, check back within 30 minutes for Codex's automatic review of
  it, handle/reply to each comment, resolve handled threads, and repeat after
  functional fixes. Missing reviews stay pending.
- Routed Git/PR work globally through Codex instructions and two installer-managed
  Claude Code/Cursor user-rule files. The adapters point to the shared policy
  without replacing other rules. Targeted installer link selection avoids
  rendering unrelated Codex/shell settings. No credential or provider changes.
- Addressed PR #26 feedback: preserve enclosing feedback around nested About Codex
  details blocks, and reject truncated/inconsistent check-run responses, including
  the conservative 1,000-run boundary. `--no-filter` exposes completion evidence.
- Follow-up review also protects inline/fenced code examples during HTML
  filtering and separates current six-link routing status from the older harness
  observations and remaining fresh-client verification plan.
- Extended code protection to indented examples and rechecks submitted review
  IDs, decisions, commits, and bodies before returning a snapshot.
- Added request-specific reaction evidence (actor/content/time), blockquoted
  indented-code protection, and final issue/inline comment state checks so edits
  and reaction-only review completion are visible to the review loop.
- Recheck thread disposition and reaction state before the final ref read, and
  preserve significant indentation when a comment contains only a code example.
- Narrowed default filtering so it cannot hide feedback: only exact `@codex review`
  triggers and the Codex bot's summary comment are dropped, and About boilerplate
  is stripped only from Codex-bot comments. Human comments and Codex findings that
  mention the trigger now remain. Inline `diff_hunk` context is opt-in (`--hunks`),
  and `--output` writes the JSON to a file, since full context exceeded agent
  tool-output limits (283 KB for PR #26, 76% hunks).
- Addressed Codex review of that change: `--output` uses an exclusively created
  temporary file, receipt markers inside code examples are preserved, and
  installer restore rewrites a pre-existing symlink's target only when it is one
  of the two installer-rendered `local/` files, so edits to dotfiles-managed or
  other linked rules made after install are not rolled back.
- Codex's GitHub integration now reviews every PR push automatically (configured
  in Codex settings, outside this repository). The loop no longer posts
  `@codex review` request comments and warns that any mention of the bot starts a
  separate Codex task. The helper replaces request-reaction tracking
  (`review_requests`) with `codex_review`, the commit Codex last reviewed parsed
  from its summary comment, plus `covers_head` for the current head.
- Addressed Codex's first automatic review: `statuses` keeps only each context's
  newest state, targeted `--only-link` installation validates `config/mcp.json`
  as full installation does, and restore's content guard applies only to the two
  installer-rendered files, so a pull that updates a tracked rule no longer blocks
  restore. Request comments were not reinstated as a fallback; a review that never
  starts is reported to the user as possibly disabled automatic review.
- Agents now always open PRs ready for review, never as drafts, and mark a draft
  ready after pushing to it, so every PR they create or update gets automatic
  Codex review. Drafts are reserved for PRs the user parks to pause reviews.
- Addressed Codex's review of that change: installation refuses to replace an
  existing text destination (such as a user's own rule file) whose content
  differs from its source, status history at GitHub's 1,000-entry limit fails
  rather than risk omitting a context, and Enterprise PR URLs keep custom ports.
  Readying a parked draft that an agent pushes to remains intended.

## 2026-11-02 — Shared PR context and feedback replies

- Clarified Git and PR management handoffs: validate and push each fix, then reply
  to every addressed comment with the outcome, commit, and validation before
  resolving its thread. One fix addressing several comments still needs replies
  to each; already-posted responses should not be duplicated.
- Added the common read-only `scripts/pr-context.py`, symlinked from both skills.
  It paginates PR feedback, threads, commits, changed files, and head checks/statuses;
  returns compact context with optional diff; and rejects incomplete/stale reads.
- Added reversible output filtering for Codex summary/request comments and the
  About Codex details block, preserving review decisions and substantive replies.
  The helper reuses native `gh` authentication and does not mutate GitHub data,
  credential stores, managed application links, or provider settings.

## 2026-11-02 — Claude Code skill compatibility and last30days setup

- Verified that Claude Code discovers all 17 shared skills through per-skill links in
  `~/.claude/skills` and ran `engineering-research`, `railway-iac` (read-only
  project/service listing), and `last30days` end to end from Claude Code.
- Resolved merge-conflict markers committed in `parallel-deep-research` by
  restoring its standalone-import text (verified `parallel-cli` 0.9.3), plus the
  shared self-reflection footer that commit intended.
- Documented Claude Code page fetching and the helper's result shape in
  `engineering-research`, the `claude-code` Railway MCP agent and a deployed-service
  query in `railway-iac`, and host-compatibility notes in `last30days`.
- Ran the last30days first-run setup on this Mac with Paul's browser-cookie consent;
  registered its application-owned config as `application.last30days-config` with
  an update, revocation and recovery runbook. No API keys were stored, yt-dlp was installed with Homebrew, and X cookie access is
  still unverified (Safari access denied; no Chromium x.com login found).
- The `~/.claude/skills` links are not managed by `config/links.json`; new skills
  need a link until installation covers Claude Code.

## 2026-11-01 — Patched Cloudflare CLI dependency tree

- Pinned cf to 1.0.0-beta.23, the first release with the patched upstream Zod and
  undici dependencies, to repair the toolkit audit blocking PRs #20 and #21.
- Aligned tool engine metadata and restore guidance with upstream's supported
  Node 22.23+, 24.22+, and 26.12+ ranges. Existing Node 24.22.2 was used for review.
- Validated a clean install without lifecycle scripts, the enforced dependency
  audit and offline command compatibility. Active tools, runtimes, credentials,
  native settings and provider resources are not changed by this source update.

## 2026-10-31 — Railway connection audit

- Clarified normal shell inheritance versus clean noninteractive processes and the
  role of `~/.shortcuts.sh`; the `railway.workspace` profile remains the owner of
  local token loading. Local operations and CI now explicitly select one token type.
- Completed the Railway skill’s project map with Events, Facts and HCI, exact CI
  secret stores, separate LivX serving access, and project-token verification and
  recovery. The hosting and provider skills use the same connection rules.
- Replaced five rejected GitHub Actions credentials with newly scoped project
  tokens: Map’s `RAILWAY_TOKEN` (Map/dev), Map’s `WEBARTS_RAILWAY_TOKEN_DEV`
  (Experimental/dev), Paul’s `RAILWAY_TOKEN_DEV` (Paul/dev), and HCI’s
  `development` environment `RAILWAY_TOKEN` (HCI/dev), and NLP’s
  `WEBARTS_RAILWAY_TOKEN_DEV` (Experimental/dev). Each new token’s
  project/environment was read back before saving through stdin; no token values
  or fragments were recorded. Existing unrelated credentials were preserved.

## 2026-10-31 — Railway token from the shell secrets file

- Profile `railway.workspace` points at `~/.secrets.sh` and reads only its literal
  `RAILWAY_API_TOKEN` assignment; profiles may now list `variables` for shell files
  and never execute them. The Paul manifest and `bin/railway-mcp` select it.
- Railway rejected the token in `~/.config/railway/webarts.env`; profile
  `railway.webarts` was removed and nothing reads that file. Inventory records
  `railway.workspace-token` and the global `shell.secrets` source.
- Every zsh loads `~/.secrets.sh` from `~/.zshenv`; bash loads it from `~/.profile`
  and `~/.bashrc`. Verified: `check --live` Railway read, and project-scoped Railway
  MCP calls with an empty environment.

## 2026-10-29 — Local development service operations

- Added `local-dev-services` for status, scoped recovery and full restart of the
  existing `~/git/local-dev` service catalog and private Tailscale routes.
- Added a read-only workspace checker that uses the owning manager's identity,
  local readiness and route ownership checks plus real private HTTPS probes.
  Its Node 24 selector reuses an existing runtime without installing tools.
- Documented native Tailscale versus per-app proxy recovery, bounded retries,
  worker-code reload, no-Git operation and the distinction between availability
  and source freshness. Ports and commands remain owned by local-dev config.
- No schedule, competing supervisor, account, credentials or native app settings
  were installed. Skill discovery needs no inventory registration.

## 2026-10-17 — Immediate Codex review requests

- Updated the Git and PR management skills to request Codex review immediately
  after creating every PR, including drafts, with a standalone `@codex review`
  comment and verification that it was posted.
- A failed comment leaves the review request incomplete. This policy does not
  install configuration, grant provider access, or satisfy independent review.

## 2026-10-16 — Last 30 Days research skill

- Imported `last30days` 3.28.0 from a pinned upstream commit into `skills/`,
  preserving its exported scripts, references, native metadata, and licenses.
- Recorded the upstream revision and update procedure in `licenses/README.md`.
  Shared skill discovery requires no configuration inventory registration.
- Added local review corrections for hosted constraint enforcement, numeric UTC
  watchlist scheduling, failed-run finalization and budget validation.
- Installation adds the research workflow only; provider access, setup wizard,
  browser cookies, optional CLIs, and hosted publishing were not configured.

## 2026-10-16 — Shared SMS command and skill

- Added `bin/agents-sms`, a dependency-free Node adaptation of Paul's existing
  Twilio transport, plus the `send-sms` skill for manually requested texts and
  authorized task notifications from any local project.
- Registered `twilio.sms` in the profile catalog and credential/consumer inventory.
  Initial credentials and fixed numbers are copied from `~/git/paul/.env.local`
  to ignored owner-only storage; the source uses an account Auth Token. No secret
  values or phone numbers are tracked, and existing grants are reused.
- Added local configuration/dry-run checks, sanitized message-status reads,
  no-overwrite profile import, and SMS usage/rotation/recovery documentation.
  Transport retains bounded Unicode-safe chunking, timeouts, and no retries.
- Added SMS regression tests to the existing Node 24 CI validation workflow.
- A single user-approved setup-test SMS was accepted and subsequently reported
  delivered by Twilio with no error code on 2026-10-16.
- No application settings, permission rules, account grants, MCP connections,
  services, or recurring automations changed. Remote agents need separately
  authorized local runtime and credential provisioning.

## 2026-10-15 — Configuration inventory and maintenance improvements

- Removed the skill catalog, individual skill references, generated skill table,
  and skill count from the configuration inventory. Skills remain discoverable
  directly from `skills/` without registration.
- Replaced `config/skill-sources.json` with `licenses/README.md`, preserving only
  the two imported provider revisions, local adaptations, and license links needed
  for deliberate upstream updates. Inventory commands no longer read skill metadata.
- Narrowed repository/global instructions and the maintenance skill/runbooks:
  update inventory records when configuration maintenance metadata changes;
  ordinary skill edits do not require inventory changes.
- Added regression coverage that validates and regenerates configuration docs
  independently of skills and import provenance. Preserved application settings,
  provider credentials, licenses, and tool pins.

## 2026-10-15 — Full main-to-prod promotions

- Production promotion now uses a PR with head `main` and base `prod`, including
  all work already merged into development; feature work and conflict fixes land
  in `main` first unless a narrower release is explicitly requested.
- Git and deployment skills include necessary production database migrations,
  verified target/configuration precedence, compatible rollout sequencing, schema
  and data checks, and exact deployed-commit/application/database validation.
- PR management and Railway IaC route to the owning promotion instructions.
  Intentional environment secrets, domains and feature flags remain distinct.
- Documented the policy ownership in the owning skills and maintenance runbook.
  No application branches, databases, deployments, credentials or tool pins changed.

## 2026-10-14 — Codex/Cursor discovery and lifecycle plan

- Researched native skill/instruction/configuration loading, command policies,
  hooks, subagents, local project opening, and desktop-control scope. Saved a
  source-linked harness map and prioritized acceptance plan in `docs/agent-harnesses.md`.
- Added the portable `agent-customization` skill and a maintenance runbook for
  diagnosing discovery, execution, account, and workflow gaps and contributing
  persistent improvements through the owning sources.
- Registered previously unlisted native policy/settings/context locations and
  project-secret conventions as references. Extended the global shell-source notes
  without reading its secret values or sourcing it for discovery.
- Confirmed Codex global rules/shared skill discovery using captured prompt-input
  metadata. Cursor effective User Rules, editor policy, and native MCP calls remain
  explicit verification work in the plan.
- No native permissions, active client configuration, provider grants, credential
  values, processes, DNS, deployments, or tool pins were changed. The new shared
  skill is available to local discovery; further setup changes remain proposed.

## 2026-10-14 — Implementation review and account consistency

- Centralized credential locations in `config/profiles.json`. CLI/MCP launchers,
  hosting helpers, token setup, and inventory now resolve the same profile IDs;
  no credential files or values were moved or rotated.
- Replaced line-based TOML rewriting with hash-pinned TOML Kit, restored only in
  ignored local Python packages. Valid quoted/dotted/inline tables and multiline
  strings are preserved; already-matching application config is not rewritten.
- Static validation now detects unsupported defaults, unregistered shared config or
  MCP definitions, invalid link sources/targets, and malformed profile metadata.
  Local checks flag added/removed plugins or application MCP runtimes and tool drift.
- Removed the deprecated zone-membership field as DNS Edit evidence. Live checks
  verify real DNS reads and explicitly mark write permissions untested; recorded
  permission scope comes from the dashboard grant.
- Live checks accept an explicit manifest and bind Cloudflare MCP verification to
  its account and zone. Added native GitHub authentication context and editor schema
  association without exposing native credential stores.
- New install backups retain private installed-state snapshots; restore refuses to
  overwrite subsequent file edits. Historical backups retain their original guard.
- Review evidence and scope limits are recorded in `docs/reviews/2026-10-14.md`.

## 2026-10-14 — Configuration inventory

- Added a concise root `AGENTS.md` linking repository work to the inventory,
  global rules, and required maintenance commands.
- Plugin checks now report malformed application settings as a failed result and
  continue other checks; regression coverage includes root and per-plugin formats.
- Added `config/inventory.json`, its schema, generated `docs/INVENTORY.md`, and
  `agents-config` lookup/validation/check commands. Registered credential profiles,
  environment variables, installed links, MCP integrations, tools, skills, runtime
  ownership, and plugin toggles. Secret values remain outside Git.
- Captured the six existing non-secret Codex preferences in
  `config/codex.defaults.toml`. The installer manages those keys while preserving
  other application settings; the captured values match the existing machine setup.
- Added credential/configuration update and recovery instructions, explicit live
  checks, sanitized ignored verification reports, and CI documentation validation.
- No provider grants, token values, DNS records, deployments, or tool pins changed
  as part of the inventory implementation. Git/PR history links this entry to its
  implementation and validation results.

## 2026-10-14 — Cloudflare all-domains identity permission

- `cloudflare.dns-token`: the user approved and saved User Details Read on
  **Agent DNS — all domains**, preserving DNS Edit and Zone Read for all zones.
  The original token value remained in the same ignored owner-only profile.
- Verification: token active, user read succeeded, all 12 current zones were readable,
  the dashboard declared DNS Edit for all zones, and the official hosted MCP
  initialized and executed a zone read. Legacy zone membership fields are not
  evidence of API-token grants.
- Permission edits and secret rotation are different operations. No DNS changes
  were used to test access. Documentation was originally published in PR #4;
  the inventory PR includes that update for one review.

## 2026-10-14 — Shared hosting toolkit

- Established shared MCP definitions, configuration links, explicit credential
  loading, pinned cf CLI, imported provider skills, and Railway/Cloudflare hosting
  helpers. Kept application state, credentials, backups, plans, and journals ignored.
- Registered all-domains DNS/zone access instead of a single-zone token. Preserved
  the existing WebArts Railway workspace profile and working deployment tool pins.
- Delivered through [PR #3](https://github.com/paulshorey/agents/pull/3).

## 2026-10-16 — Parallel asynchronous research skill

- Imported the official `parallel-deep-research` skill at a pinned upstream revision, preserving its license and update provenance.
- Shared skill discovery adds no inventory entry or application configuration. The facts project owns its local Parallel CLI; no credentials, account grants, or browser sessions changed.
- Replaced the unavailable plugin setup command with standalone project-owned
  setup/authentication guidance verified against CLI 0.9.3. Ordinary lookups use
  available web tools without depending on an unimported companion skill.

## 2026-10-17 — Parallel legacy authentication guidance

- Handle active legacy stored logins during authorized setup, and distinguish
  environment-key precedence from missing Account API tokens. Recheck the active
  authentication source after login without exposing credentials or retrying loops.
