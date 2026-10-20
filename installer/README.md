# Smartys Downloader — Setup-Installer (C++ / Win32)

Vollwertiger Windows-Installer: Wizard mit Begrüßung, Komponenten-Auswahl,
Zielordner (Durchsuchen-Dialog), Progress-Bar und Fertig-Seite mit
„Jetzt starten"-Option. Per-User-Installation (keine Admin-Rechte).

## Features
- Eigenes Icon (6 Größen, 16–256px) + deutsche Versions-Ressource
  (Rechtsklick → Details zeigt Produkt, Version, smartys.tech)
- Komponenten-Auswahl: Browser-Erweiterung, Desktop-Link, Autostart
- Zielordner frei wählbar (Standard: %LOCALAPPDATA%\SmartDownloader)
- Dark-Theme passend zur Web-GUI (#0b0d12, blauer Akzent)
- Add/Remove-Programme-Eintrag + eigene Uninstall.exe mit Dialog
- Payload (der Downloader selbst) in die Setup.exe eingebettet — EINE Datei

## Build auf PC-MAMA

Voraussetzung: Visual Studio 2022 Community (Desktop-Development mit C++)
— oder MinGW-w64 + CMake. Dann:

```powershell
# 1. payload bauen (der downloader selbst):
..\build_windows.ps1

# 2. installer:
cd installer
cmake -B build -DPAYLOAD=..\dist\SmartDownloader-0.2.0-windows.zip
cmake --build build --config Release
# → build\Release\SmartDownloaderSetup.exe (eine Datei, alles drin)
```

Für Visual Studio statt Ninja: `cmake -B build -G "Visual Studio 17 2022" -A x64 ...`

## Uninstall.exe mit ausliefern

Beim Payload-Build die frisch kompilierte `SmartDownloaderUninstall.exe`
als `Uninstall.exe` in `dist\SmartDownloader\` kopieren — sie wird mit
installiert und unter „Apps & Features" verlinkt.
