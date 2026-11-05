-- Create a dedicated read-only login for AI agents. Run once per database as its
-- owner (Railway's `postgres` user), for example in Railway's Postgres "Data" tab
-- or with psql using that database's DATABASE_PUBLIC_URL.
--
-- Replace REPLACE_WITH_GENERATED_PASSWORD with a new random password (for example
-- from `openssl rand -base64 32 | tr -d '/+='`). Never reuse the owner password.
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

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_readonly') THEN
    CREATE ROLE agent_readonly LOGIN;
  END IF;
END $$;
ALTER ROLE agent_readonly WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
  CONNECTION LIMIT 5 PASSWORD 'REPLACE_WITH_GENERATED_PASSWORD';
ALTER ROLE agent_readonly SET default_transaction_read_only = on;
ALTER ROLE agent_readonly SET statement_timeout = '30s';
ALTER ROLE agent_readonly SET idle_in_transaction_session_timeout = '60s';

DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO agent_readonly', current_database()); END $$;
GRANT USAGE ON SCHEMA public TO agent_readonly;
-- PostgreSQL 15+ already denies this to PUBLIC; agents-sql refuses roles that can create.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
-- Non-transactional WAL messages survive a rollback. PUBLIC can execute this
-- built-in by default; the owner/superuser application connection is unaffected.
DO $$
DECLARE f regprocedure;
BEGIN
  FOR f IN SELECT oid::regprocedure FROM pg_proc WHERE proname = 'pg_logical_emit_message'
    AND pronamespace = 'pg_catalog'::regnamespace LOOP
    EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC', f);
  END LOOP;
END $$;

-- Read base tables (and partitions) only. Views and materialized views run with
-- their owner's privileges and can expose withheld columns, so they are not
-- granted; grant an audited view explicitly. No default privileges are kept, so
-- future tables (and views) stay unreadable until this script is re-run.
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM agent_readonly;
DO $$
DECLARE rel regclass;
BEGIN
  FOR rel IN SELECT c.oid::regclass FROM pg_class c
    WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('v', 'm') LOOP
    EXECUTE format('REVOKE ALL ON %s FROM agent_readonly', rel);
  END LOOP;
  FOR rel IN SELECT c.oid::regclass FROM pg_class c
    WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p') LOOP
    EXECUTE format('GRANT SELECT ON %s TO agent_readonly', rel);
  END LOOP;
END $$;

-- Withhold credentials and bearer codes on each table and every inheritance or
-- partition descendant (children have their own grants).
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
    FOR rel IN WITH RECURSIVE tree(oid) AS (
        SELECT to_regclass('public.' || quote_ident(t))::oid
        UNION SELECT i.inhrelid FROM pg_inherits i JOIN tree ON i.inhparent = tree.oid)
      SELECT oid::regclass FROM tree LOOP
      EXECUTE format('REVOKE ALL ON %s FROM agent_readonly', rel);
      IF secret_columns ? t THEN
        SELECT string_agg(quote_ident(a.attname), ', ' ORDER BY a.attnum) INTO cols
          FROM pg_attribute a
          WHERE a.attrelid = rel AND a.attnum > 0 AND NOT a.attisdropped
            AND a.attname NOT IN (SELECT jsonb_array_elements_text(secret_columns -> t));
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
