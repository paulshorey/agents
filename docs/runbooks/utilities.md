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
First check that `node --version` satisfies `tools/package.json`'s `engines` range;
the current pin requires Node 22.23+, 24.22+, or 26.12+ within those majors.
Use an existing supported runtime when available. Updating the source pin does not
replace an installed runtime or restore `tools/node_modules` automatically.
Restore the TOML editor with the README's hash-verified pip command. Its wheel is
pure Python and has no transitive dependencies; it is installed only under ignored
`local/python-packages`, not into the global Python environment.
Version changes are deliberate lockfile edits, followed by review and validation.
The beta.23 cf pin updates the upstream dependency tree to patched Zod and undici
releases. Validate a clean restore, `npm audit --omit=dev`, version/help, command
search, schema inspection and a DNS dry run before adopting another pin. Keep the
audit enforced; do not force an automatic upgrade or add unvalidated overrides.
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

## PR context

`scripts/pr-context.py` is the shared, read-only PR fetcher for
[`git-management`](../../skills/git-management/SKILL.md) and
[`pr-management`](../../skills/pr-management/SKILL.md). Both skill `scripts/`
folders symlink to this source; edit the common file. It needs Python 3.11+ and
an authenticated `gh` with `api --paginate --slurp` support. It reuses GitHub CLI's
native sign-in; no credential copy, new profile, or installation step is needed.
Git supplies repository/branch context through `gh`; GitHub APIs supply hosted
PR metadata and feedback.

```sh
python3 ~/.agents/scripts/pr-context.py https://github.com/OWNER/REPO/pull/123
python3 ~/.agents/scripts/pr-context.py 123 --repo OWNER/REPO --diff
python3 ~/.agents/skills/git-management/scripts/pr-context.py 123 --no-filter
python3 ~/.agents/skills/pr-management/scripts/pr-context.py
```

Omit the PR to select the current branch's PR. Use a URL or
`--repo [HOST/]OWNER/REPO` for another repository/host. Output is one compact JSON document:

- `pr`: description, head/base SHAs, state, merge/review decisions, labels,
  assignees, and requested reviewers/teams.
- `commits`, `files`: all commits and changed-file metadata; `--diff` adds the
  GitHub diff. Use local `git diff`/`git show` for further code inspection.
- `comments`: issue comments, inline comments/replies, and review bodies together,
  newest updated first. IDs, URLs, authors, review IDs, reply-parent IDs, and inline
  code context remain available for individual responses.
- `reviews`: decisions and reviewed commits, even when their text is filtered.
  `threads`: resolution/outdated state, root comment IDs, and visible comment IDs.
  Bodies appear only in `comments`, avoiding duplicated thread/review text.
- `checks`, `statuses`: check runs and commit statuses for the captured head.
- `filtering`: counts of removed entries and cleaned bodies. `--no-filter` keeps
  the original comment text and entries in the same output schema.

The helper uses 100 items per REST page and follows all pagination links/cursors
for comments, reviews, threads, commits, files, and checks/statuses. Inline replies
come from their own fully paginated endpoint, avoiding nested GraphQL reply limits.
If fetching manually, follow `Link: rel="next"` or GraphQL `hasNextPage`/`endCursor`.
When a default page contains 30 comments, check/request the next page unless the
API explicitly reports none. Do not infer completeness from the first page or sort
only that page.

Filtering changes output only. First, a regex tag scan balances nested `<details>`
blocks and removes only the block owning `<summary>ℹ️ About Codex in GitHub</summary>`.
Inline code and fenced code examples are masked during that scan and preserved
verbatim in the returned body.
Other details blocks and code formatting are preserved. Then any comment body
containing `## Codex Review Summary` or `@codex review` is omitted, regardless of
author. This order preserves useful review text when the excluded phrase appears
only in the removed boilerplate. The Codex receipt HTML marker is also removed.
Review decisions and thread metadata remain visible; filtered roots do not hide
useful replies. No other bot/human findings are automatically discarded.

Failures exit nonzero without partial JSON. This includes access/rate-limit errors,
incomplete file/commit counts, feedback-count changes, and head/base changes during
the read. GitHub caps the files endpoint at 3,000; inspect larger PRs with Git rather
than assuming a truncated file list is complete. Check runs must match the API's
`total_count`; the helper also fails conservatively at 1,000 runs rather than
assuming the endpoint has not truncated them. Each CLI call times out after 60
seconds. Errors omit raw response bodies. The result is an observation, not an
atomic snapshot; fetch again before replying, resolving threads, or merging.
The helper never posts, resolves, or deletes GitHub comments. Those actions follow
the task's authorization and the skills' requirement to reply to each addressed
comment after validating and pushing its fix.

The [Git management review loop](../../skills/git-management/references/review-loop.md)
owns review requests, the 30-minute timeout, completion evidence for the current
head, replies/resolution, and repetition after functional changes. The
`pr-management` entrypoint routes to that same policy. Use `--no-filter` for
request/completion evidence; it is intentionally absent from filtered output.

Validate changes with `python3 -m unittest discover -s tests -p test_pr_context.py -v`
and a read-only fetch of an accessible PR. Run both symlink entrypoints and compare
counts against an unfiltered fetch. Authentication failures need an existing-account
access/sign-in check, not changes to stored credentials or unrelated configuration.
The [GitHub CLI pagination guide](https://cli.github.com/manual/gh_api) and
[review-comments API](https://docs.github.com/en/rest/pulls/comments#list-review-comments-on-a-pull-request)
document the underlying commands and feedback endpoints.

CI checks schema/references, generated-document freshness, unit tests, and tool pins
without local credential access or provider authentication. To restore on another
machine, clone the repository, restore tools, inspect/install links, supply the registered
credential profiles or complete native sign-in, then run local and authorized live checks.
