# Codex and Cursor: discovery, capabilities, and improvement plan

Researched October 14, 2026 against current official documentation and this Mac.
Observed clients: Codex CLI 0.162.1 and Cursor editor 3.24.18. This task adds
documentation, inventory references, and a maintenance skill. Proposed settings,
hooks, integrations, account changes, and infrastructure are not applied here.

## What reads `~/.agents` automatically

Both local harnesses document `~/.agents/skills/<name>/SKILL.md` as a personal skill
location. Supporting resources inside a selected skill can be read or executed
when relevant. Neither documents a general user-level `~/.agents/config`,
`~/.agents/mcp.json`, `~/.agents/rules`, or `~/.agents/AGENTS.md` loader.
The shared directory is a skill convention, not a universal configuration home.
[Codex skills](https://learn.chatgpt.com/docs/build-skills),
[Cursor skills](https://cursor.com/docs/skills).

Consequently, our other directories do not collide with a documented loader.
`AGENTS.md` at this checkout's root applies when working in this repository;
it is not automatically global guidance for every application. Our inventory,
README, helpers, and hosting manifests become useful through explicit instructions,
skill references, commands, and the links declared in `config/links.json`.

Keep this layout. Do not move the entire checkout to `CODEX_HOME` or
`CURSOR_CONFIG_DIR`, or symlink whole native application directories into Git.
That would mix authored configuration with credentials and application state.

## Native configuration surfaces

| Purpose | Codex | Cursor | Sharing decision |
| --- | --- | --- | --- |
| Persistent instructions | `~/.codex/AGENTS.md`; nonempty `AGENTS.override.md` wins. Repository and nested instruction files add context. | User Rules in Customize → Rules; repository/nested `AGENTS.md` and `.cursor/rules/*.mdc`. | Keep prose in `rules/`; install through each supported entrypoint. |
| Reusable skills | `~/.agents/skills`, repository `.agents/skills`, bundled/admin sources; per-skill controls in config. | Shared/native skills plus documented Claude/Codex compatibility locations. | Author once in `skills/`; avoid duplicate copies and name collisions. |
| Settings and MCP | `~/.codex/config.toml`, selected profile files, trusted project `.codex/config.toml`. | `~/.cursor/mcp.json`, project `.cursor/mcp.json`; editor settings and CLI configuration have different owners. | Shared MCP source and a small owned preference set; preserve everything else. |
| Command execution policy | Sandbox/approval settings and `~/.codex/rules/*.rules`. | Run Modes; `~/.cursor/permissions.json` for Auto-review guidance, `sandbox.json` for reach; CLI also has `cli-config.json`. | Harness-specific policies, not a shared rules-file syntax. |
| Lifecycle hooks | `~/.codex/hooks.json` or inline hooks in config; project and plugin sources also exist. | `~/.cursor/hooks.json`, project hooks, plugin/team sources. | Shared helper logic with separate event/JSON adapters. |
| Custom subagents | Standalone TOML in `~/.codex/agents/` or project `.codex/agents/`. | Markdown with YAML frontmatter in `~/.cursor/agents/`; compatibility lookup exists. | Do not assume formats or tool restrictions translate. |
| Local project setup | Desktop-generated project `.codex/` configuration for setup scripts/actions. | Project instructions/scripts and editor tasks; cloud environments are a separate setup. | Keep app-specific commands with the app and reuse its service manager. |
| Native identity/state | Native auth store/keychain, sessions, plugin caches, desktop state, automations. | Native account/OAuth state, extensions, projects, caches, plugins. | Application-owned; record references, not contents. |

Instruction lookup and configuration layering are separate mechanisms. Codex
loads its global instruction file and the project path, with closer instructions
winning; project config requires trust. Cursor's published rules describe User
Rules through its UI and project rules on disk. They do not establish arbitrary
`~/.cursor/AGENTS.md` or global `~/.cursor/rules/*.mdc` as a replacement for User
Rules. Treat alternate global rule layouts as unverified until the installed
client demonstrates them. [Codex instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md),
[configuration](https://learn.chatgpt.com/docs/config-file/config-basic),
[Cursor rules](https://cursor.com/docs/rules).

Current Codex profiles use `~/.codex/NAME.config.toml` selected with `--profile`;
the documented migration from inline `[profiles.NAME]` happened in 0.134.0.
Our provider credential profiles in `config/profiles.json` are a different local
abstraction. Do not confuse them or copy old configuration examples without
checking the installed version. [Codex advanced configuration](https://learn.chatgpt.com/docs/config-file/config-advanced).

Codex `.rules` files describe executable command prefixes, not Markdown guidance.
Cursor Auto-review guidance and sandbox boundaries also do different jobs.
Its sandbox reference supports `additionalReadwritePaths`,
`additionalReadonlyPaths`, `additionalReadPaths`, `readBoundary`, and network
policy; an instruction to edit a secret does not expand the sandbox.
[Codex execution rules](https://learn.chatgpt.com/docs/agent-configuration/rules),
[Cursor Run Modes](https://cursor.com/docs/agent/security/run-modes),
[sandbox schema](https://cursor.com/docs/reference/sandbox).

Hooks merge across sources; avoid double execution and broad transcript logging.
Codex requires review/trust of non-managed hook definitions. Cursor hook names,
response fields, working directories, and lifecycle coverage differ. A future
context helper should emit public paths and instructions only, with no credential
values or environment dumps. [Codex hooks](https://learn.chatgpt.com/docs/hooks),
[Cursor hooks](https://cursor.com/docs/hooks).

Custom subagents are optional specialization. They are not needed to grant normal
shell, GitHub, or hosting access. Codex roles inherit parent permissions/provider/MCP;
Cursor has its own role fields and precedence. Start with portable skills and add
roles only for demonstrated benefits. [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents),
[Cursor subagents](https://cursor.com/docs/subagents).

Prefer skills for new reusable prompts. Codex's old `~/.codex/prompts` feature is
deprecated; avoid a parallel prompt library. [Official deprecation](https://learn.chatgpt.com/docs/custom-prompts).

Codex desktop local environments can declare setup scripts and actions in a
project file. These are useful for new checkouts/worktrees, but should call the
app's established commands and preserve managed service ownership.
[Local environments](https://learn.chatgpt.com/docs/environments/local-environment).

Cursor editor preferences also live outside `~/.cursor`: this Mac has
`~/Library/Application Support/Cursor/User/settings.json`. Keep its private/full
contents application-owned; export only deliberately managed preference keys.
Cursor's CLI configuration and permission schemas are documented separately from
editor preferences. [CLI configuration](https://cursor.com/docs/cli/reference/configuration),
[CLI permissions](https://cursor.com/docs/cli/reference/permissions).

Project `.cursorignore`, default ignores, and global ignore settings can hide
files from Cursor's file/context tools; `.env*` is in the documented default list.
Terminal/MCP access is a separate path governed by execution permissions. Keep
secrets out of indexing while using an authorized, non-printing edit procedure;
do not globally expose `.env` files just to make edits possible.
[Cursor ignore behavior](https://cursor.com/docs/reference/ignore-file).

## What is already configured on this Mac

- All four installer links match their declared sources. The installer preserves
  unrelated Codex settings and refuses a conflicting Cursor MCP file.
- `~/.codex/AGENTS.md` points to `rules/AGENTS.md`. The current Codex user config
  selects `danger-full-access` and `approval_policy = "never"`; those existing
  values remain application-owned, outside the six managed preferences. This is
  an observation, not a proposed permission change.
- A native `~/.codex/rules/default.rules` exists and was missing from the inventory.
  It is now registered as application-owned; its contents were not copied or edited.
- A captured `codex debug prompt-input` run from Paul confirmed the global rules,
  inventory instruction, and shared deployment skill in the rendered input.
  Raw prompt data was neither printed nor saved. This checks discovery, not tool
  authentication or an end-to-end autonomous run.
- A second rendered-input check discovered the new `agent-customization` skill
  from an application repository outside this checkout.
- Cursor's MCP file points to the shared manifest. `cli-config.json` exists with
  read/write/shell permission entries. No agent CLI executable was found on this
  shell's PATH. The `cursor` executable is the editor launcher, not proof of an
  installed `agent` CLI.
- No user `~/.cursor/hooks.json`, `permissions.json`, or `sandbox.json` was present.
  File absence does not determine effective editor mode or team policy. Cursor User
  Rules were not inspected through the UI; no shared startup instruction bridge is
  registered or verified. Fresh Cursor skill/MCP calls remain to be tested.
- Codex's Computer Use and Node REPL runtimes belong to its application. Do not
  copy their private executable definitions into Cursor and assume interoperability.

These are dated observations. The inventory stores ownership/update references;
`agents-config check` does not yet inspect every native policy surface listed here.

## Coverage of the development lifecycle

| Goal | Existing capability | Gap / acceptance evidence |
| --- | --- | --- |
| Start/stop services and recover processes | Shell; central local-dev manager documented in `~/git/AGENTS.md`. | Add a focused lifecycle skill using existing manager commands. Verify PID/CWD/owner, readiness, and restart behavior; do not kill unrelated listeners. |
| Open a new local Codex project | Installed `codex app PATH` accepts a workspace directory; `codex -C PATH` scopes CLI work. | New-project runbook should create/inspect the folder, open it with the supported command, and verify the actual saved project/context. Opening a folder alone does not prove remote/mobile registration. |
| GitHub repository/issues/PRs/branches/settings | Git, authenticated `gh`, Git management skills, native connector. | Add owner/visibility/default-branch/settings guidance and per-operation permission checks. Identity or PR access does not prove repository/org admin rights. |
| Railway projects/environments/services/databases/secrets | Provider CLI/MCP and deployment/IaC skills. | Existing doctor targets registered projects; full bootstrap, database provisioning and recovery need a disposable-project acceptance run when authorized. |
| Find/edit local and global secrets | `~/.secrets.sh`, project `.env*`, registered provider profiles. | Document per-project loaders/precedence and safe edits. Current inventory documents provider profiles, not every project secret. |
| Cloudflare domains and third-party DNS | Pinned cf API CLI, explicit identity and hosting manifest. | Hosting reconciler handles Railway CNAME/TXT requirements. MX and other integrations use native cf operations with exact record identity and read-back, not the Railway-only reconciler. |
| GUI apps and account-specific browsing | Codex native Computer Use and Wavebox skill. | Establish Cursor's own supported desktop tool route and macOS permissions; verify app/session identity in each harness. |
| Maintain skills and integrations | Shared skills, source/license records, installer, inventory and CI. | New maintenance skill routes changes through these sources; add behavioral checks when mechanics warrant them. |
| Recover on a new machine | Versioned config, links, tool pins, runbooks. | Restore private credentials/sign-ins separately, then verify each harness and each intended account. Git does not restore OAuth or secret values. |

`codex app PATH` was checked against installed CLI help and the
[CLI reference](https://learn.chatgpt.com/docs/cli/reference). Use the supported app
project/thread tools where available; never patch desktop SQLite or private state
JSON to register projects. A tool that creates a chat in an existing saved project
is not automatically a tool for registering an arbitrary new folder.

Cursor's native browser automation is distinct from full desktop control. Its
documented self-hosted worker can use the signed-in macOS desktop through the
Cursor Computer Use helper and privacy permissions. That is a separate deployment
mode, not proof of local editor access. Evaluate it or an appropriate desktop MCP
for the actual desired mode before installing anything.
[Cursor browser](https://cursor.com/docs/agent/tools/browser),
[self-hosted desktop control](https://cursor.com/docs/cloud-agent/self-hosted/computer-use).

## Proposed implementation order

1. **Establish Cursor startup context.** Keep a short canonical instruction in
   `rules/` directing agents to the README/inventory, global rules, and workspace
   instructions. Publish it through supported Cursor User Rules; record that
   account-synced UI location and update procedure. For selected repositories,
   add a small `AGENTS.md` entrypoint when needed, preserving their existing rules.
   Acceptance: fresh Cursor chats in this repo and an app report the intended
   instruction sources and can find the registered profile without revealing it.
2. **Make permissions and launch context explicit.** Record the actual Cursor
   editor mode/team overrides and CLI availability separately. Design owned,
   minimal native policy fragments only for required filesystem paths, package
   caches, shell operations, and provider network access. Preserve Codex's current
   policy unless the user requests a change. Extend installer merging/backup tests
   before managing additional files. Acceptance: a disposable `.env` edit and
   process start/stop work in both clients with the intended policy.
3. **Extend capability checks per harness.** Report declared, locally detected,
   and live-verified states separately. Include global instruction overrides,
   native rule files, policy files, hook trust, CLI version/PATH, skill discovery,
   available MCP tools, and explicit account/target reads. Cursor's remote MCP
   authentication must be tested in Cursor; Codex's header helper is not a Cursor
   auth mechanism. Store sanitized dated observations under ignored `local/`.
4. **Finish secrets and account onboarding.** Add project metadata for environment
   file locations/loaders and secret names as needed, referencing provider profiles.
   Authorized edits should preserve permissions and unrelated values, use atomic
   writes, and avoid shell tracing, value-bearing command arguments and diff output.
   Check Cursor ignore behavior separately from shell/file permissions; verify
   secret edits without making private files available to automatic indexing.
   Test with dummy values; document reload/redeploy requirements and encrypted
   recovery. Do not automatically source the broad executable `~/.secrets.sh` into
   every tool. GUI-launched apps may have different environments from login shells.
5. **Add focused project/process and GitHub administration runbooks.** Reuse
   local-dev's registry/manager and existing Git skills rather than creating a second
   service supervisor. A new-app workflow should cover local folder, repository,
   explicit owner/visibility, project instructions, Codex opening, dev/production
   hosting, secrets, domains, and returned resource IDs. Use `gh`/API capability
   checks for settings beyond the connector's tools. Verify each requested outcome.
6. **Test provider creation and recovery deliberately.** On an authorized disposable
   app, verify GitHub source integration, Railway workspace and environments,
   service/database/secrets, domains, DNS, certificate, exact deployment commit,
   and teardown. Record actual blockers and required scopes. Run TXT/MX integration
   tests separately when requested. Current read checks do not prove all writes.
7. **Make GUI support explicit for each harness.** Record supported app/browser
   entrypoints, required macOS permissions, authentication/session boundaries and
   known limitations. Reuse Wavebox's verified space/group distinctions. Test a
   harmless read/navigation task before relying on desktop control for setup.
8. **Keep maintenance bounded.** Use `agent-customization` for failures/new tools,
   update the inventory/runbook/changelog in the same PR, pin tools deliberately,
   and verify fresh-session behavior. Add hooks or roles only when simpler rules,
   skills, and existing commands leave a demonstrated gap.

Every applied step should identify its source file, native destination, owner,
reload behavior, validation, live proof where relevant, and rollback. Proposed
paths such as `config/cursor/` and `config/codex/` are candidates for future owned
fragments, not newly installed conventions. Any future `config/` files must be
registered before validation passes.

## Local and cloud contexts

The current goal is local development. Local skills, shell environments, native
OAuth, MCP connections, and home-directory files do not imply access from cloud
workers. Cursor documents sync for personal `~/.cursor/skills` only, not
`~/.agents/skills`; use intentional packaging if cloud execution becomes a goal.
Do not duplicate all skills to enable sync without considering local paths/tools.
[Cursor skill distribution](https://cursor.com/docs/skills#use-personal-skills-with-cloud-agents).

For ongoing changes use the [customization runbook](runbooks/agent-customization.md).
