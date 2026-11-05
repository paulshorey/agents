---
name: database-query
description: Run read-only SQL against registered deployed databases (LivX dev and production on Railway) with `agents-sql`, for diagnostics, release checks and data questions. Use when a task needs to look at live data. Not for migrations, writes or schema changes.
---

# Read-only database queries

`~/.agents/bin/agents-sql` runs SQL against the targets in
this machine's ignored `~/.agents/local/databases.json` (list them with
`agents-sql targets`) using a dedicated read-only role. The connection
URL stays in an owner-only credential file and is never printed or passed on the
command line. Before every query the tool verifies the role cannot write, own or
create anything, and the session defaults to read-only with a 30s statement timeout.

```sh
~/.agents/bin/agents-sql targets                      # targets and whether a credential is stored
~/.agents/bin/agents-sql check livx-production        # connect and verify the role
~/.agents/bin/agents-sql query livx-dev -c "SELECT count(*) FROM public.users"
~/.agents/bin/agents-sql query livx-production -f check.sql --csv
```

## Rules

- Production reads are allowed when the task needs live data (diagnostics, release
  checks, answering the user's data question). Say which target you queried.
- Prefer aggregates and counts. Select only the columns you need, add `LIMIT`, and
  do not paste personal data (emails, names, phone numbers) into chat, PRs, issues
  or logs unless the user asked for those specific records.
- One `SELECT`/`WITH`/`TABLE`/`VALUES`/`SHOW`/`EXPLAIN` statement per `query` call;
  it runs in an enforced read-only transaction.
- SQL may not contain backslashes (psql meta-commands are disabled); use `chr(92)`
  for a literal backslash. Connections use TLS (`sslmode=require` or stronger).
- Never print, echo or store a connection URL, password or token. Credentials,
  session tokens, invitation codes and voucher QR tokens are not readable by the role.
- Writes, migrations, backfills and role changes are out of scope. Follow the
  project's migration runbook (LivX: `docs/database-migrations.md`) with explicit
  authorization for that target.
- If a target reports `credential=missing` or the role check fails, stop and tell
  the user what is needed; see the runbook below. Do not fall back to an owner or
  admin connection.

## Setup and adding targets

Owner steps (create the role, store its URL) and how to register another database:
[`docs/runbooks/databases.md`](../../docs/runbooks/databases.md). The role SQL is
[`references/readonly-role.sql`](references/readonly-role.sql).
