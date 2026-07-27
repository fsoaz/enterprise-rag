-- Runs once on first Postgres volume init (superuser).
-- Creates app roles, grants, and extensions. Schema comes from Alembic.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rag_migrate') THEN
    CREATE ROLE rag_migrate LOGIN PASSWORD 'rag_migrate' BYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rag_app') THEN
    CREATE ROLE rag_app LOGIN PASSWORD 'rag_app' NOSUPERUSER NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rag_maint') THEN
    CREATE ROLE rag_maint LOGIN PASSWORD 'rag_maint' NOSUPERUSER NOBYPASSRLS;
  END IF;
END
$$;

-- The same bootstrap is used for the disposable integration database. Resolve
-- the current database rather than granting only the development database name.
DO $$
BEGIN
  EXECUTE format(
    'GRANT CONNECT ON DATABASE %I TO rag_migrate, rag_app, rag_maint',
    current_database()
  );
END
$$;
GRANT USAGE, CREATE ON SCHEMA public TO rag_migrate;
GRANT USAGE ON SCHEMA public TO rag_app, rag_maint;

-- Future tables created by rag_migrate inherit usable defaults for app roles.
ALTER DEFAULT PRIVILEGES FOR ROLE rag_migrate IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO rag_app;
ALTER DEFAULT PRIVILEGES FOR ROLE rag_migrate IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO rag_app;
ALTER DEFAULT PRIVILEGES FOR ROLE rag_migrate IN SCHEMA public
  GRANT SELECT ON TABLES TO rag_maint;

ALTER ROLE rag_migrate SET search_path TO public;
ALTER ROLE rag_app SET search_path TO public;
ALTER ROLE rag_maint SET search_path TO public;
