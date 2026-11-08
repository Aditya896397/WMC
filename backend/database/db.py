"""Database engine/session setup (SQLite by default, any SQLAlchemy URL via DATABASE_URL).

Optional Supabase: set DATABASE_URL to the Supabase Postgres connection
string (postgresql+psycopg://...) and `pip install psycopg[binary]`.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_DB = PROJECT_ROOT / "database" / "smart_ambulance.db"
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB.as_posix()}"

_is_sqlite = DATABASE_URL.startswith("sqlite")
if _is_sqlite:
    DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
    pool_pre_ping=True,
    future=True,
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):  # WAL = concurrent readers while the simulator writes
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass
