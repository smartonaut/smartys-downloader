# Extension installieren

## Firefox (temporär, zum Testen)
1. `about:debugging#/runtime/this-firefox` öffnen
2. "Temporäres Add-on laden" → `extension/manifest.json` wählen
3. Fertig — Badge + Kontextmenü sind aktiv solange die Session läuft

## Chrome/Chromium/Edge (dauerhaft, Entwicklermodus)
1. `chrome://extensions` öffnen
2. "Entwicklermodus" einschalten (oben rechts)
3. "Entpackt laden" → Ordner `extension/` wählen
4. Fertig — läuft dauerhaft (nach Browser-Start automatisch)

## Was die Extension tut
- **DLC-Klick abfangen**: Jeder Download einer `.dlc`-Datei wird abgebrochen
  und der DLC-Inhalt an den Downloader geschickt (Port 9666) — die Links
  landen direkt als Paket im Panel
- **Click'n'Load / JD2-Buttons**: Webseiten feuern die Links an
  `127.0.0.1:9666` — unser Downloader lauscht dort (JD2-kompatibel),
  Buttons funktionieren 1:1 ohne JD2
- **Kontextmenü**: Rechtsklick auf einen Link → "An Smartys Downloader senden"
  (auch für markierten Text mit mehreren Links)
- **Badge auf Webseiten**: erkennt CNL2-Formulare und DLC-Links

Der Downloader muss laufen (Port 8765 + 9666).
