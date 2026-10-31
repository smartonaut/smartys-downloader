# Smartys Downloader — KI-Assistent installieren (One-Click, Windows)
# Installiert ollama + lädt ein Modell. Für ein blankes Windows.
#
# Nutzung (PowerShell):
#   .\setup_ai.ps1                        # Default: qwen2.5:7b
#   .\setup_ai.ps1 -Model "hf.co/bartowski/Qwen2.5-7B-Instruct-GGUF:Q4_K_M"
param([string]$Model = "qwen2.5:7b")

$ErrorActionPreference = "Stop"
Write-Host "=== Smartys Downloader — KI-Install ===" -ForegroundColor Cyan

# --- 1. ollama prüfen/installieren ---
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "[1/2] ollama vorhanden" -ForegroundColor Green
} else {
    Write-Host "[1/2] ollama nicht gefunden — installiere…" -ForegroundColor Yellow
    $setup = "$env:TEMP\OllamaSetup.exe"
    Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $setup
    Start-Process -FilePath $setup -ArgumentList "/SILENT" -Wait
    # PATH aktualisieren (ollama liegt unter %LOCALAPPDATA%\Programs\Ollama)
    $env:Path += ";$env:LOCALAPPDATA\Programs\Ollama"
    Write-Host "[1/2] ollama installiert" -ForegroundColor Green
}

# --- 2. Modell laden ---
Write-Host "[2/2] lade Modell: $Model (kann einige Minuten dauern)…" -ForegroundColor Yellow
& ollama pull $Model
Write-Host ""
Write-Host "FERTIG. Modell $Model ist bereit." -ForegroundColor Green
Write-Host "Im Downloader: Einstellungen -> KI-Assistent -> Modell auswählen."
