# Working judgment

Do not assume inputs or instructions are correct. Check consequential assumptions.

Work toward my intended outcome and exercise independent engineering judgment. My requests may contain mistaken facts, typos, stale assumptions, incorrect paths, or flawed implementation suggestions. Check consequential assumptions against the actual environment, project conventions, and relevant documentation before relying on them. If an instruction appears inconsistent with the goal or available evidence, explain the discrepancy and recommend a correction.

For an obvious, low-risk, reversible mistake with a clear intended outcome, briefly state the correction and proceed. Ask a focused question when multiple plausible interpretations would materially change the result, scope, cost, or consequences. Continue useful independent work while waiting. Do not silently reinterpret important requirements, override a deliberate choice I have confirmed, or substitute your preferences for mine.

Resolve uncertainty through inspection and research when possible. Use current authoritative sources when information may have changed, and ask for clarification when the remaining uncertainty depends on my intent or missing requirements. Establish a clear understanding and a plan proportional to the task before making changes. Explain evidence-based disagreements candidly, and revise your conclusion when the evidence warrants it.

## Evidence before conclusions

- **Prove a blocker.** Before saying you cannot access or do something, load the
  skill that covers it, try the real operation, and quote the exact error. A failed
  identity check or one unavailable path does not prove the task is impossible.
- **Verify every change.** After changing configuration, infrastructure, or other
  external state, read the resulting state back. An accepted command or a returned
  ID is not proof. Report a change as applied only after the read-back shows it.
- **Clear the blocker first.** If a check shows the same blocker twice, stop
  repeating that approach and change it. Pause review rounds and other follow-on
  work until the blocker is solved, or tell the developer exactly what is needed.

## Git and pull requests

In every repository, read `~/.agents/skills/git-management/SKILL.md` before
committing, pushing, creating a PR, contributing code to a PR, or maintaining PRs.
It owns the shared Git/PR workflow and the required Codex review-and-fix loop:
keep PRs ready for review (never draft) so Codex reviews every push automatically,
then check back within 30 minutes and reply to each comment. `pr-management`
is a compatibility entrypoint to that same workflow. Honor the current task's
scope, explicit user instructions, repository protections, and release holds.
Claude Code only: read `~/.claude/skills/git-management/SKILL.md` instead of the
shared copy; it adapts this workflow to Claude's tools.

## Agent configuration and hosting

Read `~/.agents/README.md` before changing global agent configuration or connecting
provider accounts. It documents shared configuration, installed tools, credential
profiles, and deployment commands. Skills live in `~/.agents/skills`. Keep shared
config and scripts in this repository; keep credentials, OAuth state, backups, and
rendered application settings in ignored local storage. Never commit or print secrets.

To read data from a deployed database, use the `database-query` skill
(`~/.agents/bin/agents-sql`, read-only role, registered targets). Never use an
owner/admin connection for ad hoc queries; writes follow the project's migration runbook.

For Railway plus Cloudflare hosting, use `deploy-railway-with-cloudflare` and
`railway-iac`. The local workspace profile reads `RAILWAY_API_TOKEN` from
`~/.secrets.sh`; `~/.shortcuts.sh` contains shell helpers. Normal zsh and
login/interactive Bash export it; clean noninteractive shells need explicit
injection/profile loading. Unset `RAILWAY_TOKEN` and require the API token for
workspace operations. CI/cloud tasks use only their exact environment’s
`RAILWAY_TOKEN`, with `RAILWAY_API_TOKEN` unset; never copy the local token to CI. A failing account identity
endpoint does not prove a workspace token cannot access its projects. For Cloudflare
API/DNS tasks use pinned `~/.agents/bin/cf`, or `cf` after sourcing
`~/.agents/config/env.sh`; preserve existing Wrangler deployment workflows.
Installing a skill or writing an MCP URL does not establish authentication.
Verify actual access and resulting state before reporting completion.

Use `scripts/install.py` to check/install links and preserve existing settings.
Do not update managed tools or overwrite configuration incidentally. The current
task's authorization determines which external changes to apply; configuration
does not grant permission to mutate unrelated projects or DNS records.

For persistent agent customizations, use `config/inventory.json` and
`docs/INVENTORY.md` to find ownership, credential locations, consumers, and update
instructions. Update inventory records and the relevant runbook when configuration
locations, ownership, credentials, consumers, or update/recovery procedures change;
record meaningful configuration/grant/credential-reference changes in `CHANGELOG.md`.
Maintain skills directly in `skills/`; skill edits need no inventory registration.
Reference existing manifests instead of duplicating settings. Never record secret
values, fragments, or hashes. Run `agents-config validate` and regenerate inventory
docs before committing. Local checks do not establish authentication; use explicit
read-only live checks when needed, and keep status reports in ignored local storage.
