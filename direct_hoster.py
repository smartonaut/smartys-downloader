"""DIRECT_HOSTER — Fallback-Schiene für Hoster, die KEIN Debrid-Dienst anbietet.

Wenn der Debrid-Router einen Hoster nicht kennt (filejoker, webshare.cz,
krakenfiles, ...), versucht diese Schiene den Free-Download direkt:
  1. Hoster-Seite laden (curl_cffi mit Chrome-TLS)
  2. Wartezeit/Captcha erkennen (Free-Tier) — Premium-Accounts via Cookies umgehen das
  3. Direkt-Link aus der Download-Form extrahieren

Premium-Accounts: Hoster-Cookies in ~/.config/smartys-downloader/hoster_cookies/
pro hoster eine JSON: {"cookies": {"name": "value"}, "user_agent": "..."}.

Plugin-Struktur: pro Hoster eine Klasse in HOSTERS, gemeinsame Logik in
_DirectHosterBase. XFS-Forks (ddownload-artig) deckt XfsHoster ab.
"""
import json
import re
import time
from pathlib import Path
from curl_cffi import requests as creq
from .config import CONFIG_DIR
from .urls import _domain_of

COOKIES_DIR = CONFIG_DIR / "hoster_cookies"


class DirectHosterError(Exception):
    pass


class _DirectHosterBase:
    """Basisklasse: Free-Download mit Retry, Premium via Cookie-Datei."""
    name = "base"

    # Subklassen setzen:
    DOMAINS: list[str] = []

    def __init__(self):
        self.session = creq.Session(impersonate="chrome")
        self._load_cookies()

    def _cookie_file(self) -> Path:
        return COOKIES_DIR / f"{self.name}.json"

    def _load_cookies(self):
        f = self._cookie_file()
        if f.exists():
            try:
                d = json.loads(f.read_text())
                for k, v in d.get("cookies", {}).items():
                    self.session.cookies.set(k, v)
            except Exception:
                pass

    def has_premium(self) -> bool:
        return self._cookie_file().exists()

    def resolve(self, url: str) -> dict:
        """Hoster-Link → {url, filename, size, via}."""
        raise NotImplementedError


# ============================================================================
# XFS-Grundmuster (Click-N-Load-artige Free-Hoster)
# ============================================================================
class XfsHoster(_DirectHosterBase):
    """XFileSharing-Grundmuster: zwei Formulare (free/premium) → direkter Link.

    Deckt die typischen 'slow download'-Seiten ab: Formular mit
    method_free → Wartecountdown → Download-Link im zweiten Formular.
    Premium-Cookies überspringen den Countdown.
    """
    name = "xfs"

    def resolve(self, url: str) -> dict:
        r = self.session.get(url, timeout=25)
        if r.status_code != 200:
            raise DirectHosterError(f"HTTP {r.status_code}")
        html = r.text
        self.url = str(r.url)

        # Dateiname aus dem Titel
        m = re.search(r'<title[^>]*>([^<]{3,120})</title>', html)
        filename = ""
        if m:
            title = m.group(1)
            # "filename.rar - Hoster" oder "Hoster - filename"
            title = re.sub(r'\s*[-–|]\s*(Download|Free|Fast|secure|Hoster.*|online storage.*)?\s*$', '', title, flags=re.I).strip()
            filename = title.split(" - ")[0].strip()

        # Premium-Kurzform: direkt-Link im html (premium-user)
        dl = re.search(r'href="(https?://[^"]+/dl/[^"]+)"', html) \
             or re.search(r'href="(https?://[^"]+\.(?:rar|zip|7z|mkv|mp4|avi|ts|iso)[^"]*)"', html)
        if dl and self.has_premium():
            return {"url": dl.group(1), "filename": filename,
                    "size": 0, "via": f"direct-{self.name}"}

        # Free: form mit method_free abschicken
        form = re.search(
            r'<form[^>]*action="([^"]*)"[^>]*>.*?name="method_free"[^>]*value="([^"]*)"',
            html, re.S)
        if not form:
            form = re.search(
                r'<form[^>]*action="([^"]*)"[^>]*>.*?name="method_isfree"[^>]*value="([^"]*)"',
                html, re.S)
        if not form:
            raise DirectHosterError("kein free-formular gefunden (premium nötig?)")

        action, method = form.group(1), form.group(2)
        action_url = action if action.startswith("http") else self.url

        r2 = self.session.post(action_url, data={"method_free": method,
                                                 "method_isfree": method},
                               timeout=25)
        html2 = r2.text

        # Countdown?
        wait = re.search(r'countdown[^0-9]*(\d+)\s*(?:seconds|Sekunden)', html2, re.I)
        if wait:
            time.sleep(min(int(wait.group(1)), 60))

        # Direkt-Link im zweiten schritt
        dl = re.search(r'<form[^>]*action="(https?://[^"]+)"[^>]*>.*?name="download1?"', html2, re.S) \
             or re.search(r'href="(https?://[^"]+/d/[^"]+)"', html2) \
             or re.search(r'href="(https?://pr\d*\.[^"]+)"', html2)
        if not dl:
            # direkter href mit token
            dl = re.search(r'href="(https?://[^"]+\?(?:token|k|id)=[^"]+)"', html2)
        if not dl:
            raise DirectHosterError("kein download-link nach free-form (captcha nötig?)")

        return {"url": dl.group(1), "filename": filename,
                "size": 0, "via": f"direct-{self.name}"}


# ============================================================================
# Konkrete Hosters
# ============================================================================
class FileJoker(XfsHoster):
    name = "filejoker"
    DOMAINS = ["filejoker.net"]


class KrakenFiles(XfsHoster):
    name = "krakenfiles"
    DOMAINS = ["krakenfiles.com"]


class WebshareCz(_DirectHosterBase):
    """webshare.cz — eigener API-artiger Flow (POST /download/ mit cookie)."""
    name = "webshare"
    DOMAINS = ["webshare.cz"]

    def resolve(self, url: str) -> dict:
        m = re.search(r'webshare\.cz/(?:file|stahnout|file-stat)/([a-z0-9]+)/', url) \
            or re.search(r'webshare\.cz/#!/file/([a-z0-9]+)', url)
        if not m:
            raise DirectHosterError("webshare: keine file-id in url")
        fid = m.group(1)

        api = f"https://webshare.cz/api/{fid}/"
        r = self.session.post(api, data={"download": "1"}, timeout=25)
        if r.status_code != 200:
            # fallback: seite laden und button suchen
            r2 = self.session.get(url, timeout=25)
            dl = re.search(r'href="(https?://.*ws\.cdn\.cz[^"]*)"', r2.text) \
                 or re.search(r'href="(https?://[^"]*/download[^"]*)"', r2.text)
            if not dl:
                raise DirectHosterError("webshare: kein link (premium nötig?)")
            return {"url": dl.group(1), "filename": fid, "size": 0,
                    "via": "direct-webshare"}
        d = r.json()
        link = d.get("link") or d.get("download_link")
        if not link:
            raise DirectHosterError("webshare: keine link in antwort")
        return {"url": link, "filename": d.get("filename", fid),
                "size": int(d.get("size", 0) or 0), "via": "direct-webshare"}


class F2H(XfsHoster):
    name = "f2h"
    DOMAINS = ["f2h.to", "file2host.net"]


# ============================================================================
# Registry
# ============================================================================
HOSTERS: dict[str, type[_DirectHosterBase]] = {
    "filejoker": FileJoker,
    "krakenfiles": KrakenFiles,
    "webshare": WebshareCz,
    "f2h": F2H,
}


def _find_hoster(url: str) -> _DirectHosterBase | None:
    dom = _domain_of(url)
    for cls in HOSTERS.values():
        for d in cls.DOMAINS:
            if dom == d or dom.endswith("." + d):
                return cls()
    return None


def can_resolve(url: str) -> bool:
    return _find_hoster(url) is not None


def resolve_direct(url: str) -> dict:
    """Direkt-Download versuchen. Wirft DirectHosterError wenn Hoster unbekannt."""
    h = _find_hoster(url)
    if not h:
        raise DirectHosterError(f"kein direct-hoster-plugin für {url}")
    return h.resolve(url)