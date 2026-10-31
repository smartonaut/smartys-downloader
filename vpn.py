"""VPN-Steuerung: Surfshark-CLI oder OpenVPN, aus den Einstellungen konfigurierbar.

Typen:
  - "surfshark" : offizielle Surfshark-Linux-CLI (`surfshark-vpn connect/disconnect/status`)
  - "openvpn"   : OpenVPN mit Surfshark-.ovpn (system-weit, --daemon)

Der VPN ist system-weit — damit laufen auch die XDCC/DCC- und HTTP-Downloads
durch den Tunnel. Einstellungen → VPN: ein/aus + Typ + Befehl/Config.
"""
import subprocess

from . import store

# Surfshark-Linux-CLI ist NACHZURÜSTEN (nicht die snap-GUI):
#   curl -f https://downloads.surfshark.com/linux/debian-install.sh | sh
#   surfshark-vpn login   (einmalig, Account-E-Mail + Passwort)
SURFSHARK_CLI = "surfshark-vpn"

# Surfshark-.ovpn bekommt man aus dem Account-Portal („Manual setup").
# Credentials (Service-Credentials, NICHT das Account-Passwort) in eine Datei.


def _cfg() -> dict:
    return {
        "enabled": store.get_setting("vpn_enabled", "0") == "1",
        "type": store.get_setting("vpn_type", "surfshark"),
        "cli": store.get_setting("vpn_cli", SURFSHARK_CLI),
        "ovpn_config": store.get_setting("vpn_ovpn_config", ""),
        "ovpn_auth": store.get_setting("vpn_ovpn_auth", ""),
    }


def _run(cmd: list, timeout: int = 30) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace").strip()
    except FileNotFoundError:
        return 127, "Befehl nicht gefunden"
    except subprocess.TimeoutExpired:
        return 124, "Timeout"


def _surfshark(sub: str) -> tuple[int, str]:
    cli = store.get_setting("vpn_cli", SURFSHARK_CLI)
    return _run([cli, sub])


def connect() -> dict:
    cfg = _cfg()
    if cfg["type"] == "openvpn":
        if not cfg["ovpn_config"]:
            return {"ok": False, "error": "keine OpenVPN-Config gesetzt"}
        cmd = ["openvpn", "--config", cfg["ovpn_config"], "--daemon"]
        if cfg["ovpn_auth"]:
            cmd += ["--auth-user-pass", cfg["ovpn_auth"]]
        code, out = _run(cmd)
        if code != 0:
            return {"ok": False, "error": out[:140]}
        return {"ok": True, "detail": "openvpn gestartet"}
    # surfshark (default)
    code, out = _surfshark("connect")
    if code != 0 and "already" not in out.lower():
        return {"ok": False, "error": (out or "connect fehlgeschlagen")[:160]}
    return {"ok": True, "detail": out[:160]}


def disconnect() -> dict:
    cfg = _cfg()
    if cfg["type"] == "openvpn":
        _run(["pkill", "-f", "openvpn"])
        return {"ok": True, "detail": "openvpn beendet"}
    code, out = _surfshark("disconnect")
    return {"ok": code == 0, "detail": out[:160]}


def status() -> dict:
    cfg = _cfg()
    if cfg["type"] == "openvpn":
        code, out = _run(["pgrep", "-f", "openvpn"])
        active = code == 0
    else:
        code, out = _surfshark("status")
        active = code == 0
    return {"active": active, "detail": out[:200], "enabled": cfg["enabled"], "type": cfg["type"]}
