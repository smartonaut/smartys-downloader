"""Blog-/DDL-Quellen: RSS-Discovery + Post-Auflösung (quellen-neutral).

Die Downloader-Codebasis bleibt frei von Seiten-Namen: Quellen sind reine
NUTZERDATEN in der settings-Tabelle (Key ``ddl_sources``). Eine Quelle ist ein
dict mit:

    {
      "name":   "meineseite",             # Anzeigename / Schlüssel
      "base":   "https://example.tld",    # Origin, für relative Links
      "rss":    "/rss.xml",               # Feed-Pfad oder absolute URL (optional)
      "leech":  true                      # Links hinter /do=go&url=<base64> entpacken
    }

Zwei Schritte, die die API/der Nutzer steuert:

1. ``latest(source, limit)``  — neue Posts aus dem RSS (kein Site-Scrape der Suche:
   robots.txt solcher Seiten verbietet ``?do=search``, RSS ist der saubere Weg).
2. ``resolve(url)``           — Post-Seite holen (Cloudflare → FlareSolverr) und
   die echten Hoster-Links herauslösen: ``labels`` ("MP3 320", "FLAC") bleiben
   erhalten, damit man gezielt eine Qualität greifen kann.
3. ``grab(url, quality)``     — die gewählten Links als Paket in die normale
   Queue legen (ein Debrid-Dienst löst die Hoster-Seiten auf).

Alles andere (Multi-Segment, Resume, Debrid, Entpacken) macht die bestehende
Engine — dieses Modul liefert nur Links.
"""
import base64
import json
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote, urljoin, urlparse, unquote

from . import config, store
from .urls import get_hoster

SOURCES_KEY = "ddl_sources"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_GO_RE = re.compile(r"do=go&(?:amp;)?url=([A-Za-z0-9+/=%_-]+)", re.I)
_ANCHOR_RE = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)


# --------------------------------------------------------------------------
# Quellen-Verwaltung
# --------------------------------------------------------------------------
def get_sources() -> list[dict]:
    raw = store.get_setting(SOURCES_KEY, "") or ""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def save_sources(sources: list[dict]) -> list[dict]:
    clean = []
    for s in sources or []:
        if not isinstance(s, dict) or not s.get("name") or not s.get("base"):
            continue
        clean.append({
            "name": str(s["name"]).strip(),
            "base": str(s["base"]).rstrip("/"),
            "rss": str(s.get("rss") or "").strip(),
            "leech": bool(s.get("leech", True)),
        })
    store.set_setting(SOURCES_KEY, json.dumps(clean, ensure_ascii=False))
    return clean


def get_source(name: str) -> dict | None:
    for s in get_sources():
        if s["name"].lower() == (name or "").lower():
            return s
    return None


def source_for_url(url: str) -> dict | None:
    host = (urlparse(url).hostname or "").lower()
    for s in get_sources():
        if (urlparse(s["base"]).hostname or "").lower() == host:
            return s
    return None


# --------------------------------------------------------------------------
# HTTP (curl_cffi, Cloudflare-Fallback über FlareSolverr)
# --------------------------------------------------------------------------
def _fs_url() -> str:
    return store.get_setting("flaresolverr_url", config.FLARESOLVERR_URL) or ""


def _http(url: str, timeout: int = 30) -> str:
    """GET als Browser. Bei Cloudflare/WAF einmal über FlareSolverr."""
    try:
        from curl_cffi import requests as creq
        r = creq.get(url, impersonate="chrome", timeout=timeout,
                     headers={"Accept-Language": "de-DE,de;q=0.9,en;q=0.8"})
        body = r.text or ""
        if r.status_code == 200 and "Just a moment" not in body[:2000]:
            return body
    except Exception:
        body = ""
    # Fallback: echter Browser im FlareSolverr-Container
    fs = _fs_url()
    if not fs:
        return body
    from . import flaresolverr
    sid = store.get_setting("ddl_fs_session", "") or ""
    if not sid:
        try:
            sid = flaresolverr.create_session()
            store.set_setting("ddl_fs_session", sid)
        except Exception:
            sid = ""
    sol = flaresolverr.solve_get(url, session=sid or None)
    return sol.get("html", "") or body


def _text(html: str) -> str:
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    t = _TAG_RE.sub(" ", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#039;", "'")
    t = t.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">")
    return _WS_RE.sub(" ", re.sub(r"\s*\n\s*", "\n", t)).strip()


# --------------------------------------------------------------------------
# RSS
# --------------------------------------------------------------------------
def latest(name: str, limit: int = 25) -> dict:
    src = get_source(name)
    if not src:
        return {"ok": False, "error": "unbekannte quelle"}
    if not src.get("rss"):
        return {"ok": False, "error": "quelle hat keinen rss-pfad"}
    url = src["rss"] if src["rss"].startswith("http") else urljoin(src["base"] + "/", src["rss"].lstrip("/"))
    xml = _http(url)
    if not xml.strip():
        return {"ok": False, "error": "feed leer oder nicht erreichbar"}
    try:
        root = ET.fromstring(xml.encode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"feed nicht parsebar: {exc}"}
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or it.findtext("guid") or "").strip()
        if not title or not link:
            continue
        out.append({
            "title": title,
            "url": link,
            "date": (it.findtext("pubDate") or "").strip(),
            "genre": (it.findtext("category") or "").strip(),
        })
        if len(out) >= max(1, min(limit, 100)):
            break
    return {"ok": True, "source": src["name"], "count": len(out), "items": out}


# --------------------------------------------------------------------------
# Post auflösen
# --------------------------------------------------------------------------
def _decode_go(href: str) -> str | None:
    """DLE-Leech-Link (/index.php?do=go&url=<base64>) → Ziel-URL."""
    m = _GO_RE.search(href or "")
    if not m:
        return None
    raw = unquote(m.group(1))
    pad = raw + "=" * (-len(raw) % 4)
    for dec in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            val = dec(pad.encode()).decode("utf-8", "replace")
        except Exception:
            continue
        if val.startswith("http"):
            return val
    return None


def _label_of(inner_html: str) -> str:
    t = _text(inner_html)
    t = re.sub(r"\s+", " ", t).strip(" -:\u2013\u2014")
    return t[:40]


def resolve(url: str, source_name: str = "") -> dict:
    """Post-Seite → Titel, Metadaten, Qualitäts-Labels und echte Hoster-Links."""
    src = get_source(source_name) if source_name else source_for_url(url)
    html = _http(url)
    if not html.strip():
        return {"ok": False, "error": "seite nicht ladbar (Cloudflare/offline)"}

    title = ""
    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    if m:
        title = _text(m.group(1)).split(" - ")[0].strip()
    if not title:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
        title = _text(m.group(1)) if m else ""

    links: list[dict] = []
    seen = set()
    for href, inner in _ANCHOR_RE.findall(html):
        target = _decode_go(href) if (src or {}).get("leech", True) else None
        if not target:
            cand = urljoin(url, href)
            if get_hoster(cand) or re.search(r"(filecrypt\.|hide\.cx|tolink\.)", cand, re.I):
                target = cand
        if not target or target in seen:
            continue
        host = get_hoster(target) or ""
        container = "filecrypt" if "filecrypt." in target else ""
        if not host and not container:
            continue
        seen.add(target)
        links.append({"label": _label_of(inner), "host": host or container, "url": target})

    body = _text(html)
    meta = {}
    for field, pat in (("artist", r"Artist:\s*([^:\n]{1,80}?)\s*(?:Album:|$|\n)"),
                       ("album", r"Album:\s*([^:\n]{1,80}?)\s*(?:Genre:|$|\n)"),
                       ("genre", r"Genre:\s*([^:\n]{1,80}?)\s*(?:Country:|$|\n)"),
                       ("year", r"Released:\s*(\d{4})"),
                       ("quality", r"Quality:\s*([^\n]{1,60})"),
                       ("country", r"Country:\s*([^:\n]{1,40}?)\s*(?:Released:|$|\n)")):
        mm = re.search(pat, body)
        if mm:
            meta[field] = mm.group(1).strip()
    pw = re.search(r"(?:Pass(?:wort)?|Archive Password)\s*[:=]\s*(\S{3,40})", body, re.I)

    return {
        "ok": True,
        "url": url,
        "source": (src or {}).get("name", ""),
        "title": title,
        "meta": meta,
        "password": (pw.group(1) if pw else ""),
        "links": links,
        "count": len(links),
    }


# --------------------------------------------------------------------------
# In die Queue legen
# --------------------------------------------------------------------------
def grab(url: str, quality: str = "", category: str = "music",
         source_name: str = "") -> dict:
    """Links eines Posts als Paket anlegen (Debrid/Engine übernehmen den Rest)."""
    res = resolve(url, source_name=source_name)
    if not res.get("ok"):
        return res
    picked = res["links"]
    if quality:
        want = quality.strip().lower()
        filtered = [l for l in picked if want in (l["label"] or "").lower()
                    or want in (l["host"] or "").lower()]
        if filtered:
            picked = filtered
    if not picked:
        return {"ok": False, "error": "keine passenden Hoster-Links gefunden",
                "post": res.get("title", "")}

    name = res.get("title") or urlparse(url).path.rsplit("/", 1)[-1]
    if quality:
        name = f"{name} [{quality}]"
    pid = store.add_package(name, res.get("password") or None, category=category)
    added = 0
    for l in picked:
        # direkt 'queued': die Engine nimmt nur queued/new-Pakete an, /api/packages
        # lässt neue Downloads sonst auf 'new' stehen und startet sie nie.
        store.add_download(pid, l["url"], hoster=l["host"] or "datei", status="queued")
        added += 1
    store.update_package(pid, status="ready")
    return {"ok": True, "package_id": pid, "added": added, "name": name,
            "links": [{"label": l["label"], "host": l["host"]} for l in picked]}
