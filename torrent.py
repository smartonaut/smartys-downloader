"""Torrent/Magnet-Unterstützung über aria2 (externes Binary).

Warum aria2 statt libtorrent: libtorrent hat keine Wheels für Python 3.14,
eine C++-Kompilierung wäre Ballast. aria2 ist ein schlankes Binary, das
Torrent, Magnet-Link und Metalink nativ beherrscht und über JSON-RPC
steuerbar ist — perfekt für einen leichtgewichtigen Downloader.

Architektur:
  - Ein einziger langlebiger aria2c-Daemon (RPC, Port konfigurierbar).
  - add_torrent / add_magnet reichen die Datei bzw. den Magnet-Link ein.
  - tellStatus/tellActive/tellStopped liefern Fortschritt pro GID.
  - Pause/Remove über forcePause / forceRemove.

aria2c muss installiert sein (apt install aria2). Fehlt es, meldet das
Modul einen klaren Fehler statt zu crashen.
"""
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request

from . import config

RPC_HOST = "127.0.0.1"
RPC_PORT = 6800
RPC_SECRET = ""  # optional, aus ENV

_proc: subprocess.Popen | None = None
_lock = threading.Lock()


def _aria2c() -> str | None:
    return shutil.which("aria2c")


def is_available() -> bool:
    return _aria2c() is not None


def _port() -> int:
    return getattr(config, "ARIA2_RPC_PORT", RPC_PORT) or RPC_PORT


def _rpc(method: str, params: list, token: str = "") -> dict | None:
    url = f"http://{RPC_HOST}:{_port()}/jsonrpc"
    payload = {"jsonrpc": "2.0", "id": "smartdl",
               "method": method, "params": [token, *params] if token else params}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _token() -> str:
    return getattr(config, "ARIA2_RPC_SECRET", "") or RPC_SECRET or ""


def ensure_running(download_dir: str, rpc_port: int | None = None) -> bool:
    """Startet den aria2c-Daemon, falls er nicht läuft. Idempotent."""
    global _proc
    port = rpc_port or _port()
    if not is_available():
        return False
    with _lock:
        # läuft schon? (RPC erreichbar)
        if _rpc("aria2.getVersion", []) is not None:
            return True
        if _proc is not None and _proc.poll() is None:
            return True
        cmd = [
            _aria2c(),
            "--enable-rpc",
            f"--rpc-listen-port={port}",
            "--rpc-listen-all=false",
            "--daemon=false",
            "--dir", download_dir,
            "--seed-time=0",          # nicht seeden nach Fertigstellung
            "--max-concurrent-downloads=4",
            "--disable-ipv6",
            "--check-integrity=true",
        ]
        secret = _token()
        if secret:
            cmd.append(f"--rpc-secret={secret}")
        _proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        # warten bis RPC antwortet
        for _ in range(50):
            time.sleep(0.1)
            if _rpc("aria2.getVersion", []) is not None:
                return True
        return False


def add_torrent(torrent_file: str, dest_dir: str) -> dict:
    """Lädt eine .torrent-Datei. Liefert {ok, gid, error}."""
    if not is_available():
        return {"ok": False, "error": "aria2c nicht installiert"}
    if not os.path.exists(torrent_file):
        return {"ok": False, "error": f"Torrent-Datei fehlt: {torrent_file}"}
    # aria2 erwartet die .torrent als base64 im RPC-Aufruf
    import base64
    with open(torrent_file, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    r = _rpc("aria2.addTorrent", [b64, [], {"dir": dest_dir}], _token())
    if r and "result" in r:
        return {"ok": True, "gid": r["result"]}
    return {"ok": False, "error": json.dumps(r.get("error", "unbekannt"))}


def add_magnet(magnet: str, dest_dir: str) -> dict:
    """Lädt einen Magnet-Link. Liefert {ok, gid, error}."""
    if not is_available():
        return {"ok": False, "error": "aria2c nicht installiert"}
    r = _rpc("aria2.addUri", [[magnet], {"dir": dest_dir}], _token())
    if r and "result" in r:
        return {"ok": True, "gid": r["result"]}
    return {"ok": False, "error": json.dumps(r.get("error", "unbekannt"))}


def _status_to_dict(s: dict) -> dict:
    def _f(key):
        v = s.get(key, "")
        try:
            return int(v)
        except (TypeError, ValueError):
            return v
    return {
        "gid": s.get("gid"),
        "status": s.get("status", ""),
        "total": _f("totalLength"),
        "downloaded": _f("completedLength"),
        "speed": _f("downloadSpeed"),
        "progress": float(s.get("totalLength", 0) and
                          int(s.get("completedLength", 0)) / int(s.get("totalLength", 1))),
        "name": _bittorrent_name(s),
        "seeds": int(s.get("numSeeders", 0)) if s.get("numSeeders", "").isdigit() else 0,
        "peers": int(s.get("connections", 0)) if s.get("connections", "").isdigit() else 0,
    }


def _bittorrent_name(s: dict) -> str:
    bt = s.get("bittorrent", {})
    if isinstance(bt, dict) and bt.get("info", {}).get("name"):
        return bt["info"]["name"]
    files = s.get("files", [])
    if files and isinstance(files, list):
        p = files[0].get("path", "")
        return os.path.basename(p) or p
    return ""


def status(gid: str = "") -> list[dict]:
    """Status aller (oder eines) Torrent-Downloads."""
    method = "aria2.tellStatus" if gid else "aria2.tellActive"
    params = [gid] if gid else []
    r = _rpc(method, params, _token())
    if not r or "result" not in r:
        return []
    res = r["result"]
    if isinstance(res, list):
        return [_status_to_dict(s) for s in res]
    return [_status_to_dict(res)]


def pause(gid: str) -> dict:
    r = _rpc("aria2.forcePause", [gid], _token())
    return {"ok": r is not None and "result" in r}


def resume(gid: str) -> dict:
    r = _rpc("aria2.unpause", [gid], _token())
    return {"ok": r is not None and "result" in r}


def remove(gid: str) -> dict:
    r = _rpc("aria2.forceRemove", [gid], _token())
    return {"ok": r is not None and "result" in r}


def stop():
    global _proc
    with _lock:
        if _proc is not None:
            try:
                _rpc("aria2.shutdown", [], _token())
            except Exception:
                pass
            try:
                _proc.terminate()
                _proc.wait(timeout=5)
            except Exception:
                pass
            _proc = None
