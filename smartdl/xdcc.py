"""XDCC-Orchestrierung: IRC verbinden → xdcc send → DCC-Transfer.

URL-Format (source_url in der downloads-Tabelle):
    xdcc://<network>/<bot>/<pack_number>

Die Ziel-Datei wird DIREKT nach DOWNLOAD_DIR geschrieben (nicht erst über
Debrid/HTTP) — danach übernimmt der bestehende Postprocess-Pfad.
"""
import time

from . import config, keystore
from .irc import IRCClient, IRCError
from .dcc import receive, parse_dcc_send, DCCError


def parse_xdcc_url(url: str) -> tuple[str, str, str, str]:
    """xdcc://Network/Bot/42[?ch=#channel] → (network, bot, pack, channel)."""
    rest = url[len("xdcc://"):]
    base, _, qs = rest.partition("?")
    parts = base.split("/")
    if len(parts) < 3:
        raise ValueError(f"ungültige XDCC-URL: {url}")
    channel = ""
    if qs.startswith("ch="):
        channel = qs[3:]
    return parts[0], parts[1], parts[2], channel


def _network_cfg(network: str) -> dict:
    cfg = config.IRC_NETWORKS.get(network)
    if not cfg:
        raise IRCError(f"unbekanntes IRC-Netzwerk: {network}")
    return cfg


def nickserv_password(network: str) -> str:
    """NickServ-Passwort aus dem verschlüsselten Keystore."""
    return keystore.get_service_key(f"irc_nickserv_{network.lower()}") or ""


def _irc_user_settings(network: str = "") -> dict:
    """Effektive IRC-Einstellungen des Nutzers: Settings-Tabelle > env/config.

    Der Nick ist PRO NETZ konfigurierbar (irc_nicks als JSON-Dict), mit dem
    globalen irc_nick als Fallback. Enthält KEINE Secrets (NickServ-Passwort
    liegt im Keystore).
    """
    from . import store
    import json as _json
    nicks: dict = {}
    raw = store.get_setting("irc_nicks", "")
    if raw:
        try:
            nicks = _json.loads(raw)
        except (_json.JSONDecodeError, ValueError):
            nicks = {}
    nick = nicks.get(network, "") if network else ""
    if not nick:
        nick = store.get_setting("irc_nick", config.IRC_NICK)
    return {
        "nick": nick,
        "user": store.get_setting("irc_user", config.IRC_USER),
        "realname": store.get_setting("irc_realname", config.IRC_REALNAME),
    }


def _wait_for_dcc_offer(client: IRCClient, bot: str, timeout: float = 90.0):
    """Auf das DCC-SEND-Offer des Bots warten → dict (filename/ip/port/size).

    Der Bot kann erst eine 'queued'-NOTICE schicken oder langsam antworten —
    Socket-Timeouts werden deshalb NICHT als Fehler gewertet, wir warten bis
    zum Deadline einfach weiter.
    """
    import socket as _socket
    deadline = time.time() + timeout
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise IRCError(f"kein DCC-SEND von {bot} innerhalb {timeout:.0f}s")
        client.sock.settimeout(max(1.0, remaining))
        try:
            line = client.read_line()
        except (TimeoutError, _socket.timeout):
            continue  # Bot noch nicht soweit (Queue/Slot) — weiter warten
        # nur Zeilen vom Bot betrachten
        prefix = f":{bot}!" if "!" in line and line.startswith(":") else None
        if prefix and not line.startswith(prefix):
            # Zeile von wem anders — überspringen (aber PING wurde schon behandelt)
            continue
        if "\x01DCC SEND " in line:
            offer = parse_dcc_send(line)
            if offer:
                return offer
        # Sonst: weiterlesen (queued-notice, etc.)


def fetch(network: str, bot: str, pack: str, dest: str,
          filename: str = "", size: int = 0, channel: str = "",
          progress_cb=None, stop_event=None) -> dict:
    """Einen XDCC-Pack ziehen. Blockierend. Liefert {ok, filename, size}."""
    cfg = _network_cfg(network)
    uset = _irc_user_settings(network)
    base_nick = uset["nick"] or "user"

    # EINDEUTIGER Nick pro Download: parallele Downloads kollidieren sonst
    # auf demselben Nick („433 nickname in use") und der zweite hängt im
    # register()-Timeout. BEAST-X-Bots servieren auch unregistrierte Nicks
    # (verifiziert) — der Random-Suffix ist also unkritisch.
    import random
    nick = f"{base_nick}{random.randint(1000, 9999)}"

    client = IRCClient(
        host=cfg["host"], port=cfg.get("port", 6697),
        use_ssl=cfg.get("ssl", True),
        nick=nick, user=uset["user"] or "user",
        realname=uset["realname"] or "Smart Downloader",
    )
    try:
        client.connect()
        client.register()
        if cfg.get("nickserv"):
            client.identify("NickServ", nickserv_password(network))
        # Channel beitreten: konfigurierte Download-Channels des Netzes
        # + der Kanal aus dem Suchergebnis, falls abweichend.
        # Manche Bots servieren nur, wenn man in ihren Channels ist.
        chans = list(cfg.get("channels", []))
        if channel and channel not in chans:
            chans.append(channel)
        for ch in chans:
            client.join(ch)
        if chans:
            time.sleep(1.5)

        client.privmsg(bot, f"xdcc send #{pack}")

        offer = _wait_for_dcc_offer(client, bot)
        got_name = offer["filename"] or filename
        got_size = offer["size"] or size

        received = receive(
            offer["ip"], offer["port"], got_size, dest,
            offset=0, progress_cb=progress_cb, stop_event=stop_event,
        )
        return {"ok": True, "filename": got_name, "size": received}
    finally:
        client.close()
