# JDownloader 2 — Vollständige Analyse

Analyse der Live-Installation auf dem ThinkPad (Snap `jdownloader2`, App vom 22.09.2026,
`~/snap/jdownloader2/common/`, 377 MB). Ziel: verstehen, wie JD2 tickt — und was
SmartDownloader leichter machen kann.

## 1. Installations-Anatomie (377 MB)

| Bestandteil | Größe | Inhalt |
|---|---|---|
| `JDownloader.jar` | 5,1 MB | Nur Bootstrap: AppWork-Utils, Updater, Launcher |
| `Core.jar` | 8,9 MB | **4.813 Klassen** — GUI, Controller, API, alles |
| `libs/` | 32 MB | 37 JARs: BouncyCastle (4×), 7-Zip-JBinding, JNA, JAntiCaptcha, JDHttp, DBus, UPnP (Cling), Rhino-JS-Engine (js.jar), Look&Feel (Synthetica 3×), svgSalamander, zip4j … |
| `jd/plugins/hoster/` | ~12 MB | **1.572 Klassen** — ein Plugin pro Filehoster |
| `jd/plugins/decrypter/` | ~8 MB | **784 Klassen** — Link-Decrypter/Container/Folder |
| `tools/linux/` | 279 MB | **FFmpeg + ffprobe** (Video/Media-Hoster) |
| `extensions/` | 0,5 MB | Extraction.jar (Entpacken), Linux-Natives |
| `java/` | (im Snap) | default-jre — die ganze JVM wird mitgeschleppt |

Dazu läuft alles in einer JVM mit Swing-GUI (JDGUI.jar + Synthetica-Look&Feel).

**Fazit Gewicht:** ~90 MB eigentlicher Code + 279 MB FFmpeg + JVM-RAM ( typisch
300-500 MB RSS für eine Swing-App dieser Größe).

## 2. Kern-Architektur (aus Core.jar-Klassennamen rekonstruiert)

```
Link rein
   │
   ▼
LinkCrawler / LinkCollector ("LinkGrabber")
   │  ordnet Links Plugins zu (hoster/decrypter via Domain-Match)
   ▼
PluginForDecrypt (Decrypter)          z.B. FilecryptFolder, AdfLy, Pastebin
   │  löst Container/Redirects/Folder zu direkten Hoster-Links auf
   ▼
DownloadLink (60 KB Klasse!)          das zentrale Datenobjekt
   │  gehört zu einem Package; Zustand, Größe, Konto-Info, Retry-State
   ▼
DownloadWatchDog (99 KB Klasse!)      die Queue-Engine
   │  ├─ DownloadLinkCandidateSelector (was darf als nächstes?)
   │  ├─ DownloadLinkCandidateLoadBalancer
   │  └─ pro Download: SingleDownloadController
   ▼
PluginForHost (Hoster-Plugin)         z.B. DdownloadCom, RapidGatorNet
   │  ├– AccountController liefert Premium-Account (Cache pro Hoster)
   │  └– löst Link → Direkt-URL auf, startet Chunk-Download
   ▼
HTTP-Download (jd/http/Browser)      Chunked, Resume, Rate-Limit, Proxies
   │
   ▼
Extraction (Extension)               7-Zip/RAR, Passwort-Liste, CRC-Check
```

### Die 5 Subsysteme, die JD2 groß machen

1. **Captcha-System** (`org.jdownloader.captcha.v2`): ChallengeResponseController,
   Dialog-Handler (Basic/Click/MultiClick), externe Solver (TwoCaptcha, 9kw, …),
   JAntiCaptcha.jar. *Braucht es nur für Free-Tier-Hoster ohne Debrid.*
2. **Reconnect-System** (`jd.controlling.reconnect`): Router-Reset-Skripte
   (LiveHeader-Scripts), um Free-Hoster-IP-Sperren zu umgehen. *Veraltet —
   Debrid macht das überflüssig.*
3. **MyJDownloader-Cloud-Remote-API** (`org.jdownloader.api.myjdownloader`):
   Vermittlungsserver-Verbindung für Fernsteuerung. *Bei uns: WG-VPN, Web-UI.*
4. **Packagizer/Filter/Hoster-Regeln**: Regelwerk zum Sortieren von Links in
   Pakete (JSON-Configs in `cfg/`). *Gut, aber als simple Regeln genug.*
5. **Update-/Installer-System**: Updater-Revision 5770, eigener Installer,
   WebInstaller. *Git/PyPI/docker pull macht das einfacher.*

## 3. Was JD2 clever macht (übernehmen!)

| JD2-Konzept | Klasse | Für SmartDownloader |
|---|---|---|
| **Zwei Plugin-Typen**: Decrypter (Link→Links) und Hoster (Link→Datei) | `PluginForDecrypt` (39 KB), `PluginForHost` (103 KB) | Genau so: `resolver/` und `hoster/` — gleiche Trennung |
| **XFileSharingProBasic**: EINE Basisklasse für alle XFS-Hoster (ddownload, turbobit, nitroflare sind alle XFS-Forks) | `XFileSharingProBasic` + `YetiShareCore` | Übernehmen: eine `XfsPlugin`-Basisklasse, Hoster nur noch mit Domain+Annotation |
| **AccountController mit Cache**: Multi-Account pro Hoster, Timeout-Handling, Disable bei Fehlern | `jd.controlling.AccountController` (38 KB) | Vereinfachen: pro Hoster eine Account-Liste mit Status |
| **LinkCrawler mit Crawl-Tiefen-Regeln**: was wird verfolgt, was ignoriert | `jd.controlling.linkcrawler` | Übernehmen als Pipeline-Stage |
| **jd/http/Browser**: HTTP-Client mit pro-Plugin-Cookies, Redirect-Kette, Rate-Limit | `jd/http/Browser` (in JDHttp.jar) | curl_cffi-Session pro Plugin-Instanz |
| **Chunk-Downloads**: Datei in N Segmente, parallel, Resume | `ChunkedDownload`-Klassen | httpx/aria2-Integration |
| **DLC-Container** (AES-verschlüsselt, Server-signiert) | `org.jdownloader.dlc.DLCFactory` | Optional, später — Filecrypt-Workflow nutzt DLC |

## 4. Was Smarty NICHT braucht (das sparen wir ein)

| JD2-Ballast | Einsparung |
|---|---|
| 1.572 Hoster-Plugins | **DebridLink löst 345 Hoster auf** — wir brauchen ~5 eigene Plugins als Fallback (XFS-Basis deckt die meisten ab) |
| Swing-GUI + Synthetica + SVG + Icon-Pakete | Web-UI (htmx/React) — der Server läuft headless |
| MyJDownloader-Cloud | WG-VPN — direkter Zugriff |
| Captcha-Farm (TwoCaptcha, 9kw, AntiCaptcha) | curl_cffi (Chrome-TLS) + Debrid = kaum Captchas |
| Reconnect/LiveHeader-Router-Scripts | IP-Sperren irrelevant bei Debrid |
| FFmpeg-Bundle (279 MB) | Nur laden wenn Video-Hoster gebraucht wird |
| UPnP/DBus/Tray/JNA | Weg |
| Updater/Installer-System | `git pull` / `docker pull` |
| JVM | Python oder Go-Binary |

## 5. Der eigentliche Kern — klein!

Wenn man Ballast weglässt, bleibt eine überschaubare Engine:

1. **LinkCrawler**: URL rein → Domain → zuständiges Plugin (Decrypter oder Hoster)
2. **Resolver**: Link → Direkt-URL (+ Account/Cookie wenn nötig)
3. **Queue**: State-Machine pro Download (queued → resolving → downloading → extracting → done / error / retry)
4. **Downloader**: chunked HTTP, Resume, Speed-Limit, Retry mit Backoff
5. **Account-Store**: Hoster → Credentials, mit Test + Disable
6. **Paket-Logik**: Gruppe von Links, Zielordner, Entpacken, Passwort-Liste
7. **Web-UI/REST**: Paketeliste, Fortschritt, Speed, Historie, Add-Links

**Schätzung:** Das Kernsystem ist in Python ~1.500–2.500 Zeilen. JD2 braucht
dafür 4.813 Klassen, weil es GUI + 1.500 Hoster + Captcha + Reconnect +
Updater + Cloud gleichzeitig trägt.

## 6. Messpunkte (live vermessen)

- Installation: 377 MB (davon 279 MB FFmpeg)
- Core.jar allein: 4.813 Klassen / 8,9 MB
- Plugins: 2.356 Klassen (1.572 hoster + 784 decrypter)
- Config-Format: JSON pro Tabelle (`cfg/*.json`), Account-DB **verschlüsselt**
  (`.ejs`/`.efs` — BouncyCastle), Plugin-Subconfigs pro Host
- build.json: JDBrowserRevision 52119 — **aktiv entwickelter Code**, Stand 22.09.2026

## 7. Architektur-Vorbild für SmartDownloader (Python-Referenz)

```
smartdownloader/
├── core/
│   ├── crawler.py        # LinkCrawler-Pipeline
│   ├── queue.py          # DownloadWatchDog (asyncio State-Machine)
│   ├── downloader.py     # chunked HTTP, Resume, Speed-Limit
│   ├── accounts.py       # Account-Store (DebridLink zuerst)
│   └── packages.py       # Pakete, Entpacken, Passwort-Liste
├── plugins/
│   ├── base.py           # ResolverPlugin / HosterPlugin Basisklassen
│   ├── xfs_base.py       # XFileSharingProBasic-Pendant (ein Plugin, viele Hoster)
│   ├── hoster/           # ddownload.py, rapidgator.py, turbobit.py, ...
│   └── resolver/         # filecrypt.py, serienfans.py, url-shortener.py
├── debrid/
│   └── debridlink.py     # API v2 — PRIMÄRER Resolver (345 Hoster!)
├── api/
│   └── server.py         # FastAPI: REST + WebSocket-Progress + Web-UI
├── web/
│   └── index.html        # Dashboard (Pakete, Speed, Historie)
└── cli.py                # smartdl add|list|status|pause|resume
```

**Gewichts-Vergleich am Ende:** Ziel < 30 MB Footprint, < 100 MB RAM,
Start < 2 s — statt 377 MB + JVM + Swing.