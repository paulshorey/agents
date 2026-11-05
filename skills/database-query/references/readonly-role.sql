-- Create a dedicated read-only login for AI agents. Run once per database as a
-- superuser (Railway's `postgres` user is one): it creates a role and changes
-- grants on objects other roles own, including a pg_catalog function, which neither
-- database ownership nor CREATEROLE allows. Run it, for example, in
-- Railway's Postgres "Data" tab or with psql using that database's DATABASE_PUBLIC_URL.
--
-- Do not edit this template: `agents-sql prepare TARGET` keeps a new connection URL
-- pending privately and writes a ready-to-run copy, with the password's SCRAM-SHA-256
-- verifier in place of REPLACE_WITH_SCRAM_VERIFIER, to
-- ~/.agents/local/credentials/TARGET-readonly-role.sql. Only the verifier reaches the
-- server, so statement logging never records a usable password. The script aborts
-- on anything else. Afterwards `agents-sql activate TARGET` verifies and stores it.
-- Re-running is safe: it updates the password and grants. Re-run it after
-- migrations add tables: only base tables that exist now are granted.
--
-- Roles are cluster-wide. If two registered databases share one PostgreSQL
-- cluster, they share this role and password: reuse the existing password (or
-- update every affected stored URL together) instead of generating a new one.
-- On Railway each Postgres service is its own cluster.
-- Keep the withheld tables/columns below in sync with the target's `withheld`
-- list in local/databases.json; agents-sql refuses a role that can read them.
-- Everything runs in one transaction: any error leaves the previous grants intact.

BEGIN;
-- Resolve every unqualified name in the catalogs, never in a schema another role
-- can write to, while this runs with role-management privileges.
SET LOCAL search_path TO pg_catalog, pg_temp;

SET LOCAL agents.readonly_verifier = 'REPLACE_WITH_SCRAM_VERIFIER';

DO $$
DECLARE secret text := current_setting('agents.readonly_verifier');
BEGIN
  IF secret !~ '^SCRAM-SHA-256\$[0-9]+:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+$' THEN
    RAISE EXCEPTION 'Set agents.readonly_verifier to the SCRAM-SHA-256 verifier from agents-sql prepare (run its prepared role SQL file, never a cleartext password)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = current_user AND rolsuper) THEN
    RAISE EXCEPTION 'Run this as a superuser (Railway: the postgres user). It creates a role and changes grants on objects other roles own, which neither database ownership nor CREATEROLE allows.';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_readonly') THEN
    CREATE ROLE agent_readonly LOGIN;
  END IF;
  EXECUTE format('ALTER ROLE agent_readonly WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION '
    'NOBYPASSRLS CONNECTION LIMIT 5 PASSWORD %L', secret);
END $$;
-- Clear every persistent setting (a stale `SET role` would make the login act as
-- another role) before setting the ones this role needs.
ALTER ROLE agent_readonly RESET ALL;
DO $$ BEGIN EXECUTE format('ALTER ROLE agent_readonly IN DATABASE %I RESET ALL', current_database()); END $$;
ALTER ROLE agent_readonly SET default_transaction_read_only = on;
ALTER ROLE agent_readonly SET statement_timeout = '30s';
ALTER ROLE agent_readonly SET idle_in_transaction_session_timeout = '60s';

DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO agent_readonly', current_database()); END $$;
-- Roles are cluster-wide and PUBLIC can connect to every database by default.
-- agents-sql refuses the role while it can connect to another database that the
-- target does not list in other_databases; name them here so the owner can decide.
DO $$
DECLARE others text;
BEGIN
  SELECT string_agg(datname, ', ' ORDER BY datname) INTO others FROM pg_database
    WHERE datallowconn AND datname <> current_database()
      AND has_database_privilege('agent_readonly', oid, 'CONNECT');
  IF others IS NOT NULL THEN
    RAISE NOTICE 'agent_readonly can also connect to: %. Revoke CONNECT on them from PUBLIC (grant it to the roles that need it), or audit them and list them in the target''s other_databases.', others;
  END IF;
END $$;
GRANT USAGE ON SCHEMA public TO agent_readonly;
-- PostgreSQL 15+ denies CREATE on schema public to PUBLIC. On an older or upgraded
-- database PUBLIC may still have it; agents-sql refuses such a role, and revoking it
-- here would also affect application roles, so stop and let the owner decide.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_namespace n, aclexplode(n.nspacl) a
      WHERE n.nspname = 'public' AND a.grantee = 0 AND a.privilege_type = 'CREATE') THEN
    RAISE EXCEPTION 'PUBLIC can create objects in schema public. Grant CREATE explicitly to the application roles that need it, run REVOKE CREATE ON SCHEMA public FROM PUBLIC, then re-run this script.';
  END IF;
END $$;
-- Non-transactional WAL messages survive a rollback, and PUBLIC can execute this
-- built-in by default. Every existing role keeps its current access through an
-- explicit grant; only agent_readonly (and roles created later) lose it.
DO $$
DECLARE
  f regprocedure;
  other name;
BEGIN
  FOR f IN SELECT p.oid::regprocedure FROM pg_proc p WHERE p.proname = 'pg_logical_emit_message'
    AND p.pronamespace = 'pg_catalog'::regnamespace
    AND has_function_privilege('public', p.oid, 'EXECUTE') LOOP
    FOR other IN SELECT rolname FROM pg_roles
      WHERE rolname <> 'agent_readonly' AND rolname !~ '^pg_' LOOP
      EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO %I', f, other);
    END LOOP;
    EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC', f);
  END LOOP;
END $$;

-- Read base tables (and partitions) only. Views and materialized views run with
-- their owner's privileges and can expose withheld columns, so they are not
-- granted; grant an audited view explicitly. No default privileges are kept, so
-- future tables (and views) stay unreadable until this script is re-run.
-- Clear default privileges naming this role for every creator, global or per schema.
-- Changing another role's defaults requires membership in it (or superuser).
DO $$
DECLARE
  d record;
  missing text;
BEGIN
  SELECT string_agg(DISTINCT pg_get_userbyid(da.defaclrole), ', ') INTO missing
    FROM pg_default_acl da, aclexplode(da.defaclacl) a
    WHERE a.grantee = 'agent_readonly'::regrole AND NOT pg_has_role(current_user, da.defaclrole, 'MEMBER');
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION 'Default privileges for agent_readonly were created by %. Run this script as a superuser or a member of those roles.', missing;
  END IF;
  FOR d IN SELECT pg_get_userbyid(da.defaclrole) AS owner, da.defaclnamespace::regnamespace AS nsp,
      CASE da.defaclobjtype WHEN 'r' THEN 'TABLES' WHEN 'S' THEN 'SEQUENCES' WHEN 'f' THEN 'FUNCTIONS'
        WHEN 'T' THEN 'TYPES' WHEN 'n' THEN 'SCHEMAS' WHEN 'L' THEN 'LARGE OBJECTS' END AS kind
    FROM pg_default_acl da, aclexplode(da.defaclacl) a
    WHERE a.grantee = 'agent_readonly'::regrole
  LOOP
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I %s REVOKE ALL ON %s FROM agent_readonly',
      d.owner, CASE WHEN d.nsp::oid = 0 THEN '' ELSE format('IN SCHEMA %I', d.nsp) END, d.kind);
  END LOOP;
END $$;
DO $$
DECLARE rel regclass;
BEGIN
  FOR rel IN SELECT c.oid::regclass FROM pg_class c
    WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('v', 'm') LOOP
    EXECUTE format('REVOKE ALL ON %s FROM agent_readonly', rel);
  END LOOP;
  FOR rel IN SELECT c.oid::regclass FROM pg_class c
    WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p') LOOP
    -- Drop any stale grant (table and column level) before granting SELECT.
    EXECUTE format('REVOKE ALL ON %s FROM agent_readonly', rel);
    EXECUTE format('GRANT SELECT ON %s TO agent_readonly', rel);
  END LOOP;
END $$;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM agent_readonly;
-- Large objects cannot be withheld individually; drop any grant to this role.
DO $$
DECLARE lo oid;
BEGIN
  FOR lo IN SELECT l.oid FROM pg_largeobject_metadata l, aclexplode(l.lomacl) a
    WHERE a.grantee = 'agent_readonly'::regrole LOOP
    EXECUTE format('REVOKE ALL ON LARGE OBJECT %s FROM agent_readonly', lo);
  END LOOP;
END $$;
REVOKE ALL ON ALL ROUTINES IN SCHEMA public FROM agent_readonly;

-- Withhold credentials and bearer codes on each table, every inheritance or
-- partition descendant (children have their own grants) and every ancestor
-- (querying a parent returns its children's rows).
DO $$
DECLARE
  secret_tables text[] := ARRAY['user_auth_tokens', 'password_reset_tokens'];
  -- table => columns agents must not read
  secret_columns jsonb := '{"users": ["password", "api_token"], "device_push_tokens": ["token"],
    "membership_offers": ["code"], "get_deals": ["qr_token"]}';
  t text;
  rel regclass;
  cols text;
BEGIN
  FOR t IN SELECT unnest(secret_tables) UNION SELECT jsonb_object_keys(secret_columns) LOOP
    IF to_regclass('public.' || quote_ident(t)) IS NULL THEN
      CONTINUE;
    END IF;
    FOR rel IN WITH RECURSIVE
        down(oid) AS (SELECT to_regclass('public.' || quote_ident(t))::oid
          UNION SELECT i.inhrelid FROM pg_inherits i JOIN down ON i.inhparent = down.oid),
        up(oid) AS (SELECT to_regclass('public.' || quote_ident(t))::oid
          UNION SELECT i.inhparent FROM pg_inherits i JOIN up ON i.inhrelid = up.oid)
      SELECT oid::regclass FROM down UNION SELECT oid::regclass FROM up LOOP
      EXECUTE format('REVOKE ALL ON %s FROM agent_readonly', rel);
      IF secret_columns ? t THEN
        -- Skip the secret columns and any generated column computed from them.
        SELECT string_agg(quote_ident(a.attname), ', ' ORDER BY a.attnum) INTO cols
          FROM pg_attribute a
          WHERE a.attrelid = rel AND a.attnum > 0 AND NOT a.attisdropped
            AND a.attname NOT IN (SELECT jsonb_array_elements_text(secret_columns -> t))
            AND NOT EXISTS (
              SELECT 1 FROM pg_attrdef ad
                JOIN pg_depend d ON d.classid = 'pg_attrdef'::regclass AND d.objid = ad.oid
                  AND d.refclassid = 'pg_class'::regclass AND d.refobjid = rel
                JOIN pg_attribute src ON src.attrelid = rel AND src.attnum = d.refobjsubid
              WHERE ad.adrelid = rel AND ad.adnum = a.attnum AND a.attgenerated <> ''
                AND src.attname IN (SELECT jsonb_array_elements_text(secret_columns -> t)));
        IF cols IS NOT NULL THEN
          EXECUTE format('GRANT SELECT (%s) ON %s TO agent_readonly', cols, rel);
        END IF;
      END IF;
    END LOOP;
  END LOOP;
END $$;

-- Verify: should list only SELECT, and none of the withheld tables.
SELECT table_name, privilege_type FROM information_schema.table_privileges
WHERE grantee = 'agent_readonly' ORDER BY 1, 2;

COMMIT;
