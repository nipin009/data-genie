-- Development Docker role. The API must not use the Postgres bootstrap superuser.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datagenie_app') THEN
    CREATE ROLE datagenie_app LOGIN PASSWORD 'datagenie_app' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
END
$$;

GRANT CONNECT ON DATABASE datagenie TO datagenie_app;
GRANT USAGE ON SCHEMA public TO datagenie_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO datagenie_app;
ALTER DEFAULT PRIVILEGES FOR ROLE datagenie IN SCHEMA public GRANT SELECT ON TABLES TO datagenie_app;
