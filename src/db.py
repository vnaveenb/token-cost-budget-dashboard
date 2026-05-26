from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

_local = threading.local()
_DB_PATH: Path | None = None


def configure(db_path: str | Path) -> None:
    global _DB_PATH
    _DB_PATH = Path(db_path)
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_conn() -> sqlite3.Connection:
    if _DB_PATH is None:
        raise RuntimeError("Call db.configure(path) before using the database")
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


def init_db() -> None:
    conn = get_conn()
    schema_path = Path(__file__).parent.parent / "schema" / "init.sql"
    with schema_path.open() as f:
        conn.executescript(f.read())
    conn.commit()
    _seed_pricing(conn)


def _seed_pricing(conn: sqlite3.Connection) -> None:
    PRICING = [
        ("claude-sonnet-4-6",        3.00, 15.00),
        ("claude-haiku-4-5",         0.80,  4.00),
        ("gpt-4o",                   2.50, 10.00),
        ("gpt-4o-mini",              0.15,  0.60),
        ("gemini/gemini-2.5-flash",  0.15,  0.60),
        ("gemini/gemini-2.5-pro",    1.25, 10.00),
        ("mistral/mistral-large",    2.00,  6.00),
    ]
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        "INSERT OR IGNORE INTO pricing VALUES (?, ?, ?, ?)",
        [(m, i, o, now) for m, i, o in PRICING],
    )
    conn.commit()


def close_conn() -> None:
    if hasattr(_local, "conn") and _local.conn is not None:
        _local.conn.close()
        _local.conn = None
