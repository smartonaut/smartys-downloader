"""SQLite-Persistenz: Pakete + Downloads."""
import sqlite3
import threading
import time
from .config import DB_PATH

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _db() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _init_schema(_conn)
        return _conn


def _init_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS packages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        status TEXT DEFAULT 'new',          -- new|collecting|ready|downloading|extracting|done|error
        created_at REAL,
        password TEXT,
        comment TEXT
    );
    CREATE TABLE IF NOT EXISTS downloads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        package_id INTEGER REFERENCES packages(id) ON DELETE CASCADE,
        source_url TEXT NOT NULL,           -- Original-Link (Hoster/Container)
        direct_url TEXT,                    -- Aufgelöster Debrid-Direktlink
        filename TEXT,
        hoster TEXT,
        via TEXT,                           -- realdebrid|debridlink|direct|...
        size INTEGER DEFAULT 0,
        downloaded INTEGER DEFAULT 0,
        speed INTEGER DEFAULT 0,
        status TEXT DEFAULT 'new',          -- new|resolving|queued|downloading|paused|done|error
        error TEXT,
        eta INTEGER DEFAULT 0,
        retries INTEGER DEFAULT 0,
        created_at REAL,
        finished_at REAL,
        UNIQUE(source_url, package_id)
    );
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)
    conn.commit()


def q(sql: str, params=()) -> list[sqlite3.Row]:
    conn = _db()
    with _lock:
        conn.execute(sql, params)
        conn.commit()
    return []


def rows(sql: str, params=()) -> list[sqlite3.Row]:
    conn = _db()
    with _lock:
        return conn.execute(sql, params).fetchall()


def add_package(name: str, password: str | None = None,
                category: str = "movie") -> int:
    conn = _db()
    with _lock:
        cur = conn.execute(
            "INSERT INTO packages (name, status, created_at, password, category) "
            "VALUES (?,?,?,?,?)",
            (name, "new", time.time(), password, category))
        conn.commit()
        return cur.lastrowid or 0


def add_download(package_id: int, source_url: str, filename: str = "",
                 hoster: str = "", status: str = "new") -> int:
    conn = _db()
    with _lock:
        cur = conn.execute(
            "INSERT OR IGNORE INTO downloads (package_id, source_url, filename, hoster, status, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (package_id, source_url, filename, hoster, status, time.time()))
        conn.commit()
        return cur.lastrowid or 0


def update_download(did: int, **fields):
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    conn = _db()
    with _lock:
        conn.execute(f"UPDATE downloads SET {sets} WHERE id=?",
                     (*fields.values(), did))
        conn.commit()


def update_package(pid: int, **fields):
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    conn = _db()
    with _lock:
        conn.execute(f"UPDATE packages SET {sets} WHERE id=?", (*fields.values(), pid))
        conn.commit()


def claim_package_processing(pid: int) -> bool:
    """Atomar auf 'processing' setzen — nur EIN Worker gewinnt.

    Verhindert doppeltes Postprocessing, wenn zwei Worker gleichzeitig den
    letzten Download eines Pakets beenden (UPDATE ... WHERE = compare-and-set).
    """
    conn = _db()
    with _lock:
        cur = conn.execute(
            "UPDATE packages SET status='processing' "
            "WHERE id=? AND status NOT IN ('processing','postprocessed')",
            (pid,))
        conn.commit()
        return cur.rowcount == 1


def get_setting(key: str, default: str = "") -> str:
    r = rows("SELECT value FROM settings WHERE key=?", (key,))
    return r[0]["value"] if r else default


def set_setting(key: str, value: str):
    q("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value))