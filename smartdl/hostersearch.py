"""Hoster-/Forum-Suche: 1-Click-Hoster-Seiten (gully.to, boerse.bz, serienfans.org …).

Der Nutzer trägt seine Seiten SELBST ein (URL + Login). Login-Daten liegen
verschlüsselt im Keystore (Passwort unter hoster_<name>), Seiten-Metadaten in
den Einstellungen. Die Suche loggt sich ein, kratzt die Treffer und liefert
Download-Links zurück — die laufen dann durch die bestehende Debrid-/Hoster-Pipeline.

Typen:
  - "xenforo"   : XenForo-Forum (data-load.me, boerse.bz, serienfans.org) — _xfToken-Login
  - "wordpress" : WordPress (funxd.site) — wp-login.php
  - "custom"    : generische Suche über URL-Template mit {query}

Cloudflare: curl_cffi (chrome-Impersonation) umgeht TLS-Fingerprinting —
funktioniert für data-load.me/funxd.site, NICHT für JS-Challenge-Seiten
(serienfans.org) — die brauchen einen echten Browser.
"""
import re

from . import store, keystore

try:
    from curl_cffi import requests as cf_requests
except ImportError:
    cf_requests = None

# Hoster-Domains, nach denen wir in Treffern suchen (Download-Links)
HOSTER_RE = re.compile(
    r"https?://[^\s\"'<>]+",
    re.IGNORECASE,
)


def get_sites() -> list[dict]:
    raw = store.get_setting("hoster_sites", "")
    sites = []
    if raw:
        try:
            import json
            sites = json.loads(raw)
        except Exception:
            sites = []
    return [s for s in sites if isinstance(s, dict) and s.get("url")]


def save_sites(sites: list[dict]) -> list[dict]:
    clean = []
    for s in sites:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name", "")).strip() or "site"
        url = str(s.get("url", "")).strip().rstrip("/")
        if not url:
            continue
        clean.append({
            "name": name,
            "url": url,
            "type": s.get("type", "custom") if s.get("type") in ("xenforo", "wordpress", "custom") else "custom",
            "username": str(s.get("username", "")).strip(),
        })
    store.set_setting("hoster_sites", __import__("json").dumps(clean))
    return clean


def _pw(name: str) -> str:
    return keystore.get_service_key(f"hoster_{name}") or ""


def set_password(name: str, password: str):
    if password:
        keystore.add_service(f"hoster_{name}", password)
    else:
        keystore.remove_service(f"hoster_{name}")


def _session():
    if cf_requests is None:
        raise RuntimeError("curl_cffi nicht installiert")
    return cf_requests.Session(impersonate="chrome")


def _login_xenforo(session, site) -> bool:
    """XenForo-Login: _xfToken holen → /login/login POST. Liefert True bei Erfolg."""
    base = site["url"]
    u = site.get("username", "")
    p = _pw(site["name"])
    if not (u and p):
        return False
    r = session.get(f"{base}/login/", timeout=15)
    m = re.search(r'name="_xfToken" value="([^"]+)"', r.text)
    if not m:
        return False
    r = session.post(f"{base}/login/login", data={
        "_xfToken": m.group(1), "login": u, "password": p, "remember": "1",
    }, timeout=15)
    return "xf_user" in session.cookies.get_dict() or r.status_code == 200


def _login_wordpress(session, site) -> bool:
    base = site["url"]
    u = site.get("username", "")
    p = _pw(site["name"])
    if not (u and p):
        return False
    session.post(f"{base}/wp-login.php", data={
        "log": u, "pwd": p, "wp-submit": "Anmelden",
        "redirect_to": f"{base}/", "testcookie": "1",
    }, timeout=15)
    return "wordpress_logged_in" in session.cookies.get_dict()


def _extract_links(html: str, hoster_hint: str = "") -> list[str]:
    """Alle externen Links aus HTML ziehen (ohne Bilder/css/js)."""
    links = []
    for m in HOSTER_RE.finditer(html):
        url = m.group(0).rstrip(".,)")
        if any(x in url.lower() for x in (".png", ".jpg", ".css", ".js", ".svg", ".ico", ".gif")):
            continue
        if hoster_hint and hoster_hint.lower() not in url.lower():
            continue
        if url not in links:
            links.append(url)
    return links


def search(site: dict, query: str) -> list[dict]:
    """Eine Seite durchsuchen → Download-Links. Liefert [{url, title}]."""
    base = site["url"]
    stype = site.get("type", "custom")
    s = _session()
    out: list[dict] = []

    if stype == "xenforo":
        _login_xenforo(s, site)
        r = s.get(f"{base}/search/search?keywords={query}", timeout=20)
        html = r.text
    elif stype == "wordpress":
        _login_wordpress(s, site)
        r = s.get(f"{base}/?s={query}", timeout=20)
        html = r.text
    else:  # custom: URL-Template
        tmpl = site.get("search_url", "")
        if not tmpl:
            return []
        url = tmpl.replace("{query}", query)
        r = s.get(url, timeout=20)
        html = r.text

    for link in _extract_links(html):
        out.append({"url": link, "site": site["name"]})
    return out
