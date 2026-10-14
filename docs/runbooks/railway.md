# Railway profiles and hosting configuration

Use `agents-config show railway.webarts-token` to locate the selected workspace
profile. Its source of truth is the Railway profile reference in the Paul manifest.
The current file is `~/.config/railway/webarts.env`, outside this repository and
owner-only mode 600. Its secret variable is `RAILWAY_API_TOKEN`.

The generic `~/.secrets.sh` Railway token accesses another workspace. It is an
external reference, not an inventory-managed dotenv file. Inventory checks neither
source nor parse it. `RAILWAY_TOKEN` is a separate environment/project CI credential;
update it in the affected CI secret store and document that store's reference.

## Update a workspace credential

Use Railway's supported credential management for the intended workspace. Edit
only the selected profile locally with a trusted editor and hidden secret handling.
Keep literal `KEY=value` assignments, not executable shell commands, and mode 600.
Never paste a value into a command argument, documentation, or Git.

Run `agents-config check --live`; the Railway result reads the registered project
and validates workspace, environments, and source branches. A failing account
identity endpoint alone does not establish that a workspace token is invalid.
Restart an existing Railway MCP session after a credential change; a fresh launcher
clears inherited Railway tokens and loads the explicit profile.

Record the replacement date, profile reference, affected consumers, and outcome in
`CHANGELOG.md`. To recover, retrieve the value from your encrypted backup or issue
a replacement through Railway. No value or OAuth store is backed up in Git.

## Update project mappings

`config/hosting/paul.json` owns Paul project/workspace/service/environment IDs,
source branches, domains, health checks, and profile references. Copy the example
manifest for a new project and replace placeholders with verified provider IDs.
Do not change the shared profile to target another workspace incidentally.

```sh
~/.agents/bin/agents-hosting doctor
~/.agents/bin/agents-hosting verify
```

These are read-only. Project creation, deployments, Railway IaC apply, DNS changes,
and SMS tests require the current task's authorization. Use the hosting skills and
their bootstrap references for those operations; an inventory record is not a grant.

The native Railway CLI remains externally installed. Project repositories own
their CLI/SDK pins. Check `railway --version` before troubleshooting; do not update
managed tools as a side effect of a credential edit.
