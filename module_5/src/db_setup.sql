-- One-time PostgreSQL setup (Modules 3-4). Run as the PostgreSQL superuser:
--
--   psql -U postgres -h localhost -f db_setup.sql
--
-- The application role's password is read from the GRADCAFE_APP_PASSWORD environment
-- variable (the same password you put in DATABASE_URL), so no secret is stored in this
-- file. The script is safe to re-run.

\getenv app_password GRADCAFE_APP_PASSWORD

-- Application role (created if missing; password always synced to the variable)
SELECT 'CREATE ROLE gradcafe_app LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gradcafe_app') \gexec
ALTER ROLE gradcafe_app PASSWORD :'app_password';

-- Real database and a scratch database used only by the automated tests
SELECT 'CREATE DATABASE gradcafe OWNER gradcafe_app'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'gradcafe') \gexec
SELECT 'CREATE DATABASE gradcafe_test OWNER gradcafe_app'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'gradcafe_test') \gexec
