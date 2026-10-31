"""Synchroner IRC-Client (SSL) für XDCC-Downloads.

Blockierend — läuft im Engine-Worker-Thread, kein asyncio nötig.
Bewusst schlank: NICK/USER-Registration, 001-Warten, NickServ-IDENTIFY,
JOIN, PRIVMSG und ein Zeilen-Reader der PING automatisch beantwortet.
"""
import socket
import ssl
import time


class IRCError(Exception):
    pass


class IRCClient:
    def __init__(self, host: str, port: int = 6697, use_ssl: bool = True,
                 nick: str = "OdinDL", user: str = "odin",
                 realname: str = "Odin Downloader"):
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.nick = nick
        self.user = user
        self.realname = realname
        self.sock: socket.socket | None = None
        self._buf = ""

    # ---------- Transport ----------
    def connect(self, timeout: float = 20.0) -> "IRCClient":
        s = socket.create_connection((self.host, self.port), timeout=timeout)
        if self.use_ssl:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            s = ctx.wrap_socket(s, server_hostname=self.host)
        s.settimeout(timeout)
        self.sock = s
        self.send_raw(f"NICK {self.nick}")
        self.send_raw(f"USER {self.user} 0 * :{self.realname}")
        return self

    def send_raw(self, line: str):
        self.sock.sendall((line + "\r\n").encode("utf-8", "replace"))

    def _read_until_crlf(self) -> str:
        while "\r\n" not in self._buf:
            data = self.sock.recv(4096)
            if not data:
                raise IRCError("Verbindung geschlossen")
            self._buf += data.decode("utf-8", "replace")
        line, self._buf = self._buf.split("\r\n", 1)
        return line

    def read_line(self) -> str:
        """Eine IRC-Zeile lesen — PING wird automatisch beantwortet."""
        while True:
            line = self._read_until_crlf()
            if line.startswith("PING "):
                self.send_raw("PONG " + line.split(" ", 1)[1])
                continue
            return line

    def wait_for(self, predicate, timeout: float = 30.0) -> str:
        """Zeilen lesen, bis predicate(line) wahr ist → liefert die Zeile."""
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise IRCError("Timeout beim Warten auf IRC-Antwort")
            self.sock.settimeout(max(0.5, remaining))
            line = self.read_line()
            if predicate(line):
                return line

    # ---------- IRC-Protokoll ----------
    def register(self, timeout: float = 30.0) -> "IRCClient":
        """Auf 001 (Willkommensnachricht) warten."""
        self.wait_for(lambda l: " 001 " in l, timeout)
        return self

    def identify(self, service: str = "NickServ", password: str = ""):
        if password:
            self.send_raw(f"PRIVMSG {service} :IDENTIFY {password}")
            time.sleep(1.0)

    def join(self, channel: str):
        if channel:
            self.send_raw(f"JOIN {channel}")

    def privmsg(self, target: str, message: str):
        self.send_raw(f"PRIVMSG {target} :{message}")

    def close(self):
        if self.sock:
            try:
                self.send_raw("QUIT :done")
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
