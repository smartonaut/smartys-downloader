# Changelog — Smartys Downloader

Quelle: Versionslog im Forum (https://forum.smartys.tech/d/3) · Pakete: https://downloader.smartys.tech

## v0.3.1 — 20.10.2026

Bugfixes nach einem Code-Audit der Download-Engine:

- **Postprocessing für alle Archive** — `.zip` und `.7z` werden jetzt genauso entpackt wie `.rar`. Vorher wurde ein ZIP-Paket still als „fertig" markiert und nie verschoben.
- **Container-Auflösung ist kein Fehler mehr** — nach dem Auflösen eines Filecrypt-/DLC-Containers blieb die Zeile auf `error` stehen; damit wurde das Paket nie fertig und das Postprocessing lief nie an. Jetzt `done` über eine eigene `ContainerExpanded`-Behandlung.
- **Kein doppeltes Entpacken** — atomarer Claim (`claim_package_processing`) verhindert, dass zwei Worker dasselbe Paket gleichzeitig verarbeiten.
- **Range-Downloads gehärtet** — antwortet ein Server auf einen Range-Request mit `200`, wurde vorher die komplette Datei an jedes Segment-Offset geschrieben (stille Korruption). Jetzt Abbruch und Single-Stream-Fallback.
- **Segmente zählen Bytes** — eine früh abgebrochene Verbindung gilt nicht mehr als vollständiges Segment; die Endkontrolle verlangt 100 % statt 99,5 %.
- **Resume-Fortschritt korrekt** — bereits geladene Bytes werden mitgezählt, der Balken springt nicht mehr zurück.
- **ZIP ohne unrar** — `.zip` läuft über die Python-stdlib; `unrar`/`7z` sind nur noch für `.rar`/`.7z` nötig, ein fehlendes `unrar` fällt sauber auf `7z` zurück.
- **Windows-Postprocessing** — die Ziel-Kopie nutzt `robocopy` (Fallback `shutil.copy2`) statt `rsync`.
- Versionsnummer in `__init__.py`, `packaging/control` und `smartdl.rc` angeglichen (waren auseinandergelaufen).

---

Hier sammeln wir alle Änderungsschritte am **Smartys Downloader** — dem schlanken Download-Beschleuniger und -Manager.

---

## v0.3.0 — 05.10.2026

Die Beta wird zum vollwertigen Download-Beschleuniger.

- **Zeitplan (Scheduler)** — Downloads zeitgesteuert starten und pausieren (Fenster, Wochentage, auch über Mitternacht)
- **Reconnect** — neue IP vom Router ziehen (Fritz!Box SOAP / Skript / URL), um Hoster-Wartezeiten zurückzusetzen
- **Multi-Mirror** — dieselbe Datei parallel von mehreren Quellen laden
- **Torrent & Magnet** — integrierter BitTorrent-Client (aria2)
- **Browser-Extension** — fängt DLC-Container und JD2 „Click'n'Load"-Klicks ab
- **Windows-Installer** — Setup-Wizard mit Zielordner-Wahl und sauberer Deinstallation
- **Linux-Pakete** — .deb (Ubuntu + Debian) und .rpm (RHEL/Fedora + openSUSE)

---

## v0.2.0 — 05.10.2026

Erste öffentliche Beta für Windows, Ubuntu und Debian.

- **Multi-Segment-Beschleunigung** — Dateien werden in mehrere Teile geteilt und parallel geladen.
- **Resume & Fortsetzen** — unterbrochene Downloads werden exakt an der Abbruchstelle fortgesetzt.
- **Web-Panel** — dunkles Dashboard mit Live-Fortschritt, Pause/Resume und Speed.
- **Verschlüsselter Download** — zeitbegrenzte, verschlüsselte Download-Links.
- **Windows (.zip) · Ubuntu (.deb) · Debian (.deb)**

---

Fragen, Probleme und Ideen gerne in die passenden Unterforen. 🙂
