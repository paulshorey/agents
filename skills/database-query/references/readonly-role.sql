-- Create or update `agent_readonly`, the login AI agents use through agents-sql.
-- It can SELECT tables in schema public and nothing else; credential and bearer-code
-- tables and columns are withheld below (LivX names; edit the lists for other
-- projects).
--
-- Do not run this template directly: `agents-sql prepare TARGET` writes a private,
-- ready-to-run copy to ~/.agents/local/credentials/TARGET-readonly-role.sql with the
-- new password's SCRAM-SHA-256 verifier in place of REPLACE_WITH_SCRAM_VERIFIER, so
-- the cleartext password never reaches the server or its logs. Run that copy as a
-- superuser (Railway: the `postgres` user, in the Postgres service's Data tab or with
-- psql), then `agents-sql activate TARGET`.
--
-- Re-running is safe: it resets the password, settings and grants. Re-run it after
-- migrations add tables (only tables that exist now are granted) or secrets.
-- Roles are cluster-wide; on Railway each Postgres service is its own cluster.

BEGIN;
-- Resolve unqualified names in the catalogs only while running as a superuser.
SET LOCAL search_path TO pg_catalog, pg_temp;
SET LOCAL agents.readonly_verifier = 'REPLACE_WITH_SCRAM_VERIFIER';

DO $$
DECLARE verifier text := current_setting('agents.readonly_verifier');
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this as a superuser (Railway: the postgres user).';
  END IF;
  -- PostgreSQL 14 (and clusters upgraded from it) lets PUBLIC create in schema public,
  -- which agents-sql refuses; stop before changing anything.
  IF has_schema_privilege('public', 'public', 'CREATE') THEN
    RAISE EXCEPTION 'PUBLIC can create objects in schema public (PostgreSQL 14 default). Grant CREATE to the application roles that need it, run REVOKE CREATE ON SCHEMA public FROM PUBLIC, then re-run this script.';
  END IF;
  IF verifier !~ '^SCRAM-SHA-256\$[0-9]+:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+$' THEN
    RAISE EXCEPTION 'Run the copy that agents-sql prepare wrote, not this template (it needs a SCRAM verifier, never a cleartext password).';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_readonly') THEN
    CREATE ROLE agent_readonly LOGIN;
  END IF;
  EXECUTE format('ALTER ROLE agent_readonly WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION '
    'NOBYPASSRLS CONNECTION LIMIT 5 PASSWORD %L', verifier);
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO agent_readonly', current_database());
END $$;

-- Clear stale settings (a persistent `SET role` would make the login act as another role).
ALTER ROLE agent_readonly RESET ALL;
DO $$ BEGIN EXECUTE format('ALTER ROLE agent_readonly IN DATABASE %I RESET ALL', current_database()); END $$;
ALTER ROLE agent_readonly SET default_transaction_read_only = on;
ALTER ROLE agent_readonly SET statement_timeout = '30s';
ALTER ROLE agent_readonly SET idle_in_transaction_session_timeout = '60s';

-- SELECT on base tables only. Views run with their owner's privileges and could
-- expose withheld columns, so grant an audited view explicitly if one is needed.
-- Clear any earlier grants (table, column and sequence level) in every schema first.
DO $$
DECLARE
  nsp text;
  rel regclass;
  cols text;
BEGIN
  FOR nsp IN SELECT nspname FROM pg_namespace
      WHERE nspname NOT IN ('pg_catalog', 'information_schema') AND nspname !~ '^pg_(toast|temp_|toast_temp_)' LOOP
    EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM agent_readonly', nsp);
    EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM agent_readonly', nsp);
    IF nsp <> 'public' THEN
      EXECUTE format('REVOKE ALL ON SCHEMA %I FROM agent_readonly', nsp);
    END IF;
  END LOOP;
  FOR rel, cols IN SELECT a.attrelid::regclass, string_agg(quote_ident(a.attname), ', ')
      FROM pg_attribute a WHERE a.attacl IS NOT NULL AND a.attnum > 0 AND NOT a.attisdropped
      GROUP BY a.attrelid LOOP
    EXECUTE format('REVOKE ALL (%s) ON %s FROM agent_readonly', cols, rel);
  END LOOP;
END $$;
GRANT USAGE ON SCHEMA public TO agent_readonly;
DO $$
DECLARE rel regclass;
BEGIN
  FOR rel IN SELECT c.oid::regclass FROM pg_class c
      WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p') LOOP
    EXECUTE format('GRANT SELECT ON %s TO agent_readonly', rel);
  END LOOP;
END $$;

-- Withhold credentials and bearer codes: whole tables, then columns.
DO $$
DECLARE
  secret_tables text[] := ARRAY['user_auth_tokens', 'password_reset_tokens'];
  secret_columns jsonb := '{"users": ["password", "api_token"], "device_push_tokens": ["token"],
    "membership_offers": ["code"], "get_deals": ["qr_token"]}';
  t text;
  rel regclass;
  cols text;
BEGIN
  FOR t IN SELECT unnest(secret_tables) UNION SELECT jsonb_object_keys(secret_columns) LOOP
    rel := to_regclass(format('public.%I', t));
    CONTINUE WHEN rel IS NULL;
    -- A PUBLIC grant or a parent/child table would still expose the secrets.
    IF has_any_column_privilege('public', rel, 'SELECT') THEN
      RAISE EXCEPTION 'PUBLIC can read %, which holds secrets; revoke that grant and re-run.', rel;
    END IF;
    -- Views run with their owner's privileges, so a PUBLIC-readable view over it leaks too.
    IF EXISTS (SELECT 1 FROM pg_depend d JOIN pg_rewrite w ON d.classid = 'pg_rewrite'::regclass AND d.objid = w.oid
        WHERE d.refclassid = 'pg_class'::regclass AND d.refobjid = rel AND w.ev_class <> rel
          AND has_any_column_privilege('public', w.ev_class, 'SELECT')) THEN
      RAISE EXCEPTION 'A view over % is readable by PUBLIC; revoke that grant and re-run.', rel;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_inherits WHERE inhrelid = rel OR inhparent = rel) THEN
      RAISE EXCEPTION '% has inheritance or partition relatives; extend this script to withhold its secrets there.', rel;
    END IF;
  END LOOP;
  FOREACH t IN ARRAY secret_tables LOOP
    rel := to_regclass(format('public.%I', t));
    IF rel IS NOT NULL THEN
      EXECUTE format('REVOKE ALL ON %s FROM agent_readonly', rel);
    END IF;
  END LOOP;
  FOR t IN SELECT jsonb_object_keys(secret_columns) LOOP
    rel := to_regclass(format('public.%I', t));
    CONTINUE WHEN rel IS NULL;
    SELECT string_agg(quote_ident(a.attname), ', ' ORDER BY a.attnum) INTO cols FROM pg_attribute a
      WHERE a.attrelid = rel AND a.attnum > 0 AND NOT a.attisdropped
        AND a.attname NOT IN (SELECT jsonb_array_elements_text(secret_columns -> t))
        AND a.attgenerated = '';  -- a generated column may be computed from a secret
    EXECUTE format('REVOKE ALL ON %s FROM agent_readonly', rel);
    IF cols IS NOT NULL THEN
      EXECUTE format('GRANT SELECT (%s) ON %s TO agent_readonly', cols, rel);
    END IF;
  END LOOP;
END $$;

COMMIT;
