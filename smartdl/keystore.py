"""Verschlüsselter API-Key-Store.

API-Keys liegen NIEMALS plaintext in der DB oder env — sondern
Fernet-verschlüsselt (AES-128-CBC + HMAC) mit einem lokalen Gerät-Schlüssel.

Gerät-Schlüssel: ~/.config/smartys-downloader/.keystore.key (0600, einmalig
erzeugt). Wer den Rechner kontrolliert, könnte den Key theoretisch lesen —
aber die DB alleine (Backups, Sync-Lecks) gibt keine Keys mehr her.

Dienst-Verwaltung (GUI):
  add_service(name, key)     → verschlüsselt speichern
  remove_service(name)       → löschen
  list_services()            → namen (ohne keys!)
  get_service_key(name)      → entschlüsselt (nur intern)

Auch Login-basierte Dienste (derzeit LinkSnappy): GUI schickt user/pass →
der Server holt den API-Key beim Dienst und speichert NUR den key — niemals
das Passwort.
"""
import os
import sqlite3
import threading

from cryptography.fernet import Fernet
from . import store
from .config import CONFIG_DIR

_KEY_FILE = CONFIG_DIR / ".keystore.key"
_lock = threading.Lock()


def _load_fernet() -> Fernet:
    """Gerät-Schlüssel laden oder einmalig erzeugen."""
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _KEY_FILE.exists():
        key = _KEY_FILE.read_bytes()
    else:
        key = Fernet.generate_key()
        # 0600 — nur der user selbst
        fd = os.open(_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
    return Fernet(key)


def _conn() -> sqlite3.Connection:
    """Eigene Tabelle in der bestehenden DB."""
    c = sqlite3.connect(store.DB_PATH, check_same_thread=False)
    c.execute("""CREATE TABLE IF NOT EXISTS service_keys (
        name TEXT PRIMARY KEY,
        enc_key TEXT NOT NULL,
        created_at REAL
    )""")
    return c


# ============================================================================
# CRUD
# ============================================================================
def add_service(name: str, api_key: str) -> bool:
    """API-Key verschlüsselt speichern (überschreibt vorhandenen)."""
    import time
    f = _load_fernet()
    enc = f.encrypt(api_key.encode()).decode()
    with _lock:
        c = _conn()
        try:
            c.execute("INSERT OR REPLACE INTO service_keys (name, enc_key, created_at) "
                      "VALUES (?,?,?)", (name, enc, time.time()))
            c.commit()
        finally:
            c.close()
    return True


def remove_service(name: str) -> bool:
    with _lock:
        c = _conn()
        try:
            c.execute("DELETE FROM service_keys WHERE name=?", (name,))
            n = c.execute("SELECT changes()").fetchone()[0]
            c.commit()
        finally:
            c.close()
    return n > 0


def list_services() -> list[dict]:
    """Namen + Zeitstempel — NIEMALS die Keys."""
    c = _conn()
    try:
        rows = c.execute(
            "SELECT name, created_at FROM service_keys ORDER BY name").fetchall()
        return [{"name": r[0], "created_at": r[1]} for r in rows]
    finally:
        c.close()


def get_service_key(name: str) -> str | None:
    """Entschlüsselter Key (nur für den internen Gebrauch)."""
    f = _load_fernet()
    c = _conn()
    try:
        row = c.execute("SELECT enc_key FROM service_keys WHERE name=?",
                        (name,)).fetchone()
    finally:
        c.close()
    if not row:
        return None
    try:
        return f.decrypt(row[0].encode()).decode()
    except Exception:
        return None


# ============================================================================
# Login→Key-Flow für Dienste mit Username/Passwort
# ============================================================================
def fetch_key_via_login(service: str, username: str, password: str) -> str:
    """Bei Diensten mit Login-API den API-Key holen.

    Das Passwort wird NIE gespeichert — nur der geholte Key landet im Store.
    Wirft ValueError mit Klartext-Grund wenn der Login fehlschlägt.
    """
    from curl_cffi import requests as creq
    s = creq.Session(impersonate="chrome")

    if service == "linksnappy":
        # LinkSnappy AUTHENTICATE → apiKey in der Antwort
        r = s.get("https://linksnappy.com/api/AUTHENTICATE",
                  params={"u": username, "p": password}, timeout=20)
        try:
            d = r.json()
        except Exception:
            raise ValueError("LinkSnappy: ungültige Antwort")
        if d.get("status") != "OK":
            raise ValueError("LinkSnappy: " + str(d.get("error", "Login fehlgeschlagen")))
        key = d.get("apiKey") or d.get("api_key")
        if not key:
            raise ValueError("LinkSnappy: kein apiKey in der Antwort")
        return key

    # Weitere Dienste mit Login-API hier ergänzen (TorBox braucht session_token
    # aus dem Browser — deshalb dort nur manuelle Key-Eingabe)

    raise ValueError(f"{service}: Login-Flow nicht verfügbar — bitte API-Key manuell eintragen")