#!/usr/bin/env bash
# Capture the least-privilege evidence for the report into ../least_privilege_evidence.txt:
#   1. db_verify_privileges.sql  as the owner role   (what the app role holds)
#   2. db_demo_refusals.sql      as the app role     (forbidden statements being refused)
#
# Settings come from the environment or the git-ignored ../.env:
#   DB_HOST DB_PORT DB_OWNER_USER DB_OWNER_PASSWORD DB_USER DB_PASSWORD
# The real database is inspected read-only; the refusal demo runs against the scratch
# database (gradcafe_m5_test) and wraps every statement in BEGIN ... ROLLBACK.
# psql is taken from PATH; set PSQL=/path/to/psql to use a specific one.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
ENV_FILE="../.env"
OUTPUT="../least_privilege_evidence.txt"

PSQL="${PSQL:-$(command -v psql || true)}"
if [ -z "$PSQL" ]; then
    echo "psql was not found. Add PostgreSQL's bin folder to PATH or set PSQL=/path/to/psql." >&2
    exit 1
fi

# Take a value from the environment, else from the first matching line of .env.
env_or_file() {
    local name="$1" default="${2:-}"
    if [ -n "${!name:-}" ]; then
        printf '%s' "${!name}"
    elif [ -f "$ENV_FILE" ] && grep -qE "^${name}=" "$ENV_FILE"; then
        grep -E "^${name}=" "$ENV_FILE" | head -n 1 | cut -d= -f2-
    else
        printf '%s' "$default"
    fi
}

HOST="$(env_or_file DB_HOST localhost)"
PORT="$(env_or_file DB_PORT 5432)"
OWNER="$(env_or_file DB_OWNER_USER gradcafe_m5_owner)"
OWNER_PASSWORD="$(env_or_file DB_OWNER_PASSWORD)"
APP="$(env_or_file DB_USER gradcafe_m5_app)"
APP_PASSWORD="$(env_or_file DB_PASSWORD)"
DATABASE="$(env_or_file DB_NAME gradcafe_m5)"
if [ -z "$OWNER_PASSWORD" ] || [ -z "$APP_PASSWORD" ]; then
    echo "Set DB_OWNER_PASSWORD and DB_PASSWORD (in your shell or in module_5/.env) first." >&2
    exit 1
fi

{
    echo "Least-privilege evidence for Module 5"
    echo "Captured: $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "Server:   $(PGPASSWORD="$OWNER_PASSWORD" "$PSQL" -h "$HOST" -p "$PORT" -U "$OWNER" -d "$DATABASE" -Atc 'select version()' | cut -d, -f1)"
    echo
    echo "### 1. psql -U $OWNER -d $DATABASE -f db_verify_privileges.sql"
    PGPASSWORD="$OWNER_PASSWORD" "$PSQL" -h "$HOST" -p "$PORT" -U "$OWNER" -d "$DATABASE" \
        -f db_verify_privileges.sql 2>&1
    echo
    echo "### 2. psql -U $APP -d ${DATABASE}_test -f db_demo_refusals.sql"
    PGPASSWORD="$APP_PASSWORD" "$PSQL" -h "$HOST" -p "$PORT" -U "$APP" -d "${DATABASE}_test" \
        -f db_demo_refusals.sql 2>&1
} > "$OUTPUT"

echo "Wrote $(basename "$OUTPUT")"
