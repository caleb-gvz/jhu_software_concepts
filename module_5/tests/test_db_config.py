"""Connection settings: DB_* environment variables, DATABASE_URL as an optional override."""

import pytest

import db_config
from db_config import (
    _libpq_url,
    connection_settings,
    database_url,
    report_connection_error,
    setting,
    sqlalchemy_url,
    with_database,
)

pytestmark = pytest.mark.db

ENV_NAMES = ("DATABASE_URL", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
LEGACY_NAMES = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in ENV_NAMES + LEGACY_NAMES:
        monkeypatch.delenv(name, raising=False)
    # Never let a developer's real .env leak into these tests.
    monkeypatch.setattr(db_config, "ENV_FILE", tmp_path / "missing.env")


# ---- DATABASE_URL (optional full override) -------------------------------------------------

def test_database_url_environment_variable_wins(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example:6543/app")
    monkeypatch.setenv("DB_HOST", "ignored-host")
    assert database_url() == "postgresql://u:p@db.example:6543/app"


def test_database_url_can_come_from_the_env_file(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=postgresql://file@h/filedb\n", encoding="utf-8")
    monkeypatch.setattr(db_config, "ENV_FILE", env_file)
    assert database_url() == "postgresql://file@h/filedb"


# ---- DB_* variables ------------------------------------------------------------------------

def test_database_url_is_built_from_the_db_variables_when_absent(monkeypatch):
    monkeypatch.setenv("DB_USER", "someone")
    monkeypatch.setenv("DB_PASSWORD", "p@ss/word")
    monkeypatch.setenv("DB_NAME", "other")

    url = database_url()

    assert url.startswith("postgresql://someone:")
    assert url.endswith("@localhost:5432/other")
    assert sqlalchemy_url(url).password == "p@ss/word"      # special characters survive


def test_database_url_defaults_without_credentials():
    assert database_url() == "postgresql://localhost:5432/gradcafe"


def test_settings_come_from_environment(monkeypatch):
    monkeypatch.setenv("DB_HOST", "db.example")
    monkeypatch.setenv("DB_PORT", "5433")
    monkeypatch.setenv("DB_NAME", "other")
    monkeypatch.setenv("DB_USER", "someone")
    monkeypatch.setenv("DB_PASSWORD", "secret")

    assert connection_settings() == {
        "host": "db.example",
        "port": 5433,
        "dbname": "other",
        "user": "someone",
        "password": "secret",
    }


def test_env_file_fills_in_values_missing_from_the_environment(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n\nnot a setting\nDB_USER=file_user\nDB_PASSWORD=file_pw\nDB_NAME=file_db\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(db_config, "ENV_FILE", env_file)
    monkeypatch.setenv("DB_NAME", "real_env_wins")

    settings = connection_settings()

    assert settings["user"] == "file_user"
    assert settings["password"] == "file_pw"
    assert settings["dbname"] == "real_env_wins"


def test_defaults_when_environment_is_empty():
    settings = connection_settings()
    assert settings["host"] == "localhost"
    assert settings["port"] == 5432
    assert settings["dbname"] == "gradcafe"
    assert settings["user"] is None and settings["password"] is None


def test_the_old_libpq_variables_are_no_longer_read(monkeypatch):
    # A stray superuser PGPASSWORD in someone's shell must not become the app's login.
    monkeypatch.setenv("PGUSER", "postgres")
    monkeypatch.setenv("PGPASSWORD", "superuser-secret")
    monkeypatch.setenv("PGHOST", "elsewhere")
    monkeypatch.setenv("PGDATABASE", "postgres")

    assert database_url() == "postgresql://localhost:5432/gradcafe"


def test_a_port_that_is_not_a_whole_number_gets_a_clear_error(monkeypatch):
    monkeypatch.setenv("DB_PORT", "55432; DROP")

    with pytest.raises(ValueError, match="DB_PORT"):
        connection_settings()


# ---- URL helpers ---------------------------------------------------------------------------

def test_with_database_swaps_only_the_database_name():
    assert with_database("postgresql://u:p@h:1/real", "scratch") == "postgresql://u:p@h:1/scratch"


def test_sqlalchemy_url_always_uses_the_psycopg_driver():
    url = sqlalchemy_url("postgresql://u:p@h:5433/d")
    assert url.drivername == "postgresql+psycopg"
    assert (url.host, url.port, url.database, url.username) == ("h", 5433, "d", "u")


def test_libpq_url_strips_a_sqlalchemy_driver_suffix():
    assert _libpq_url("postgresql+psycopg://u@h:5432/d") == "postgresql://u@h:5432/d"
    assert _libpq_url("postgresql://u@h:5432/d") == "postgresql://u@h:5432/d"


def test_password_is_hidden_when_the_sqlalchemy_url_is_printed(monkeypatch):
    monkeypatch.setenv("DB_PASSWORD", "topsecret")
    assert "topsecret" not in str(sqlalchemy_url())


def test_connect_uses_the_given_url(db_url):
    with db_config.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        assert cur.fetchone()[0] == db_config.sqlalchemy_url(db_url).database


def test_the_connection_error_message_names_the_db_variables_and_never_a_password(capsys):
    report_connection_error("connection refused")

    err = capsys.readouterr().err
    for name in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"):
        assert name in err
    assert "Could not connect to PostgreSQL" in err and "connection refused" in err


def test_setting_reads_the_environment_then_the_env_file_then_the_default(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ONLY_IN_FILE=from_file\nIN_BOTH=file_value\n", encoding="utf-8")
    monkeypatch.setattr(db_config, "ENV_FILE", env_file)
    monkeypatch.setenv("IN_BOTH", "environment_value")

    assert setting("ONLY_IN_FILE") == "from_file"
    assert setting("IN_BOTH") == "environment_value"      # the real environment wins
    assert setting("NOWHERE", "fallback") == "fallback"
    assert setting("NOWHERE") is None
