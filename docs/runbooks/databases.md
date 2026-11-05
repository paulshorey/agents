# Read-only database access for agents

Agents query deployed databases with `~/.agents/bin/agents-sql` (skill
[`database-query`](../../skills/database-query/SKILL.md)). Each target in the ignored
`~/.agents/local/databases.json` (format:
[`config/databases.example.json`](../../config/databases.example.json)) names a
credential profile, a variable, and the expected host, port and database. Real
endpoints stay out of this public repository; copy them from the project's private
runbook. This machine registers `livx-dev` and `livx-production`. The registry must be
owned by you and mode 600. Credentials are connection
URLs for a dedicated `agent_readonly` role, stored in the profile's owner-only file:

| Profile | File | Variables |
| --- | --- | --- |
| `postgres.livx-readonly` | `~/.agents/local/credentials/livx-db-readonly.env` | `LIVX_DEV_READONLY_DATABASE_URL`, `LIVX_PRODUCTION_READONLY_DATABASE_URL` |

## Safety model

- The role has `SELECT` on base tables only (views and materialized views run with
  their owner's privileges, so they are granted only after an audit), owns nothing,
  cannot create objects, and defaults to read-only sessions with statement and idle
  timeouts. The role SQL clears default privileges naming the role for every creator
  (global or per schema), and the check refuses any default privilege for the role or
  PUBLIC, so future tables stay unreadable: re-run it after migrations add tables.
  Re-running also drops stale table, sequence, routine and large-object grants. It
  revokes `pg_logical_emit_message` from PUBLIC (non-transactional WAL writes survive
  a rollback) after granting it explicitly to every existing role, so only
  `agent_readonly` and roles created later lose it. Large objects cannot be withheld
  individually, so any `SELECT`/`UPDATE` grant on one to the role or PUBLIC fails the
  check. Credential writes hold a file lock; `prepare` holds it across both the URL and
  the prepared role SQL, so concurrent runs cannot pair one password with another's verifier. If PUBLIC can still create
  in schema `public` (PostgreSQL 14 or an upgraded database), it stops and asks the
  owner to grant application roles explicitly first, rather than changing that ACL. Secret tables and columns
  (`user_auth_tokens`, `password_reset_tokens`, `users.password`, `users.api_token`,
  `device_push_tokens.token`, `membership_offers.code`, `get_deals.qr_token`) are
  withheld. New tables become readable by default; extend the withheld list in
  [`readonly-role.sql`](../../skills/database-query/references/readonly-role.sql)
  and re-run it when a migration adds a secret.
- `agents-sql` refuses a stored URL whose host, port or database differs from the
  target, and refuses any role that is elevated, owns or can create objects, has
  non-`SELECT` table grants, or belongs to other roles. An owner URL is never usable.
- Each target's `withheld` list (tables or columns) must be unreadable directly,
  through inheritance or partition descendants and ancestors (a parent returns its
  children's rows), and through any view or
  materialized view built on them, including whole-row references (security-invoker
  views excepted), and through generated columns computed from them. Verification queries pin `search_path` to `pg_catalog`. Checks use
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
  executable `SECURITY DEFINER` or untrusted-language (e.g. `plpython3u`) routines in
  any schema (stock PostgreSQL has none), granted default-restricted built-ins
  (`pg_read_file`, `pg_ls_dir`, ...), compiled routines that are not core built-ins
  (any schema, including ones created in `pg_catalog` after `initdb`) unless listed in
  the target's `allowed_routines`, foreign-data-wrapper `USAGE`, `MAINTAIN` (PostgreSQL 17+)
  and configuration-parameter privileges (15+), and EXECUTE on `pg_logical_emit_message`.
- Residual risk: anyone who can read the credential file can connect without the
  tool and switch a session to read-write. The role's grants then still prevent data
  changes, but any login role can create large objects or temp tables. Keep the file
  mode 600 and the role limited to this use.

## Owner setup (once per database)

1. Generate and store the credential:

   ```sh
   ~/.agents/bin/agents-sql prepare livx-production
   ```

   The password and URL go straight to the owner-only credential file. The role SQL,
   with the password's SCRAM-SHA-256 verifier substituted, is written next to it as
   `~/.agents/local/credentials/<target>-readonly-role.sql` (mode 600); nothing secret
   is printed. The verifier cannot log in but allows offline password guessing, so
   keep that file private and delete it after step 3.
   Roles are cluster-wide: if this database shares a cluster with another registered
   target, prepare once and copy that URL's password to the other target instead.
2. Run that prepared copy of [`readonly-role.sql`](../../skills/database-query/references/readonly-role.sql)
   (one transaction; it covers schema `public`) as the database owner: `pbcopy < FILE`
   and paste into the hosting provider's SQL console for that database (Railway:
   Postgres service → **Data** tab), or `psql OWNER_URL -f FILE`. It must run as a
   superuser or a member of every role that created default privileges naming
   `agent_readonly`; otherwise it names those roles and changes nothing. Project, environment, service IDs
   and public endpoints are in the project's private runbook (LivX:
   `~/git/livx/docs/database-migrations.md`). The script aborts on anything other
   than a verifier.
3. Verify:

   ```sh
   ~/.agents/bin/agents-sql check livx-production
   ```

`agents-sql set-url TARGET` remains for storing an existing read-only URL (hidden
prompt; verified before saving). If a target has audited compiled extension routines
(language `c`/`internal` outside `pg_catalog`, for example `pgcrypto`, or created in
`pg_catalog` after `initdb`, OID 16384 or above), list each by full identity in its registry entry, e.g.
`"allowed_routines": ["public.digest(text,text)"]`; an unlisted routine or overload,
such as `dblink_exec`, is refused.

An agent may run step 2 itself only with explicit authorization for that database
and a credential that can reach its owner connection (see
[Railway profiles](railway.md)); it must keep the owner URL in memory and never print it.

## Rotate, revoke, add a target

- Rotate: `agents-sql prepare TARGET`, run the newly prepared
  `<target>-readonly-role.sql` as the owner, then `agents-sql check TARGET`.
- Revoke: `ALTER ROLE agent_readonly NOLOGIN;` (or `DROP OWNED BY agent_readonly; DROP ROLE agent_readonly;`)
  and delete the variable from the credential file.
- Add a database: add a target to `local/databases.json`, register its variable
  in the profile in `config/profiles.json` (or a new `postgres.*` profile), update
  `config/inventory.json`, regenerate the inventory docs, then do the owner setup.

Recovery: the credential file is local only and not backed up in Git. If it is lost,
rotate the password and store the new URL.
