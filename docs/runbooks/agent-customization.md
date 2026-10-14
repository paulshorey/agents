# Maintain agent capabilities and native configuration

Use this when a tool is missing, an agent repeatedly gets stuck, or a persistent
skill/configuration change is requested. The [harness research and plan](../agent-harnesses.md)
maps native paths and known gaps; refresh official documentation for the specific
installed version before relying on a new convention.

## Identify the failing layer

Read the root README, generated inventory, global rules, and applicable project
instructions. Inspect the working tree and exact target/account. Then distinguish:

| Layer | Useful evidence | Appropriate correction |
| --- | --- | --- |
| Discovery | Skill selector/rendered context, loaded instruction sources, overrides. | Correct path/description or instruction bridge; new session where required. |
| Configuration | Native config parse, owned manifest/link status, client version. | Update the authoritative source and preserve application-owned fields. |
| Local execution | Tool availability/PATH, sandbox paths/network, process owner. | Fix launcher or intended native policy, not unrelated global permissions. |
| Authentication/authorization | Account identity plus exact resource read or required operation. | Restore the intended profile/sign-in or obtain the specific missing grant. |
| Workflow | Actual error, provider operation, state read-back and expected result. | Improve the relevant runbook/helper/skill and verify the result. |

Inventory presence, an MCP URL, and a successful parser check prove different
things from actual authenticated access. Capture small sanitized evidence rather
than native auth files, raw prompt dumps, or full environment/config output.

## Choose the owning source

- Put portable workflows in `skills/`. Keep the entrypoint short; use references
  for conditional detail. Check existing skills before adding another. Imported
  skills retain source revisions/licenses in `config/skill-sources.json`.
- Use repository `AGENTS.md` for project context and `rules/AGENTS.md` for the
  managed Codex global instructions. Cursor User Rules are application/account
  settings; creating a similarly named home file does not prove it loads.
- Shared MCP definitions belong in `config/mcp.json`; private profile locations in
  `config/profiles.json`; provider project selectors in the relevant hosting manifest.
  Keep actual credentials in their registered ignored/native locations.
- Other settings, hooks, native command rules, and roles need harness-specific
  sources. Extend `scripts/install.py` with preservation/restore coverage before
  adding managed destinations to `config/links.json`. Do not copy native auth,
  project databases, plugin executables, or whole settings directories into Git.
- Native Codex command rules currently live in `~/.codex/rules/default.rules`.
  Cursor's CLI settings live in `~/.cursor/cli-config.json`; editor sandbox and
  Auto-review files have separate schemas. Record intended ownership before edits.

## Secrets and local services

The global shell source is `~/.secrets.sh`. Provider-specific profiles are listed
in `config/profiles.json`; application `.env*` files remain in their project.
Inspect the project's actual loader and precedence before choosing a file. Do not
load another workspace's token as an authentication fallback.

When the task authorizes secret edits, use the registered private destination,
preserve unrelated assignments and owner-only permissions, and update atomically.
Suppress value-bearing logs/diffs and verify names/presence or authenticated
behavior without printing values. A shell source can execute commands; do not
source arbitrary contents just to discover variable names. Record only paths,
names, consumers, reload steps, and grants in Git.

For process/service work, start with `~/git/AGENTS.md` and the actual project's
instructions. Existing web services use `~/git/local-dev`; read its runbook and
registry before selecting a manager command. Check PID/CWD/ownership before killing
anything. Do not create a competing supervisor to solve a configuration problem.

## Contribute and prove the change

Use the Git management workflow on a feature branch based on current main. Register
persistent changes in `config/inventory.json`, update the relevant runbook, and
record meaningful changes in `CHANGELOG.md`. Reference actual manifests rather
than copying their settings into notes.

```sh
~/.agents/bin/agents-config validate
~/.agents/bin/agents-config docs
~/.agents/bin/agents-config docs --check
git diff --check
```

For mechanics changes, run focused regression tests and installation/restore in a
temporary home. Test a new skill with realistic requests and available tools; its
frontmatter validator alone does not prove behavior. For provider work, select the
intended manifest/profile and use an explicit read or authorized bounded operation.
Restart/reopen the target client when required and verify actual skill/rule/MCP
discovery. A passing Codex call does not establish a passing Cursor call.

Record observed versions, target IDs and sanitized checks in ignored local status
when useful. Publish the PR with validation and remaining gaps, and leave active
application configuration intact unless this task authorizes changing it. A proposed
policy or connection is not an installed capability.
