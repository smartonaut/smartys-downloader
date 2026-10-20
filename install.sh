#!/usr/bin/env bash
# ============================================================================
#  Smartys Downloader — Installer
#  Kern: Python-venv + Dependencies + GUI   (läuft überall, ~2 Minuten)
#  Optional: Filecrypt-Support via FlareSolverr (separater Schritt, unten)
#
#  Nutzung:
#    bash install.sh              # Kern installieren + interaktiv konfigurieren
#    bash install.sh --unattended # keine Fragen, Defaults
#    bash install.sh --uninstall  # alles rückgängig (bis auf Downloads)
#
#  Nach der Installation:
#    Start:   ~/smartys-downloader/start.sh     (oder systemd-Service, s.u.)
#    GUI:     http://127.0.0.1:8765
#    Konfig:  ~/.config/smartys-downloader/smartdl.env
# ============================================================================
set -euo pipefail

# --- Konstanten ---
APP_NAME="smartys-downloader"
INSTALL_DIR="$HOME/$APP_NAME"
VENV_DIR="$INSTALL_DIR/.venv"
CONFIG_DIR="$HOME/.config/$APP_NAME"
ENV_FILE="$CONFIG_DIR/smartdl.env"
SERVICE_FILE="$HOME/.config/systemd/user/$APP_NAME.service"
PORT="8765"
REPO_URL="https://github.com/smartys-tech/smartys-downloader.git"

# --- Farben ---
if [ -t 1 ]; then
  G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[1;34m'; N='\033[0m'
else
  G=''; Y=''; R=''; B=''; N=''
fi
info()  { echo -e "${B}[i]${N} $*"; }
ok()    { echo -e "${G}[✓]${N} $*"; }
warn()  { echo -e "${Y}[!]${N} $*"; }
err()   { echo -e "${R}[✗]${N} $*"; exit 1; }

UNATTENDED=0
case "${1:-}" in
  --unattended) UNATTENDED=1 ;;
  --uninstall) do_uninstall=1 ;;
esac

# ============================================================================
# Uninstall
# ============================================================================
if [ "${do_uninstall:-0}" = "1" ]; then
  info "Deinstalliere $APP_NAME..."
  systemctl --user stop "$APP_NAME" 2>/dev/null || true
  systemctl --user disable "$APP_NAME" 2>/dev/null || true
  rm -f "$SERVICE_FILE"
  rm -rf "$INSTALL_DIR"
  rm -rf "$CONFIG_DIR"
  ok "Deinstallation fertig. Downloads in ~/Downloads/SmartDownloader blieben unberührt."
  exit 0
fi

# ============================================================================
# 1. Voraussetzungen prüfen
# ============================================================================
info "Prüfe Voraussetzungen..."

command -v python3 >/dev/null 2>&1 || err "python3 fehlt (mindestens 3.10). Installiere es mit deinem Paket-Manager."
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
ok "python3 $PY_VER"

command -v git >/dev/null 2>&1 || err "git fehlt. apt install git / dnf install git / brew install git"

# SQLite ist bei Python dabei; unrar für das Entpacken:
if ! command -v unrar >/dev/null 2>&1; then
  warn "unrar fehlt — Entpacken von RAR-Archiven funktioniert nicht."
  warn "  Nachinstallieren: sudo apt install unrar  (Debian/Ubuntu) | dnf install unrar (Fedora)"
  if [ "$UNATTENDED" = "0" ]; then
    read -rp "  Ohne unrar weitermachen? [j/N] " a
    [[ "${a:-n}" =~ ^[jJ] ]] || err "unrar wird für den Vollbetrieb benötigt."
  fi
fi

# ============================================================================
# 2. Code besorgen
# ============================================================================
if [ -d "$INSTALL_DIR/.git" ]; then
  info "Bestehende Installation gefunden in $INSTALL_DIR — aktualisiere..."
  git -C "$INSTALL_DIR" pull --ff-only 2>/dev/null || warn "git pull fehlgeschlagen (arbeite mit lokalem Stand weiter)"
else
  if [ -d "$INSTALL_DIR" ]; then
    err "$INSTALL_DIR existiert bereits, ist aber kein Git-Checkout. Bitte vorher sichern/entfernen."
  fi
  info "Klone nach $INSTALL_DIR..."
  git clone "$REPO_URL" "$INSTALL_DIR" || err "Clone fehlgeschlagen: $REPO_URL"
fi

# ============================================================================
# 3. Virtuelle Umgebung + Dependencies
# ============================================================================
info "Erstelle Python-Virtualenv..."
python3 -m venv "$VENV_DIR"

info "Installiere Dependencies (kann 1-2 Minuten dauern)..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q
ok "Dependencies installiert."

# ============================================================================
# 4. Konfiguration
# ============================================================================
mkdir -p "$CONFIG_DIR"

ask_key() {
  # $1 name, $2 beschreibung, $3 example
  local val=""
  if [ "$UNATTENDED" = "1" ]; then
    info "$2 → leer (später in $ENV_FILE eintragen)"
    echo "$1=" >> "$ENV_FILE"
    return
  fi
  read -rp "  $2 (z.B. $3): " val
  echo "$1=${val:-}" >> "$ENV_FILE"
}

if [ ! -f "$ENV_FILE" ]; then
  info "Konfiguration anlegen: $ENV_FILE"
  cat > "$ENV_FILE" <<EOF
# Smartys Downloader Konfiguration
# Real-Debrid API-Key: https:...oken
EOF
  ask_key "REALDEBRID_API_KEY"  "Real-Debrid API-Key (optional, stark empfohlen)" "a1b2c3..."
  cat >> "$ENV_FILE" <<EOF
# DebridLink API-Key: https:...k.fr → Einstellungen → API
EOF
  ask_key "DEBRIDLINK_API_KEY"  "DebridLink API-Key (optional, Fallback)" "x7y8z9..."
  cat >> "$ENV_FILE" <<EOF

# --- Optional: Filecrypt-Support ( siehe unten ) ---
# FlareSolverr-URL, z.B. http://127.0.0.1:8191/v1 oder http://anderer-pc:8191/v1
# LEER LASSEN wenn kein FlareSolverr vorhanden — alles außer Filecrypt läuft normal.
EOF
  ask_key "FLARESOLVERR_URL"    "FlareSolverr-URL (optional, für filecrypt.cc)" "http://127.0.0.1:8191/v1"
  cat >> "$ENV_FILE" <<EOF

# Download-Ziel (leer = ~/Downloads/SmartDownloader)
DOWNLOAD_DIR=
EOF
  # Kategorie-Ziele abfragen (alle optional, leer = nur entpacken):
  echo
  info "Nachbearbeitung: Wohin mit fertigen Downloads? (alles optional — leer = nur entpacken)"
  info "Formate: user@host:/pfad/ (rsync) oder lokaler Pfad /pfad/"
  ask_key "MOVIE_TARGET"     "Filme-Ziel"            "user@media-pc:/medien/filme/"
  ask_key "SERIES_TARGET"    "Serien-Ziel"           "user@media-pc:/medien/serien/"
  ask_key "AUDIOBOOK_TARGET" "Hörspiel/Hörbuch-Ziel" "user@media-pc:/medien/hoerbuecher/"
  ask_key "MUSIC_TARGET"     "Musik-Ziel"            "/mnt/musik/"
  ask_key "SOFTWARE_TARGET"  "Software-Ziel"         "/opt/software/"
  ask_key "KIDS_TARGET"      "Kinder-Ziel"           "user@media-pc:/medien/kinder/"
  ask_key "OTHER_TARGET"     "Sonstiges-Ziel"        "/mnt/sonstiges/"
  chmod 600 "$ENV_FILE"
  ok "Konfiguration angelegt."
else
  ok "Konfiguration existiert bereits — übersprungen."
fi

# ============================================================================
# 4b. Web-Login-Passwort (schützt das Panel sofort)
# ============================================================================
if [ "$UNATTENDED" = "1" ]; then
  if ! grep -q "^SMARTDL_PASSWORD=" "$ENV_FILE" 2>/dev/null; then
    warn "Unattended-Modus: kein Passwort gesetzt — Panel ist OFFEN."
    warn "Später setzen: in $ENV_FILE  SMARTDL_PASSWORD=...  eintragen oder über die GUI."
  fi
else
  # Passwort nur abfragen, wenn noch keins gesetzt ist (DB-Check via API wäre
  # komplex — wir prüfen ob SMARTDL_PASSWORD schon in der env steht)
  if ! grep -q "^SMARTDL_PASSWORD=.\+" "$ENV_FILE" 2>/dev/null; then
    echo
    info "Web-Login-Passwort für das Panel (http://127.0.0.1:$PORT)"
    info "Regeln: mind. 12 Zeichen, Groß+Kleinbuchstaben, Zahl UND Sonderzeichen."
    while true; do
      read -rsp "  Passwort: " PW1; echo
      read -rsp "  Wiederholen: " PW2; echo
      if [ "$PW1" != "$PW2" ]; then
        warn "Passwörter stimmen nicht überein — nochmal."
        continue
      fi
      if [ ${#PW1} -lt 12 ]; then warn "Zu kurz: mind. 12 Zeichen nötig."; continue; fi
      if ! echo "$PW1" | grep -q "[A-Z]"; then warn "Mind. 1 Großbuchstabe nötig."; continue; fi
      if ! echo "$PW1" | grep -q "[a-z]"; then warn "Mind. 1 Kleinbuchstabe nötig."; continue; fi
      if ! echo "$PW1" | grep -q "[0-9]"; then warn "Mind. 1 Zahl nötig."; continue; fi
      if ! echo "$PW1" | grep -qE "[^A-Za-z0-9]"; then warn "Mind. 1 Sonderzeichen nötig."; continue; fi
      break
      break
    done
    if grep -q "^SMARTDL_PASSWORD=" "$ENV_FILE" 2>/dev/null; then
      sed -i "s|^SMARTDL_PASSWORD=.*|SMARTDL_PASSWORD=$PW1|" "$ENV_FILE"
    else
      echo "" >> "$ENV_FILE"
      echo "# Web-Login-Passwort (Panel-Schutz)" >> "$ENV_FILE"
      echo "SMARTDL_PASSWORD=$PW1" >> "$ENV_FILE"
    fi
    ok "Login-Passwort gesetzt."
    info "Zwei-Faktor (2FA) kannst du später in der GUI aktivieren: Einstellungen → Web-Login."
  fi
fi

# Passwort-Liste anlegen (falls neu) — LEER, keine vorkonfigurierten Passwörter.
# Der Nutzer trägt seine eigenen Container-/Archiv-Passwörter selbst in der
# GUI ein (Einstellungen → Passwörter) oder hier in diese Datei.
if [ ! -f "$CONFIG_DIR/archive_passwords.txt" ]; then
  cat > "$CONFIG_DIR/archive_passwords.txt" <<'EOF'
# Passwörter für Container und Archive (eins pro Zeile, wird durchgetestet)
# Eigene Passwörter hier ergänzen oder bequemer in der GUI: Einstellungen → Passwörter.
EOF
fi

# ============================================================================
# 5. Start-Script + systemd-Service (optional)
# ============================================================================
cat > "$INSTALL_DIR/start.sh" <<EOF
#!/usr/bin/env bash
# Startet den Smartys Downloader (GUI: http://127.0.0.1:$PORT)
cd "$INSTALL_DIR"
set -a; source "$ENV_FILE"; set +a
exec "$VENV_DIR/bin/python" run.py
EOF
chmod +x "$INSTALL_DIR/start.sh"

if command -v systemctl >/dev/null 2>&1 && [ -d "$HOME/.config/systemd/user" ] || systemctl --user true >/dev/null 2>&1; then
  if [ "$UNATTENDED" = "1" ]; then
    want_service="j"
  else
    read -rp "Als systemd-Service installieren (Autostart beim Login)? [J/n] " want_service
  fi
  if [[ ! "${want_service:-j}" =~ ^[nN] ]]; then
    mkdir -p "$HOME/.config/systemd/user"
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Smartys Downloader
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_DIR/bin/python run.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now "$APP_NAME"
    ok "systemd-Service installiert und gestartet."
  fi
fi

# ============================================================================
# 6. Filecrypt-Hinweis
# ============================================================================
if ! grep -q "^FLARESOLVERR_URL=.\+" "$ENV_FILE" 2>/dev/null; then
  warn ""
  warn "Filecrypt-Support ist OHNE FlareSolverr nicht aktiv."
  warn "Alles andere (hide.cx, Hoster-Links, data-load) funktioniert normal."
  warn ""
  warn "FlareSolverr nachrüsten (einmalig, auf DIESEM oder einem anderen Rechner):"
  warn "  docker run -d --name flaresolverr -p 8191:8191 \\"
  warn "    --restart unless-stopped ghcr.io/flaresolverr/flaresolverr:latest"
  warn "Dann in $ENV_FILE eintragen:"
  warn "  FLARESOLVERR_URL=http://<ip>:8191/v1"
  warn ""
fi

# ============================================================================
# 7. Fertig
# ============================================================================
if systemctl --user is-active "$APP_NAME" >/dev/null 2>&1; then
  ok "$APP_NAME LÄUFT."
else
  ok "Installation fertig. Starten:  $INSTALL_DIR/start.sh"
fi
echo
ok "GUI:            http://127.0.0.1:$PORT"
ok "Konfiguration:  $ENV_FILE"
ok "Downloads:      ${DOWNLOAD_DIR_HOME:-$HOME/Downloads/SmartDownloader}"
echo
info "Erste Schritte: Einfach einen Download-Link kopieren — der Clipboard-Watcher"
info "schlägt vor, ihn als Paket zu übernehmen. Oder Links ins GUI-Feld einwerfen."