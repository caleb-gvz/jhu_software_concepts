#!/usr/bin/env bash
# One-time PostgreSQL setup (bash / Git Bash). Creates the gradcafe_app role and the
# gradcafe / gradcafe_test databases by running db_setup.sql as the postgres superuser.
# psql will prompt for that superuser's password; it is never stored.
#
# The app role's password comes from GRADCAFE_APP_PASSWORD in your environment, or from
# the git-ignored module_5/.env file (GRADCAFE_APP_PASSWORD=... or PGPASSWORD=...).
# psql is taken from PATH; set PSQL=/path/to/psql to use a specific one.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
ENV_FILE="../.env"

PSQL="${PSQL:-$(command -v psql || true)}"
if [ -z "$PSQL" ]; then
    echo "psql was not found. Add PostgreSQL's bin folder to PATH or set PSQL=/path/to/psql." >&2
    exit 1
fi

if [ -z "${GRADCAFE_APP_PASSWORD:-}" ] && [ -f "$ENV_FILE" ]; then
    GRADCAFE_APP_PASSWORD="$(grep -E '^(GRADCAFE_APP_PASSWORD|PGPASSWORD)=' "$ENV_FILE" | head -n 1 | cut -d= -f2-)"
fi
if [ -z "${GRADCAFE_APP_PASSWORD:-}" ]; then
    echo "Set GRADCAFE_APP_PASSWORD (in your shell or in module_5/.env) first." >&2
    exit 1
fi
export GRADCAFE_APP_PASSWORD

"$PSQL" -U postgres -h "${PGHOST:-localhost}" -f db_setup.sql
echo "Database setup finished."
