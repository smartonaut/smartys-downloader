"""Reconnect — neue IP vom Router ziehen (um Hoster-Wartezeiten zu umgehen).

Zweck: Bei One-Click-Hostern mit Free-Limit zählt die IP-Adresse die
Downloads. Ein Reconnect weist dem Anschluss eine neue IP zu und setzt
so das Limit zurück. Nützlich für die Direct-Hoster-Fallback-Schiene
(filejoker, webshare.cz …), wo kein Debrid-Dienst das Limit umgeht.

Unterstützt drei konfigurierbare Wege (Reihenfolge = Fallback):
  1. Externes Skript  RECONNECT_SCRIPT  (z. B. curl-Aufruf an die
     Router-WebUI mit Login) — flexibelste Variante.
  2. HTTP-URL          RECONNECT_URL     — GET auf eine URL, die der
     Router als "Neue Verbindung" interpretiert (manche Router bieten
     einen reconnect-Endpoint; sonst über das Script abbilden).
  3. Fritz!Box UPnP     RECONNECT_FRITZ_HOST + USER/PASS — nutzt die
     offizielle Fritz!Box SOAP-Schnittstelle (WANIPConnection:ForceTermination).

Das Modul misst die aktuelle externe IP vor/nach dem Reconnect und
meldet, ob sie sich geändert hat. Aufruf manuell über API oder
automatisch durch die Direct-Hoster-Engine, wenn ein Limit erkannt wird.
"""
import re
import time
import subprocess

from . import store
from . import config

# Env-Namen (werden auch aus config.py geladen, die aus smartdl.env liest)
ENV_SCRIPT = "RECONNECT_SCRIPT"
ENV_URL = "RECONNECT_URL"
ENV_FRITZ_HOST = "RECONNECT_FRITZ_HOST"
ENV_FRITZ_USER = "RECONNECT_FRITZ_USER"
ENV_FRITZ_PASS = "RECONNECT_FRITZ_PASS"


def _ip_public() -> str:
    """Aktuelle externe IP — über mehrere Dienste, erster Treffer gewinnt."""
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip",
                "https://checkip.amazonaws.com"):
        try:
            out = subprocess.run(["curl", "-fsS", "--max-time", "10", url],
                                 capture_output=True, text=True, timeout=15)
            ip = out.stdout.strip()
            if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip):
                return ip
        except Exception:
            continue
    return ""


def _env(key: str, default: str = "") -> str:
    """Wert aus der settings-Tabelle (GUI) zuerst, sonst config.py (ENV)."""
    v = store.get_setting(key.lower(), "")
    if v:
        return v
    mapped = {
        ENV_SCRIPT: getattr(config, "RECONNECT_SCRIPT", ""),
        ENV_URL: getattr(config, "RECONNECT_URL", ""),
        ENV_FRITZ_HOST: getattr(config, "RECONNECT_FRITZ_HOST", ""),
        ENV_FRITZ_USER: getattr(config, "RECONNECT_FRITZ_USER", ""),
        ENV_FRITZ_PASS: getattr(config, "RECONNECT_FRITZ_PASS", ""),
    }
    return mapped.get(key, default)


def _run_external_script(script: str) -> bool:
    try:
        r = subprocess.run(["bash", "-c", script], capture_output=True,
                           text=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def _reconnect_fritz(host: str, user: str, pw: str) -> bool:
    """Fritz!Box WAN-Reconnect über die SOAP-API (ForceTermination)."""
    # Fritz!Box: TR-064 / upnp WANIPConnection
    # Einfacher, verbreiteter Weg: POST auf den "Internet neu verbinden"-Pfad
    # der TR-064-Schnittstelle. Ohne gesicherte Library nutzen wir curl.
    soap = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        '<s:Body><u:ForceTermination xmlns:u="urn:schemas-upnp-org:service:WANIPConnection:1"/>'
        '</s:Body></s:Envelope>'
    )
    url = f"http://{host}:49000/upnp/control/WANIPConn1"
    try:
        r = subprocess.run(
            ["curl", "-fsS", "--max-time", "20", "-X", "POST", url,
             "-H", "Content-Type: text/xml; charset=\"utf-8\"",
             "-H", 'SOAPAction: "urn:schemas-upnp-org:service:WANIPConnection:1#ForceTermination"',
             "-u", f"{user}:{pw}", "--data", soap],
            capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def reconnect() -> dict:
    """Führe Reconnect aus; liefere {ok, ip_before, ip_after, changed, method}."""
    before = _ip_public()

    script = _env(ENV_SCRIPT)
    url = _env(ENV_URL)
    fritz_host = _env(ENV_FRITZ_HOST)

    method = None
    success = False

    if script:
        method = "script"
        success = _run_external_script(script)
    elif fritz_host:
        method = "fritzbox"
        success = _reconnect_fritz(fritz_host, _env(ENV_FRITZ_USER),
                                   _env(ENV_FRITZ_PASS))
    elif url:
        method = "url"
        try:
            r = subprocess.run(["curl", "-fsS", "--max-time", "20", url],
                               capture_output=True, text=True, timeout=30)
            success = r.returncode == 0
        except Exception:
            success = False

    if not success:
        return {"ok": False, "ip_before": before, "ip_after": before,
                "changed": False, "method": method, "error": "Reconnect fehlgeschlagen"}

    # kurz warten, dann neue IP messen
    time.sleep(3)
    after = _ip_public()
    changed = bool(after) and after != before
    return {"ok": True, "ip_before": before, "ip_after": after,
            "changed": changed, "method": method}


def is_configured() -> bool:
    return bool(_env(ENV_SCRIPT) or _env(ENV_URL) or _env(ENV_FRITZ_HOST))
