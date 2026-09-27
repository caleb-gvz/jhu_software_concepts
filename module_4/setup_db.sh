#!/usr/bin/env bash
# One-time PostgreSQL setup for Module 3 (Git Bash). Creates the gradcafe_app role and
# the gradcafe / gradcafe_test databases by running db_setup.sql as the postgres
# superuser. psql will prompt for that superuser's password; it is never stored.
#
# The app role's password comes from the git-ignored .env file (PGPASSWORD=...).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

PSQL="/c/Program Files/PostgreSQL/18/bin/psql.exe"
if [ ! -x "$PSQL" ]; then
    echo "psql not found at: $PSQL" >&2
    echo "Edit PSQL in setup_db.sh to point at your PostgreSQL bin folder." >&2
    exit 1
fi
if [ ! -f .env ]; then
    echo ".env not found in $(pwd)" >&2
    exit 1
fi

GRADCAFE_APP_PASSWORD="$(grep '^PGPASSWORD=' .env | cut -d= -f2-)"
export GRADCAFE_APP_PASSWORD

"$PSQL" -U postgres -h localhost -f db_setup.sql
echo "Database setup finished."
