-- Demonstrate that the least-privilege role is refused everything destructive or owner-only.
-- Run it AS THE APPLICATION ROLE, against the SCRATCH database:
--
--   psql -U gradcafe_m5_app -h localhost -d gradcafe_m5_test -f db_demo_refusals.sql
--
-- Every statement is wrapped in BEGIN ... ROLLBACK, so even if a privilege were ever
-- misconfigured nothing could be changed. Each of the statements below is EXPECTED to fail
-- with "permission denied" or "must be owner"; the SELECT at the end is expected to work.

\set ON_ERROR_STOP off
\pset pager off

SELECT current_user AS connected_as, current_database() AS database;

\echo
\echo '>>> DROP TABLE applicants'
BEGIN; DROP TABLE applicants; ROLLBACK;

\echo '>>> ALTER TABLE applicants ADD COLUMN extra TEXT'
BEGIN; ALTER TABLE applicants ADD COLUMN extra TEXT; ROLLBACK;

\echo '>>> TRUNCATE applicants'
BEGIN; TRUNCATE applicants; ROLLBACK;

\echo '>>> DELETE FROM applicants'
BEGIN; DELETE FROM applicants; ROLLBACK;

\echo '>>> UPDATE applicants SET status = ''hacked''   (only the two llm_* columns are updatable)'
BEGIN; UPDATE applicants SET status = 'hacked'; ROLLBACK;

\echo '>>> CREATE TABLE evil (id INT)'
BEGIN; CREATE TABLE evil (id INT); ROLLBACK;

\echo '>>> CREATE ROLE evil LOGIN'
BEGIN; CREATE ROLE evil LOGIN; ROLLBACK;

\echo
\echo '>>> SELECT count(*) FROM applicants   (allowed)'
SELECT count(*) AS rows_visible FROM applicants;
