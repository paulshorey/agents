# Tools, skills, and inventory maintenance

`agents-config` uses Python 3.11 or newer. Metadata lookup, validation, and generation
use the standard library. Configuration rendering uses the pinned TOML editor restored
into ignored `local/python-packages` by the README's hash-verified pip command.
`~/.agents/bin` is already on the managed login-shell PATH; existing sessions can use
the absolute utility path.

```sh
~/.agents/bin/agents-config list cloudflare
~/.agents/bin/agents-config show cloudflare.dns-token
~/.agents/bin/agents-config validate
~/.agents/bin/agents-config docs
~/.agents/bin/agents-config docs --check
~/.agents/bin/agents-config check
~/.agents/bin/agents-config check --live --save-status
```

Lookup displays registered metadata, never file contents from secret profiles.
Validation and documentation generation only read shared sources. Local checks read
credential profiles in memory to confirm required names exist; they report statuses,
not values. They also check links, managed rendering, registered plugin toggles, and
CLI availability. An existing credential file is not proof of authentication.

`--live` adds read-only probes for the Cloudflare token/API/MCP and the Railway
project selected by `--manifest` (default: `config/hosting/paul.json`). The report
names the manifest; MCP verifies its exact account and zone. It never runs commands from inventory
metadata or applies infrastructure. Raw provider errors and responses are not output.
Live checks are observations of current access, not authorization for writes. They
do not prove DNS Edit, all-zone grants, other mutation permissions, or SMS behavior.
The output explicitly marks write permissions unverified. Native OAuth stores are not inspected.

By default checks do not save files. `--save-status` explicitly writes only sanitized
results and a timestamp to ignored `local/inventory/status.json`, mode 600. This is
a machine-specific observation; do not treat an old result as current readiness.

## Maintain configuration records

The inventory records configuration locations, ownership, credentials, consumers,
and update/recovery procedures. Update it when that metadata changes. Skills are
maintained and discovered directly in `skills/`; adding or editing a skill does
not require an inventory entry or changes to inventory references.

1. Give it a stable inventory ID, kind, owner, purpose, and update runbook.
2. Reference an existing manifest/file for settings and locations. `path_ref` uses
   a JSON Pointer into tracked JSON/TOML data instead of copying the same path.
3. For credentials, record names, permissions, profile reference, and consumers.
   Record update/recovery steps; never values, fragments, or value hashes.
4. Update the relevant runbook and add a changelog entry for meaningful file,
   credential, grant, integration, or ownership changes. Git records ordinary diffs.
5. Regenerate documentation, run validation/checks, and include metadata in the PR.

Every managed link must have exactly one inventory entry. The helper catalog derives
`bin/` and `scripts/`.
The JSON Schema disallows additional entry fields such as a credential `value`.
The built-in validator supports the explicit keywords used in the checked-in schema;
unsupported schema extensions fail until the validator is updated.

Validation also checks owned defaults, link definitions, profile structure, explicit
MCP registrations, and references for every shared JSON/TOML/shell file under `config/`.
Local checks flag new application plugins/MCP runtimes and compare the installed cf
version with its pin. These checks cover declared/managed configuration, not a scan of
every application or secret on the machine.

The repository is public. Shared records must be safe to publish. If a customization
needs private account details, keep those details in ignored local storage and register
the location and maintenance procedure without publishing the contents.

## Restore and update tools

Restore the pinned cf CLI with `npm ci --prefix ~/.agents/tools --ignore-scripts`.
Restore the TOML editor with the README's hash-verified pip command. Its wheel is
pure Python and has no transitive dependencies; it is installed only under ignored
`local/python-packages`, not into the global Python environment.
Version changes are deliberate lockfile edits, followed by review and validation.
The Railway native CLI is externally installed; application repositories keep their
own pins. Do not switch existing Wrangler deployments to cf incidentally.

Skills live under `skills/`. Imported provider material retains revisions,
adaptation notes, and license links in [`licenses/README.md`](../../licenses/README.md)
for future updates. Preserve provider licenses and local adaptations when updating
imports; update their provenance notes and validate the changed skill. New skills
and MCP definitions normally need a new agent session.

Production-promotion policy is owned by [git-management](../../skills/git-management/SKILL.md):
where `main` is development and `prod` is production, promote the full `main` branch
with a `main`-to-`prod` PR, including required database migrations and validation.
[deploy-railway-with-cloudflare](../../skills/deploy-railway-with-cloudflare/SKILL.md)
owns the production-target, migration sequencing and deployment verification details;
PR management and Railway IaC route to those instructions. Maintain these owning
sources together, preserving project-specific configuration and existing authorization.

CI checks schema/references, generated-document freshness, unit tests, and tool pins
without local credential access or provider authentication. To restore on another
machine, clone the repository, restore tools, inspect/install links, supply the registered
credential profiles or complete native sign-in, then run local and authorized live checks.
