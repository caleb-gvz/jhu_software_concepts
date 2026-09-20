import pytest

from db_config import connection_settings, sqlalchemy_url

ENV_NAMES = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


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
