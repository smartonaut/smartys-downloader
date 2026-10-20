"""Filecrypt.cc-Container-Auflösung.

Pipeline (alles durch FlareSolverrs Browser — Session-Stickiness!):
  1. FlareSolverr GET → Cloudflare gelöst, Passwort-Formular
  2. Passwort-POST (Default funxd) → PoW-Captcha-Seite
  3. Challenge vom Session-Endpoint HOLEN (durch denselben Browser!)
  4. PoW in Python lösen (SHA1 leading zeros) + pow_x/pow_data aus Node (m.js/s.js)
  5. cform-POST mit allen Feldern → CNL2-Seite (jk + crypted)
  6. CNL2 AES-CBC entschlüsseln → direkte Hoster-Links
"""
import base64
import json
import re
from Crypto.Cipher import AES
from . import flaresolverr
from .pow_captcha import solve_pow, gen_pow_browser_fields
from .urls import is_filecrypt
from .config import FILECRYPT_ENABLED

# Typische Container-Passwörter (funxd nutzt "funxd")
DEFAULT_PASSWORDS = ["funxd", "serienfans.org", "filecrypt", "ddl"]


class FilecryptError(Exception):
    pass


def _cnl2_unpack_jk(jk: str) -> bytes:
    """JK-Feld: 'function f(){ return "0123456789abcdef..."; }' → 32-Byte AES-Key."""
    m = re.search(r'["\']([0-9a-fA-F]{64})["\']', jk)
    if m:
        return bytes.fromhex(m.group(1))
    m = re.search(r'["\']([0-9a-f]{32,64})["\']', jk)
    if m:
        return bytes.fromhex(m.group(1))
    raise FilecryptError(f"CNL2 jk nicht lesbar: {jk[:80]}")


def _cnl2_decrypt(crypted_b64: str, key: bytes) -> list[str]:
    """CNL2 'crypted': Base64 → AES-CBC (iv=key[:16]) → URLs pro Zeile."""
    data = base64.b64decode(crypted_b64)
    if len(data) % 16:
        crypted_b64 = crypted_b64.strip()
        data = base64.b64decode(crypted_b64 + "=" * (-len(crypted_b64) % 4))
    iv = key[:16]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    plain = cipher.decrypt(data)
    pad = plain[-1]
    if 1 <= pad <= 16:
        plain = plain[:-pad]
    text = plain.decode("utf-8", errors="replace")
    return [line.strip() for line in text.splitlines()
            if line.strip().startswith("http")]


def _parse_cnl2(html: str) -> tuple[str, str] | None:
    """CNL2-Formular (crypted + jk) aus HTML."""
    m = re.search(
        r'name="jk"[^>]*value\s*=\s*["\']([^"\']*)["\'].*?'
        r'name="crypted"[^>]*value\s*=\s*["\']([^"\']*)["\']',
        html, re.S)
    if m:
        return m.group(1), m.group(2)
    m = re.search(
        r'name="crypted"[^>]*value\s*=\s*["\']([^"\']*)["\'].*?'
        r'name="jk"[^>]*value\s*=\s*["\']([^"\']*)["\']',
        html, re.S)
    if m:
        return m.group(1), m.group(2)
    return None


def _json_from_html(h: str) -> dict:
    m = re.search(r'\{.*\}', h, re.S)
    return json.loads(m.group(0)) if m else json.loads(h)


def _has_pow(html: str) -> bool:
    return "pow-captcha" in html and "pow_id" in html


def resolve_container(url: str, password: str | None = None) -> list[str]:
    """Filecrypt-Container → Liste direkter Hoster-Links."""
    if not is_filecrypt(url):
        raise FilecryptError(f"Kein Filecrypt-Link: {url}")
    if not FILECRYPT_ENABLED:
        raise FilecryptError(
            "Filecrypt nicht konfiguriert: FLARESOLVERR_URL in smartdl.env setzen "
            "(siehe README — FlareSolverr einmalig per Docker starten)")

    # UC-WEG ZUERST (bewährt): filecrypt_uc2.py im FlareSolverr-Container auf
    # sickram — echter Chrome übersteht CF+PoW; die FS-API-Pipeline unten
    # scheitert an Turnstiles. Fallback bleibt als zweite Chance.
    from .filecrypt_remote import resolve_container_remote
    try:
        return resolve_container_remote(url, password)
    except FilecryptError:
        pass  # → Fallback: klassische FlareSolverr-Pipeline unten

    passwords = ([password] if password else []) + DEFAULT_PASSWORDS
    sid = flaresolverr.create_session()
    try:
        # 1. Container öffnen
        r = flaresolverr.solve_get(url, session=sid)
        html = r["html"]

        # 2. Passwort (falls nötig) → PoW-Seite
        current_pw = password or DEFAULT_PASSWORDS[0]
        if "password required" in html.lower():
            got_open = False
            for pw_try in passwords:
                rr = flaresolverr.solve_post(url, f"password={pw_try}&lang=en",
                                             session=sid)
                if "wrong password" not in rr["html"].lower():
                    html = rr["html"]
                    current_pw = pw_try
                    got_open = True
                    break
            if not got_open:
                raise FilecryptError("PASSWORT_FALSCH (kein Default gegriffen)")

        # CNL2 direkt? (manche Container ohne captcha)
        cnl = _parse_cnl2(html)
        if cnl:
            crypted, jk = cnl
            return _cnl2_decrypt(crypted, _cnl2_unpack_jk(jk))

        # 3. PoW-Captcha lösen
        if _has_pow(html):
            m = re.search(r'data-session="(/captchasession/[^"]+\.json)"', html)
            if not m:
                raise FilecryptError("PoW ohne session-pfad")
            sp = m.group(1)

            # pow_x + pow_data aus Node-Generierung
            try:
                browser_fields = gen_pow_browser_fields()
            except Exception as e:
                raise FilecryptError(f"powgen fehlgeschlagen: {e}")

            # Challenge durch denselben Browser holen
            r3 = flaresolverr.solve_post(
                "https://www.filecrypt.cc" + sp,
                f"pow_x={browser_fields['pow_x']}&pow_y=&pow_yn="
                f"&tz=Europe/Berlin&wt=0", session=sid)
            j = _json_from_html(r3["html"])
            c = j["challenge"]
            if not c or "challenge" not in c:
                raise FilecryptError(f"kein challenge: {str(j)[:150]}")

            # PoW in Python
            soln = solve_pow(c["challenge"], int(c["difficulty"]))

            # 4. cform-POST mit ALLEN Feldern durch den Browser
            fields = (f"password={current_pw}&lang=en"
                      f"&pow_id={c['id']}&pow_nonce={soln['nonce']}"
                      f"&pow_elapsed={soln['ms']}&pow_pauses=0"
                      f"&pow_data={browser_fields['pow_data']}"
                      f"&pow_x={browser_fields['pow_x']}")
            r4 = flaresolverr.solve_post(url, fields, session=sid)
            html = r4["html"]

            if "wrong password" in html.lower():
                raise FilecryptError("PASSWORT_FALSCH (nach PoW)")

        # 5. CNL2 extrahieren
        cnl = _parse_cnl2(html)
        if cnl:
            crypted, jk = cnl
            return _cnl2_decrypt(crypted, _cnl2_unpack_jk(jk))

        # Fallback: direkte Hoster-Links
        from .urls import extract_urls
        links = extract_urls(html)
        hoster_links = [l for l in links
                        if not any(x in l for x in (
                            "filecrypt", "static.filecrypt",
                            "challenges.cloudflare", "google", "facebook",
                            "aclib", "visit.php", "cutcaptcha", "pow."))]
        if hoster_links:
            return hoster_links

        state = re.search(r'data-state="([a-z]+)"', html)
        raise FilecryptError(
            f"CNL2 nicht gefunden (captcha-state={state.group(1) if state else '?'})")
    finally:
        flaresolverr.destroy_session(sid)