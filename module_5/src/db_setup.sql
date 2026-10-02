-- One-time PostgreSQL provisioning for Module 5 (least privilege).
-- Run as a PostgreSQL superuser, from this folder (setup_db.sh / setup_db.bat do this):
--
--   psql -U postgres -h localhost -f db_setup.sql
--
-- Two NON-superuser roles are created, so the web app never holds more power than it needs:
--
--   gradcafe_m5_owner  owns the databases and the applicants table. Used only for schema
--                      work (this script, `load_data.py --reset`) and by the test suite,
--                      which empties and refills a scratch database.
--   gradcafe_m5_app    the role the Flask app and the command-line tools log in as.
--                      Allowed: CONNECT, USAGE on the public schema, SELECT, INSERT, and
--                      UPDATE on just the two LLM columns. Nothing else: no DROP, ALTER,
--                      TRUNCATE, DELETE or CREATE, and no ownership of anything.
--
-- Passwords are read from the environment (DB_OWNER_PASSWORD and DB_PASSWORD), never
-- stored in this file. The script is safe to re-run: it re-syncs passwords and re-applies
-- the grants.

\set ON_ERROR_STOP on
\getenv owner_password DB_OWNER_PASSWORD
\getenv app_password DB_PASSWORD

\if :{?owner_password}
\else
    \echo 'Set DB_OWNER_PASSWORD (in your shell or in module_5/.env) first.'
    \quit
\endif
\if :{?app_password}
\else
    \echo 'Set DB_PASSWORD (in your shell or in module_5/.env) first.'
    \quit
\endif

-- ---- 1. Roles ------------------------------------------------------------------------
SELECT 'CREATE ROLE gradcafe_m5_owner LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gradcafe_m5_owner') \gexec
ALTER ROLE gradcafe_m5_owner
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    PASSWORD :'owner_password';

SELECT 'CREATE ROLE gradcafe_m5_app LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gradcafe_m5_app') \gexec
ALTER ROLE gradcafe_m5_app
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    PASSWORD :'app_password';

-- ---- 2. Databases: the real one and a scratch one for the automated tests --------------
SELECT 'CREATE DATABASE gradcafe_m5 OWNER gradcafe_m5_owner'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'gradcafe_m5') \gexec
SELECT 'CREATE DATABASE gradcafe_m5_test OWNER gradcafe_m5_owner'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'gradcafe_m5_test') \gexec

-- Nobody may connect unless granted; the app role may connect and nothing more.
REVOKE ALL ON DATABASE gradcafe_m5 FROM PUBLIC;
REVOKE ALL ON DATABASE gradcafe_m5_test FROM PUBLIC;
REVOKE ALL ON DATABASE gradcafe_m5 FROM gradcafe_m5_app;
REVOKE ALL ON DATABASE gradcafe_m5_test FROM gradcafe_m5_app;
GRANT CONNECT ON DATABASE gradcafe_m5 TO gradcafe_m5_app;
GRANT CONNECT ON DATABASE gradcafe_m5_test TO gradcafe_m5_app;

-- ---- 3. Table and grants, identical in both databases ----------------------------------
\connect gradcafe_m5
\ir db_privileges.sql
\connect gradcafe_m5_test
\ir db_privileges.sql

\echo 'Module 5 database setup finished.'
