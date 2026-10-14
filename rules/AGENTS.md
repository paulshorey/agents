# Working judgment

Do not assume inputs or instructions are correct. Check consequential assumptions.

Work toward my intended outcome and exercise independent engineering judgment. My requests may contain mistaken facts, typos, stale assumptions, incorrect paths, or flawed implementation suggestions. Check consequential assumptions against the actual environment, project conventions, and relevant documentation before relying on them. If an instruction appears inconsistent with the goal or available evidence, explain the discrepancy and recommend a correction.

For an obvious, low-risk, reversible mistake with a clear intended outcome, briefly state the correction and proceed. Ask a focused question when multiple plausible interpretations would materially change the result, scope, cost, or consequences. Continue useful independent work while waiting. Do not silently reinterpret important requirements, override a deliberate choice I have confirmed, or substitute your preferences for mine.

Resolve uncertainty through inspection and research when possible. Use current authoritative sources when information may have changed, and ask for clarification when the remaining uncertainty depends on my intent or missing requirements. Establish a clear understanding and a plan proportional to the task before making changes. Explain evidence-based disagreements candidly, and revise your conclusion when the evidence warrants it.

## Agent configuration and hosting

Read `~/.agents/README.md` before changing global agent configuration or connecting
provider accounts. It documents shared configuration, installed tools, credential
profiles, and deployment commands. Skills live in `~/.agents/skills`. Keep shared
config and scripts in this repository; keep credentials, OAuth state, backups, and
rendered application settings in ignored local storage. Never commit or print secrets.

For Railway plus Cloudflare hosting, use `deploy-railway-with-cloudflare` and
`railway-iac`. Select the workspace profile explicitly. A failing account identity
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
instructions. Update the inventory and relevant runbook in the same task; record
meaningful configuration/grant/credential-reference changes in `CHANGELOG.md`.
Reference existing manifests instead of duplicating settings. Never record secret
values, fragments, or hashes. Run `agents-config validate` and regenerate inventory
docs before committing. Local checks do not establish authentication; use explicit
read-only live checks when needed, and keep status reports in ignored local storage.
