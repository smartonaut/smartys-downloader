# Smartys Downloader — KI-Assistent installieren (One-Click, Windows)
# Installiert ollama + lädt ein Modell. Für ein blankes Windows.
#
# Erkennt eine evtl. schon laufende KI (ollama auf 11434 u.a.) und fragt,
# ob diese GENUTZT oder ein EIGENES ollama auf freiem Port (11435) installiert
# werden soll — damit bestehende Installationen (ollama/Hermes) nicht gestört werden.
#
# Nutzung (PowerShell):
#   .\setup_ai.ps1                        # Default: GPU-abhängig (7B/3B/1.5B)
#   .\setup_ai.ps1 -Model "hf.co/bartowski/Qwen2.5-7B-Instruct-GGUF:Q4_K_M"
param([string]$Model = "")

$ErrorActionPreference = "Stop"
Write-Host "=== Smartys Downloader — KI-Install ===" -ForegroundColor Cyan

$Port = 11434

# --- 1. Bestehende lokale KI erkennen ---
$existing = $null
try {
    $r = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
    if ($r.StatusCode -eq 200) { $existing = "ollama auf http://localhost:11434" }
} catch {}

if ($existing) {
    Write-Host "[i] Es läuft schon eine KI: $existing" -ForegroundColor Yellow
    $answer = Read-Host "  Nutzen (j) oder eigenes ollama auf Port 11435 installieren (n)? [J/n]"
    if ($answer -match '^[nN]') {
        $Port = 11435
        Write-Host "[i] Eigenes ollama auf Port $Port — das bestehende bleibt unberührt." -ForegroundColor Yellow
    } else {
        Write-Host "[✓] Nutze bestehende KI. Im Downloader: Einstellungen -> KI-Assistent -> Endpoint = $existing" -ForegroundColor Green
        if ($Model) {
            Write-Host "[i] Modell $Model in die bestehende KI laden…" -ForegroundColor Yellow
            & ollama pull $Model 2>$null
        }
        exit 0
    }
}

# --- 2. ollama prüfen/installieren ---
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "[✓] ollama vorhanden" -ForegroundColor Green
} else {
    Write-Host "[i] ollama nicht gefunden — installiere…" -ForegroundColor Yellow
    $setup = "$env:TEMP\OllamaSetup.exe"
    Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $setup
    Start-Process -FilePath $setup -ArgumentList "/SILENT" -Wait
    $env:Path += ";$env:LOCALAPPDATA\Programs\Ollama"
    Write-Host "[✓] ollama installiert" -ForegroundColor Green
}

# --- 3. Port-Auswahl (eigenes auf 11435 = OLLAMA_HOST) ---
if ($Port -ne 11434) {
    $env:OLLAMA_HOST = "127.0.0.1:$Port"
    Write-Host "[i] ollama auf Port $Port starten (eigenes, parallel)…" -ForegroundColor Yellow
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

# --- 4. GPU-abhängiges Standard-Modell wählen ---
if (-not $Model) {
    $Model = "qwen2.5:7b"
    try {
        $vram = (nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1).Trim()
        if ($vram) {
            $vramMb = [int]$vram
            if ($vramMb -lt 5000) { $Model = "qwen2.5:3b" }
            if ($vramMb -ge 20000) { $Model = "qwen2.5:14b" }
        }
    } catch {}
}

# --- 5. Modell laden ---
Write-Host "[i] lade Modell: $Model (kann einige Minuten dauern)…" -ForegroundColor Yellow
& ollama pull $Model
Write-Host ""
Write-Host "FERTIG. Modell $Model ist bereit (Port $Port)." -ForegroundColor Green
Write-Host "Im Downloader: Einstellungen -> KI-Assistent -> Endpoint http://localhost:$Port + Modell wählen."
