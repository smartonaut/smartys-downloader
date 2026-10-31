"""FastAPI-Backend: REST-API + Web-GUI + WebSocket-Progress."""
import asyncio
import os
import sys
import json
import threading
from pathlib import Path
from fastapi import FastAPI, WebSocket, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from . import store, config
from .engine import QueueEngine
from .clipboard import watch as clipboard_watch
from .urls import extract_urls, get_hoster, is_filecrypt
from .debrid import DebridRouter, SERVICES as DEBRID_SERVICES
from .direct_hoster import HOSTERS as DIRECT_HOSTERS
from . import auth as webauth
from . import scheduler
from . import reconnect
from . import torrent

app = FastAPI(title="SmartDownloader")
engine = QueueEngine()
_clipboard_stop = threading.Event()


@app.on_event("startup")
async def _startup():
    # Dynamische Hoster-Liste laden (alle konfigurierten Multihoster)
    from .urls import load_dynamic_hosters
    n = load_dynamic_hosters()
    print(f"[smartdl] {n} multihoster-domains geladen")
    threading.Thread(target=engine.start, daemon=True).start()
    scheduler.start()
    if config.CLIPBOARD_WATCH:
        threading.Thread(
            target=clipboard_watch,
            args=(_on_clipboard_links, _clipboard_stop),
            daemon=True).start()


def _on_clipboard_links(links: list[dict]):
    store.set_setting("clipboard_last", json.dumps(links))


@app.on_event("shutdown")
async def _shutdown():
    engine.stop()
    _clipboard_stop.set()


# ---------- WebSocket Progress ----------
@app.middleware("http")
async def _guard(request: Request, call_next):
    if webauth.has_login():
        path = request.url.path
        needs_auth = not (path.startswith("/api/auth")
                          or path in ("/", "/login")
                          or path.startswith("/favicon"))
        if needs_auth:
            sid = request.cookies.get(webauth.COOKIE_NAME)
            if not webauth.valid_session(sid):
                if path.startswith("/api/"):
                    from fastapi.responses import JSONResponse
                    return JSONResponse({"error": "nicht eingeloggt"}, status_code=401)
                from fastapi.responses import RedirectResponse
                return RedirectResponse("/login")
    return await call_next(request)


# ---------- Dienste-Verwaltung (GUI) ----------
@app.get("/api/services")
def list_services():
    """Alle dienste mit: konfiguriert-ja/nein, login-flow verfügbar."""
    from .debrid import SERVICES as REG
    from . import keystore
    stored = {s["name"] for s in keystore.list_services()}
    out = []
    for name in REG:
        has_env = bool(os.getenv({
            "realdebrid": "REALDEBRID_API_KEY",
            "debridlink": "DEBRIDLINK_API_KEY",
            "alldebrid": "ALLDEBRID_API_KEY",
            "premiumize": "PREMIUMIZE_API_KEY",
            "torbox": "TORBOX_API_KEY",
            "easydebrid": "EASYDEBRID_API_KEY",
            "linksnappy": "LINKSNAPPY_API_KEY",
            "offcloud": "OFFCLOUD_API_KEY",
        }.get(name, ""), ""))
        out.append({
            "name": name,
            "configured": name in stored or has_env,
            "via_store": name in stored,
            "via_env": has_env,
            "login_flow": name == "linksnappy",  # user/pass→key möglich
        })
    return out


@app.post("/api/services/{name}/key")
async def add_service_key(name: str, request: Request):
    """API-Key für einen Dienst speichern (verschlüsselt)."""
    sid = request.cookies.get(webauth.COOKIE_NAME)
    if webauth.has_login() and not webauth.valid_session(sid):
        return {"ok": False, "error": "nicht eingeloggt"}
    from .debrid import SERVICES as REG
    if name not in REG:
        return {"ok": False, "error": "unbekannter dienst"}
    body = await request.json()
    key = str(body.get("api_key", "")).strip()
    if not key:
        return {"ok": False, "error": "key leer"}
    from . import keystore
    # validieren: dienst muss den key akzeptieren UND einen echten user liefern
    svc = REG[name](key)
    try:
        u = svc.user()
    except Exception as e:
        return {"ok": False, "error": f"key ungültig: {str(e)[:100]}"}
    user = (u.get("username") or u.get("login") or u.get("email")
            or (u.get("user") or {}).get("username") if isinstance(u, dict) else None)
    if not user or user == "?" or (isinstance(user, str) and user.strip() == ""):
        return {"ok": False, "error": "key ungültig — der Dienst hat keinen Account geliefert"}
    keystore.add_service(name, key)
    return {"ok": True, "user": user}


@app.post("/api/services/{name}/login")
async def add_service_login(name: str, request: Request):
    """Login (user/pass) → API-Key holen → verschlüsselt speichern.
    Das Passwort wird nie gespeichert."""
    sid = request.cookies.get(webauth.COOKIE_NAME)
    if webauth.has_login() and not webauth.valid_session(sid):
        return {"ok": False, "error": "nicht eingeloggt"}
    body = await request.json()
    user = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    if not user or not password:
        return {"ok": False, "error": "user/pass fehlt"}
    from . import keystore
    try:
        key = keystore.fetch_key_via_login(name, user, password)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    keystore.add_service(name, key)
    return {"ok": True, "note": "api-key geholt und verschlüsselt gespeichert"}


@app.delete("/api/services/{name}")
def remove_service(name: str, request: Request):
    sid = request.cookies.get(webauth.COOKIE_NAME)
    if webauth.has_login() and not webauth.valid_session(sid):
        return {"ok": False, "error": "nicht eingeloggt"}
    from . import keystore
    return {"ok": keystore.remove_service(name)}


# ---------- Auth ----------
@app.post("/api/auth/login")
async def auth_login(request: Request):
    body = await request.json()
    if not webauth.verify_password(body.get("password", "")):
        return {"ok": False, "error": "falsches passwort"}
    if webauth.has_2fa():
        code = str(body.get("code", ""))
        if not webauth.verify_2fa(code):
            return {"ok": False, "error": "2FA-Code falsch", "need_2fa": True}
    sid = webauth.create_session()
    resp = JSONResponse({"ok": True})
    resp.set_cookie(webauth.COOKIE_NAME, sid, max_age=webauth.SESSION_TTL,
                    httponly=True, samesite="lax")
    return resp


@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    sid = request.cookies.get(webauth.COOKIE_NAME)
    if sid:
        webauth.logout(sid)
    return {"ok": True}


@app.post("/api/auth/password")
async def auth_password(request: Request):
    """Passwort setzen/ändern (nur wenn eingelogged ODER frisch ohne pw)."""
    body = await request.json()
    if webauth.has_login():
        sid = request.cookies.get(webauth.COOKIE_NAME)
        if not webauth.valid_session(sid):
            return {"ok": False, "error": "nicht eingeloggt"}
    pw = str(body.get("password", ""))
    errs = webauth.password_errors(pw)
    if errs:
        return {"ok": False, "error": "Passwort zu schwach: " + ", ".join(errs)}
    webauth.set_password(pw)
    return {"ok": True}


@app.get("/api/auth/status")
def auth_status():
    return {"login_required": webauth.has_login(), "twofa": webauth.has_2fa()}


# ---------- 2FA ----------
@app.post("/api/auth/2fa/setup")
async def twofa_setup(request: Request):
    """Neues 2FA-Secret erzeugen (noch NICHT aktiv)."""
    sid = request.cookies.get(webauth.COOKIE_NAME)
    if webauth.has_login() and not webauth.valid_session(sid):
        return {"ok": False, "error": "nicht eingeloggt"}
    secret = webauth.generate_2fa_secret()
    return {"ok": True, "secret": secret,
            "uri": webauth.otpauth_uri(secret)}


@app.post("/api/auth/2fa/enable")
async def twofa_enable(request: Request):
    """2FA mit bestätigungs-code aktivieren."""
    sid = request.cookies.get(webauth.COOKIE_NAME)
    if webauth.has_login() and not webauth.valid_session(sid):
        return {"ok": False, "error": "nicht eingeloggt"}
    body = await request.json()
    secret = body.get("secret", "")
    code = str(body.get("code", ""))
    if not webauth.totp_verify(secret, code):
        return {"ok": False, "error": "code falsch — App und Secret prüfen"}
    webauth.enable_2fa(secret)
    return {"ok": True}


@app.post("/api/auth/2fa/disable")
async def twofa_disable(request: Request):
    """2FA ausschalten — erfordert Passwort UND aktuellen 2FA-Code."""
    sid = request.cookies.get(webauth.COOKIE_NAME)
    if not webauth.valid_session(sid):
        return {"ok": False, "error": "nicht eingeloggt"}
    body = await request.json()
    if not webauth.verify_password(body.get("password", "")):
        return {"ok": False, "error": "Passwort falsch"}
    if webauth.has_2fa() and not webauth.verify_2fa(str(body.get("code", ""))):
        return {"ok": False, "error": "2FA-Code falsch"}
    webauth.disable_2fa()
    return {"ok": True}


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return (WEB_DIR / "login.html").read_text(encoding="utf-8")


# ---------- Einstellungen ----------
KATEGORIES = ["movie", "series", "software", "music", "audiobook", "kids", "other"]
KATEGORY_LABELS = {"movie": "Filme", "series": "Serien", "software": "Software",
                   "music": "Musik", "audiobook": "Hörspiel", "kids": "Kinder",
                   "other": "Sonstiges"}


def _irc_nicks() -> dict:
    """Pro-Netz-Nicks aus den Einstellungen (JSON-Dict)."""
    raw = store.get_setting("irc_nicks", "")
    if raw:
        try:
            d = json.loads(raw)
            if isinstance(d, dict):
                return {str(k): str(v) for k, v in d.items()}
        except Exception:
            pass
    return {}


def _category_targets() -> dict:
    from .config import CATEGORY_TARGETS_ENV
    raw = store.get_setting("category_targets", "")
    if raw:
        try:
            d = json.loads(raw)
            # env-werte als fallback für leere kategorien:
            for k, v in CATEGORY_TARGETS_ENV.items():
                if not d.get(k) and v:
                    d[k] = v
            return d
        except Exception:
            pass
    # db leer → env-defaults (installer):
    env = {k: v for k, v in CATEGORY_TARGETS_ENV.items() if v}
    # legacy: altes einzelnes jellyfin_target = filme-ziel
    legacy = store.get_setting("jellyfin_target", os.getenv("JELLYFIN_TARGET", ""))
    if legacy and not env.get("movie"):
        env["movie"] = legacy
    return env


@app.get("/api/settings")
def get_settings():
    from . import config
    return {
        "max_parallel": store.get_setting("max_parallel", str(config.MAX_PARALLEL)),
        "speed_limit_kb": store.get_setting("speed_limit_kb", str(config.SPEED_LIMIT_KB)),
        "download_dir": str(config.DOWNLOAD_DIR),
        "debrid_order": store.get_setting("debrid_order", ",".join(config.DEBRID_ORDER)),
        "clipboard_watch": store.get_setting("clipboard_watch",
                                             "1" if config.CLIPBOARD_WATCH else "0"),
        "category_targets": _category_targets(),
        "categories": [{"key": k, "label": KATEGORY_LABELS[k]} for k in KATEGORIES],
        "debrid_services": list(DEBRID_SERVICES.keys()),
        "direct_hosters": list(DIRECT_HOSTERS.keys()),
        "schedule_rules": scheduler.load_rules(),
        "segments": store.get_setting("segments", str(config.SEGMENTS)),
        "aria2_rpc_port": store.get_setting("aria2_rpc_port", str(config.ARIA2_RPC_PORT)),
        "irc": {
            "nick": store.get_setting("irc_nick", config.IRC_NICK),
            "user": store.get_setting("irc_user", config.IRC_USER),
            "realname": store.get_setting("irc_realname", config.IRC_REALNAME),
            "huginn_url": store.get_setting("irc_huginn_url", config.HUGINN_URL),
            "nicks": _irc_nicks(),
        },
        "ai": {
            "endpoint": store.get_setting("ai_endpoint", "http://localhost:11434"),
            "model": store.get_setting("ai_model", "qwen2.5:7b"),
        },
        "vpn": {
            "enabled": store.get_setting("vpn_enabled", "0"),
            "type": store.get_setting("vpn_type", "surfshark"),
            "cli": store.get_setting("vpn_cli", "surfshark-vpn"),
            "ovpn_config": store.get_setting("vpn_ovpn_config", ""),
            "ovpn_auth": store.get_setting("vpn_ovpn_auth", ""),
        },
        "reconnect": {
            "configured": reconnect.is_configured(),
            "script": store.get_setting("reconnect_script", config.RECONNECT_SCRIPT),
            "url": store.get_setting("reconnect_url", config.RECONNECT_URL),
            "fritz_host": store.get_setting("reconnect_fritz_host", config.RECONNECT_FRITZ_HOST),
            "fritz_user": store.get_setting("reconnect_fritz_user", config.RECONNECT_FRITZ_USER),
            "fritz_pass": store.get_setting("reconnect_fritz_pass", config.RECONNECT_FRITZ_PASS),
        },
    }


@app.put("/api/settings")
@app.post("/api/settings")
async def save_settings(request: Request):
    body = await request.json()
    for key in ("max_parallel", "speed_limit_kb", "debrid_order", "clipboard_watch",
                "segments", "aria2_rpc_port", "reconnect_script", "reconnect_url",
                "reconnect_fritz_host", "reconnect_fritz_user", "reconnect_fritz_pass",
                "irc_nick", "irc_user", "irc_realname", "irc_huginn_url",
                "ai_endpoint", "ai_model",
                "vpn_enabled", "vpn_type", "vpn_cli", "vpn_ovpn_config", "vpn_ovpn_auth"):
        if key in body:
            store.set_setting(key, str(body[key]))
    # NickServ-Passwort → NIE plaintext, sondern verschlüsselt im Keystore.
    # (leer = vorhandenes Passwort des Netzes entfernen)
    if "irc_nickserv_password" in body and body.get("irc_nickserv_network"):
        from . import keystore
        net = str(body["irc_nickserv_network"]).lower()
        pw = str(body.get("irc_nickserv_password", ""))
        if pw:
            keystore.add_service(f"irc_nickserv_{net}", pw)
        else:
            keystore.remove_service(f"irc_nickserv_{net}")
    if "category_targets" in body:
        # dict → json; nur bekannte kategorien
        clean = {k: str(v) for k, v in body["category_targets"].items()
                 if k in KATEGORIES}
        store.set_setting("category_targets", json.dumps(clean))
        # legacy-feld mitschreiben (kompatibilitaet)
        store.set_setting("jellyfin_target", clean.get("movie", ""))
    if "irc_nicks" in body:
        nicks = {str(k): str(v) for k, v in body["irc_nicks"].items()
                 if str(v).strip()}
        store.set_setting("irc_nicks", json.dumps(nicks))
    # sofort anwenden:
    from . import config
    if "max_parallel" in body:
        try:
            config.MAX_PARALLEL = max(1, int(body["max_parallel"]))
        except ValueError:
            pass
    if "speed_limit_kb" in body:
        try:
            config.SPEED_LIMIT_KB = max(0, int(body["speed_limit_kb"]))
        except ValueError:
            pass
    if "clipboard_watch" in body:
        config.CLIPBOARD_WATCH = str(body["clipboard_watch"]) == "1"
    if "segments" in body:
        try:
            config.SEGMENTS = max(1, int(body["segments"]))
        except ValueError:
            pass
    if "aria2_rpc_port" in body:
        try:
            config.ARIA2_RPC_PORT = max(1, int(body["aria2_rpc_port"]))
        except ValueError:
            pass
    return {"ok": True}


@app.get("/api/schedule")
def get_schedule():
    return scheduler.load_rules()


@app.post("/api/reconnect")
def do_reconnect():
    """Neue IP vom Router ziehen. Liefert vorher/nachher IP + ob sie sich geändert hat."""
    return reconnect.reconnect()


@app.get("/api/reconnect")
def reconnect_status():
    return {"configured": reconnect.is_configured()}


@app.get("/api/torrent")
def torrent_status():
    """Torrent-Status + ob aria2 verfügbar ist."""
    avail = torrent.is_available()
    items = torrent.status() if avail else []
    return {"available": avail, "torrents": items}


@app.post("/api/torrent/magnet")
async def torrent_add_magnet(request: Request):
    """Body: {magnet, dest_dir?}"""
    body = await request.json()
    magnet = body.get("magnet", "")
    if not magnet.startswith("magnet:?"):
        return {"ok": False, "error": "kein gültiger Magnet-Link"}
    if not torrent.is_available():
        return {"ok": False, "error": "aria2c nicht installiert (apt install aria2)"}
    torrent.ensure_running(str(config.DOWNLOAD_DIR))
    dest = body.get("dest_dir") or str(config.DOWNLOAD_DIR)
    return torrent.add_magnet(magnet, dest)


@app.post("/api/torrent/file")
async def torrent_add_file(file: UploadFile = File(...)):
    """Lädt eine .torrent-Datei hoch und startet sie."""
    if not torrent.is_available():
        return {"ok": False, "error": "aria2c nicht installiert (apt install aria2)"}
    data = await file.read()
    if not data:
        return {"ok": False, "error": "leere Datei"}
    tmp = Path(config.DOWNLOAD_DIR) / ".tmp_torrents"
    tmp.mkdir(parents=True, exist_ok=True)
    dest_file = tmp / (file.filename or "upload.torrent")
    dest_file.write_bytes(data)
    torrent.ensure_running(str(config.DOWNLOAD_DIR))
    r = torrent.add_torrent(str(dest_file), str(config.DOWNLOAD_DIR))
    # aufräumen (aria2 hat die .torrent geparst)
    try:
        dest_file.unlink(missing_ok=True)
    except Exception:
        pass
    return r


@app.post("/api/torrent/pause")
async def torrent_pause(request: Request):
    body = await request.json()
    return torrent.pause(body.get("gid", ""))


@app.post("/api/torrent/resume")
async def torrent_resume(request: Request):
    body = await request.json()
    return torrent.resume(body.get("gid", ""))


@app.post("/api/torrent/remove")
async def torrent_remove(request: Request):
    body = await request.json()
    return torrent.remove(body.get("gid", ""))


@app.put("/api/schedule")
@app.post("/api/schedule")
async def save_schedule(request: Request):
    """Body: {rules: [{package_id, window_start, window_end, days, enabled}]}"""
    body = await request.json()
    rules = body.get("rules", [])
    # validieren: nur bekannte Felder + korrekte Typen
    clean = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        try:
            start = str(r.get("window_start", "22:00"))
            end = str(r.get("window_end", "06:00"))
            # HH:MM validieren
            int(start.split(":")[0]); int(start.split(":")[1])
            int(end.split(":")[0]); int(end.split(":")[1])
            days = [int(d) for d in r.get("days", []) if int(d) in range(7)]
        except (ValueError, IndexError):
            continue
        clean.append({
            "package_id": int(r.get("package_id", 0)),
            "window_start": start,
            "window_end": end,
            "days": days,
            "enabled": bool(r.get("enabled", True)),
        })
    scheduler.save_rules(clean)
    scheduler._sync_once()  # sofort anwenden
    return {"ok": True, "rules": clean}


@app.post("/api/passwords")
async def add_password(request: Request):
    """Passwort zur Archiv/Container-Liste hinzufügen."""
    body = await request.json()
    pw = body.get("password", "").strip()
    if not pw:
        return {"ok": False, "error": "leer"}
    from .config import PASSWORD_FILE
    PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PASSWORD_FILE, "a") as f:
        f.write(pw + "\n")
    return {"ok": True}


@app.put("/api/passwords")
async def replace_passwords(request: Request):
    """Komplette Passwort-Liste ersetzen."""
    body = await request.json()
    pws = [str(p).strip() for p in body.get("passwords", []) if str(p).strip()]
    from .config import PASSWORD_FILE
    PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PASSWORD_FILE, "w") as f:
        f.write("\n".join(pws) + ("\n" if pws else ""))
    return {"ok": True}


@app.get("/api/passwords")
def list_passwords():
    from .config import PASSWORD_FILE
    if not PASSWORD_FILE.exists():
        return {"passwords": []}
    pws = [l.strip() for l in PASSWORD_FILE.read_text().splitlines()
           if l.strip() and not l.strip().startswith("#")]
    return {"passwords": pws}


@app.websocket("/ws")
async def ws_progress(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            data = store.rows(
                "SELECT id, package_id, filename, downloaded, size, speed, eta, status, via, hoster, error "
                "FROM downloads WHERE status IN ('downloading','resolving','queued')")
            pkgs = store.rows(
                "SELECT id, name, status FROM packages WHERE status NOT IN ('done')")
            await ws.send_json({"downloads": [dict(x) for x in data],
                                "packages": [dict(x) for x in pkgs]})
            await asyncio.sleep(1)
    except Exception:
        pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


# ---------- REST API ----------
@app.get("/api/packages")
def list_packages():
    r = store.rows("""
        SELECT p.*, COUNT(d.id) as n_links,
               SUM(CASE WHEN d.status='done' THEN 1 ELSE 0 END) as n_done,
               COALESCE(SUM(d.size),0) as total_size,
               COALESCE(SUM(d.downloaded),0) as total_downloaded
        FROM packages p LEFT JOIN downloads d ON d.package_id=p.id
        GROUP BY p.id ORDER BY p.id DESC""")
    return [dict(x) for x in r]


@app.get("/api/packages/{pid}/downloads")
def package_downloads(pid: int):
    r = store.rows("SELECT * FROM downloads WHERE package_id=? ORDER BY id", (pid,))
    return [dict(x) for x in r]


@app.post("/api/packages")
async def add_package(req: Request):
    """Body: {links: "text mit URLs", name?: str, password?: str}"""
    body = await req.json()
    text = body.get("links", "")
    name = body.get("name") or ""
    password = body.get("password") or None

    urls = extract_urls(text)
    if not urls:
        return {"ok": False, "error": "keine URLs gefunden"}

    if not name:
        if len(urls) == 1 and is_filecrypt(urls[0]):
            name = "Filecrypt-Container"
        else:
            name = urls[0].split("//")[-1].split("/")[0] + f" ({len(urls)})"

    pid = store.add_package(name, password,
                            category=body.get("category", "movie"))
    added = 0
    for u in urls:
        if is_filecrypt(u):
            store.add_download(pid, u, hoster="filecrypt")
            added += 1
        else:
            h = get_hoster(u)
            if h:
                store.add_download(pid, u, hoster=h)
                added += 1
            else:
                # unbekannter hoster: datei-artig oder direct-plugin → annehmen,
                # die engine löst auf (debrid → direct) oder zeigt sauberen fehler
                from .urls import is_direct_file
                from .direct_hoster import can_resolve
                if is_direct_file(u) or can_resolve(u):
                    store.add_download(pid, u, hoster="datei")
                    added += 1
    store.update_package(pid, status="ready")
    return {"ok": True, "package_id": pid, "added": added}


@app.post("/api/packages/{pid}/start")
def start_package(pid: int):
    store.q("UPDATE downloads SET status='queued' WHERE package_id=? AND status IN ('new','paused','error')",
            (pid,))
    store.update_package(pid, status="downloading")
    return {"ok": True}


@app.post("/api/downloads/{did}/pause")
def pause_download(did: int):
    engine.pause(did)
    return {"ok": True}


@app.post("/api/downloads/{did}/resume")
def resume_download(did: int):
    engine.resume(did)
    return {"ok": True}


@app.post("/api/downloads/{did}/retry")
def retry_download(did: int):
    engine.retry(did)
    return {"ok": True}


@app.delete("/api/packages/{pid}")
def delete_package(pid: int):
    store.q("DELETE FROM downloads WHERE package_id=?", (pid,))
    store.q("DELETE FROM packages WHERE id=?", (pid,))
    return {"ok": True}


@app.get("/api/clipboard")
def clipboard_suggestions():
    raw = store.get_setting("clipboard_last", "")
    if not raw:
        return {"links": []}
    try:
        return {"links": json.loads(raw)}
    except Exception:
        return {"links": []}


@app.post("/api/clipboard/clear")
def clipboard_clear():
    store.set_setting("clipboard_last", "")
    return {"ok": True}


@app.get("/api/debrid/status")
def debrid_status():
    router = DebridRouter()
    out = {}
    for svc in router.services:
        try:
            u = svc.user()
            # dienst-agnostisch: username wo vorhanden
            name = (u.get("username") or u.get("login") or u.get("email")
                    or u.get("user", {}).get("username") or "?")
            premium = bool(u.get("premium") or u.get("premium_left")
                          or u.get("is_premium") or u.get("premiumUntil"))
            out[svc.name] = {"user": name, "premium": premium,
                             "expires": u.get("expiration",
                                              u.get("validuntil",
                                                    u.get("premium_until", "")))}
        except Exception as e:
            out[svc.name] = {"error": str(e)[:80]}
    return out


@app.get("/api/status")
def status():
    # aktive Downloads + Geschwindigkeit
    act = store.rows("""SELECT COUNT(*) as n, COALESCE(SUM(speed),0) as speed
                        FROM downloads WHERE status='downloading'""")
    return {
        "active": act[0]["n"],
        "speed": act[0]["speed"],
        "download_dir": str(config.DOWNLOAD_DIR),
        "clipboard_watch": config.CLIPBOARD_WATCH,
    }


# ---------- XDCC / IRC ----------
@app.get("/api/xdcc/networks")
def xdcc_networks():
    from .config import IRC_NETWORKS
    return {"networks": {k: {"host": v["host"], "nickserv": v.get("nickserv", False)}
                         for k, v in IRC_NETWORKS.items()},
            "nicks": _irc_nicks()}


@app.get("/api/xdcc/search")
def xdcc_search(q: str = "", network: str = "", channel: str = "",
                bot_name: str = "", limit: int = 100):
    """Suche über alle konfigurierten Suchmaschinen (freie + eigene)."""
    from . import search, config
    engines = search.get_engines()
    # Legacy-Huginn-URL (falls konfiguriert) als zusätzliche Maschine anhängen
    huginn = store.get_setting("irc_huginn_url", config.HUGINN_URL) or config.HUGINN_URL
    if huginn and not any(e.get("url", "").rstrip("/") == huginn.rstrip("/") for e in engines):
        engines = list(engines) + [{"name": "huginn", "url": huginn, "type": "huginn", "enabled": True}]
    if not engines:
        return {"results": [], "count": 0,
                "error": "keine Suchmaschine konfiguriert (Einstellungen → Suchmaschinen)"}
    try:
        results = search.search_all(q, engines, network=network, channel=channel,
                                    bot=bot_name, limit=min(limit, 500))
        return {"results": results, "count": len(results)}
    except Exception as e:
        return {"results": [], "count": 0, "error": str(e)[:120]}


@app.get("/api/search/engines")
def get_search_engines():
    from . import search
    return {"engines": search.get_engines()}


@app.post("/api/search/engines")
async def save_search_engines(request: Request):
    body = await request.json()
    from . import search
    engines = search.save_engines(body.get("engines", []))
    return {"ok": True, "engines": engines}


@app.get("/api/xdcc/status")
def xdcc_status():
    """Erreichbarkeit + Statistiken des Huginn-Index."""
    import urllib.request
    from . import config
    HUGINN_URL = store.get_setting("irc_huginn_url", config.HUGINN_URL) or config.HUGINN_URL
    if not HUGINN_URL:
        return {"reachable": False, "error": "kein Suchindex konfiguriert"}
    try:
        with urllib.request.urlopen(f"{HUGINN_URL}/api/stats", timeout=8) as r:
            import json as _json
            return {"reachable": True,
                    "stats": _json.loads(r.read().decode("utf-8", "replace"))}
    except Exception as e:
        return {"reachable": False, "error": str(e)[:120]}


@app.post("/api/xdcc/download")
async def xdcc_download(request: Request):
    """Body: {network, bot, pack, filename, size, channel, category}.

    Legt Paket + Download (source_url=xdcc://...) an → Engine übernimmt.
    """
    body = await request.json()
    network = str(body.get("network", "")).strip()
    bot = str(body.get("bot", "")).strip()
    pack = str(body.get("pack", "")).strip()
    filename = str(body.get("filename", "")).strip()
    channel = str(body.get("channel", "")).strip()
    category = str(body.get("category", "movie")).strip() or "movie"
    if not (network and bot and pack):
        return {"ok": False, "error": "network/bot/pack fehlt"}
    from .config import IRC_NETWORKS
    if network not in IRC_NETWORKS:
        return {"ok": False, "error": f"unbekanntes Netzwerk: {network}"}

    url = f"xdcc://{network}/{bot}/{pack}"
    if channel:
        url += f"?ch={channel}"

    name = filename or f"{bot} #{pack}"
    pid = store.add_package(name, category=category)
    try:
        size = int(body.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    store.add_download(pid, url, filename=filename, hoster="xdcc",
                       status="queued", size=size)
    store.update_package(pid, status="downloading")
    return {"ok": True, "package_id": pid, "name": name}


@app.post("/api/ai/chat")
async def ai_chat(request: Request):
    """KI-Assistent: {message, history} → autonome Suche+Download, Endantwort."""
    body = await request.json()
    message = str(body.get("message", "")).strip()
    history = body.get("history") or []
    if not message:
        return {"ok": False, "error": "keine Nachricht"}
    from . import ai
    try:
        result = ai.run_agent(message, history=history)
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": f"KI nicht erreichbar: {str(e)[:140]}"}


@app.get("/api/ai/models")
def ai_models():
    from . import ai
    return {"models": ai.list_models(), "reachable": ai.is_reachable()}


@app.get("/api/ai/gpu")
def ai_gpu():
    from . import gpudetect
    return gpudetect.gpu_summary()


@app.get("/api/ai/detect")
def ai_detect():
    from . import ai
    return {"existing": ai.detect_existing_llm()}


@app.post("/api/ai/pull")
async def ai_pull(request: Request):
    body = await request.json()
    model = str(body.get("model", "")).strip()
    if not model:
        return {"ok": False, "error": "kein Modellname"}
    from . import ai
    try:
        return ai.pull_model(model)
    except Exception as e:
        return {"ok": False, "error": str(e)[:140]}


@app.get("/api/vpn/status")
def vpn_status():
    from . import vpn
    return vpn.status()


@app.post("/api/vpn/connect")
def vpn_connect():
    from . import vpn
    return vpn.connect()


@app.post("/api/vpn/disconnect")
def vpn_disconnect():
    from . import vpn
    return vpn.disconnect()


@app.get("/api/hoster/sites")
def get_hoster_sites():
    from . import hostersearch
    return {"sites": hostersearch.get_sites()}


@app.post("/api/hoster/sites")
async def save_hoster_sites(request: Request):
    body = await request.json()
    from . import hostersearch
    sites = body.get("sites", [])
    # Passwörter (falls mitgeschickt) → verschlüsselter Keystore, NIE in settings
    for s in sites:
        if isinstance(s, dict) and "password" in s and s.get("name"):
            hostersearch.set_password(s["name"], str(s.get("password", "")))
    clean = hostersearch.save_sites(sites)
    return {"ok": True, "sites": clean}


@app.post("/api/hoster/search")
async def hoster_search(request: Request):
    body = await request.json()
    query = str(body.get("query", "")).strip()
    if not query:
        return {"results": [], "count": 0, "error": "keine Suchanfrage"}
    from . import hostersearch
    results = []
    errors = []
    for s in hostersearch.get_sites():
        try:
            results.extend(hostersearch.search(s, query))
        except Exception as e:
            errors.append(f"{s['name']}: {str(e)[:80]}")
    return {"results": results, "count": len(results), "errors": errors}


@app.get("/api/releases/sources")
def get_info_sources():
    from . import releaseinfo
    return {"sources": releaseinfo.get_sources()}


@app.post("/api/releases/sources")
async def save_info_sources(request: Request):
    body = await request.json()
    from . import releaseinfo
    sources = releaseinfo.save_sources(body.get("sources", []))
    return {"ok": True, "sources": sources}


@app.get("/api/releases/categories")
def get_release_categories():
    from . import releaseinfo
    return {"categories": [c[0] for c in releaseinfo.CATEGORIES]}


@app.get("/api/releases")
def get_releases(sort: str = "time", lang: str = "", quality: str = "",
                 year: str = "", q: str = "", category: str = ""):
    from . import releaseinfo
    try:
        if category:
            releases = releaseinfo.fetch_category(category, sort=sort, lang=lang,
                                                  quality=quality, q=q)
        else:
            releases = releaseinfo.fetch_releases(sort=sort, lang=lang, quality=quality,
                                                  year=year, q=q)
        return {"ok": True, "releases": releases}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


# ---------- Web-GUI ----------
# Im PyInstaller-Build liegt web/ in sys._MEIPASS (bzw. neben der exe beim onedir-build)
_APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
WEB_DIR = _APP_DIR / "web"
if not WEB_DIR.exists():  # quell-tree fallback (entwicklung)
    WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@app.get("/", response_class=HTMLResponse)
def index():
    # encoding explizit: windows-default ist cp1252 → crash bei utf-8/emojis
    return (WEB_DIR / "index.html").read_text(encoding="utf-8")