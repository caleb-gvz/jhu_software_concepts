import pytest

import db_config
from db_config import connection_settings, sqlalchemy_url

ENV_NAMES = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    # Never let a developer's real .env leak into these tests.
    monkeypatch.setattr(db_config, "ENV_FILE", tmp_path / "missing.env")


def test_env_file_fills_in_values_missing_from_the_environment(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n\nPGUSER=file_user\nPGPASSWORD=file_pw\nPGDATABASE=file_db\n",
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

    settings = connection_settings()

    assert settings == {
        "host": "db.example",
        "port": 5433,
        "dbname": "other",
        "user": "someone",
        "password": "secret",
    }


def test_sqlalchemy_url_uses_psycopg_driver_and_same_settings(monkeypatch):
    monkeypatch.setenv("PGHOST", "h")
    monkeypatch.setenv("PGPORT", "5433")
    monkeypatch.setenv("PGDATABASE", "d")
    monkeypatch.setenv("PGUSER", "u")
    monkeypatch.setenv("PGPASSWORD", "p@ss/word")

    url = sqlalchemy_url()

    assert url.drivername == "postgresql+psycopg"
    assert (url.host, url.port, url.database, url.username) == ("h", 5433, "d", "u")
    assert url.password == "p@ss/word"


def test_password_is_hidden_when_url_is_printed(monkeypatch):
    monkeypatch.setenv("PGPASSWORD", "topsecret")
    assert "topsecret" not in str(sqlalchemy_url())
