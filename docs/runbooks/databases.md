# Read-only database access for agents

Agents query deployed databases with `~/.agents/bin/agents-sql` (skill
[`database-query`](../../skills/database-query/SKILL.md)). Each target in the ignored
`~/.agents/local/databases.json` (format:
[`config/databases.example.json`](../../config/databases.example.json)) names a
credential profile, a variable, and the expected host, port and database. Real
endpoints stay out of this public repository; copy them from the project's private
runbook. This machine registers `livx-dev` and `livx-production`. Credentials are connection
URLs for a dedicated `agent_readonly` role, stored in the profile's owner-only file:

| Profile | File | Variables |
| --- | --- | --- |
| `postgres.livx-readonly` | `~/.agents/local/credentials/livx-db-readonly.env` | `LIVX_DEV_READONLY_DATABASE_URL`, `LIVX_PRODUCTION_READONLY_DATABASE_URL` |

## Safety model

- The role has `SELECT` on base tables only (views and materialized views run with
  their owner's privileges, so they are granted only after an audit), owns nothing,
  cannot create objects, and defaults to read-only sessions with statement and idle
  timeouts. The role SQL keeps no default privileges: re-run it after migrations add
  tables. It also revokes `pg_logical_emit_message` from PUBLIC (non-transactional
  WAL writes survive a rollback). Secret tables and columns
  (`user_auth_tokens`, `password_reset_tokens`, `users.password`, `users.api_token`,
  `device_push_tokens.token`, `membership_offers.code`, `get_deals.qr_token`) are
  withheld. New tables become readable by default; extend the withheld list in
  [`readonly-role.sql`](../../skills/database-query/references/readonly-role.sql)
  and re-run it when a migration adds a secret.
- `agents-sql` refuses a stored URL whose host, port or database differs from the
  target, and refuses any role that is elevated, owns or can create objects, has
  non-`SELECT` table grants, or belongs to other roles. An owner URL is never usable.
- Each target's `withheld` list (tables or columns) must be unreadable directly,
  through inheritance or partition descendants, and through any view or
  materialized view built on them (security-invoker views excepted). Checks use
  effective privileges, so a column grant or `pg_read_all_data` is refused. Keys are
  `table` (schema `public`) or `schema.table`. A withheld relation or column that does
  not exist fails closed, so update the list when a migration renames one.
  Any role membership is refused.
- The URL is passed to `psql` through libpq environment variables only, with inherited
  `PG*`/`DATABASE_URL` settings dropped. SQL containing a backslash is rejected, so
  psql meta-commands (`\!`, `\o |cmd`, `\copy ... program`) cannot start a local
  program that inherits the password. Use `chr(92)` for a literal backslash.
- Deployed connections must use `sslmode=require` (the default when omitted),
  `verify-ca` or `verify-full`; the latter two need `sslrootcert`. Railway's public TCP
  proxy serves a self-signed certificate, so `require` (encrypted, server not
  authenticated) is the practical baseline there; pin the exported root CA with
  `verify-ca` for authentication. Weaker modes are accepted only for loopback hosts.

- Each `query` runs exactly one `SELECT`, `WITH`, `TABLE`, `VALUES`, `SHOW` or
  `EXPLAIN` statement inside a `READ ONLY` transaction that has already taken a
  snapshot, then rolls back. Transaction control (including `PREPARE TRANSACTION`),
  `SET`, `DO`, `CALL` and `LOCK` are rejected before connecting. PostgreSQL refuses to switch that
  transaction to read-write, so writes, `nextval`, large-object creation, temp tables
  and DDL fail even if a grant was missed. Multi-statement input is rejected.
- The role check also refuses ownership of any object (via `pg_shdepend`), grant
  options, sequence `USAGE`/`UPDATE`, foreign-server `USAGE`, large-object `UPDATE`,
  executable `SECURITY DEFINER` routines in any schema (stock PostgreSQL has none), `MAINTAIN` (PostgreSQL 17+)
  and configuration-parameter privileges (15+), and EXECUTE on `pg_logical_emit_message`.
- Residual risk: anyone who can read the credential file can connect without the
  tool and switch a session to read-write. The role's grants then still prevent data
  changes, but any login role can create large objects or temp tables. Keep the file
  mode 600 and the role limited to this use.

## Owner setup (once per database)

1. Generate a password: `openssl rand -base64 32 | tr -d '/+='`. Roles are
   cluster-wide: if this database shares a cluster with another registered target,
   reuse that role's password (or update every affected URL together).
2. Run [`readonly-role.sql`](../../skills/database-query/references/readonly-role.sql) (one
   transaction; it covers schema `public`)
   as the database owner with that password substituted: in the hosting provider's
   SQL console for that database (Railway: Postgres service → **Data** tab), or with
   psql using its owner connection. Project, environment and service IDs are in the
   project's private runbook (LivX: `~/git/livx/docs/database-migrations.md`).
3. Build the URL from the database's public host and port, documented in that same
   runbook: `postgresql://agent_readonly:PASSWORD@HOST:PORT/DATABASE`.
4. Store it without echo. The tool verifies the role before saving:

   ```sh
   ~/.agents/bin/agents-sql set-url livx-production   # paste at the hidden prompt
   ~/.agents/bin/agents-sql check livx-production
   ```

An agent may perform steps 1–4 itself only with explicit authorization for that
database and a Railway credential that can read the project (see
[Railway profiles](railway.md)); it must keep the owner URL and generated password
in memory and never print them.

## Rotate, revoke, add a target

- Rotate: re-run the role SQL with a new password, then `agents-sql set-url TARGET`.
- Revoke: `ALTER ROLE agent_readonly NOLOGIN;` (or `DROP OWNED BY agent_readonly; DROP ROLE agent_readonly;`)
  and delete the variable from the credential file.
- Add a database: add a target to `local/databases.json`, register its variable
  in the profile in `config/profiles.json` (or a new `postgres.*` profile), update
  `config/inventory.json`, regenerate the inventory docs, then do the owner setup.

Recovery: the credential file is local only and not backed up in Git. If it is lost,
rotate the password and store the new URL.
