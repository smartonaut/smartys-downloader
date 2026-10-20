"""DLC-Container entschlüsseln (pyLoad-Algorithmus, JD2-kompatibel).

DLC (Download Link Container) Aufbau:
  <base64-daten> || <letzte 88 base64-zeichen = key-fragment>

Ablauf (identisch zu pyLoad):
  1. Letzte 88 Zeichen (rc) an service.jdownloader.org schicken
  2. Service liefert den Container-Key — MIT DEM APP-KEY VERSCHLÜSSELT
  3. Key mit App-Key/IV entschlüsseln
  4. Daten-Teil mit diesem Key AES-entschlüsseln → XML
  5. XML: <package name=b64><file><url>b64</url></file></package>
"""
import base64
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from Crypto.Cipher import AES

# App-Key/IV des pylo-Desttypes (der Service verschlüsselt den
# Container-Key damit — gleiche Werte wie pyLoad)
_APP_KEY = b"cb99b5cbc24db398"
_APP_IV = b"9bc24cb995cb8db3"


def dlc_fetch(source: str) -> str:
    """DLC-Inhalt laden (curl_cffi gegen CF, Fallback plain)."""
    if not re.match(r"https?://", source):
        from pathlib import Path
        return Path(source).read_text(errors="replace")
    try:
        from curl_cffi import requests as creq
        s = creq.Session(impersonate="chrome")
        r = s.get(source, timeout=20)
        if r.status_code == 200 and len(r.text) > 50:
            return r.text
    except Exception:
        pass
    try:
        with urllib.request.urlopen(source, timeout=20) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def dlc_decrypt(dlc_b64: str) -> list[tuple[str, list[str]]]:
    """DLC-Container komplett entschlüsseln.

    Return: [(paketname, [urls]), ...]
    Wirft ValueError mit Klartext-Grund bei Fehlern.
    """
    raw = (dlc_b64 or "").strip()
    if len(raw) < 200:
        raise ValueError("DLC zu kurz")
    data = raw + "=" * (-len(raw) % 4)
    dlc_key = data[-88:]
    dlc_data = base64.b64decode(data[:-88])

    # 1. key-fragment (rc) an den jd2-service:
    api = ("http://service.jdownloader.org/dlcrypt/service.php"
           f"?srcType=dlc&destType=pylo&data={urllib.parse.quote(dlc_key)}")
    req = urllib.request.Request(api, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        content = r.read().decode()
    m = re.search(r"<rc>(.+)</rc>", content, re.S)
    if not m:
        raise ValueError(f"DLC-Service ohne <rc>: {content[:80]}")
    rc = base64.b64decode(m.group(1))[:16]

    # 2. service-key mit dem app-key entschluesseln:
    cipher = AES.new(_APP_KEY, AES.MODE_CBC, _APP_IV)
    key = iv = cipher.decrypt(rc)

    # 3. daten-teil entschluesseln → xml:
    cipher = AES.new(key, AES.MODE_CBC, iv)
    xml = base64.b64decode(cipher.decrypt(dlc_data)).decode("utf-8", errors="replace")

    # 4. packages parsen (alles im xml ist base64):
    root = ET.fromstring(xml)
    packages = []
    for pkg in root.iter("package"):
        try:
            pname = base64.b64decode(pkg.get("name") or "").decode("utf-8", "replace")
        except Exception:
            pname = "DLC-Paket"
        urls = []
        for f in pkg.iter("file"):
            u = f.find("url")
            if u is not None and (u.text or "").strip():
                try:
                    urls.append(base64.b64decode(u.text.strip()).decode("utf-8", "replace"))
                except Exception:
                    continue
        if urls:
            packages.append((pname, urls))
    return packages


def dlc_extract(source: str) -> list[str]:
    """DLC laden (URL/Pfad/Inhalt) → flache Liste aller Hoster-Links."""
    raw = (source or "").strip()
    # content oder url/pfad?
    if re.fullmatch(r"[A-Za-z0-9+/=\s]{100,}", raw or "x"):
        content = raw
    else:
        content = dlc_fetch(source)
    if not content:
        return []
    try:
        packages = dlc_decrypt(content)
    except Exception as e:
        print(f"[dlc] decrypt fehlgeschlagen: {str(e)[:120]}")
        return []
    urls: list[str] = []
    for _name, links in packages:
        urls.extend(links)
    return urls


def dlc_extract_packages(source: str) -> list[tuple[str, list[str]]]:
    """Wie dlc_extract, aber mit Paketnamen."""
    raw = (source or "").strip()
    if re.fullmatch(r"[A-Za-z0-9+/=\s]{100,}", raw or "x"):
        content = raw
    else:
        content = dlc_fetch(source)
    if not content:
        return []
    try:
        return dlc_decrypt(content)
    except Exception as e:
        print(f"[dlc] decrypt fehlgeschlagen: {str(e)[:120]}")
        return []


def is_dlc(url: str) -> bool:
    return ".dlc" in url.lower() and "filecrypt" not in url.lower()