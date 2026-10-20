# Smartys Downloader

Ein leichtgewichtiger, selbst gehosteter Download-Manager — der JDownloader-2-Ansatz ohne JVM-Ballast.

[Website](https://downloader.smartys.tech) · [Downloads](https://downloader.smartys.tech) · [Community & Versionslog](https://forum.smartys.tech) · [Changelog](CHANGELOG.md)

**Status:** v0.3.1 — Kern-Engine + Beschleuniger-Features (Multi-Segment, Scheduler, Reconnect, Multi-Mirror, Torrent) + Debrid/Filecrypt-Pipeline E2E

## Was ist das?

Ein Download-Manager für Szene-Container und One-Click-Hoster, gebaut als schlanke
Alternative zu JDownloader 2 (377 MB + JVM) und PyLoad (Plugin-Wartungs-Friedhof).

Kernidee: **Debrid-Dienste (Real-Debrid + DebridLink) lösen 634+ Hoster auf** —
statt hunderte eigener Hoster-Plugins zu pflegen wie JD2. Was übrig bleibt ist eine
saubere Pipeline:

```
Link/Container rein
   ↓
Container-Resolver (Filecrypt CF+PoW nativ im Browser / hide.cx API / data-load)
   ↓
Debrid-Router (Real-Debrid → DebridLink, erster gewinnt, mit Fallback)
   ↓
Queue-Engine (parallele Downloads, Resume, Pause, Retry)
   ↓
Paket-Post-Processing (wartet auf ALLE Parts → unrar → Video zum Media-Server → Archive löschen)
   ↓
Web-GUI mit Clipboard-Watcher
```

## Features

- **Web-GUI** — dunkles Dashboard, Paketliste mit Fortschritt, Speed, Pause/Resume
- **Clipboard-Watcher** — Links kopieren → Vorschlag erscheint (Wayland: event-getrieben via `wl-paste --watch`, kein Polling)
- **Multihoster-Registry (8 Dienste)** — Real-Debrid, DebridLink, AllDebrid, Premiumize, TorBox, EasyDebrid, LinkSnappy, Offcloud — mit automatischem Fallback, Multi-Accounts pro Dienst; neue Dienste = 1 Python-Klasse
- **600+ Hoster-Domains** — dynamisch von allen konfigurierten Multihostern geladen (nicht hart codiert)
- **Filecrypt-Resolver** — Cloudflare-Challenge + PoW-Captcha (SHA1-Puzzle) nativ im echten Browser gelöst, CNL2 (AES-CBC) lokal entschlüsselt
- **hide.cx-Resolver** — Container-API direkt (JSON, keine Captchas)
- **data-load.me-Login** — XenForo-Login + Release-Threads parsen
- **Passwort-Liste** — `archive_passwords.txt` wird für Container- und Archiv-Passwörter durchgetestet
- **Chunked Downloads** — Resume via `.part`, Speed-Limit, Auto-Retry (3×)
- **Multi-Segment (Beschleuniger)** — Dateien in 8 parallelen Range-Verbindungen laden (FDM-Stil); Range-Support wird automatisch erkannt, sonst Single-Stream-Fallback; Segment-Fortschritt im `.parts`-Sidecar → Resume setzt exakt bei fehlenden Ranges an
- **Scheduler (Zeitplan)** — Downloads zeitgesteuert starten/pausieren: Fenster pro Paket oder global, Wochentage, über-Mitternacht-Fenster (z. B. 22:00–06:00)
- **Reconnect** — neue IP vom Router ziehen (Fritz!Box-SOAP, externes Skript oder URL), um Hoster-Wartezeiten/Limits zurückzusetzen
- **Multi-Mirror** — dieselbe Datei parallel von mehreren Quellen laden; Größen werden abgeglichen, fehlende Ranges round-robin verteilt, Bandbreite summiert sich
- **Torrent/Magnet** — via aria2 (externes Binary, JSON-RPC); `.torrent` + Magnet-Links, Pause/Resume/Remove
- **Direct-Hoster-Fallback (M6)** — für Hoster, die KEIN Debrid-Dienst anbietet (filejoker, webshare.cz, krakenfiles, f2h.to): eigenes Plugin mit Free-Download-Flow oder Premium-Cookies (`~/.config/smartys-downloader/hoster_cookies/<name>.json`), greift automatisch wenn alle Debrid-Dienste den Hoster nicht kennen
- **Paket-weises Entpacken** — Multipart-RAR erst entschlüsseln wenn ALLE Parts da sind, größte Videodatei via rsync zum Ziel (z. B. Jellyfin), danach Archive automatisch löschen

## Quick Start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env    # API-Keys eintragen
.venv/bin/python run.py # → http://127.0.0.1:8765
```

## Konfiguration (.env)

| Key | Beschreibung |
|---|---|
| `REALDEBRID_API_KEY` | https://real-debrid.com/apitoken |
| `DEBRIDLINK_API_KEY` | https://debrid-link.fr API |
| `FLARESOLVERR_URL` | FlareSolverr-Endpoint für Filecrypt |
| `DOWNLOAD_DIR` | Ziel-Ordner (Default `~/Downloads/SmartDownloader`) |
| `MAX_PARALLEL` | Parallele Downloads (Default 3) |
| `SEGMENTS` | Parallele Verbindungen pro Download (Default 8) |
| `ARIA2_RPC_PORT` | Port des aria2-RPC-Daemons für Torrent (Default 6800) |
| `ARIA2_RPC_SECRET` | Optionales RPC-Passwort für aria2 |
| `RECONNECT_SCRIPT` / `RECONNECT_URL` / `RECONNECT_FRITZ_*` | Reconnect-Weg (Skript, URL oder Fritz!Box) |

## Architektur

```
smartdl/
├── api.py          # FastAPI: REST + WebSocket-Progress + GUI
├── engine.py       # Queue-State-Machine (new→resolving→downloading→done)
├── debrid.py       # Real-Debrid + DebridLink Router
├── urls.py         # Hoster-Erkennung (dynamisch: 634 Domains)
├── downloader.py   # Multi-Segment HTTP, Resume, Speed-Limit
├── multimirror.py  # Dieselbe Datei parallel von mehreren Quellen
├── scheduler.py    # Zeitplan (zeitgesteuert starten/pausieren)
├── reconnect.py    # Neue IP vom Router (Hoster-Limits zurücksetzen)
├── torrent.py      # Torrent/Magnet via aria2 (JSON-RPC)
├── filecrypt.py    # CNL2-Extraktion + AES-Entschlüsselung
├── flaresolverr.py # Cloudflare-Bypass-Client
├── clipboard.py    # Clipboard-Watcher (wl-paste --watch / X11-Fallback)
├── postprocess.py  # Entpacken → Media-Server → Cleanup
├── store.py        # SQLite-Persistenz (Pakete + Downloads)
├── pow_captcha.py  # Filecrypt PoW-Solver (SHA1 Leading-Zeros)
├── js/             # m.js/s.js für pow_x/pow_data-Generierung (Node)
└── config.py       # Einstellungen
remote/             # Resolver die auf anderen Hosts laufen (sickram/FlareSolverr-Container)
web/                # Web-GUI (dunkles Dashboard)
```

## Warum kein JDownloader/PyLoad?

| | JDownloader 2 | PyLoad | Smartys Downloader |
|---|---|---|---|
| Footprint | 377 MB + JVM | Docker + Plugin-Zoo | < 50 MB |
| Hoster-Support | 1.572 Plugins (einzeln pflegen) | veraltete Plugins | 634 via 2 Debrid-APIs |
| Filecrypt PoW-Captcha | Plugin tot | `Unknown captcha found` | nativ im Browser gelöst |
| GUI | Swing (JVM) | alt | Web (überall erreichbar) |
| Fernzugriff | MyJDownloader-Cloud | offen im Netz | WG-VPN / localhost |

## Version-Log

### v0.3 (05.10.2026)
- **Multi-Segment-Downloader**: 8 parallele Range-Verbindungen mit `.parts`-Sidecar-Resume, Single-Stream-Fallback, globalem Speed-Limit (SHA-verifiziert)
- **Scheduler**: zeitgesteuerte Downloads (Fenster, Wochentage, über Mitternacht), API `GET/PUT /api/schedule`
- **Reconnect**: neue IP via Fritz!Box-SOAP / Skript / URL, API `POST /api/reconnect`
- **Multi-Mirror**: Datei parallel von mehreren Quellen (Größenabgleich, round-robin Ranges)
- **Torrent/Magnet**: aria2-Wrapper (`.torrent`, Magnet), API `/api/torrent/*`

### v0.1 (04.10.2026)
- Kern-Engine: Queue-State-Machine, chunked Downloads mit Resume, SQLite-Store
- Real-Debrid + DebridLink Router mit Fallback (E2E: 1,6 GB via Rapidgator-Links)
- Web-GUI + WebSocket-Fortschritt + Clipboard-Watcher (Wayland event-getrieben)
- **Filecrypt komplett entschlüsselt**: CF-Turnstile per TAB+SPACE-Trick (aus FlareSolverr-Source), PoW-Captcha nativ im uc-Browser, CNL2-AES lokal
- **hide.cx Container-API** entschlüsselt (JSON + Link-Endpunkte)
- **data-load.me** XenForo-Login + Thread-Parsing
- **634 dynamische Hoster-Domains** von DebridLink + Real-Debrid
- Paket-weises Post-Processing (Multipart-RAR wartet auf alle Parts)
- JD2-Vollanalyse als Architektur-Blueprint (docs/JD2_ANALYSIS.md)

## Lizenz

MIT
## Installation

### Linux (.deb)
```bash
sudo apt install ./releases/smartys-downloader_0.1.0_amd64.deb
```
Danach im Startmenü „Smartys Downloader" oder `smartys-downloader` im Terminal.
Das Panel läuft auf http://127.0.0.1:8765 — beim ersten Start fragt der
Installer/Erststart nach Passwort und API-Keys.

### Aus dem Quellcode
```bash
git clone <repo-url> && cd smartys-downloader
bash install.sh
```

### Windows
Siehe `build_windows.md` — auf einem Windows-System `pyinstaller smartys-downloader.spec`
ausführen, Ergebnis ist `dist/SmartDownloader/SmartDownloader.exe`.

## Download-Ziele je Kategorie

Jedes Paket bekommt eine Kategorie (Filme, Serien, Software, Musik, Hörspiel/Hörbuch,
Kinder, Sonstiges). In den Einstellungen legt man fest, wohin fertige Downloads je
Kategorie wandern (rsync-Ziel `user@host:/pfad/` oder lokaler Pfad) — leer bedeutet
nur entpacken. Beispiele: Filme → Jellyfin-Bibliothek, Hörspiele → Audiobookshelf.

## Sicherheit

- Web-Panel: Login mit Passwort (mind. 12 Zeichen, Groß+Klein, Zahl, Sonderzeichen)
- 2FA (TOTP) über QR-Code mit jeder Authenticator-App — in den Einstellungen ein-/ausschaltbar
- API-Keys verschlüsselt (Fernet) in der lokalen Datenbank — nicht im Klartext lesbar
