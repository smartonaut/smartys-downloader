#!/usr/bin/env bash
# ============================================================================
#  Smartys Downloader — KI-Assistent installieren (One-Click)
#  Installiert ollama + lädt ein Modell. Für ein blankes System.
#
#  Nutzung:
#    bash setup_ai.sh [modell]          # Default: qwen2.5:7b
#    bash setup_ai.sh qwen2.5:7b        # ollama-Modell
#    bash setup_ai.sh "hf.co/bartowski/Qwen2.5-7B-Instruct-GGUF:Q4_K_M"  # HuggingFace
#
#  Ohne ollama: lädt + installiert ollama automatisch.
# ============================================================================
set -euo pipefail

MODEL="${1:-qwen2.5:7b}"

G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; N='\033[0m'
info() { echo -e "${Y}[i]${N} $*"; }
ok()   { echo -e "${G}[✓]${N} $*"; }

# --- 1. ollama prüfen/installieren ---
if command -v ollama >/dev/null 2>&1; then
  ok "ollama vorhanden: $(command -v ollama)"
else
  info "ollama nicht gefunden — installiere…"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL https://ollama.com/install.sh | sh
  else
    wget -qO- https://ollama.com/install.sh | sh
  fi
  ok "ollama installiert"
fi

# --- 2. ollama-Daemon sicherstellen ---
if ! curl -s -m 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
  info "ollama-Daemon starten…"
  if systemctl is-active --quiet ollama 2>/dev/null; then
    : # läuft schon als service
  elif systemctl list-unit-files ollama >/dev/null 2>&1; then
    sudo systemctl enable --now ollama 2>/dev/null || true
  else
    nohup ollama serve >/tmp/ollama.log 2>&1 &
  fi
  # warten bis erreichbar
  for _ in $(seq 1 15); do
    curl -s -m 2 http://localhost:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
  done
fi

# --- 3. Modell laden ---
info "lade Modell: $MODEL (kann einige Minuten dauern)…"
ollama pull "$MODEL"
ok "Fertig. Modell $MODEL ist bereit."
echo "Im Downloader: Einstellungen → KI-Assistent → Modell auswählen."
