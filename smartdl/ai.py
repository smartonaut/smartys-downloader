"""KI-Assistent: lokales LLM (ollama/llama-server) mit Tool-Calling (Suche + Download).

Der Nutzer sagt in natürlicher Sprache, was er will („lade Datei X von Netz Y").
Die KI sucht autonom über die konfigurierten Suchmaschinen, startet den Download
und meldet das Ergebnis — komplett ohne manuellen Schritt.

Backend: OpenAI-kompatibel (/v1/chat/completions) → funktioniert mit ollama
(http://localhost:11434) UND llama.cpp llama-server (http://localhost:8080).
"""
import json
import urllib.request

from . import store, search

DEFAULT_ENDPOINT = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:7b"

SYSTEM_PROMPT = (
    "Du bist ein Download-Assistent für XDCC (Dateitausch über IRC). "
    "Der Nutzer sagt dir, was er haben will (Film, Serie, Datei). "
    "Ablauf — STRENG in dieser Reihenfolge: "
    "1) Rufe IMMER zuerst 'search' mit einem passenden Suchbegriff auf. "
    "2) Wähle aus dem Suchergebnis den besten Treffer (deutsche Fassung, wenn gewünscht). "
    "3) Rufe 'download' mit den EXAKTEN Werten (network, bot, pack, filename, channel) aus dem Suchergebnis auf. "
    "WICHTIG: Rufe 'download' NIE ohne echte Treffer auf. Liefert die Suche count=0 oder keine "
    "Ergebnisse, sage ehrlich 'nichts gefunden' und rufe download NICHT auf. "
    "Erfinde NIE bot/pack/network/filename selbst — niemals Platzhalter wie 'example', 'test' oder '12345'. "
    "Antworte am Ende auf Deutsch, knapp und sachlich."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "search",
        "description": "Suche nach einem XDCC-Pack. Liefert Bot, Netz, Kanal, Pack-Nr, Größe, Dateiname.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                       "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "download",
        "description": "Starte einen XDCC-Download. Übernimm network/bot/pack/filename/channel aus dem search-Ergebnis.",
        "parameters": {"type": "object", "properties": {
            "network": {"type": "string"}, "bot": {"type": "string"},
            "pack": {"type": "string"}, "filename": {"type": "string"},
            "channel": {"type": "string"},
        }, "required": ["network", "bot", "pack", "filename"]},
    }},
]


def _endpoint() -> str:
    return store.get_setting("ai_endpoint", DEFAULT_ENDPOINT).rstrip("/")


def _model() -> str:
    return store.get_setting("ai_model", DEFAULT_MODEL)


def llm_chat(messages: list, tools: list | None = None) -> dict:
    url = f"{_endpoint()}/v1/chat/completions"
    body = {"model": _model(), "messages": messages, "stream": False, "temperature": 0.2,
            "keep_alive": "30m"}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _resolve_network(network: str) -> str:
    """Hostname/Fragment → gültiger Netzwerk-Name (z. B. Host → Netzwerk-Key)."""
    from . import xdcc
    nets = xdcc.get_networks()
    n = (network or "").lower().strip()
    for key, cfg in nets.items():
        if n == key.lower() or n in cfg["host"].lower() or cfg["host"].lower() in n:
            return key
    for key in nets:
        if key.lower() in n:
            return key
    return ""


def _run_search(args: dict) -> dict:
    q = args.get("query", "")
    hits = search.search_all(q)
    return {"count": len(hits), "results": hits[:15]}


def _run_download(args: dict) -> dict:
    network = _resolve_network(args.get("network", ""))
    if not network:
        return {"ok": False, "error": f"Netzwerk '{args.get('network')}' nicht konfiguriert"}
    bot = str(args.get("bot", "")).strip()
    pack = str(args.get("pack", "")).strip().lstrip("#")
    filename = str(args.get("filename", "")).strip()
    channel = str(args.get("channel", "")).strip()
    # Anti-Halluzination: Platzhalter-Werte ablehnen
    for val, name in ((bot, "bot"), (pack, "pack")):
        v = val.lower()
        if v in ("example", "examplebot", "test", "testbot", "bot", "12345") or \
           v.startswith("example") or v.startswith("test"):
            return {"ok": False, "error": f"'{name}' sieht nach Platzhalter aus — nutze echte Werte aus der Suche"}
    if not (bot and pack):
        return {"ok": False, "error": "bot/pack fehlt"}
    url = f"xdcc://{network}/{bot}/{pack}" + (f"?ch={channel}" if channel else "")
    name = filename or f"{bot} #{pack}"
    pid = store.add_package(name, category="movie")
    store.add_download(pid, url, filename=filename, hoster="xdcc", status="queued", size=0)
    store.update_package(pid, status="downloading")
    return {"ok": True, "package_id": pid, "name": name}


def run_tool(name: str, args: dict) -> dict:
    if name == "search":
        return _run_search(args)
    if name == "download":
        return _run_download(args)
    return {"error": f"unbekanntes Tool: {name}"}


def run_agent(user_message: str, history: list | None = None) -> dict:
    """Function-Calling-Loop: Suche + Download autonom bis zur Endantwort."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages += history
    messages.append({"role": "user", "content": user_message})
    calls_log: list = []
    searched = False
    for _ in range(6):  # max. 6 LLM-Runden
        resp = llm_chat(messages, tools=TOOLS)
        msg = resp.get("choices", [{}])[0].get("message", {})
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            return {"reply": msg.get("content", "") or "(keine Antwort)", "tool_calls": calls_log}
        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": tool_calls})
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except (json.JSONDecodeError, ValueError):
                args = {}
            if name == "download" and not searched:
                # Guard: Download VOR Suche = halluzinierte Werte → erzwinge Suche
                result = {"error": "Suche zuerst mit 'search' — du hast noch keine echten Werte."}
            else:
                result = run_tool(name, args)
                if name == "search":
                    searched = True
            calls_log.append({"tool": name, "args": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": tc.get("id", name),
                             "content": json.dumps(result, ensure_ascii=False)})
    return {"reply": "Die Aufgabe wurde nicht abgeschlossen.", "tool_calls": calls_log}


# ---- Modell-Verwaltung (ollama) ----

def list_models() -> list[str]:
    """Verfügbare Modelle vom lokalen ollama (localhost:11434/api/tags)."""
    url = f"{_endpoint()}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


def pull_model(name: str) -> dict:
    """Modell nachladen (ollama pull) — blockiert bis fertig (kann Minuten dauern)."""
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "kein Modellname"}
    url = f"{_endpoint()}/api/pull"
    body = json.dumps({"name": name, "stream": False}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        r.read()
    return {"ok": True, "model": name}


def is_reachable() -> bool:
    try:
        with urllib.request.urlopen(f"{_endpoint()}/api/tags", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


# ---- Bestehende lokale KI erkennen (Port-Konflikt vermeiden) ----

# Häufige lokale LLM-Ports: (port, name, pfad)
LLM_CANDIDATES = [
    (11434, "ollama", "/api/tags"),
    (11434, "ollama (OpenAI)", "/v1/models"),
    (8080, "llama.cpp / OpenAI", "/v1/models"),
    (1234, "LM Studio", "/v1/models"),
    (8000, "OpenAI-kompatibel", "/v1/models"),
]


def detect_existing_llm() -> dict | None:
    """Prüft, ob schon eine lokale KI läuft. Liefert {url, name, port} oder None."""
    for port, name, path in LLM_CANDIDATES:
        url = f"http://127.0.0.1:{port}"
        try:
            req = urllib.request.Request(url + path, headers={"User-Agent": "smartdl"})
            with urllib.request.urlopen(req, timeout=2) as r:
                if r.status == 200:
                    return {"url": url, "name": name, "port": port}
        except Exception:
            continue
    return None
