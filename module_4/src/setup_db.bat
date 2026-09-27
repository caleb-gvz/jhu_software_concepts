@echo off
rem One-time PostgreSQL setup for Module 3 (double-click this file).
rem Creates the gradcafe_app role and the gradcafe / gradcafe_test databases.
rem You will be asked for the password of the PostgreSQL "postgres" superuser.
rem The app role's password is read from the git-ignored .env file.
cd /d "%~dp0"

for /f "tokens=1,* delims==" %%a in ('findstr /b "PGPASSWORD=" .env') do set GRADCAFE_APP_PASSWORD=%%b

echo.
echo Enter the password you chose for the PostgreSQL "postgres" user when you installed it.
echo (Nothing will show as you type. Press Enter when done.)
echo.
"C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -f db_setup.sql

echo.
echo ------------------------------------------------------------
echo Success looks like: CREATE ROLE, ALTER ROLE, CREATE DATABASE (twice)
echo and no lines starting with ERROR.
echo ------------------------------------------------------------
pause
