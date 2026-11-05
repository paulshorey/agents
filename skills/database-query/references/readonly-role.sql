-- Create a dedicated read-only login for AI agents. Run once per database as its
-- owner (Railway's `postgres` user), for example in Railway's Postgres "Data" tab
-- or with psql using that database's DATABASE_PUBLIC_URL.
--
-- Replace REPLACE_WITH_GENERATED_PASSWORD with a new random password (for example
-- from `openssl rand -base64 32 | tr -d '/+='`). Never reuse the owner password.
-- Re-running is safe: it updates the password and grants.

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

-- Read every table, then withhold credentials and bearer codes.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO agent_readonly;
DO $$
DECLARE
  secret_tables text[] := ARRAY['user_auth_tokens', 'password_reset_tokens'];
  -- table => columns agents must not read
  secret_columns jsonb := '{"users": ["password", "api_token"], "device_push_tokens": ["token"],
    "membership_offers": ["code"], "get_deals": ["qr_token"]}';
  t text;
  cols text;
BEGIN
  FOREACH t IN ARRAY secret_tables LOOP
    IF to_regclass('public.' || quote_ident(t)) IS NOT NULL THEN
      EXECUTE format('REVOKE ALL ON public.%I FROM agent_readonly', t);
    END IF;
  END LOOP;
  FOR t IN SELECT jsonb_object_keys(secret_columns) LOOP
    IF to_regclass('public.' || quote_ident(t)) IS NOT NULL THEN
      SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position) INTO cols
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = t
          AND column_name NOT IN (SELECT jsonb_array_elements_text(secret_columns -> t));
      EXECUTE format('REVOKE ALL ON public.%I FROM agent_readonly', t);
      EXECUTE format('GRANT SELECT (%s) ON public.%I TO agent_readonly', cols, t);
    END IF;
  END LOOP;
END $$;

-- Verify: should list only SELECT, and none of the withheld tables.
SELECT table_name, privilege_type FROM information_schema.table_privileges
WHERE grantee = 'agent_readonly' ORDER BY 1, 2;
