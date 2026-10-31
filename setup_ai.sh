#!/usr/bin/env bash
# ============================================================================
#  Smartys Downloader — KI-Assistent installieren (One-Click)
#  Installiert ollama + lädt ein Modell. Für ein blankes System.
#
#  Erkennt eine evtl. schon laufende KI (ollama auf 11434 u.a.) und fragt,
#  ob diese GENUTZT oder ein EIGENES ollama auf freiem Port (11435) installiert
#  werden soll — damit bestehende Installationen (ollama/Hermes) nicht gestört werden.
#
#  Nutzung:
#    bash setup_ai.sh [modell]          # Default: GPU-abhängig (7B/3B/1.5B)
#    bash setup_ai.sh qwen2.5:7b        # ollama-Modell
#    bash setup_ai.sh "hf.co/bartowski/Qwen2.5-7B-Instruct-GGUF:Q4_K_M"  # HuggingFace
# ============================================================================
set -euo pipefail

MODEL="${1:-}"
PORT=11434
OLLAMA_HOST_OVERRIDE=""

G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; N='\033[0m'
info() { echo -e "${Y}[i]${N} $*"; }
ok()   { echo -e "${G}[✓]${N} $*"; }

# --- 1. Bestehende lokale KI erkennen ---
EXISTING=""
if curl -s -m 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
  EXISTING="ollama auf http://localhost:11434"
fi

if [ -n "$EXISTING" ]; then
  info "Es läuft schon eine KI: $EXISTING"
  read -rp "  Nutzen (j) oder eigenes ollama auf Port 11435 installieren (n)? [J/n] " a
  if [[ "${a:-j}" =~ ^[nN] ]]; then
    PORT=11435
    OLLAMA_HOST_OVERRIDE="127.0.0.1:11435"
    info "Eigenes ollama auf Port $PORT — das bestehende bleibt unberührt."
  else
    ok "Nutze bestehende KI. Im Downloader: Einstellungen → KI-Assistent → Endpoint = $EXISTING"
    if [ -n "$MODEL" ]; then
      info "Modell $MODEL in die bestehende KI laden…"
      ollama pull "$MODEL" 2>/dev/null || true
    fi
    exit 0
  fi
fi

# --- 2. ollama prüfen/installieren ---
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

# --- 3. Daemon mit dem richtigen Port sicherstellen ---
if [ -n "$OLLAMA_HOST_OVERRIDE" ]; then
  export OLLAMA_HOST="$OLLAMA_HOST_OVERRIDE"
  info "ollama-Daemon auf Port $PORT starten (eigenes, parallel)..."
  nohup ollama serve >"/tmp/ollama-$PORT.log" 2>&1 &
else
  if ! curl -s -m 2 "http://localhost:$PORT/api/tags" >/dev/null 2>&1; then
    info "ollama-Daemon starten…"
    if systemctl is-active --quiet ollama 2>/dev/null; then
      :
    elif systemctl list-unit-files ollama >/dev/null 2>&1; then
      sudo systemctl enable --now ollama 2>/dev/null || true
    else
      nohup ollama serve >/tmp/ollama.log 2>&1 &
    fi
    for _ in $(seq 1 15); do
      curl -s -m 2 "http://localhost:$PORT/api/tags" >/dev/null 2>&1 && break
      sleep 1
    done
  fi
fi

# --- 4. GPU-abhängiges Standard-Modell wählen ---
if [ -z "$MODEL" ]; then
  MODEL="qwen2.5:7b"
  if command -v nvidia-smi >/dev/null 2>&1; then
    VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')
    if [ -n "${VRAM_MB:-}" ]; then
      if [ "$VRAM_MB" -lt 5000 ]; then MODEL="qwen2.5:3b"; fi
      if [ "$VRAM_MB" -ge 20000 ]; then MODEL="qwen2.5:14b"; fi
    fi
  else
    MODEL="qwen2.5:1.5b"
  fi
fi

# --- 5. Modell laden ---
info "lade Modell: $MODEL (kann einige Minuten dauern)…"
if [ -n "$OLLAMA_HOST_OVERRIDE" ]; then
  OLLAMA_HOST="$OLLAMA_HOST_OVERRIDE" ollama pull "$MODEL"
else
  ollama pull "$MODEL"
fi
ok "Fertig. Modell $MODEL ist bereit (Port $PORT)."
echo "Im Downloader: Einstellungen → KI-Assistent → Endpoint http://localhost:$PORT + Modell wählen."
