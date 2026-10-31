"""Click'n'Load-2-Empfänger (JD2-kompatibel).

Läuft auf 127.0.0.1:9666 — genau dort, wo JDownloader2 seine Flash-Bridge
hat. Webseiten (filecrypt & co.) feuern dort ein Formular mit AES-
verschlüsselten Links ab ("Klick to download with JD2"-Button).
Wir entschlüsseln und legen die Links als Paket an.
"""
import base64
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from Crypto.Cipher import AES

from . import store


def cnl2_key(jk: str) -> bytes:
    """jk='function f(){ return \'31323334...\';}' → bytes."""
    m = re.search(r"([0-9a-fA-F]{32,})", jk or "")
    return bytes.fromhex(m.group(1)) if m else b""


def cnl2_decrypt(crypted_b64: str, key: bytes) -> list[str]:
    """Base64 → AES-CBC (iv=key[:16]) → URL-Zeilen."""
    data = base64.b64decode(crypted_b64)
    iv = key[:16]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    plain = cipher.decrypt(data)
    # CNL2 nutzt NULL-Padding (PHP-mcrypt-Stil, per JD-Wiki-Referenz
    # verifiziert 12.10.): die Links enden auf \x00-Fuellbytes, NICHT
    # PKCS5. Erst Nullen strippen, sonst haengen sie an der letzten URL.
    plain = plain.rstrip(b"\x00")
    pad = plain[-1]
    if 1 <= pad <= 16 and plain[-pad:] == bytes([pad]) * pad:
        plain = plain[:-pad]  # Fallback, falls ein Hoster PKCS5 sendet
    text = plain.decode("utf-8", errors="replace")
    return [line.strip("\x00 \t\r\n") for line in text.splitlines()
            if line.strip("\x00 \t\r\n").startswith("http")]


def decode_cnl_form(body: str) -> dict:
    """Formular-Felder aus einem POST extrahieren (alle bekannten Felder)."""
    fields = urllib.parse.parse_qs(body)
    out = {}
    for k in ("crypted", "jk", "passwords", "source", "name", "package",
              "dlc", "url", "urls", "link", "links"):
        v = fields.get(k, [None])[0]
        if v is not None:
            out[k] = v
    return out


class CNL2Handler(BaseHTTPRequestHandler):
    """JD2-Flash-Bridge-Protokoll: /flashadd, /flash/add, /flash/addcrypted2."""

    server_version = "JD2"

    def log_message(self, fmt, *args):  # still
        pass

    def _log(self, method: str, note: str = ""):
        """Jede CNL2/DLC-Übergabe mitloggen (Debugging)."""
        try:
            from .config import LOG_PATH
            import time
            with open(LOG_PATH, "a") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {method} {self.path[:120]} {note}\n")
        except Exception:
            pass

    def _ok(self, html: str = "<html><body>ok</body></html>"):
        data = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._ok("")

    def do_GET(self):
        """GET ist der CNL2-STANDARD: Webseiten (filecrypt & co.) öffnen ein
        Popup auf http://127.0.0.1:9666/flash/addcrypted2?crypted=...&jk=...
        Die Links liegen in den QUERY-PARAMETERN."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.lower()
        qs = urllib.parse.parse_qs(parsed.query)

        # jdcheck.js — JD2-PRAESENZ-CHECK DER WEBSEITE (das CNL2-Protokoll):
        # filecrypt & co. laden <script src="http://127.0.0.1:9666/jdcheck.js">
        # und schalten die CNL2/Open-Buttons NUR frei, wenn das Script die
        # Variable jdownloader auf true setzt (JD-Wiki-CNl2-Referenz).
        # Ohne diesen Handler blieb sie false => die Klicks gingen nie raus.
        if "jdcheck" in path:
            self._log("GET", "jdcheck.js -> jdownloader=true")
            data = b"var jdownloader = true;"
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        # CNL2 via GET (popup-variante):
        if "addcrypted" in path:
            self._log("GET-CNL2")
            key = cnl2_key(qs.get("jk", [""])[0])
            crypted = qs.get("crypted", [""])[0]
            links = []
            if key and crypted:
                try:
                    links = cnl2_decrypt(crypted, key)
                except Exception:
                    links = []
            if links:
                self._handle_links(
                    links,
                    qs.get("package", ["CNL2-Paket"])[0] or "CNL2-Paket",
                    qs.get("passwords", [None])[0])
            self._ok()
            return

        # DLC via GET (?url=<dlc-download-url>) — downloader lädt selbst:
        if "dlc" in path and qs.get("url"):
            self._log("GET-DLC", qs["url"][0][:80])
            from .dlc import dlc_extract
            links = dlc_extract(qs["url"][0])
            if links:
                self._handle_links(links, qs.get("name", ["DLC-Paket"])[0],
                                   None)
            self._ok()
            return

        # Link via GET (?url=...) — kontextmenü/extension:
        if "link" in path and qs.get("url"):
            self._log("GET-LINK", qs["url"][0][:80])
            self._handle_links([qs["url"][0]],
                               qs.get("name", ["Extension-Link"])[0], None)
            self._ok()
            return

        # Flash-Policy-Check der Webseite:
        self._log("GET", "policy/default")
        self._ok()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        self._log("POST", f"len={length}")

        # --- addcrypted2: die Links, AES-verschluesselt ---
        if "addcrypted2" in self.path:
            self._log("POST-CNL2")
            f = decode_cnl_form(body)
            key = cnl2_key(f.get("jk", ""))
            crypted = f.get("crypted", "")
            links = []
            if key and crypted:
                try:
                    links = cnl2_decrypt(crypted, key)
                except Exception:
                    links = []
            if links:
                self._handle_links(
                    links,
                    f.get("package") or f.get("name") or "CNL2-Paket",
                    f.get("passwords") or None)
            self._ok()
            return

        # --- DLC-Container: url= (downloader lädt selbst) ODER inhalt ---
        if "dlc" in self.path.lower():
            f = decode_cnl_form(body)
            dlc_data = f.get("dlc") or ""
            note = f"len={len(dlc_data)} url={f.get('url') or '-'} anfang={dlc_data[:60]!r}"
            self._log("POST-DLC", note[:160])
            links = []
            # letzte dlc immer dumpen (debug + retry möglich):
            try:
                from .config import LOG_PATH
                dpath = LOG_PATH.parent / "last_container.dlc"
                dpath.write_text(dlc_data or (f.get("url") or ""), errors="replace")
            except Exception:
                pass
            if f.get("url") and not dlc_data:
                from .dlc import dlc_extract
                links = dlc_extract(f["url"])
            elif dlc_data:
                from .dlc import dlc_extract_packages
                try:
                    packages = dlc_extract_packages(dlc_data)
                except Exception:
                    packages = []
                if packages:
                    # jedes paket aus dem dlc wird ein eigenes smartdl-paket:
                    for pname, urls in packages:
                        self._handle_links(urls, pname or "DLC-Paket",
                                           f.get("passwords"))
                    self._ok()
                    return
                links = []
                if f.get("url"):
                    from .dlc import dlc_extract
                    links = dlc_extract(f["url"])
            else:
                links = []
            if links:
                self._handle_links(links, f.get("name") or "DLC-Paket",
                                   f.get("passwords"))
            self._ok()
            return

        # --- Einzelne Links (Kontextmenü / Extension) ---
        if "link" in self.path.lower():
            f = decode_cnl_form(body)
            urls = []
            for k in ("url", "urls", "link", "links"):
                if f.get(k):
                    urls = [l.strip() for l in str(f[k]).splitlines()
                            if l.strip().startswith("http")]
                    break
            if not urls:
                urls = [l.strip() for l in body.splitlines()
                        if l.strip().startswith("http")]
            if urls:
                self._handle_links(urls, f.get("name") or "Extension-Link", None)
            self._ok()
            return

        # --- add: Klartext-Links (Click'n'Load 1) ---
        links = [l.strip() for l in body.splitlines()
                 if l.strip().startswith("http")]
        if not links:
            f = decode_cnl_form(body)
            if f.get("urls"):
                links = [l.strip() for l in f["urls"].splitlines()
                         if l.strip().startswith("http")]
        if links:
            self._handle_links(links, "CNL-Paket", None)
        self._ok()

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except Exception as e:
            self._log("ERROR", str(e)[:120])

    def _handle_links(self, links: list[str], name: str, passwords: str | None):
        """Angekommene Links als Paket anlegen + automatisch starten."""
        pw_list = [p.strip() for p in (passwords or "").splitlines()
                   if p.strip()] if passwords else []
        pid = store.add_package((name or "CNL2-Paket")[:120],
                                password=pw_list[0] if pw_list else None)
        for l in links:
            store.add_download(pid, l, status="queued")
        store.q("UPDATE downloads SET status='queued' "
                "WHERE package_id=? AND status='new'", (pid,))
        store.update_package(pid, status="downloading")


def start_receiver(port: int = 9666, host: str = "127.0.0.1"):
    """CNL2-Server starten (nicht blockierend, daemon-thread)."""
    srv = ThreadingHTTPServer((host, port), CNL2Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True,
                         name="cnl2-receiver")
    t.start()
    return srv
