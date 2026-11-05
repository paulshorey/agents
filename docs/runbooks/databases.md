# Read-only database access for agents

Agents (Claude Code, Codex, Cursor) query deployed databases with
`~/.agents/bin/agents-sql` (skill [`database-query`](../../skills/database-query/SKILL.md)).

## How it works

- **The database role is the security boundary.** `agent_readonly` can only `SELECT`
  base tables in schema `public`; credential and bearer-code tables and columns are
  withheld. The role is created by
  [`readonly-role.sql`](../../skills/database-query/references/readonly-role.sql).
  Even if a credential leaked or an agent connected without the tool, it could not
  change data.
- **Targets are chosen by name.** The ignored `~/.agents/local/databases.json` (mode
  600; format in [`config/databases.example.json`](../../config/databases.example.json))
  lists each target's description, credential profile variable, host, port and
  database. A stored URL that points anywhere else is refused. Unknown keys are refused.
- **Credentials stay private.** URLs live in the owner-only file of a `postgres.*`
  profile in `config/profiles.json` and reach `psql` only through libpq environment
  variables, never arguments or output. Deployed hosts require TLS (`sslmode=require`,
  or `verify-ca`/`verify-full` with a pinned `sslrootcert`).
- **Guardrails against mistakes.** Each query runs in one `psql` session that first
  checks the role and runs the SQL only if the role is not elevated, not a member of
  other roles, owns nothing and cannot write or create objects. That catches an owner
  or app URL stored by mistake. The SQL then runs in a read-only transaction with
  `search_path` set to `public`, and is cancelled on the server after `--timeout`
  seconds. The role also has a 30 s statement timeout and a 5-connection limit.

| Profile | File | Variables |
| --- | --- | --- |
| `postgres.livx-readonly` | `~/.agents/local/credentials/livx-db-readonly.env` | `LIVX_DEV_READONLY_DATABASE_URL`, `LIVX_PRODUCTION_READONLY_DATABASE_URL` |

## Set up or rotate a target

1. `~/.agents/bin/agents-sql prepare TARGET` generates a password and writes two
   owner-only files next to the credential file: `TARGET-pending.url` and
   `TARGET-readonly-role.sql`, the role SQL with the password's SCRAM verifier. Nothing
   secret is printed, and any current credential keeps working. A stored
   `verify-ca`/`verify-full` setting carries over.
2. Run that SQL file as a superuser (Railway: the `postgres` user), by pasting it into
   the Postgres service's **Data** tab, or with
   `psql 'host=HOST port=PORT dbname=DB user=postgres sslmode=require' -f FILE`, which
   prompts for the password (never put the owner URL on the command line). It stops
   without changing anything if PUBLIC can create in schema `public` (PostgreSQL 14
   default) or read a secret table, or if a secret table has parent or child tables. Endpoints and service IDs are
   in the project's private runbook (LivX: `~/git/livx/docs/database-migrations.md`).
3. `~/.agents/bin/agents-sql activate TARGET` checks the new role, stores the URL and
   deletes both files. If the check fails, nothing changes.

Re-run the role SQL (steps 1-3) after migrations add tables, since only existing
tables are granted, or add secrets (edit the lists in the SQL first). An agent may run
step 2 only with explicit authorization for that database.

## Add a target, revoke, recover

- Add: a target in `local/databases.json`, its variable in a `postgres.*` profile in
  `config/profiles.json`, an inventory update (`config/inventory.json`, then
  `bin/agents-config docs`), then the setup above.
- Revoke: `ALTER ROLE agent_readonly NOLOGIN;` (or `DROP OWNED BY agent_readonly;
  DROP ROLE agent_readonly;`) and remove the variable from the credential file.
- Recover: the credential file is local only. If it is lost, rotate.

## Known limits

- Only the `agent_readonly` login is accepted, so another reader role stored by
  mistake is refused even if it cannot write.
- Roles are cluster-wide, so targets in the same cluster share one password: rotating
  one changes it for all of them. Store the new URL for each such target. On Railway
  each Postgres service is its own cluster.
- On a Railway Postgres service the role can also connect to
  the empty `postgres` and `template1` databases, where it has only PUBLIC's default
  rights. If a cluster holds other databases with data, the role's access there is
  whatever PUBLIC has.
- Personal data (emails, names) is readable. The skill tells agents to prefer
  aggregates. To restrict it later, add those columns to the role SQL's withheld
  lists, or grant an audited view instead of the table.
- The tool's SQL rules are guardrails, not a sandbox: any program running as this
  user can read the credential file. Keep it mode 600.

## Validation

```sh
python3 -m unittest tests.test_sql_query -v
AGENTS_SQL_TEST_ADMIN_URL=postgresql://admin:PASSWORD@127.0.0.1:PORT/scratch python3 -m unittest tests.test_sql_query -v
```

The second form also runs live tests against a disposable local PostgreSQL database
(superuser URL, password authentication). They create tables and roles there.
