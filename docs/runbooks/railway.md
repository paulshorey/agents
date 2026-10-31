# Railway profiles and hosting configuration

The Railway workspace token is `RAILWAY_API_TOKEN` in `~/.secrets.sh` (owner-only,
mode 600), for workspace **my workspace** (`c64d0999-e00c-4c52-bbd4-2614210e3758`).
Every shell exports it (see `agents-config show shell.secrets`). Profile
`railway.workspace` in `config/profiles.json` points at the same file and reads only
that literal assignment; the Paul manifest and the native MCP launcher select it, so
they work even when a client starts them without a shell. Use
`agents-config show railway.workspace-token` for its consumers.
`RAILWAY_TOKEN` is a separate environment/project CI credential; update it in the
affected CI secret store and document that store's reference.

## Update a workspace credential

Use Railway's supported credential management for the intended workspace. Replace
only the `RAILWAY_API_TOKEN` line in `~/.secrets.sh` with a trusted editor and hidden
secret handling. Keep it a literal `export RAILWAY_API_TOKEN="..."` assignment and
the file mode 600. Never paste a value into a command argument, documentation, or Git.

Open a new shell, then run `agents-config check --live`; the Railway result reads the
registered project and validates workspace, environments, and source branches. A
failing account identity endpoint alone does not establish that a workspace token is
invalid. Restart an existing Railway MCP session after a credential change; a fresh
launcher clears inherited Railway tokens and reads the profile file.
For another workspace, register its own profile ID and select it explicitly; do not
repoint `railway.workspace` to switch an unrelated task's account.

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
