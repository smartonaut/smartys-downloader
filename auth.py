"""Login-Schutz für die Web-GUI + API — mit TOTP-2FA (Google Authenticator).

Passwort-Regel (strikt):
  - mindestens 12 Zeichen
  - Groß- UND Kleinbuchstaben
  - mindestens 1 Zahl
  - mindestens 1 Sonderzeichen

2FA: TOTP (RFC 6238), kompatibel mit Google Authenticator / Authy / 1Password.
Setup über die GUI → Secret (base32) → in die Authenticator-App scannen/tippen.
Login: Passwort + 6-stelliger Code.

Sessions: HttpOnly-Cookie, 30 Tage.
"""
import base64
import hashlib
import hmac
import os
import secrets
import struct
import time

from . import store

COOKIE_NAME = "smartdl_session"
SESSION_TTL = 30 * 24 * 3600  # 30 tage

_sessions: dict[str, float] = {}


# ============================================================================
# Passwort-Regeln
# ============================================================================
def password_errors(password: str) -> list[str]:
    """Liste der Regel-Verletzungen — leer = Passwort ok."""
    errs = []
    if len(password) < 12:
        errs.append("mind. 12 Zeichen")
    if not any(c.isupper() for c in password):
        errs.append("mind. 1 Großbuchstabe")
    if not any(c.islower() for c in password):
        errs.append("mind. 1 Kleinbuchstabe")
    if not any(c.isdigit() for c in password):
        errs.append("mind. 1 Zahl")
    if not any(not c.isalnum() for c in password):
        errs.append("mind. 1 Sonderzeichen")
    return errs


def _pw_hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# ============================================================================
# Passwort-Verwaltung
# ============================================================================
def has_login() -> bool:
    """Login nötig? True wenn ein Passwort gesetzt ist."""
    if store.get_setting("password_hash"):
        return True
    pw = os.getenv("SMARTDL_PASSWORD", "")
    if pw:
        store.set_setting("password_hash", _pw_hash(pw))
        return True
    return False


def set_password(password: str):
    errs = password_errors(password)
    if errs:
        raise ValueError("Passwort zu schwach: " + ", ".join(errs))
    store.set_setting("password_hash", _pw_hash(password))


def verify_password(password: str) -> bool:
    target = store.get_setting("password_hash")
    if not target:
        return True  # kein login konfiguriert
    return hmac.compare_digest(target, _pw_hash(password))


# ============================================================================
# TOTP-2FA (RFC 6238)
# ============================================================================
def _b32(secret: str) -> bytes:
    # padding auffüllen
    pad = (-len(secret)) % 8
    return base64.b32decode(secret + "=" * pad, casefold=True)


def totp(secret_b32: str, step: int = 30, digits: int = 6,
         at: float | None = None) -> str:
    """6-stelligen TOTP-Code generieren."""
    t = int(at if at is not None else time.time()) // step
    msg = struct.pack(">Q", t)
    key = _b32(secret_b32)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF)
    return str(code % (10 ** digits)).zfill(digits)


def totp_verify(secret_b32: str, code: str, window: int = 1) -> bool:
    """Code prüfen — ±1 Zeitfenster (30s) Toleranz."""
    if not secret_b32 or not code or not code.isdigit():
        return False
    now = time.time()
    for off in range(-window, window + 1):
        if hmac.compare_digest(totp(secret_b32, at=now + off * 30), code):
            return True
    return False


# ============================================================================
# 2FA-Verwaltung
# ============================================================================
def has_2fa() -> bool:
    return bool(store.get_setting("totp_secret"))


def generate_2fa_secret() -> str:
    """Neues zufälliges Base32-Secret (für Google Authenticator)."""
    raw = secrets.token_bytes(20)
    return base64.b32encode(raw).decode().rstrip("=")


def otpauth_uri(secret: str, account: str = "Smartys Downloader",
                issuer: str = "smartys-downloader") -> str:
    """ otpauth://-URI für QR-Codes (Google Authenticator)."""
    from urllib.parse import quote
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}"
            f"?secret={secret}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits=6&period=30")


def enable_2fa(secret: str):
    """2FA aktivieren (secret aus dem setup-flow)."""
    store.set_setting("totp_secret", secret)


def disable_2fa():
    store.set_setting("totp_secret", "")


def verify_2fa(code: str) -> bool:
    return totp_verify(store.get_setting("totp_secret"), code)


# ============================================================================
# Sessions
# ============================================================================
def create_session() -> str:
    sid = secrets.token_urlsafe(32)
    _sessions[sid] = time.time() + SESSION_TTL
    now = time.time()
    for k in [k for k, v in _sessions.items() if v < now]:
        _sessions.pop(k, None)
    return sid


def valid_session(sid: str | None) -> bool:
    if not sid:
        return False
    exp = _sessions.get(sid)
    return bool(exp and exp > time.time())


def logout(sid: str):
    _sessions.pop(sid, None)