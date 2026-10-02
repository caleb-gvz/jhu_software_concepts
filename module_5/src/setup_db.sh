#!/usr/bin/env bash
# One-time PostgreSQL provisioning (bash / Git Bash / Linux / macOS). Creates the two
# non-superuser roles (gradcafe_m5_owner, gradcafe_m5_app), the gradcafe_m5 and
# gradcafe_m5_test databases, the applicants table and the least-privilege grants by
# running db_setup.sql as a PostgreSQL superuser. psql prompts for that superuser's
# password; it is never stored.
#
# The two role passwords come from DB_PASSWORD (app role) and DB_OWNER_PASSWORD (owner
# role) in your environment, or from the git-ignored module_5/.env file.
# psql is taken from PATH; set PSQL=/path/to/psql to use a specific one. Set
# SUPERUSER to use a superuser other than "postgres".
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
ENV_FILE="../.env"

PSQL="${PSQL:-$(command -v psql || true)}"
if [ -z "$PSQL" ]; then
    # Git Bash on Windows: the PostgreSQL installer's default folder (newest version last).
    for candidate in "/c/Program Files/PostgreSQL/"*/bin/psql.exe; do
        [ -f "$candidate" ] && PSQL="$candidate"
    done
fi
if [ -z "$PSQL" ]; then
    echo "psql was not found. Add PostgreSQL's bin folder to PATH or set PSQL=/path/to/psql." >&2
    exit 1
fi

# Take a value from the environment, else from the first matching line of .env.
env_or_file() {
    local name="$1"
    if [ -n "${!name:-}" ]; then
        printf '%s' "${!name}"
    elif [ -f "$ENV_FILE" ]; then
        grep -E "^${name}=" "$ENV_FILE" | head -n 1 | cut -d= -f2- || true
    fi
}

DB_PASSWORD="$(env_or_file DB_PASSWORD)"
DB_OWNER_PASSWORD="$(env_or_file DB_OWNER_PASSWORD)"
if [ -z "$DB_PASSWORD" ] || [ -z "$DB_OWNER_PASSWORD" ]; then
    echo "Set DB_PASSWORD and DB_OWNER_PASSWORD (in your shell or in module_5/.env) first." >&2
    exit 1
fi
export DB_PASSWORD DB_OWNER_PASSWORD

"$PSQL" -U "${SUPERUSER:-postgres}" -h "${DB_HOST:-localhost}" -p "${DB_PORT:-5432}" -f db_setup.sql
echo "Database setup finished."
