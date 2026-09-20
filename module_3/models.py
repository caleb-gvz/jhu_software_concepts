"""SQLAlchemy 2.x model of the ``applicants`` table, plus the Engine and Session setup.

This file only *maps* the table that ``load_data.py`` creates and fills; it never
calls ``create_all`` and defines no other table, so the ORM and the raw-SQL code
always read the very same rows in the same PostgreSQL database.

Connection settings come from ``db_config`` (PG* environment variables / the ignored
``.env`` file), the same source the psycopg code uses.
"""

from __future__ import annotations

import datetime
from typing import Optional

from sqlalchemy import Date, Engine, Float, Integer, Text, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from db_config import sqlalchemy_url


class Base(DeclarativeBase):
    """Declarative base for the ORM models."""


class Applicant(Base):
    """One Grad Cafe result entry (one row of ``applicants``)."""

    __tablename__ = "applicants"

    # Column order matches the table created by load_data.py.
    p_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    program: Mapped[Optional[str]] = mapped_column(Text)
    comments: Mapped[Optional[str]] = mapped_column(Text)
    date_added: Mapped[Optional[datetime.date]] = mapped_column(Date)
    url: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[Optional[str]] = mapped_column(Text)
    term: Mapped[Optional[str]] = mapped_column(Text)
    us_or_international: Mapped[Optional[str]] = mapped_column(Text)
    gpa: Mapped[Optional[float]] = mapped_column(Float)
    gre: Mapped[Optional[float]] = mapped_column(Float)
    gre_v: Mapped[Optional[float]] = mapped_column(Float)
    gre_aw: Mapped[Optional[float]] = mapped_column(Float)
    degree: Mapped[Optional[str]] = mapped_column(Text)
    llm_generated_program: Mapped[Optional[str]] = mapped_column(Text)
    llm_generated_university: Mapped[Optional[str]] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"Applicant(p_id={self.p_id}, term={self.term!r}, status={self.status!r})"


def make_engine(url: Optional[URL] = None) -> Engine:
    """Create an Engine (lazy: no connection is opened until first use).

    ``pool_pre_ping`` quietly replaces connections that PostgreSQL has closed, which
    matters for a long-running web app.
    """
    return create_engine(url or sqlalchemy_url(), pool_pre_ping=True)


engine = make_engine()
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_session() -> Session:
    """A new Session bound to the default engine; use it as a context manager."""
    return SessionLocal()
