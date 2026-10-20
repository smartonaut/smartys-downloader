# Smartys Downloader — Windows-Build (auf einem echten Windows-PC ausführen)
# Voraussetzung: Python 3.11+ von python.org installiert (PATH-Häkchen setzen!)
# Ausführen: PowerShell im Projektordner öffnen → .\build_windows.ps1

$ErrorActionPreference = "Stop"
Write-Host "=== Smartys Downloader Windows-Build ===" -ForegroundColor Cyan

# 1. venv anlegen (falls neu)
if (-Not (Test-Path ".venv-win")) {
    Write-Host "[1/4] venv anlegen..." -ForegroundColor Yellow
    python -m venv .venv-win
}
$py = ".venv-win\Scripts\python.exe"

# 2. Abhängigkeiten
Write-Host "[2/4] Abhängigkeiten installieren..." -ForegroundColor Yellow
& $py -m pip install --upgrade pip -q
& $py -m pip install -r requirements.txt pyinstaller -q

# 3. PyInstaller-Build (gleiches spec-file wie Linux/.deb)
Write-Host "[3/4] PyInstaller-Build..." -ForegroundColor Yellow
& .venv-win\Scripts\pyinstaller.exe smartys-downloader.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fehlgeschlagen" }

# 4. Extension rein + ZIP
Write-Host "[4/4] Extension + ZIP packen..." -ForegroundColor Yellow
Copy-Item -Recurse -Force extension dist\SmartDownloader\extension -ErrorAction SilentlyContinue
$ver = (Select-String -Path packaging\control -Pattern "^Version: (.+)$").Matches.Groups[1].Value
$zip = "SmartDownloader-$($ver)-windows.zip"
if (Test-Path "dist\$zip") { Remove-Item "dist\$zip" }
Compress-Archive -Path dist\SmartDownloader -DestinationPath "dist\$zip"

Write-Host ""
Write-Host "FERTIG: dist\$zip" -ForegroundColor Green
Write-Host "Test: dist\SmartDownloader\SmartDownloader.exe starten → Panel http://127.0.0.1:8765"
Write-Host "Danach ZIP an Smarty schicken für den Upload auf smartys.tech"
