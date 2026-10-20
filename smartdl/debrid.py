"""Multihoster-Anbindung — offenes Dienst-Registry.

Unterstützt: Real-Debrid, DebridLink, AllDebrid, Premiumize.me, TorBox,
EasyDebrid, LinkSnappy, Offcloud. Neue Dienste = neue Unterklasse +
Registrierung in SERVICES (siehe multihosts.de-Marktübersicht).

Jeder Dienst implementiert:
  available   → hat Key/Premium
  hosters()   → Liste unterstützter Hoster-Domains (für die dynamische Liste)
  unrestrict  → Hoster-Link → {url, filename, size, via}
  user()      → Account-Info (für die GUI)

Der Router probiert in konfigurierbarer Reihenfolge; Multi-Accounts pro Dienst
sind möglich (Keys Komma-getrennt in der ENV-Variable).

API-Referenzen:
  Real-Debrid   https://api.real-debrid.com/rest/1.0  (Bearer)
  DebridLink    https://debrid-link.fr/api/v2         (Bearer)
  AllDebrid     https://api.alldebrid.com/v4           (Bearer)
  Premiumize    https://premiumize.me/api              (apikey-Param)
  TorBox        https://api.torbox.app/v1/api          (Bearer)
  EasyDebrid    https://easydebrid.com/api/v1          (Bearer)
"""
import json
import os
import httpx
from .config import DEBRID_ORDER

from curl_cffi import requests as creq


class DebridError(Exception):
    pass


class _DebridBase:
    name = "base"

    def __init__(self, api_key: str):
        self.api_key = api_key

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def hosters(self) -> list[str]:
        return []

    def unrestrict(self, url: str) -> dict:
        raise NotImplementedError

    def user(self) -> dict:
        return {}


# ============================================================================
# Real-Debrid
# ============================================================================
class RealDebrid(_DebridBase):
    name = "realdebrid"
    BASE = "https://api.real-debrid.com/rest/1.0"

    def _hdr(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    def check_cache(self, url: str) -> dict | None:
        """Gibt's den Link schon im RD-Cache (instant)?"""
        try:
            with httpx.Client(timeout=15) as c:
                r = c.get(f"{self.BASE}/torrents/instantAvailability/{url}",
                          headers=self._hdr())
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None

    def hosters(self) -> list[str]:
        try:
            r = creq.get(f"{self.BASE}/hosts/domains", headers=self._hdr(),
                         impersonate="chrome", timeout=20)
            return r.json() if r.status_code == 200 else []
        except Exception:
            return []

    def unrestrict(self, url: str) -> dict:
        """Hoster-Link → {url, filename, size, host} — der Kern-Call."""
        with httpx.Client(timeout=30) as c:
            r = c.post(f"{self.BASE}/unrestrict/link",
                       headers=self._hdr(), data={"link": url})
        if r.status_code == 401:
            raise DebridError("realdebrid: API-Key ungültig (401)")
        if r.status_code == 403:
            raise DebridError("realdebrid: Account gesperrt/kein Premium (403)")
        if r.status_code != 200:
            raise DebridError(f"realdebrid: HTTP {r.status_code} — {r.text[:120]}")
        d = r.json()
        return {
            "url": d["download"],
            "filename": d.get("filename", ""),
            "size": d.get("filesize", 0),
            "host": d.get("host", "realdebrid"),
            "supported": d.get("supported", 0),
        }

    def user(self) -> dict:
        with httpx.Client(timeout=15) as c:
            r = c.get(f"{self.BASE}/user", headers=self._hdr())
        return r.json() if r.status_code == 200 else {}


# ============================================================================
# DebridLink
# ============================================================================
class DebridLink(_DebridBase):
    name = "debridlink"
    BASE = "https://debrid-link.fr/api/v2"

    def _hdr(self):
        return {"Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/x-www-form-urlencoded"}

    def hosters(self) -> list[str]:
        try:
            r = creq.get(f"{self.BASE}/downloader/hostnames",
                         headers=self._hdr(), impersonate="chrome", timeout=20)
            return r.json().get("value", []) if r.status_code == 200 else []
        except Exception:
            return []

    def unrestrict(self, url: str) -> dict:
        with httpx.Client(timeout=30) as c:
            r = c.post(f"{self.BASE}/downloader/add",
                       headers=self._hdr(), data={"url": url})
        if r.status_code in (401, 403):
            raise DebridError("debridlink: API-Key ungültig oder kein Premium")
        if r.status_code == 404:
            raise DebridError("debridlink: Hoster nicht unterstützt")
        try:
            data = r.json()
        except Exception:
            raise DebridError(f"debridlink: HTTP {r.status_code}")
        if r.status_code != 200:
            err = data.get("error", f"HTTP {r.status_code}")
            raise DebridError(f"debridlink: {err}")
        d = data.get("value") or data.get("data") or {}
        if not d or not d.get("downloadUrl"):
            raise DebridError("debridlink: keine downloadUrl in Antwort")
        return {
            "url": d["downloadUrl"],
            "filename": d.get("name", ""),
            "size": d.get("size", 0),
            "host": "debridlink",
        }

    def user(self) -> dict:
        with httpx.Client(timeout=15) as c:
            r = c.get(f"{self.BASE}/account/infos",
                      params={"infos": "account"}, headers=self._hdr())
        return r.json().get("value", {}) if r.status_code == 200 else {}


# ============================================================================
# AllDebrid
# ============================================================================
class AllDebrid(_DebridBase):
    name = "alldebrid"
    BASE = "https://api.alldebrid.com/v4"

    def _hdr(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    def hosters(self) -> list[str]:
        try:
            r = creq.get(f"{self.BASE}/hosts/", headers=self._hdr(),
                         impersonate="chrome", timeout=20)
            data = r.json().get("data", {})
            hosts = []
            for group in data.get("hosts", {}).values():
                hosts.extend(group.get("domains", []))
            return hosts
        except Exception:
            return []

    def unrestrict(self, url: str) -> dict:
        with httpx.Client(timeout=30) as c:
            r = c.get(f"{self.BASE}/link/unlock",
                      params={"link": url}, headers=self._hdr())
        data = r.json()
        if data.get("status") != "success":
            err = data.get("error", {}).get("message", "unbekannt")
            raise DebridError(f"alldebrid: {err}")
        d = data.get("data", {})
        return {
            "url": d.get("link"),
            "filename": d.get("filename", ""),
            "size": d.get("filesize", 0),
            "host": "alldebrid",
        }

    def user(self) -> dict:
        with httpx.Client(timeout=15) as c:
            r = c.get(f"{self.BASE}/user/", headers=self._hdr())
        return r.json().get("data", {}) if r.status_code == 200 else {}


# ============================================================================
# Premiumize.me
# ============================================================================
class Premiumize(_DebridBase):
    name = "premiumize"
    BASE = "https://premiumize.me/api"

    def hosters(self) -> list[str]:
        try:
            r = creq.get(f"{self.BASE}/services/list",
                         params={"apikey": self.api_key},
                         impersonate="chrome", timeout=20)
            if r.status_code != 200:
                return []
            out = []
            for svc in r.json():
                doms = svc.get("domains", "")
                out.extend(d.strip() for d in doms.split(",") if d.strip())
            return out
        except Exception:
            return []

    def unrestrict(self, url: str) -> dict:
        with httpx.Client(timeout=30) as c:
            r = c.post(f"{self.BASE}/transfer/directdl",
                       data={"apikey": self.api_key, "src": url})
        d = r.json()
        if d.get("status") != "success":
            raise DebridError(f"premiumize: {d.get('message', 'fehler')}")
        content = d.get("content", {})
        return {
            "url": content.get("link"),
            "filename": content.get("name", url.split("/")[-1]),
            "size": content.get("size", 0),
            "host": "premiumize",
        }

    def user(self) -> dict:
        with httpx.Client(timeout=15) as c:
            r = c.get(f"{self.BASE}/account/info",
                      params={"apikey": self.api_key})
        return r.json() if r.status_code == 200 else {}


# ============================================================================
# TorBox
# ============================================================================
class TorBox(_DebridBase):
    name = "torbox"
    BASE = "https://api.torbox.app/v1/api"

    def _hdr(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    def hosters(self) -> list[str]:
        try:
            r = creq.get(f"{self.BASE}/web/hosters", headers=self._hdr(),
                         impersonate="chrome", timeout=20)
            data = r.json().get("data", [])
            return [h.get("root_domain", "") for h in data if h.get("root_domain")]
        except Exception:
            return []

    def unrestrict(self, url: str) -> dict:
        with httpx.Client(timeout=30) as c:
            r = c.get(f"{self.BASE}/web/debrid",
                      params={"url": url}, headers=self._hdr())
        d = r.json()
        if not d.get("success"):
            raise DebridError(f"torbox: {str(d.get('error'))[:120]}")
        data = d.get("data", "")
        if isinstance(data, str) and data.startswith("http"):
            return {"url": data, "filename": url.split("/")[-1],
                    "size": 0, "host": "torbox"}
        raise DebridError("torbox: unerwartete antwort")

    def user(self) -> dict:
        with httpx.Client(timeout=15) as c:
            r = c.get(f"{self.BASE}/user/me", headers=self._hdr())
        return r.json().get("data", {}) if r.status_code == 200 else {}


# ============================================================================
# EasyDebrid
# ============================================================================
class EasyDebrid(_DebridBase):
    name = "easydebrid"
    BASE = "https://easydebrid.com/api/v1"

    def _hdr(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    def hosters(self) -> list[str]:
        try:
            r = creq.get(f"{self.BASE}/hosts", headers=self._hdr(),
                         impersonate="chrome", timeout=20)
            return r.json() if r.status_code == 200 else []
        except Exception:
            return []

    def unrestrict(self, url: str) -> dict:
        with httpx.Client(timeout=30) as c:
            r = c.post(f"{self.BASE}/download",
                       json={"url": url}, headers=self._hdr())
        if r.status_code != 200:
            raise DebridError(f"easydebrid: HTTP {r.status_code} — {r.text[:120]}")
        d = r.json()
        return {
            "url": d.get("url") or d.get("direct_link"),
            "filename": d.get("filename", ""),
            "size": d.get("size", 0),
            "host": "easydebrid",
        }

    def user(self) -> dict:
        with httpx.Client(timeout=15) as c:
            r = c.get(f"{self.BASE}/account", headers=self._hdr())
        return r.json() if r.status_code == 200 else {}


# ============================================================================
# LinkSnappy
# ============================================================================
class LinkSnappy(_DebridBase):
    """https://linksnappy.com — API /api/linkgen (auth via apiKey-Param)."""
    name = "linksnappy"
    BASE = "https://linksnappy.com/api"

    def hosters(self) -> list[str]:
        try:
            r = creq.get(f"{self.BASE}/FILEHOSTS-STATS",
                         params={"o": "json", "auth": self.api_key},
                         impersonate="chrome", timeout=20)
            if r.status_code != 200:
                return []
            data = r.json()
            hosts = data.get("hosts", {})
            if isinstance(hosts, dict):
                return list(hosts.keys())
            return []
        except Exception:
            return []

    def unrestrict(self, url: str) -> dict:
        import urllib.parse
        gen = urllib.parse.quote(json.dumps({"link": url}))
        with httpx.Client(timeout=30) as c:
            r = c.get(f"{self.BASE}/linkgen",
                      params={"genLinks": gen, "auth": self.api_key})
        try:
            data = r.json()
        except Exception:
            raise DebridError(f"linksnappy: HTTP {r.status_code}")
        links = data.get("links", [{}])
        entry = links[0] if links else {}
        if entry.get("status") != "OK":
            raise DebridError(f"linksnappy: {entry.get('error', 'fehlgeschlagen')}")
        return {
            "url": entry.get("generated"),
            "filename": entry.get("filename", ""),
            "size": 0,
            "host": entry.get("filehost", "linksnappy"),
        }

    def user(self) -> dict:
        with httpx.Client(timeout=15) as c:
            r = c.get(f"{self.BASE}/ACCOUNT",
                      params={"auth": self.api_key, "o": "json"})
        return r.json() if r.status_code == 200 else {}


# ============================================================================
# Offcloud
# ============================================================================
class Offcloud(_DebridBase):
    """https://offcloud.com — API api.offcloud.com (cookie/apikey)."""
    name = "offcloud"
    BASE = "https://api.offcloud.com"

    def hosters(self) -> list[str]:
        try:
            r = creq.post(f"{self.BASE}/cloud/expired",
                          data={"apikey": self.api_key},
                          impersonate="chrome", timeout=20)
            # offcloud hoster-liste ist unter /host (statistik) — fallback:
            r2 = creq.get(f"{self.BASE}/host/status",
                          params={"apikey": self.api_key},
                          impersonate="chrome", timeout=20)
            if r2.status_code == 200:
                d = r2.json()
                if isinstance(d, list):
                    return [h.get("host", "") for h in d if h.get("host")]
        except Exception:
            pass
        return []

    def unrestrict(self, url: str) -> dict:
        with httpx.Client(timeout=30) as c:
            r = c.post(f"{self.BASE}/cloud",
                       data={"apikey": self.api_key, "url": url})
        try:
            data = r.json()
        except Exception:
            raise DebridError(f"offcloud: HTTP {r.status_code}")
        if data.get("isError"):
            raise DebridError(f"offcloud: {data.get('errorMessage', 'fehler')}")
        return {
            "url": data.get("url"),
            "filename": data.get("fileName", ""),
            "size": data.get("size", 0),
            "host": "offcloud",
        }

    def user(self) -> dict:
        with httpx.Client(timeout=15) as c:
            r = c.post(f"{self.BASE}/account/status",
                       data={"apikey": self.api_key})
        return r.json() if r.status_code == 200 else {}


# ============================================================================
# Registry + Router
# ============================================================================
SERVICES: dict[str, type[_DebridBase]] = {
    "realdebrid": RealDebrid,
    "debridlink": DebridLink,
    "alldebrid": AllDebrid,
    "premiumize": Premiumize,
    "torbox": TorBox,
    "easydebrid": EasyDebrid,
    "linksnappy": LinkSnappy,
    "offcloud": Offcloud,
}

ENV_VARS = {
    "realdebrid": "REALDEBRID_API_KEY",
    "debridlink": "DEBRIDLINK_API_KEY",
    "alldebrid": "ALLDEBRID_API_KEY",
    "premiumize": "PREMIUMIZE_API_KEY",
    "torbox": "TORBOX_API_KEY",
    "easydebrid": "EASYDEBRID_API_KEY",
    "linksnappy": "LINKSNAPPY_API_KEY",
    "offcloud": "OFFCLOUD_API_KEY",
}


def _stored_keys(svc_name: str) -> list[str]:
    """Keys aus dem verschlüsselten Store (GUI-verwaltet).

    Fallback: ENV-Variable (Komma-getrennt, Multi-Account) — für
    Headless-Setup ohne GUI.
    """
    keys: list[str] = []
    try:
        from . import keystore
        k = keystore.get_service_key(svc_name)
        if k:
            keys.append(k)
    except Exception:
        pass
    raw = os.getenv(ENV_VARS.get(svc_name, f"{svc_name.upper()}_API_KEY"), "") or ""
    keys.extend(x.strip() for x in raw.split(",") if x.strip())
    # dedup
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def build_services() -> list[_DebridBase]:
    """Alle konfigurierten Dienste + Accounts instanziieren.

    Keys kommen aus dem verschlüsselten Keystore (GUI) und/oder der ENV.
    """
    services: list[_DebridBase] = []
    for name, cls in SERVICES.items():
        for key in _stored_keys(name):
            services.append(cls(key))
    order = {n: i for i, n in enumerate(DEBRID_ORDER)}
    services.sort(key=lambda s: (order.get(s.name, 99), s.name))
    return [s for s in services if s.available]


class DebridRouter:
    """Probiert alle konfigurierten Dienste/Accounts in Reihenfolge."""

    def __init__(self, services: list[_DebridBase] | None = None):
        self.services = services if services is not None else build_services()

    @property
    def available(self) -> list[str]:
        return [s.name for s in self.services]

    def hosters(self) -> list[str]:
        """Union aller unterstützten Hoster-Domains (für urls.py)."""
        out: set[str] = set()
        for s in self.services:
            out.update(h.lower().removeprefix("www.") for h in s.hosters())
        return sorted(out)

    def unrestrict(self, url: str) -> dict:
        """Erster Dienst der den Link auflöst, gewinnt."""
        errors = []
        for svc in self.services:
            try:
                result = svc.unrestrict(url)
                result["via"] = svc.name
                return result
            except DebridError as e:
                errors.append(f"{svc.name}: {e}")
                continue
        raise DebridError(" | ".join(errors) if errors
                          else "kein Debrid-Dienst konfiguriert")
