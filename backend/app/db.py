"""SQLite engine and session helpers.

Usage in FastAPI:
    lifespan startup -> init_db()
    def route(session: Session = Depends(get_session)): ...
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# DATA_DIR holds everything that must survive restarts: the SQLite file and
# uploaded photos. On Render, point it at a persistent disk mount.
DATA_DIR = Path(os.getenv("DATA_DIR") or Path(__file__).resolve().parents[1] / "data")
DB_PATH = DATA_DIR / "shopmcp.db"
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    # FastAPI may use a session on a different thread than the one that
    # opened the connection; SQLite blocks that unless this is off.
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")   # SQLite ignores FOREIGN KEY unless enabled
    cur.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer (dashboard polling)
    cur.close()


def init_db() -> None:
    """Create any missing tables. Safe to call on every startup."""
    from app import models  # noqa: F401  (import registers the tables)

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, closed afterwards."""
    with Session(engine) as session:
        yield session
