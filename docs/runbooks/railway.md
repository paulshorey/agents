# Railway profiles and hosting configuration

The Railway workspace token is `RAILWAY_API_TOKEN` in `~/.secrets.sh` (owner-only,
mode 600), for workspace **my workspace** (`c64d0999-e00c-4c52-bbd4-2614210e3758`).
Normal zsh and login/interactive Bash export it (see
`agents-config show shell.secrets`); clean noninteractive shells need explicit
injection/profile loading. `~/.shortcuts.sh` contains helpers, not Railway credentials. Profile
`railway.workspace` in `config/profiles.json` points at the same file and reads only
that literal assignment; the Paul manifest and the native MCP launcher select it, so
they work even when a client starts them without a shell. Use
`agents-config show railway.workspace-token` for its consumers.
`RAILWAY_TOKEN` is a separate environment/project CI credential; update it in the
affected CI secret store and document that store's reference. Use one token type at
a time: unset `RAILWAY_TOKEN` for workspace commands, and unset `RAILWAY_API_TOKEN`
for project-token commands. The local workspace token must not be copied into CI.

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

## Verify and repair a CI credential

Read the repository’s current workflow and owning runbook for the exact secret
store, project and environment. Check `railway api
'query{projectToken{projectId environmentId}}'` with only the intended project token
set, and compare both returned IDs. Project/environment selectors do not override
a token’s scope. GitHub secret metadata proves presence, not validity.

For an authorized invalid-secret repair, create a project/environment token with
Railway’s supported API/dashboard, verify its scope, and use `gh secret set NAME
--repo OWNER/REPO` with the value on hidden stdin. Never put it in arguments, logs,
PRs, or the profile catalog. Recheck secret metadata and a same-repository PR plan.
Do not rerun an apply/deploy workflow just to test authentication. Keep existing
unrelated tokens; revoke a predecessor only after its consumers are identified.
