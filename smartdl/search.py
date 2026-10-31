"""Suchmaschinen-Registry: freie XDCC-Suchmaschinen + eigene, vom Nutzer konfigurierbar.

Jede Suchmaschine ist ein Eintrag mit Name, Basis-URL und Typ. Der Typ bestimmt,
wie die Suche abgesetzt und die Antwort geparst wird:

  - "sunxdcc" : GET {url}/deliver.php?sterm={q}&page={n}  → JSON (parallele Arrays)
  - "huginn"  : GET {url}/api/search?q={q}                  → JSON {results:[...]}
  - "custom"  : GET {url} mit {query}-Platzhalter            → JSON {results:[...]}

Alle aktivierten Maschinen werden parallel abgefragt, Ergebnisse vereinheitlicht
und zusammengeführt. Der Nutzer kann über die GUI eigene Maschinen hinzufügen —
so überlebt die Suche das Kommen und Gehen freier Engines (z. B. sunxdcc→skullxdcc).
"""
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import store

# Eingebaute freie Suchmaschinen (Default — der Nutzer kann ergänzen/löschen).
# Hinweis: sunxdcc.com wird 2026 abgeschaltet; skullxdcc.com (Anubis-geschützt)
# ist der Nachfolger. Deshalb ist die Registry wichtiger als jede Einzel-Engine.
BUILTIN_ENGINES = [
    {"name": "sunxdcc", "url": "https://sunxdcc.com", "type": "sunxdcc", "enabled": True},
]

_UNIFIED_FIELDS = ("network", "channel", "bot", "pack", "size", "filename", "engine")


def get_engines() -> list[dict]:
    """Aktive Engine-Liste aus den Einstellungen (Fallback: eingebaute)."""
    raw = store.get_setting("search_engines", "")
    if raw:
        try:
            eng = json.loads(raw)
            if isinstance(eng, list):
                return [e for e in eng if isinstance(e, dict) and e.get("url")]
        except (json.JSONDecodeError, ValueError):
            pass
    return list(BUILTIN_ENGINES)


def save_engines(engines: list[dict]) -> list[dict]:
    """Engine-Liste validieren + persistieren."""
    clean = []
    for e in engines:
        if not isinstance(e, dict):
            continue
        name = str(e.get("name", "")).strip() or "custom"
        url = str(e.get("url", "")).strip()
        if not url:
            continue
        clean.append({
            "name": name,
            "url": url.rstrip("/"),
            "type": e.get("type", "custom") if e.get("type") in ("sunxdcc", "huginn", "custom") else "custom",
            "enabled": bool(e.get("enabled", True)),
        })
    store.set_setting("search_engines", json.dumps(clean))
    return clean


def _search_sunxdcc(url: str, query: str) -> list[dict]:
    """sunxdcc-API: parallele Arrays → vereinheitlichte Treffer."""
    u = f"{url}/deliver.php?" + urllib.parse.urlencode({"sterm": query, "page": 0})
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    nets = data.get("network", [])
    out = []
    for i in range(len(nets)):
        out.append({
            "network": data.get("network", [""] * (i + 1))[i],
            "channel": data.get("channel", [""] * (i + 1))[i],
            "bot": data.get("bot", [""] * (i + 1))[i],
            "pack": str(data.get("packnum", [""] * (i + 1))[i]).lstrip("#"),
            "size": str(data.get("fsize", [""] * (i + 1))[i]).strip("[]"),
            "filename": data.get("fname", [""] * (i + 1))[i],
        })
    return out


def _search_json_results(url: str, query: str) -> list[dict]:
    """huginn/custom: {results:[{network,channel,bot_name,pack_id,size,filename}]}."""
    full = url.replace("{query}", urllib.parse.quote(query))
    with urllib.request.urlopen(full, timeout=10) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    out = []
    for it in data.get("results", []):
        out.append({
            "network": it.get("network", ""),
            "channel": it.get("channel", ""),
            "bot": it.get("bot_name") or it.get("bot", ""),
            "pack": str(it.get("pack_id") or it.get("pack", "")).lstrip("#"),
            "size": str(it.get("size", "")),
            "filename": it.get("filename", ""),
        })
    return out


def _search_one(engine: dict, query: str) -> list[dict]:
    etype = engine.get("type", "custom")
    url = engine["url"]
    try:
        if etype == "sunxdcc":
            hits = _search_sunxdcc(url, query)
        else:  # huginn + custom teilen das JSON-Format
            hits = _search_json_results(url, query)
    except Exception:
        return []
    for h in hits:
        h["engine"] = engine.get("name", "")
    return hits


def search_all(query: str, engines: list[dict] | None = None,
               network: str = "", channel: str = "", bot: str = "", limit: int = 200) -> list[dict]:
    """Alle aktivierten Maschinen abfragen, Treffer vereinheitlichen + filtern."""
    engines = engines if engines is not None else get_engines()
    active = [e for e in engines if e.get("enabled", True)]
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(active) or 1) as pool:
        futs = {pool.submit(_search_one, e, query): e for e in active}
        for fut in as_completed(futs):
            results.extend(fut.result())

    # dedupe nach (network, bot, pack, filename)
    seen = set()
    deduped = []
    for r in results:
        key = (r["network"], r["bot"], r["pack"], r["filename"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    # filter (optional)
    if network:
        deduped = [r for r in deduped if network.lower() in r["network"].lower()]
    if channel:
        deduped = [r for r in deduped if channel.lower() in r["channel"].lower()]
    if bot:
        deduped = [r for r in deduped if bot.lower() in r["bot"].lower()]

    return deduped[:limit]
