"""Release-Info: zeigt an, welche Releases gerade online sind.

Info-Quellen (nutzer-konfigurierbar) — ähnlich der Suchmaschinen-Registry:
  - "xrel"   : xREL-API (api.xrel.to) — sauberes JSON mit TV/Film-Releases
  - "rss"    : RSS/Atom-Feed einer Szene-News-Seite
  - "custom" : eigene JSON-Quelle (Liste von Releases)

Der Nutzer trägt seine Quellen selbst ein; die Ergebnisse werden vereinheitlicht
und im Release-Info-Tab angezeigt. Von dort aus kann direkt gesucht/geladen werden.
"""
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

from . import store

XREL_API = "https://api.xrel.to/v2"

# xREL-Kategorien für das Menü (wie xrel.to): Label → (category_name, ext_info_type)
CATEGORIES = [
    ("Serien", "TV", "tv"),
    ("Filme", "MOVIES", "movie"),
    ("Konsole", "CONSOLE", "console"),
    ("Software", "APPS", "software"),
    ("Top Filme", "TOPMOVIE", ""),
    ("Top Games", "TOPGAME", ""),
]


def get_sources() -> list[dict]:
    raw = store.get_setting("info_sources", "")
    if raw:
        try:
            srcs = json.loads(raw)
            if isinstance(srcs, list):
                return [s for s in srcs if isinstance(s, dict) and s.get("url")]
        except (json.JSONDecodeError, ValueError):
            pass
    return [{"name": "xrel.to", "url": XREL_API, "type": "xrel", "enabled": True}]


def save_sources(sources: list[dict]) -> list[dict]:
    clean = []
    for s in sources:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name", "")).strip() or "quelle"
        url = str(s.get("url", "")).strip()
        if not url:
            continue
        clean.append({
            "name": name,
            "url": url,
            "type": s.get("type", "rss") if s.get("type") in ("xrel", "rss", "custom") else "rss",
            "enabled": bool(s.get("enabled", True)),
        })
    store.set_setting("info_sources", json.dumps(clean))
    return clean


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _parse_xrel_data(data) -> list[dict]:
    """xREL-Release-Liste (latest oder browse_category) → vereinheitlichte Dicts."""
    items = data if isinstance(data, list) else data.get("list", [])
    out = []
    for r in items:
        ext = r.get("ext_info", {})
        title = ext.get("title", "?")
        season = r.get("tv_season")
        episode = r.get("tv_episode")
        name = title
        if season is not None and episode is not None:
            name = f"{title} S{season:02d}E{episode:02d}"
        ts = r.get("time", 0)
        dt = datetime.fromtimestamp(ts) if ts else None
        flags = r.get("flags", {})
        lang = "English" if flags.get("english") else "German"
        out.append({
            "title": name,
            "group": r.get("group_name", "?"),
            "quality": r.get("video_type", "?"),
            "size": f"{r.get('size', {}).get('number', '?')} {r.get('size', {}).get('unit', '?')}",
            "lang": lang,
            "category": ext.get("type", "?"),
            "year": dt.year if dt else 0,
            "date": dt.strftime("%d.%m.%Y %H:%M") if dt else "",
            "time": ts,
        })
    return out


def _parse_xrel(base: str) -> list[dict]:
    data = _fetch_json(base.rstrip("/") + "/release/latest.json?per_page=100")
    return _parse_xrel_data(data)


def _fetch_category(base: str, category_name: str, ext_info_type: str = "") -> list[dict]:
    url = base.rstrip("/") + "/release/browse_category.json?" + urllib.parse.urlencode({
        "category_name": category_name, "ext_info_type": ext_info_type, "per_page": 100})
    return _parse_xrel_data(_fetch_json(url))


def _parse_rss(url: str) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        root = ET.fromstring(r.read())
    out = []
    for item in root.iter("item"):
        title = ""
        for tag in item:
            if tag.tag.lower().endswith("title"):
                title = (tag.text or "").strip()
                break
        if title:
            out.append({"title": title, "group": "", "quality": "", "size": "",
                        "lang": "", "category": "", "year": 0, "date": "", "time": 0})
    return out


def _parse_custom(url: str) -> list[dict]:
    data = _fetch_json(url)
    items = data if isinstance(data, list) else data.get("list", data.get("releases", []))
    out = []
    for it in items:
        if isinstance(it, str):
            out.append({"title": it, "group": "", "quality": "", "size": "",
                        "lang": "", "category": "", "year": 0, "date": "", "time": 0})
        elif isinstance(it, dict):
            out.append({
                "title": it.get("title", it.get("name", "?")),
                "group": it.get("group", it.get("group_name", "")),
                "quality": it.get("type", it.get("video_type", "")),
                "size": str(it.get("size", "")),
                "lang": it.get("lang", it.get("language", "")),
                "category": it.get("category", it.get("type", "")),
                "year": it.get("year", 0),
                "date": it.get("date", ""),
                "time": it.get("time", 0),
            })
    return out


def fetch_releases(sources: list[dict] | None = None, limit: int = 200,
                   sort: str = "time", lang: str = "", quality: str = "",
                   year: str = "", q: str = "") -> list[dict]:
    sources = sources if sources is not None else get_sources()
    out: list[dict] = []
    for s in sources:
        if not s.get("enabled", True):
            continue
        try:
            stype = s.get("type", "rss")
            if stype == "xrel":
                hits = _parse_xrel(s["url"])
            elif stype == "rss":
                hits = _parse_rss(s["url"])
            else:
                hits = _parse_custom(s["url"])
            for h in hits:
                h["source"] = s.get("name", "")
                out.append(h)
        except Exception:
            continue
    # Filter
    if lang:
        out = [r for r in out if r["lang"].lower() == lang.lower()]
    if quality:
        out = [r for r in out if quality.lower() in r["quality"].lower()]
    if year:
        out = [r for r in out if str(r["year"]) == str(year)]
    if q:
        out = [r for r in out if q.lower() in r["title"].lower()]
    # Sort: default neueste zuerst (nach Zeit), sonst Titel
    if sort == "title":
        out.sort(key=lambda r: r["title"].lower())
    else:
        out.sort(key=lambda r: r["time"], reverse=True)
    return out[:limit]


def fetch_category(category_label: str, limit: int = 200, sort: str = "time",
                   lang: str = "", quality: str = "", q: str = "") -> list[dict]:
    """Releases einer xREL-Kategorie (Serien/Filme/Konsole/Software/Top…)."""
    cat = next((c for c in CATEGORIES if c[0].lower() == category_label.lower()), None)
    if cat is None:
        return []
    label, category_name, ext_info_type = cat
    out: list[dict] = []
    for s in get_sources():
        if s.get("type") != "xrel" or not s.get("enabled", True):
            continue
        try:
            hits = _fetch_category(s["url"], category_name, ext_info_type)
            for h in hits:
                h["source"] = s.get("name", "")
                out.append(h)
        except Exception:
            continue
    if lang:
        out = [r for r in out if r["lang"].lower() == lang.lower()]
    if quality:
        out = [r for r in out if quality.lower() in r["quality"].lower()]
    if q:
        out = [r for r in out if q.lower() in r["title"].lower()]
    if sort == "title":
        out.sort(key=lambda r: r["title"].lower())
    else:
        out.sort(key=lambda r: r["time"], reverse=True)
    return out[:limit]
