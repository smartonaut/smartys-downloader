"""Smartys Downloader — Konfiguration.

Lädt Werte aus (in dieser Reihenfolge):
  1. ~/.config/smartys-downloader/smartdl.env   (Installer-Standard, systemd)
  2. <projekt>/.env                             (Dev-Checkout)
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.getenv(
    "XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "smartys-downloader"
ENV_FILE = CONFIG_DIR / "smartdl.env"
PASSWORD_FILE = CONFIG_DIR / "archive_passwords.txt"

# Installer-Config zuerst (gewinnt).
# Repo-.env als Fallback NUR in der Entwicklung (nicht im PyInstaller-Freeze —
# sonst würde ein versehentlich mitgeliefertes .env private Keys leaken):
_REPO_ENV = BASE_DIR / ".env"
_IN_FREEZE = getattr(sys, "frozen", False)
if not _IN_FREEZE and _REPO_ENV.exists():
    load_dotenv(_REPO_ENV, override=False)
load_dotenv(ENV_FILE, override=True)

# --- API Keys ---
REALDEBRID_API_KEY = os.getenv("REALDEBRID_API_KEY", "")
DEBRIDLINK_API_KEY = os.getenv("DEBRIDLINK_API_KEY", "")

# --- FlareSolverr (Cloudflare-Bypass, optional — für Filecrypt) ---
FLARESOLVERR_URL = os.getenv("FLARESOLVERR_URL", "")
FILECRYPT_ENABLED = bool(FLARESOLVERR_URL)

# --- Pfade ---
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR",
                             str(Path.home() / "Downloads" / "SmartDownloader")))
DB_PATH = Path(os.getenv("SMARTDL_DB", str(CONFIG_DIR / "smartdl.db")))
LOG_PATH = Path(os.getenv("SMARTDL_LOG", str(CONFIG_DIR / "smartdl.log")))

# --- Verhalten ---
MAX_PARALLEL = int(os.getenv("MAX_PARALLEL", "3"))
SPEED_LIMIT_KB = int(os.getenv("SPEED_LIMIT_KB", "0"))  # 0 = unbegrenzt
CLIPBOARD_WATCH = os.getenv("CLIPBOARD_WATCH", "1") == "1"
AUTO_ADD_CLIPBOARD = os.getenv("AUTO_ADD_CLIPBOARD", "0") == "1"

# Multi-Segment: parallele Verbindungen pro Download (0 = auto). Range-Server
# werden automatisch erkannt; ohne Range-Support fällt der Downloader auf
# Single-Stream zurück.
SEGMENTS = int(os.getenv("SEGMENTS", "8"))

# Torrent (aria2): Port des aria2-RPC-Daemons. aria2c muss installiert sein
# (apt install aria2); fehlt es, meldet das Torrent-Modul einen klaren Fehler.
ARIA2_RPC_PORT = int(os.getenv("ARIA2_RPC_PORT", "6800"))
ARIA2_RPC_SECRET = os.getenv("ARIA2_RPC_SECRET", "")

# Reconnect (neue IP vom Router, für Direct-Hoster-Limits). Einer der drei
# Wege reicht (Reihenfolge: script → fritzbox → url).
RECONNECT_SCRIPT = os.getenv("RECONNECT_SCRIPT", "")
RECONNECT_URL = os.getenv("RECONNECT_URL", "")
RECONNECT_FRITZ_HOST = os.getenv("RECONNECT_FRITZ_HOST", "")
RECONNECT_FRITZ_USER = os.getenv("RECONNECT_FRITZ_USER", "")
RECONNECT_FRITZ_PASS = os.getenv("RECONNECT_FRITZ_PASS", "")

# Jellyfin-Ziel fürs Post-Processing (rsync-ziel, leer = nicht verschieben)
JELLYFIN_TARGET = os.getenv("JELLYFIN_TARGET", "")

# Kategorie-Ziele aus der ENV (Defaults für Erstinstallation — in der GUI
# überschreibbar, landen dann in der DB). Alles leer = nur entpacken.
CATEGORY_TARGETS_ENV = {
    "movie":     os.getenv("MOVIE_TARGET", ""),
    "series":    os.getenv("SERIES_TARGET", ""),
    "software":  os.getenv("SOFTWARE_TARGET", ""),
    "music":     os.getenv("MUSIC_TARGET", ""),
    "audiobook": os.getenv("AUDIOBOOK_TARGET", ""),
    "kids":      os.getenv("KIDS_TARGET", ""),
    "other":     os.getenv("OTHER_TARGET", ""),
}

# Debrid-Reihenfolge: erster der den Link kennt, gewinnt
DEBRID_ORDER = [s.strip() for s in
                os.getenv("DEBRID_ORDER", "realdebrid,debridlink,alldebrid,premiumize,torbox,easydebrid,linksnappy,offcloud").split(",") if s.strip()]

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)