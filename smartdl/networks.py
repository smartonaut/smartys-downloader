"""Katalog öffentlicher IRC-Netzwerke.

Nutzerdaten bleiben Nutzerdaten: dieser Katalog ist nur ein **Vorschlag**, was
beim Einrichten zur Auswahl steht. Aktiv wird ein Netz erst, wenn es in den
Einstellungen (`irc_networks`) steht — dort landen auch die Channels, weil die
zur jeweiligen Quelle gehören und nicht zum Netz.

Alle Einträge wurden live geprüft (Registrierung bis `001`, Netzwerkname aus
`005 NETWORK=` gelesen). `checked` nennt das Datum der letzten Prüfung, damit
klar ist, wie alt die Aussage ist. Ports ohne TLS sind bewusst so eingetragen:
mehrere Netze haben dort Zertifikate, die nicht zum Hostnamen passen — ein
`ssl: true` würde dort nur mit abgeschalteter Prüfung funktionieren, und das
ist keine gute Voreinstellung.

`xdcc: true` markiert Netze, auf denen XDCC-Bots üblich sind.
"""
from __future__ import annotations

CHECKED = "2026-11-21"

PRESETS: dict[str, dict] = {
    "Abjects": {
        "host": "irc.eu.abjects.net", "port": 6697, "ssl": True, "nickserv": True,
        "xdcc": True,
        "note": "Szene-Netz mit vielen XDCC-Bots; Downloads meist nur mit "
                "registriertem Nick.",
    },
    "Rizon": {
        "host": "irc.rizon.net", "port": 6697, "ssl": True, "nickserv": True,
        "xdcc": True,
        "note": "Großes Netz, viele XDCC-Channels, Anmeldung bei NickServ üblich.",
    },
    "SceneP2P": {
        "host": "irc.scenep2p.net", "port": 6697, "ssl": True, "nickserv": True,
        "xdcc": True,
        "note": "Szene-Netz, XDCC-lastig, Release-Channels statt Chat.",
    },
    "DALnet": {
        "host": "irc.dal.net", "port": 6697, "ssl": True, "nickserv": True,
        "xdcc": True,
        "note": "Klassisches Netz, noch aktive XDCC-Bots.",
    },
    "UnderNet": {
        "host": "eu.undernet.org", "port": 6667, "ssl": False, "nickserv": False,
        "xdcc": True,
        "note": "Ohne TLS erreichbar; XDCC-Server über die Channel-Liste suchen.",
    },
    "EFNet": {
        "host": "irc.efnet.org", "port": 6667, "ssl": False, "nickserv": False,
        "xdcc": False,
        "note": "Ohne TLS erreichbar (Zertifikat passt nicht zum Hostnamen).",
    },
    "QuakeNet": {
        "host": "irc.quakenet.org", "port": 6667, "ssl": False, "nickserv": False,
        "xdcc": False,
        "note": "Ohne TLS erreichbar; Q-Authentifizierung statt NickServ.",
    },
    "IRC-Highway": {
        "host": "irc.irchighway.net", "port": 6667, "ssl": False, "nickserv": False,
        "xdcc": True,
        "note": "Bekannt für E-Book- und Comic-XDCC-Channels; TLS-Zertifikat ist "
                "selbstsigniert, deshalb ohne TLS.",
    },
    "Aniverse": {
        "host": "irc.aniverse.com", "port": 6697, "ssl": True, "nickserv": True,
        "xdcc": False,
        "note": "Kleineres Netz mit Anime-/Cartoon-Channels.",
    },
    "Snoonet": {
        "host": "irc.snoonet.org", "port": 6697, "ssl": True, "nickserv": True,
        "xdcc": False,
        "note": "Reddit-nahes Netz, viele Topic-Channels.",
    },
    "OFTC": {
        "host": "irc.oftc.net", "port": 6697, "ssl": True, "nickserv": True,
        "xdcc": False,
        "note": "Freie-Software-Netz (Debian, Tor); kein XDCC.",
    },
    "hackint": {
        "host": "irc.hackint.org", "port": 6697, "ssl": True, "nickserv": True,
        "xdcc": False,
        "note": "Deutschsprachiges Hackerspace-Netz; kein XDCC.",
    },
}


def as_network(name: str) -> dict | None:
    """Preset in die Form der Einstellungen bringen (ohne Channels).

    Channels bleiben leer: die gehören zur Quelle und werden vom Nutzer bzw.
    aus dem Suchergebnis ergänzt.
    """
    p = PRESETS.get(name)
    if not p:
        return None
    return {
        "host": p["host"],
        "port": int(p["port"]),
        "ssl": bool(p["ssl"]),
        "nickserv": bool(p["nickserv"]),
        "channels": [],
    }


def list_presets() -> list[dict]:
    """Katalog als Liste für die Oberfläche (Name, Host, Flags, Hinweis)."""
    out = []
    for name, p in PRESETS.items():
        out.append({
            "name": name,
            "host": p["host"],
            "port": int(p["port"]),
            "ssl": bool(p["ssl"]),
            "nickserv": bool(p["nickserv"]),
            "xdcc": bool(p.get("xdcc", False)),
            "note": p.get("note", ""),
            "checked": CHECKED,
        })
    return out
