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
  col text;
  rel regclass;
  cols text;
  found text;
BEGIN
  FOR t IN SELECT unnest(secret_tables) UNION SELECT jsonb_object_keys(secret_columns) LOOP
    rel := to_regclass(format('public.%I', t));
    CONTINUE WHEN rel IS NULL;
    -- Child or parent tables carry the same rows without these restrictions.
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

  -- Verify the end state as agent_readonly sees it (direct, PUBLIC and inherited
  -- grants). Any failure rolls back the whole script, password included.
  FOREACH t IN ARRAY secret_tables LOOP
    rel := to_regclass(format('public.%I', t));
    IF rel IS NOT NULL AND has_any_column_privilege('agent_readonly', rel, 'SELECT') THEN
      RAISE EXCEPTION 'agent_readonly can still read % (a grant to PUBLIC?); revoke it and re-run.', rel;
    END IF;
  END LOOP;
  FOR t, col IN SELECT k, jsonb_array_elements_text(secret_columns -> k) FROM jsonb_object_keys(secret_columns) k LOOP
    rel := to_regclass(format('public.%I', t));
    IF rel IS NOT NULL AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = rel AND a.attname = col AND NOT a.attisdropped)
        AND has_column_privilege('agent_readonly', rel, col, 'SELECT') THEN
      RAISE EXCEPTION 'agent_readonly can still read %.% (a grant to PUBLIC?); revoke it and re-run.', rel, col;
    END IF;
  END LOOP;
  -- Only base tables in public: views run with their owner's privileges and could
  -- expose withheld columns, and other schemas are out of scope.
  SELECT string_agg(c.oid::regclass::text, ', ') INTO found FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname !~ '^pg_(toast|temp_|toast_temp_)'
      AND c.relkind IN ('r', 'p', 'v', 'm', 'f') AND (n.nspname <> 'public' OR c.relkind IN ('v', 'm', 'f'))
      AND has_schema_privilege('agent_readonly', n.oid, 'USAGE')
      AND has_any_column_privilege('agent_readonly', c.oid, 'SELECT');
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'agent_readonly can read views or relations outside public: % (grants to PUBLIC?); revoke them and re-run.', found;
  END IF;
  -- Privileges that act outside a read-only transaction: TRIGGER and MAINTAIN on tables
  -- (17+), configuration parameters such as ALTER SYSTEM (15+), large-object UPDATE.
  SELECT string_agg(c.oid::regclass::text, ', ') INTO found FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname !~ '^pg_(toast|temp_|toast_temp_)' AND c.relkind IN ('r', 'p', 'm', 'v', 'f')
      AND has_table_privilege('agent_readonly', c.oid, 'TRIGGER');
  IF found IS NULL AND current_setting('server_version_num')::int >= 170000 THEN
    EXECUTE $q$SELECT string_agg(c.oid::regclass::text, ', ') FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname !~ '^pg_(toast|temp_|toast_temp_)' AND c.relkind IN ('r', 'p', 'm')
        AND has_table_privilege('agent_readonly', c.oid, 'MAINTAIN')$q$ INTO found;
  END IF;
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'agent_readonly has TRIGGER or MAINTAIN on: % (grants to PUBLIC?); revoke them and re-run.', found;
  END IF;
  IF current_setting('server_version_num')::int >= 150000 THEN
    EXECUTE $q$SELECT string_agg(p.parname, ', ') FROM pg_parameter_acl p, aclexplode(p.paracl) a
      WHERE a.grantee IN ('agent_readonly'::regrole, 0)$q$ INTO found;
    IF found IS NOT NULL THEN
      RAISE EXCEPTION 'agent_readonly or PUBLIC holds configuration parameter privileges on: %; revoke them and re-run.', found;
    END IF;
  END IF;
  FOR found IN SELECT l.oid::text FROM pg_largeobject_metadata l, aclexplode(l.lomacl) a
      WHERE a.grantee = 'agent_readonly'::regrole LOOP
    EXECUTE format('REVOKE ALL ON LARGE OBJECT %s FROM agent_readonly', found);
  END LOOP;
  IF current_setting('lo_compat_privileges')::bool OR EXISTS (SELECT 1 FROM pg_largeobject_metadata l, aclexplode(l.lomacl) a
      WHERE a.grantee = 0 AND a.privilege_type = 'UPDATE') THEN
    RAISE EXCEPTION 'Every role can write some large objects (PUBLIC UPDATE grant or lo_compat_privileges); revoke and re-run.';
  END IF;
  -- SECURITY DEFINER functions run with their owner's privileges and could return secrets.
  SELECT string_agg(p.oid::regprocedure::text, ', ') INTO found FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE p.prosecdef AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND has_function_privilege('agent_readonly', p.oid, 'EXECUTE');
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'agent_readonly can run SECURITY DEFINER functions: %; revoke EXECUTE from PUBLIC on them and re-run.', found;
  END IF;
END $$;

COMMIT;
