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

The database role's grants are the security boundary. Anything that can read the
credential file (any agent running as this OS user) can connect without
`agents-sql`, so the tool's SQL rules (one read statement, no backslashes) only stop
mistakes. The check the tool runs before every query is what catches a role
that was granted too much; keep the grants, the check and the withheld lists
correct rather than adding more client-side rules.

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
- The check and the query run in one `psql` session: the SQL runs only if the check
  in that same connection passed, so nothing can change between check and query, and
  each query costs one connection.
- Roles are cluster-wide and PostgreSQL lets PUBLIC connect to every database by
  default. The check refuses a role that can connect to another database unless the
  target lists it in `other_databases`. Either revoke `CONNECT` on those databases from
  PUBLIC (granting it to the roles that need it), or audit them and list them. Stock
  `postgres` and `template1` normally hold no data, but on PostgreSQL 14 or older PUBLIC
  can create objects in their `public` schema (and objects in `template1` are copied
  into new databases), so revoke there instead of listing them. The role SQL prints a
  notice naming these databases.
- Each target's `withheld` list (tables or columns) must be unreadable directly,
  through inheritance or partition descendants and ancestors (a parent returns its
  children's rows), and through any view or
  materialized view built on them, including whole-row references (security-invoker
  views excepted), and through generated columns computed from them. Verification queries pin `search_path` to `pg_catalog`. Checks use
  effective privileges, so a column grant or `pg_read_all_data` is refused. Keys are
  `table` (schema `public`) or `schema.table`. A withheld relation or column that does
  not exist fails closed, so update the list when a migration renames one.
  Any role membership is refused. A target with an unknown key is refused, so a
  misspelled safeguard such as `withold` fails instead of silently checking nothing.
- The check audits the login role itself: a session whose current role differs from
  the authenticated one (a persistent `SET role` setting) is refused, and the role
  SQL clears the role's persistent settings. Compiled support functions of any type
  or range count as executable even without `EXECUTE`, because reading or casting a
  value of that type calls them.
- The URL is passed to `psql` through libpq environment variables only, with inherited
  `PG*`/`DATABASE_URL` settings dropped. SQL containing a backslash is rejected, so
  psql meta-commands (`\!`, `\o |cmd`, `\copy ... program`) cannot start a local
  program that inherits the password. Use `chr(92)` for a literal backslash.
- Deployed connections must use `sslmode=require` (the default when omitted),
  `verify-ca` or `verify-full`; the latter two need `sslrootcert`. Railway's public TCP
  proxy serves a self-signed certificate, so `require` (encrypted, server not
  authenticated) is the practical baseline there; pin the exported root CA with
  `verify-ca` for authentication. Weaker modes are accepted only for loopback hosts.

- Query sessions set `search_path` to `public`, so an unqualified name never resolves in
  a schema another role controls, whatever the role's own `search_path` setting.
- `--timeout` (default 120 s) is enforced by interrupting `psql`, which sends a cancel
  request so the server stops the statement. The role's 30 s `statement_timeout` is
  only a default: a query can raise it with `set_config`, so the cancel is the bound.
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

1. Generate a pending credential:

   ```sh
   ~/.agents/bin/agents-sql prepare livx-production
   ```

   The new URL is kept pending in `~/.agents/local/credentials/<target>-pending.url`
   (mode 600); any current credential keeps working until step 3. The role SQL,
   with the password's SCRAM-SHA-256 verifier substituted, is written next to it as
   `~/.agents/local/credentials/<target>-readonly-role.sql` (mode 600); nothing secret
   is printed. The verifier cannot log in but allows offline password guessing, so
   keep that file private; step 3 deletes both files.
   Roles are cluster-wide: if this database shares a cluster with another registered
   target, prepare once and store that password for the other target with `set-url`.
2. Run that prepared copy of [`readonly-role.sql`](../../skills/database-query/references/readonly-role.sql)
   (one transaction; it covers schema `public`) as a superuser (Railway's `postgres`
   user is one). It creates a role and changes grants on objects other roles own,
   including a `pg_catalog` function, which neither database ownership nor
   `CREATEROLE` allows. It also clears the role's persistent settings: `pbcopy < FILE`
   and paste into the hosting provider's SQL console for that database (Railway:
   Postgres service → **Data** tab), or `psql OWNER_URL -f FILE`. It must run as a
   superuser or a member of every role that created default privileges naming
   `agent_readonly`; otherwise it names those roles and changes nothing. Project, environment, service IDs
   and public endpoints are in the project's private runbook (LivX:
   `~/git/livx/docs/database-migrations.md`). The script aborts on anything other
   than a verifier.
3. Verify and activate:

   ```sh
   ~/.agents/bin/agents-sql activate livx-production
   ```

   This runs the full role check with the pending URL, stores it in the credential
   file, and deletes the pending URL and prepared SQL. If the check fails, nothing
   changes. `agents-sql check TARGET` re-verifies the stored credential at any time.

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
  `<target>-readonly-role.sql` as the owner, then `agents-sql activate TARGET`. The old
  password works until the SQL runs and the stored URL changes only after `activate`
  verifies the new one, so queries in between fail for at most that gap.
- Revoke: `ALTER ROLE agent_readonly NOLOGIN;` (or `DROP OWNED BY agent_readonly; DROP ROLE agent_readonly;`)
  and delete the variable from the credential file.
- Add a database: add a target to `local/databases.json`, register its variable
  in the profile in `config/profiles.json` (or a new `postgres.*` profile), update
  `config/inventory.json`, regenerate the inventory docs, then do the owner setup.

## Personal data

`withheld` covers credentials and bearer codes. Emails, names, phone numbers and
addresses stay readable, and query results enter the agent's context (and the model
provider's logs). The skill tells agents to prefer aggregates and to select personal
fields only when the user asked for those records. To enforce more for a target:

- add personal columns to its `withheld` list and to the role SQL's
  `secret_columns`, then re-run the role SQL (agents can still count and join on ids);
- grant an audited view with the personal columns removed or hashed, instead of the
  base table; or
- create the role only on dev until production access is needed.

Recovery: the credential file is local only and not backed up in Git. If it is lost,
rotate the password and store the new URL.
