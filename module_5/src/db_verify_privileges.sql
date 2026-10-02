-- Show what the least-privilege role can and cannot do (evidence for the report).
-- Run as any role that can read the catalogs, connected to the real database:
--
--   psql -U gradcafe_m5_owner -h localhost -d gradcafe_m5 -f db_verify_privileges.sql

\echo '--- 1. Role attributes: neither role is a superuser and neither can create roles or databases'
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls
FROM pg_roles
WHERE rolname IN ('gradcafe_m5_owner', 'gradcafe_m5_app')
ORDER BY rolname;

\echo '--- 2. Table-level privileges held by gradcafe_m5_app on applicants (expect SELECT, INSERT)'
SELECT privilege_type
FROM information_schema.role_table_grants
WHERE table_name = 'applicants' AND grantee = 'gradcafe_m5_app'
ORDER BY privilege_type;

\echo '--- 3. Which columns can gradcafe_m5_app UPDATE (expect only the two llm_* columns)'
SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'applicants'
  AND has_column_privilege('gradcafe_m5_app', 'public.applicants', column_name, 'UPDATE')
ORDER BY ordinal_position;

\echo '--- 4. Owner-only operations (expect f for every row)'
SELECT p.privilege,
       has_table_privilege('gradcafe_m5_app', 'public.applicants', p.privilege) AS app_has_it
FROM (VALUES ('DELETE'), ('TRUNCATE'), ('REFERENCES'), ('TRIGGER')) AS p(privilege);
SELECT 'CREATE on schema public' AS privilege,
       has_schema_privilege('gradcafe_m5_app', 'public', 'CREATE') AS app_has_it;
SELECT 'owns the applicants table' AS privilege,
       (SELECT tableowner FROM pg_tables WHERE tablename = 'applicants') = 'gradcafe_m5_app'
           AS app_has_it;
