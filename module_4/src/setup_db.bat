@echo off
rem One-time PostgreSQL setup for Windows (double-click this file).
rem Creates the gradcafe_app role and the gradcafe / gradcafe_test databases.
rem You will be asked for the password of the PostgreSQL "postgres" superuser.
rem The app role's password is read from GRADCAFE_APP_PASSWORD (or PGPASSWORD) in the
rem git-ignored module_4\.env file. psql is taken from PATH unless PSQL is set.
cd /d "%~dp0"

if not defined PSQL set PSQL=psql
if not defined GRADCAFE_APP_PASSWORD (
    for /f "tokens=1,* delims==" %%a in ('findstr /b "PGPASSWORD=" ..\.env') do set GRADCAFE_APP_PASSWORD=%%b
    for /f "tokens=1,* delims==" %%a in ('findstr /b "GRADCAFE_APP_PASSWORD=" ..\.env') do set GRADCAFE_APP_PASSWORD=%%b
)

echo.
echo Enter the password you chose for the PostgreSQL "postgres" user when you installed it.
echo (Nothing will show as you type. Press Enter when done.)
echo.
"%PSQL%" -U postgres -h localhost -f db_setup.sql

echo.
echo ------------------------------------------------------------
echo Success looks like: CREATE ROLE, ALTER ROLE, CREATE DATABASE (twice)
echo and no lines starting with ERROR. If "psql" is not recognised, add
echo PostgreSQL's bin folder to PATH or set PSQL to the full path of psql.exe.
echo ------------------------------------------------------------
pause
