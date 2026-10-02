"""Static review of the provisioning SQL (``src/db_setup.sql`` and ``db_privileges.sql``).

These run without a database and keep the least-privilege promises from drifting:
the table definition matches the code, the roles are never superusers, no password is
written into a script, and the application role is never granted anything destructive.
"""

import re
from pathlib import Path

import pytest

from load_data import COLUMNS

pytestmark = pytest.mark.db

SRC = Path(__file__).resolve().parents[1] / "src"
SETUP = (SRC / "db_setup.sql").read_text(encoding="utf-8")
PRIVILEGES = (SRC / "db_privileges.sql").read_text(encoding="utf-8")
ALL_SQL = SETUP + "\n" + PRIVILEGES

APP_ROLE = "gradcafe_m5_app"
# Everything the application role may ever hold; anything else is a regression.
ALLOWED_FOR_APP = {"SELECT", "INSERT", "UPDATE", "USAGE", "CONNECT"}


def _code(text: str) -> str:
    """The script with ``--`` comments removed, so prose cannot trigger or hide a match."""
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


def _statements(text: str):
    return [statement.strip() for statement in _code(text).split(";") if statement.strip()]


def test_the_table_defined_in_sql_has_exactly_the_columns_the_code_uses():
    create = re.search(
        r"CREATE TABLE IF NOT EXISTS applicants \((.*?)\);", _code(PRIVILEGES), re.DOTALL
    )
    assert create, "db_privileges.sql must create the applicants table"
    columns = [line.split()[0] for line in create.group(1).strip().splitlines()]

    assert tuple(columns) == COLUMNS


def test_neither_role_is_a_superuser_and_both_are_locked_down():
    code = _code(SETUP)
    for role in ("gradcafe_m5_owner", APP_ROLE):
        alter = re.search(rf"ALTER ROLE {role}\s+(.*?)PASSWORD", code, re.DOTALL)
        assert alter, role
        attributes = set(alter.group(1).split())
        assert {"NOSUPERUSER", "NOCREATEDB", "NOCREATEROLE", "NOREPLICATION"} <= attributes
        assert "SUPERUSER" not in attributes and "CREATEDB" not in attributes


def test_no_password_is_written_into_any_script():
    code = _code(ALL_SQL)
    assert re.findall(r"PASSWORD\s+'", code) == []                # only :'variable' is allowed
    assert re.findall(r"PASSWORD\s+:'(\w+)'", code) == ["owner_password", "app_password"]
    assert "\\getenv owner_password DB_OWNER_PASSWORD" in SETUP
    assert "\\getenv app_password DB_PASSWORD" in SETUP


def test_the_application_role_is_granted_nothing_destructive_or_owner_level():
    grants = [
        statement for statement in _statements(ALL_SQL)
        if re.match(r"GRANT\b", statement) and statement.endswith(f"TO {APP_ROLE}")
    ]
    assert grants, "expected GRANT statements for the application role"

    for grant in grants:
        privileges = re.match(r"GRANT\s+(.*?)\s+ON\b", grant, re.DOTALL).group(1)
        names = {re.sub(r"\(.*?\)", "", part, flags=re.DOTALL).strip()
                 for part in re.split(r",\s*(?![^()]*\))", privileges)}
        assert names <= ALLOWED_FOR_APP, grant


def test_update_is_limited_to_the_two_llm_columns():
    updates = [s for s in _statements(PRIVILEGES) if re.match(r"GRANT\s+UPDATE\b", s)]

    assert len(updates) == 1
    columns = re.search(r"UPDATE\s*\((.*?)\)", updates[0], re.DOTALL).group(1)
    assert [c.strip() for c in columns.split(",")] == [
        "llm_generated_program", "llm_generated_university"
    ]


def test_nothing_is_ever_granted_to_everyone_or_with_the_grant_option():
    code = _code(ALL_SQL).upper()
    assert "TO PUBLIC" not in code
    assert "GRANT ALL" not in code
    assert "WITH GRANT OPTION" not in code
    assert "WITH ADMIN OPTION" not in code


def test_public_access_to_the_databases_table_and_schema_is_revoked():
    code = _code(ALL_SQL)
    for target in ("DATABASE gradcafe_m5", "DATABASE gradcafe_m5_test", "TABLE applicants",
                   "SCHEMA public"):
        assert f"REVOKE ALL ON {target} FROM PUBLIC" in code, target


# ---- the wrapper scripts -------------------------------------------------------------------

def test_the_windows_script_finds_psql_in_the_default_install_folder_when_it_is_not_on_path():
    script = (SRC / "setup_db.bat").read_text(encoding="utf-8")

    assert "where psql" in script                         # use PATH first
    assert r"%ProgramFiles%\PostgreSQL" in script        # then the installer's default folder
    assert "psql.exe" in script
    assert "was not found" in script                      # and a clear message if neither works


def test_the_bash_script_also_falls_back_to_the_default_windows_install_folder():
    script = (SRC / "setup_db.sh").read_text(encoding="utf-8")

    assert "command -v psql" in script
    assert "Program Files/PostgreSQL" in script
