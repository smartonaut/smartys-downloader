# Windows-EXE bauen

PyInstaller kann nicht cross-compilen — die .exe wird auf Windows gebaut.
Zwei Wege:

## Weg A: RAIDX18HX (Windows-Boot) — empfohlen

```powershell
# 1. Repo holen (oder vom Linux-Boot rübersyncen)
git clone <repo> C:\Projekte\SmartDownloader
cd C:\Projekte\SmartDownloader

# 2. Python 3.11+ installiert? Dann:
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt pyinstaller

# 3. rsync.exe + unrar.exe brauchen wir NICHT auf windows —
#    Ziele sind UNC-Pfade (\\raiden\Daten\...) statt rsync. Siehe Weg B-Hinweis.

# 4. Bauen (gleicher spec-file):
pyinstaller smartys-downloader.spec --noconfirm --clean

# 5. Ergebnis: dist\SmartDownloader\SmartDownloader.exe
#    Panel: http://127.0.0.1:8765
```

## Weg B: Wine auf Thinky (headless, ohne reboot)

```bash
sudo -S -p '' apt install -y wine64 python3-wine  # oder windows-python im wine-prefix
# python-installer.exe im wine-prefix installieren, dann identisch wie Weg A
```

## Windows-Anpassungen (TODO vor dem ersten Windows-Build)

- `postprocess.py`: `rsync`-Aufruf → auf Windows UNC-Kopierer
  (`shutil`/`robocopy`) ausweichen, wenn Ziel mit `\\` beginnt
- `downloader.py`: läuft (pure python + curl_cffi wheels gibt es für win)
- Clipboard-Watcher: Windows-Version (`win32clipboard`) statt wl-paste

## Installer (optional)

`Inno Setup` mit einem kleinen .iss-File packt `dist\SmartDownloader\`
in eine Setup.exe mit Startmenü-Eintrag — gleiche Struktur wie das .deb.
