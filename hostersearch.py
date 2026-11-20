"""Hoster-/Forum-Suche: 1-Click-Hoster-Seiten (nutzer-konfigurierbar).

Der Nutzer trägt seine Seiten SELBST ein (URL + Login). Login-Daten liegen
verschlüsselt im Keystore (Passwort unter hoster_<name>), Seiten-Metadaten in
den Einstellungen. Die Suche loggt sich ein, kratzt die Treffer und liefert
Download-Links zurück — die laufen dann durch die bestehende Debrid-/Hoster-Pipeline.

Typen:
  - "xenforo"   : XenForo-Forum — _xfToken-Login
  - "wordpress" : WordPress — wp-login.php
  - "custom"    : generische Suche über URL-Template mit {query}

Cloudflare: curl_cffi (chrome-Impersonation) umgeht TLS-Fingerprinting.
JS-Challenge-Seiten brauchen einen echten Browser (Playwright).
"""
import asyncio
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


# ---- Cloudflare-Bypass: curl_cffi zuerst, bei JS-Challenge → Playwright-Chromium ----

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")

CF_MARKERS = ("just a moment", "cf-browser-verification", "challenge-platform",
              "checking your browser", "cf-chl", "attention required")


def _is_challenge(html: str, status: int = 200) -> bool:
    if status in (403, 503, 429):
        return True
    low = (html or "").lower()
    return any(m in low for m in CF_MARKERS)


async def _fetch_playwright(url: str, cookies: dict | None = None) -> str:
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = await browser.new_context(user_agent=UA, locale="en-US")
        if cookies:
            try:
                await ctx.add_cookies([{"name": k, "value": v, "url": url}
                                       for k, v in cookies.items()])
            except Exception:
                pass
        page = await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        # Cloudflare-Challenge läuft im Browser automatisch — warten bis gelöst
        html = await page.content()
        for _ in range(40):
            if not _is_challenge(html):
                break
            await asyncio.sleep(1)
            html = await page.content()
        await browser.close()
        return html


def _fetch_cf(session, url: str) -> str:
    """Robuster Fetch: curl_cffi zuerst, bei Cloudflare-Challenge → Playwright."""
    try:
        r = session.get(url, timeout=20)
        if not _is_challenge(r.text, r.status_code):
            return r.text
    except Exception:
        pass
    cookies = dict(session.cookies) if hasattr(session, "cookies") else None
    last = None
    for _ in range(2):  # ein Retry
        try:
            return asyncio.run(_fetch_playwright(url, cookies=cookies))
        except Exception as e:
            last = e
    raise RuntimeError(f"Cloudflare-Bypass fehlgeschlagen: {last}")


def search(site: dict, query: str) -> list[dict]:
    """Eine Seite durchsuchen → Download-Links. Liefert [{url, title}]."""
    base = site["url"]
    stype = site.get("type", "custom")
    s = _session()
    out: list[dict] = []

    if stype == "xenforo":
        _login_xenforo(s, site)
        html = _fetch_cf(s, f"{base}/search/search?keywords={query}")
    elif stype == "wordpress":
        _login_wordpress(s, site)
        html = _fetch_cf(s, f"{base}/?s={query}")
    else:  # custom: URL-Template
        tmpl = site.get("search_url", "")
        if not tmpl:
            return []
        url = tmpl.replace("{query}", query)
        html = _fetch_cf(s, url)

    for link in _extract_links(html):
        out.append({"url": link, "site": site["name"]})
    return out
