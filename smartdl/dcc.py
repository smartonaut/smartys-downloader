"""DCC-SEND-Empfänger (XDCC-Dateitransfer).

Standard-XDCC: der Bot ist der Sender, WIR verbinden uns zu ihm
(IP+Port aus dem DCC-SEND-Offer). Das ist für Clients hinter NAT
der natürliche Weg — kein Reverse-DCC nötig, solange der Bot erreichbar ist.

Protokoll:
  - Verbinden zu bot_ip:bot_port
  - 4-Byte-Ack senden (Big-Endian Zähler der empfangenen Bytes), initial 0
    bzw. offset bei Resume
  - Daten empfangen, nach jedem recv den kumulierten Zähler als Ack senden
  - bei size erreicht: fertig
"""
import socket
import time

from .irc import IRCError


class DCCError(Exception):
    pass


def int_to_ip(n: int) -> str:
    """Unsigned 32-Bit (DCC-Konvention) → dotted quad."""
    return ".".join(str((n >> (8 * i)) & 0xFF) for i in (3, 2, 1, 0))


def _ack(sock: socket.socket, n: int):
    # DCC-Ack ist ein 32-Bit-Zähler — bei Dateien >4 GB läuft er über.
    # Deshalb modulo 2^32 wickeln, sonst OverflowError ab ~4,29 GB.
    sock.sendall((n & 0xFFFFFFFF).to_bytes(4, "big"))


def parse_dcc_accept(line: str) -> dict | None:
    """\\x01DCC ACCEPT <filename> <port> <position>\\x01 aus einer IRC-Zeile."""
    if "\x01DCC ACCEPT " not in line:
        return None
    msg = line.split(" :", 1)[1] if " :" in line else line
    msg = msg.strip().strip("\x01").strip()
    import shlex
    try:
        parts = shlex.split(msg)
    except ValueError:
        return None
    if len(parts) < 5 or parts[0].upper() != "DCC" or parts[1].upper() != "ACCEPT":
        return None
    try:
        return {"filename": parts[2], "port": int(parts[3]), "position": int(parts[4])}
    except (ValueError, IndexError):
        return None


def _quote(name: str) -> str:
    """DCC-Namen mit Leerzeichen müssen in Anführungszeichen stehen."""
    return f'"{name}"' if " " in name else name


def request_resume(client, bot: str, filename: str, port: int, position: int,
                   timeout: float = 20.0) -> bool:
    """DCC-RESUME aushandeln: RESUME senden, auf ACCEPT des Bots warten.

    Ablauf (DCC-Protokoll):
        → \\x01DCC RESUME <datei> <port> <position>\\x01
        ← \\x01DCC ACCEPT <datei> <port> <position>\\x01
    Danach verbindet sich der Empfänger wie gewohnt zum Bot und schickt den
    Offset als ersten Ack — der Bot liefert ab dieser Position weiter.

    Liefert True, wenn der Bot den Offset bestätigt hat. Ohne ACCEPT darf
    NICHT mit Offset empfangen werden (der Bot würde ab 0 senden und die
    bereits geladenen Bytes im Ziel überschreiben).
    """
    import socket as _socket
    try:
        client.privmsg(bot, f"\x01DCC RESUME {_quote(filename)} {port} {position}\x01")
    except Exception:
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        client.sock.settimeout(max(1.0, deadline - time.time()))
        try:
            line = client.read_line()
        except (TimeoutError, _socket.timeout):
            continue
        except Exception:
            return False
        acc = parse_dcc_accept(line)
        if acc and acc["position"] == position:
            return True
    return False


def parse_dcc_send(line: str) -> dict | None:
    """DCC-SEND-CTCP aus einer IRC-Zeile extrahieren.

    Format der Nachricht (nach dem letzten ' :'):
      \x01DCC SEND <filename> <ip_int> <port> <size>\x01
    Filename darf Anführungszeichen mit Leerzeichen enthalten.
    """
    if "\x01DCC SEND " not in line:
        return None
    # alles nach dem letzten ' :' ist die CTCP-Nachricht
    if " :" in line:
        msg = line.split(" :", 1)[1]
    else:
        msg = line.split(" ", 1)[1]
    msg = msg.strip().strip("\x01").strip()
    import shlex
    try:
        parts = shlex.split(msg)
    except ValueError:
        return None
    if len(parts) < 6 or parts[0].upper() != "DCC" or parts[1].upper() != "SEND":
        return None
    try:
        return {
            "filename": parts[2],
            "ip": int_to_ip(int(parts[3])),
            "port": int(parts[4]),
            "size": int(parts[5]),
        }
    except (ValueError, IndexError):
        return None


def receive(ip: str, port: int, size: int, dest: str, offset: int = 0,
            progress_cb=None, stop_event=None, timeout: float = 60.0) -> int:
    """DCC-Datei empfangen. Liefert die Zahl empfangener Bytes (inkl. offset).

    progress_cb(done, total, speed_bytes) wird ~2.5x/s gerufen (gedrosselt —
    der Aufrufer schreibt sonst nach jedem Chunk in die DB und bremst den
    Empfangs-Loop). stop_event (threading.Event) bricht ab → DCCError("PAUSED").
    """
    sock = socket.create_connection((ip, port), timeout=timeout)
    sock.settimeout(timeout)
    # Größerer Empfangspuffer + TCP_NODELAY → deutlich besserer Durchsatz
    # (DCC ist eine einzelne Verbindung, jeder RTT-Bremser zählt).
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except Exception:
        pass
    received = offset
    last_report = 0.0
    window_bytes = 0
    window_start = time.time()
    try:
        _ack(sock, received)  # initial-Ack (0 oder resume-offset)
        mode = "r+b" if offset else "wb"
        with open(dest, mode) as f:
            if offset:
                f.seek(offset)
            while received < size:
                if stop_event is not None and stop_event.is_set():
                    raise DCCError("PAUSED")
                chunk = sock.recv(min(256 * 1024, size - received))
                if not chunk:
                    raise DCCError("DCC: Verbindung vom Sender abgebrochen")
                f.write(chunk)
                received += len(chunk)
                _ack(sock, received)
                window_bytes += len(chunk)
                now = time.time()
                if progress_cb and now - last_report > 0.4:
                    speed = window_bytes / max(0.001, now - window_start)
                    progress_cb(received, size, speed)
                    window_bytes = 0
                    window_start = now
                    last_report = now
    finally:
        try:
            sock.close()
        except Exception:
            pass
    return received
