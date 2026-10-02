"""Connection settings: DATABASE_URL first, PG* variables / .env as the fallback."""

import pytest

import db_config
from db_config import (
    _libpq_url,
    connection_settings,
    database_url,
    sqlalchemy_url,
    with_database,
)

pytestmark = pytest.mark.db

ENV_NAMES = ("DATABASE_URL", "PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    # Never let a developer's real .env leak into these tests.
    monkeypatch.setattr(db_config, "ENV_FILE", tmp_path / "missing.env")


# ---- DATABASE_URL ------------------------------------------------------------------------

def test_database_url_environment_variable_wins(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example:6543/app")
    monkeypatch.setenv("PGHOST", "ignored-host")
    assert database_url() == "postgresql://u:p@db.example:6543/app"


def test_database_url_can_come_from_the_env_file(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=postgresql://file@h/filedb\n", encoding="utf-8")
    monkeypatch.setattr(db_config, "ENV_FILE", env_file)
    assert database_url() == "postgresql://file@h/filedb"


def test_database_url_is_built_from_pg_variables_when_absent(monkeypatch):
    monkeypatch.setenv("PGUSER", "someone")
    monkeypatch.setenv("PGPASSWORD", "p@ss/word")
    monkeypatch.setenv("PGDATABASE", "other")

    url = database_url()

    assert url.startswith("postgresql://someone:")
    assert url.endswith("@localhost:5432/other")
    assert sqlalchemy_url(url).password == "p@ss/word"      # special characters survive


def test_database_url_defaults_without_credentials():
    assert database_url() == "postgresql://localhost:5432/gradcafe"


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
    monkeypatch.setenv("PGPASSWORD", "topsecret")
    assert "topsecret" not in str(sqlalchemy_url())


# ---- PG* fallback settings ---------------------------------------------------------------

def test_env_file_fills_in_values_missing_from_the_environment(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n\nnot a setting\nPGUSER=file_user\nPGPASSWORD=file_pw\nPGDATABASE=file_db\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(db_config, "ENV_FILE", env_file)
    monkeypatch.setenv("PGDATABASE", "real_env_wins")

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


def test_settings_come_from_environment(monkeypatch):
    monkeypatch.setenv("PGHOST", "db.example")
    monkeypatch.setenv("PGPORT", "5433")
    monkeypatch.setenv("PGDATABASE", "other")
    monkeypatch.setenv("PGUSER", "someone")
    monkeypatch.setenv("PGPASSWORD", "secret")

    assert connection_settings() == {
        "host": "db.example",
        "port": 5433,
        "dbname": "other",
        "user": "someone",
        "password": "secret",
    }


def test_connect_uses_the_given_url(db_url):
    with db_config.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        assert cur.fetchone()[0] == db_config.sqlalchemy_url(db_url).database
