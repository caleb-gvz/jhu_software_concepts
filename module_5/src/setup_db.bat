@echo off
rem One-time PostgreSQL provisioning for Windows (double-click this file).
rem Creates the non-superuser roles gradcafe_m5_owner and gradcafe_m5_app, the
rem gradcafe_m5 / gradcafe_m5_test databases, the applicants table and the
rem least-privilege grants by running db_setup.sql.
rem You will be asked for the password of the PostgreSQL "postgres" superuser.
rem The two role passwords are read from DB_PASSWORD (app role) and DB_OWNER_PASSWORD
rem (owner role) in your environment, or from the git-ignored module_5\.env file.
rem psql is taken from PATH unless PSQL is set.
cd /d "%~dp0"

if not defined PSQL set PSQL=psql
if not defined DB_PASSWORD (
    for /f "tokens=1,* delims==" %%a in ('findstr /b "DB_PASSWORD=" ..\.env') do set DB_PASSWORD=%%b
)
if not defined DB_OWNER_PASSWORD (
    for /f "tokens=1,* delims==" %%a in ('findstr /b "DB_OWNER_PASSWORD=" ..\.env') do set DB_OWNER_PASSWORD=%%b
)

echo.
echo Enter the password you chose for the PostgreSQL "postgres" user when you installed it.
echo (Nothing will show as you type. Press Enter when done.)
echo.
"%PSQL%" -U postgres -h localhost -f db_setup.sql

echo.
echo ------------------------------------------------------------
echo Success looks like: CREATE ROLE, ALTER ROLE, CREATE DATABASE (twice),
echo CREATE TABLE and GRANT lines, and no lines starting with ERROR.
echo If "psql" is not recognised, add PostgreSQL's bin folder to PATH or set
echo PSQL to the full path of psql.exe.
echo ------------------------------------------------------------
pause
