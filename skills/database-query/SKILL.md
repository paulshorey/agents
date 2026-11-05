---
name: database-query
description: Run read-only SQL against registered deployed databases (LivX dev and production on Railway) with `agents-sql`, for diagnostics, release checks and data questions. Use when a task needs to look at live data. Not for migrations, writes or schema changes.
---

# Read-only database queries

`~/.agents/bin/agents-sql` runs SQL against the targets in
this machine's ignored `~/.agents/local/databases.json` (list them with
`agents-sql targets`) using a dedicated read-only role. The connection
URL stays in an owner-only credential file and is never printed or passed on the
command line. Each query runs in one session that first verifies the role cannot
write, own or create anything, then runs the SQL in a read-only transaction. The
tool cancels the statement on the server after `--timeout` seconds (default 120).

```sh
~/.agents/bin/agents-sql targets                      # targets and whether a credential is stored
~/.agents/bin/agents-sql check livx-production        # connect and verify the role
~/.agents/bin/agents-sql query livx-dev -c "SELECT count(*) FROM public.users"
~/.agents/bin/agents-sql query livx-production -f check.sql --csv
```

## Rules

- Production reads are allowed when the task needs live data (diagnostics, release
  checks, answering the user's data question). Say which target you queried.
- Prefer aggregates and counts. Select only the columns you need and add `LIMIT`.
  Select personal data (emails, names, phone numbers, addresses) only when the user
  asked for those specific records, and never paste it into PRs, issues or logs.
- One `SELECT`/`WITH`/`TABLE`/`VALUES`/`SHOW`/`EXPLAIN` statement per `query` call;
  it runs in an enforced read-only transaction.
- SQL may not contain backslashes (psql meta-commands are disabled); use `chr(92)`
  for a literal backslash. Connections use TLS (`sslmode=require` or stronger).
- Unqualified names resolve in schema `public`; schema-qualify anything else.
- Never read the credential file or connect with `psql` directly: the role check is
  what keeps a misconfigured role from being used. Never print, echo or store a
  connection URL, password or token. Credentials,
  session tokens, invitation codes and voucher QR tokens are not readable by the role.
- Writes, migrations, backfills and role changes are out of scope. Follow the
  project's migration runbook (LivX: `docs/database-migrations.md`) with explicit
  authorization for that target.
- If a target reports `credential=missing` or the role check fails, stop and tell
  the user what is needed; see the runbook below. Do not fall back to an owner or
  admin connection.

## Setup and adding targets

Owner steps (`agents-sql prepare TARGET`, which keeps a new credential pending and
writes a private, ready-to-run `<target>-readonly-role.sql` that a superuser runs;
then `agents-sql activate TARGET`, which verifies and stores it) and how to register another database:
[`docs/runbooks/databases.md`](../../docs/runbooks/databases.md). The role SQL is
[`references/readonly-role.sql`](references/readonly-role.sql).
