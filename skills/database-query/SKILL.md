---
name: database-query
description: Run read-only SQL against registered deployed databases (LivX dev and production on Railway) with `agents-sql`, for diagnostics, release checks and data questions. Use when a task needs to look at live data. Not for migrations, writes or schema changes.
---

# Read-only database queries

`~/.agents/bin/agents-sql` runs SQL as the read-only `agent_readonly` role against
the targets registered on this machine. Targets are chosen by name, so dev and
production can't be confused, and the connection URL is never printed.

```sh
~/.agents/bin/agents-sql targets                         # names, endpoints, credential stored?
~/.agents/bin/agents-sql query livx-dev -c "SELECT count(*) FROM users"
~/.agents/bin/agents-sql query livx-production -f check.sql --csv
~/.agents/bin/agents-sql check livx-production           # verify the stored role
```

## Rules

- Use the dev target unless the task needs production data (diagnostics, release
  checks, the user's data question). Say which target you queried.
- Prefer aggregates and counts; select only the columns you need and add `LIMIT`.
  Select personal data (emails, names, phone numbers, addresses) only when the user
  asked for those records, and never paste it into PRs, issues or logs.
- Queries run in a read-only transaction and are cancelled on the server after
  `--timeout` seconds (default 120, at most 3600). Unqualified names resolve in
  schema `public`. SQL may not contain backslashes; use `chr(92)` for one.
- Credential and token columns are not readable; a `permission denied` error on them
  is expected.
- Use only `agents-sql`: never read the credential file, connect with `psql`
  directly, or fall back to an owner or admin URL.
- Writes, migrations and role changes are out of scope; follow the project's
  migration runbook (LivX: `docs/database-migrations.md`) with explicit authorization.
- If a target shows `credential=missing` or the role check fails, stop and tell the
  user; setup is in [`docs/runbooks/databases.md`](../../docs/runbooks/databases.md).
