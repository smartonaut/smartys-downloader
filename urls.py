"""Hoster-Erkennung + URL-Parsing.

Statisch: bekannte Container-/Seiten-Dienste (filecrypt, hide.cx, data-load).
Dynamisch: DebridLink (353+) und Real-Debrid (281) liefern ihre unterstützten
Hoster-Domains — wir laden sie beim Start und erkennen damit JEDE Szene-URL.
(Das war PyLoads größter Trumpf; hier nachgebaut, aber ohne PyLoads Ballast.)
"""
import re
import time
from urllib.parse import urlparse

# --- Container-/Seiten-Dienste (nicht Debrid-Hoster) ---
CONTAINER_MAP = {
    "filecrypt.cc": "filecrypt",
    "filecrypt.co": "filecrypt",
    "filecrypt.to": "filecrypt",
    "hide.cx": "hidecx",
    "data-load.me": "dataload",
    "funxd.site": "funxd",
    "serienfans.org": "serienfans",
    "filmfans.org": "filmfans",
    "tolink.to": "tolink",
}

# Statische Basis (Fallback wenn die API-Liste nicht lädt)
HOSTER_MAP = {
    "rapidgator.net": "rapidgator",
    "rg.to": "rapidgator",
    "ddownload.com": "ddownload",
    "ddl.to": "ddownload",
    "turbobit.net": "turbobit",
    "turb.to": "turbobit",
    "nitroflare.com": "nitroflare",
    "nitro.download": "nitroflare",
    "1fichier.com": "1fichier",
    "filefactory.com": "filefactory",
    "katfile.com": "katfile",
    "mega.nz": "mega",
    "uploadhaven.com": "uploadhaven",
}

URL_RE = re.compile(r'https?://[^\s<>"\']+', re.I)
FILECRYPT_RE = re.compile(r'filecrypt\.(?:cc|co|to)/', re.I)

# --- Dynamische Debrid-Hoster-Liste (mit Cache) ---
_dynamic_hosts: dict[str, str] = {}   # domain → hoster-name
_dynamic_loaded = 0.0
_DYNAMIC_TTL = 6 * 3600  # 6h


def _hoster_name(domain: str) -> str:
    """rapidgator.net → rapidgator | www.ddl.to → ddl"""
    d = domain.lower().removeprefix("www.")
    parts = d.split(".")
    if len(parts) >= 2:
        return parts[0]
    return d


def load_dynamic_hosters(force: bool = False, **legacy_keys) -> int:
    """Hoster-Domains ALLER konfigurierter Multihoster-Dienste laden.

    Nutzt das debrid-Registry (RD, DL, AllDebrid, Premiumize, TorBox,
    EasyDebrid). Fehler pro Dienst sind nicht fatal.
    """
    global _dynamic_loaded
    if not force and _dynamic_hosts and time.time() - _dynamic_loaded < _DYNAMIC_TTL:
        return len(_dynamic_hosts)

    try:
        from .debrid import DebridRouter
        router = DebridRouter()
        for dom in router.hosters():
            dom = dom.lower().removeprefix("www.").strip()
            if dom and dom not in CONTAINER_MAP:
                _dynamic_hosts[dom] = _hoster_name(dom)
    except Exception:
        pass

    _dynamic_loaded = time.time()
    return len(_dynamic_hosts)


def normalize_url(url: str) -> str:
    url = url.strip().strip('`').strip('\'').strip('"')
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def extract_urls(text: str) -> list[str]:
    """Alle URLs aus beliebigem Text ziehen (für Clipboard)."""
    return [normalize_url(u) for u in URL_RE.findall(text)]


def _domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def get_hoster(url: str) -> str | None:
    """Hoster-Name für eine URL oder None.

    Reihenfolge: Container-Dienste → statische Map → dynamische Debrid-Liste.
    """
    dom = _domain_of(url)
    if not dom:
        return None
    if dom in CONTAINER_MAP:
        return CONTAINER_MAP[dom]
    if dom in HOSTER_MAP:
        return HOSTER_MAP[dom]
    if dom in _dynamic_hosts:
        return _dynamic_hosts[dom]
    return None


def is_container(url: str) -> bool:
    return _domain_of(url) in CONTAINER_MAP


def is_filecrypt(url: str) -> bool:
    return bool(FILECRYPT_RE.search(url)) or _domain_of(url).startswith("filecrypt.")


def is_direct_file(url: str, name_hint: str = "") -> bool:
    """Direkter Download (kein Hoster dazwischen)? Grobe Heuristik."""
    exts = (".rar", ".zip", ".7z", ".mkv", ".mp4", ".avi", ".mp3", ".iso",
            ".exe", ".apk", ".pdf", ".epub", ".flac", ".wma", ".wmv", ".ts")
    low = (url.split("?")[0]).lower()
    return low.endswith(exts) or any(name_hint.lower().endswith(e) for e in exts)