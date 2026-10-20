"""Queue-Engine — das Herzstück: State-Machine pro Download + Worker-Pool.

Pipeline pro Download:
  new → resolving (Filecrypt auflösen / Debrid unrestrict) → queued
      → downloading (chunked, resume) → done | error(retry) 
"""
import re
import threading
import time
from pathlib import Path
from . import store, config
from .debrid import DebridRouter, DebridError
from .filecrypt import resolve_container, FilecryptError
from .downloader import download
from .urls import is_filecrypt, is_direct_file
from .dlc import dlc_extract, is_dlc
from .direct_hoster import resolve_direct, DirectHosterError

_RAR_PART = re.compile(r"\.part\d+\.rar$", re.I)
_RAR_OLDVOL = re.compile(r"\.r\d{2}$", re.I)


class ContainerExpanded(FilecryptError):
    """Container wurde erfolgreich aufgelöst — das ist KEIN Fehler.

    Muss im Worker getrennt behandelt werden, sonst überschreibt der
    Fehler-Handler die Container-Zeile mit status='error' und das Paket
    erreicht nie 'alle done' -> Postprocessing läuft nie an.
    """


def _archive_starts(names: list[str]) -> list[str]:
    """Startdatei je Archiv-Satz — jedes Archiv wird genau einmal entpackt."""
    starts: list[str] = []
    for name in names:
        low = name.lower()
        if _RAR_PART.search(low):
            if re.search(r"\.part0*1\.rar$", low):
                starts.append(name)
        elif low.endswith(".rar"):
            if not _RAR_OLDVOL.search(low):  # .r00-Volumen ist kein Start
                starts.append(name)
        elif low.endswith(".zip"):
            starts.append(name)
        elif low.endswith(".7z") or re.search(r"\.7z\.0*1$", low):
            starts.append(name)
    return starts


class QueueEngine:
    def __init__(self):
        self.router = DebridRouter()
        self.stop_event = threading.Event()
        self._workers: list[threading.Thread] = []
        self._active: dict[int, threading.Event] = {}  # download_id → pause-flag
        self._lock = threading.Lock()
        self.filecrypt_passwords: list[str] = []  # optionale PW-Liste

    # ---------- Lifecycle ----------
    def start(self, n_workers: int | None = None):
        n = n_workers or config.MAX_PARALLEL
        for i in range(n):
            t = threading.Thread(target=self._worker_loop, name=f"smartdl-w{i}", daemon=True)
            t.start()
            self._workers.append(t)

    def stop(self):
        self.stop_event.set()

    # ---------- Öffentliche Aktionen ----------
    def pause(self, download_id: int):
        with self._lock:
            ev = self._active.get(download_id)
            if ev:
                ev.set()
        store.update_download(download_id, status="paused")

    def resume(self, download_id: int):
        store.update_download(download_id, status="queued")

    def retry(self, download_id: int):
        store.update_download(download_id, status="queued", error=None, retries=0)

    # ---------- Worker ----------
    def _worker_loop(self):
        while not self.stop_event.is_set():
            did = self._claim_next()
            if not did:
                self.stop_event.wait(2.0)
                continue
            self._process(did)

    def _claim_next(self) -> int | None:
        r = store.rows(
            "SELECT id FROM downloads WHERE status='queued' ORDER BY id LIMIT 1")
        if not r:
            return None
        did = r[0]["id"]
        # claimen (atomic via status-cas)
        store.q("UPDATE downloads SET status='claiming' WHERE id=? AND status='queued'", (did,))
        chk = store.rows("SELECT status FROM downloads WHERE id=?", (did,))
        if chk and chk[0]["status"] == "claiming":
            return did
        return None

    def _process(self, did: int):
        r = store.rows("SELECT * FROM downloads WHERE id=?", (did,))
        if not r:
            return
        d = dict(r[0])
        pkg = store.rows("SELECT * FROM packages WHERE id=?", (d["package_id"],))
        password = pkg[0]["password"] if pkg else None

        try:
            # Phase 1: Auflösen (nur wenn noch kein direct_url)
            if not d.get("direct_url"):
                store.update_download(did, status="resolving")
                direct = self._resolve(d["source_url"], password)
                store.update_download(did, direct_url=direct["url"],
                                      filename=direct.get("filename") or d.get("filename") or "",
                                      size=direct.get("size", 0),
                                      via=direct.get("via", "?"),
                                      status="queued")
                return  # nächster Tick nimmt ihn als queued

            # Phase 2: Download
            store.update_download(did, status="downloading")
            pause_ev = threading.Event()
            with self._lock:
                self._active[did] = pause_ev
            dest = Path(config.DOWNLOAD_DIR) / d["filename"]
            if not d["filename"]:
                dest = Path(config.DOWNLOAD_DIR) / d["direct_url"].split("/")[-1].split("?")[0]

            result = download(
                d["direct_url"], dest,
                progress_cb=lambda done, total, speed:
                    store.update_download(did, downloaded=done, size=total,
                                           speed=int(speed), eta=_eta(done, total, speed)),
                speed_limit=config.SPEED_LIMIT_KB,
                stop_event=pause_ev,
                segments=config.SEGMENTS,
            )
            with self._lock:
                self._active.pop(did, None)

            if result["ok"]:
                store.update_download(did, status="done", speed=0,
                                      finished_at=time.time())
                # Post-Processing PAKET-WEIT: erst wenn ALLE downloads des
                # pakets fertig sind → multipart-rar braucht alle parts!
                self._maybe_postprocess_package(d["package_id"])
                self._check_package_done(d["package_id"])
            else:
                err = result["error"]
                if err == "PAUSED":
                    return
                retries = (d.get("retries") or 0) + 1
                if retries <= 3:
                    store.update_download(did, status="queued", error=err, retries=retries)
                else:
                    store.update_download(did, status="error", error=err)

        except ContainerExpanded:
            # Container aufgelöst: Zeile bleibt 'done', Kind-Links laufen weiter
            store.update_download(did, status="done", error=None)
        except (FilecryptError, DebridError, DirectHosterError) as e:
            msg = str(e)
            store.update_download(did, status="error", error=msg)
        except Exception as e:
            store.update_download(did, status="error", error=f"unerwartet: {e}")

    # ---------- Auflösung ----------
    def _resolve(self, url: str, package_password: str | None) -> dict:
        # DLC-Container-Datei → lokal parsen (ohne PoW, ohne Browser)
        if url.lower().endswith(".dlc") or is_dlc(url):
            links = dlc_extract(url)
            if links:
                pkg_id = store.rows(
                    "SELECT package_id FROM downloads WHERE source_url=?",
                    (url,))
                pid = pkg_id[0]["package_id"] if pkg_id else None
                if pid:
                    for l in links:
                        store.add_download(pid, l, status="queued")
                raise ContainerExpanded(
                    f"DLC_ENTPACKT:{len(links)} Links aus DLC-Container")
        # Filecrypt-Container → Hoster-Links → als neue Downloads ins Paket
        if is_filecrypt(url):
            pw = package_password or (self.filecrypt_passwords[0] if self.filecrypt_passwords else None)
            links = resolve_container(url, password=pw)
            pkg_id = store.rows("SELECT package_id FROM downloads WHERE source_url=?", (url,))
            pid = pkg_id[0]["package_id"] if pkg_id else None
            if pid:
                for l in links:
                    # Kind-Links direkt als 'queued' anlegen — sonst liegen sie
                    # nach dem Container-Auflösen ewig auf 'new' (start lief schon)
                    store.add_download(pid, l, hoster=get_hoster_safe(l),
                                       status="queued")
                # Container selbst ist erledigt
                if pid:
                    row = store.rows(
                        "SELECT id FROM downloads WHERE source_url=? AND package_id=?",
                        (url, pid))
                    if row:
                        store.update_download(row[0]["id"], status="done")
            raise ContainerExpanded(
                f"CONTAINER_EXPANDED:{len(links)} Links ins Paket eingefügt — "
                f"Kind-Links folgen automatisch")

        # Bekannter One-Click-Hoster (ddownload, rapidgator, ...) → IMMER Debrid,
        # NIE direkt — die URL ist eine Hoster-Seite, kein Direktfile!
        # Fallback: wenn KEIN Debrid-Dienst den Hoster kennt → direct-hoster-plugin
        from .urls import get_hoster
        if get_hoster(url):
            try:
                result = self.router.unrestrict(url)
            except DebridError:
                result = resolve_direct(url)  # wirft DirectHosterError wenn kein plugin
                result["via"] = result.get("via", "direct")
            if not result.get("filename"):
                result["filename"] = url.split("/")[-1].split("?")[0]
            return result

        # Direktdatei auf unbekanntem Host → skip Debrid
        if is_direct_file(url):
            name = url.split("/")[-1].split("?")[0]
            return {"url": url, "filename": name, "size": 0, "via": "direct"}

        # Unbekannt ohne Datei-Endung: Debrid versuchen, dann direct-plugin
        try:
            result = self.router.unrestrict(url)
        except DebridError:
            result = resolve_direct(url)
            result["via"] = result.get("via", "direct")
        if not result.get("filename"):
            result["filename"] = url.split("/")[-1].split("?")[0]
        return result

    def _check_package_done(self, pid: int):
        r = store.rows("SELECT COUNT(*) as n, "
                       "SUM(CASE WHEN status IN ('done') THEN 1 ELSE 0 END) as done "
                       "FROM downloads WHERE package_id=?", (pid,))
        if r and r[0]["n"] and r[0]["n"] == r[0]["done"]:
            store.update_package(pid, status="done")

    def _maybe_postprocess_package(self, pid: int):
        """Post-Processing PAKET-WEIT: läuft genau EINMAL, wenn ALLE downloads
        des Pakets done sind (Multipart-Archive brauchen alle Teile).

        1. alle Archive (.rar-Multipart, .zip, .7z) entpacken
        2. größte passende Datei -> Ziel-Kopie (Jellyfin/NAS)
        3. Archive + Extrakte löschen
        """
        r = store.rows(
            "SELECT COUNT(*) as n FROM downloads "
            "WHERE package_id=? AND status NOT IN ('done')", (pid,))
        if r[0]["n"]:
            return  # noch was offen

        # atomarer Claim: bei zwei gleichzeitig fertigen Workern gewinnt EINER
        if not store.claim_package_processing(pid):
            return

        try:
            from .postprocess import extract, to_target, cleanup, is_archive, CATEGORY_EXTS

            pkg = store.rows("SELECT * FROM packages WHERE id=?", (pid,))
            category = "movie"
            if pkg and pkg[0]:
                row = pkg[0]
                try:
                    category = (row["category"] if "category" in dict(row) else None) or "movie"
                except Exception:
                    category = "movie"

            import json as _json
            from .config import CATEGORY_TARGETS_ENV
            raw_t = store.get_setting("category_targets", "")
            targets = _json.loads(raw_t) if raw_t else {}
            target = targets.get(category, "") or CATEGORY_TARGETS_ENV.get(category, "")
            wanted_exts = CATEGORY_EXTS.get(category, CATEGORY_EXTS["movie"])

            dl_dir = Path(config.DOWNLOAD_DIR)
            files = store.rows(
                "SELECT filename FROM downloads WHERE package_id=? AND status='done'",
                (pid,))
            names = [f["filename"] for f in files if f["filename"]]
            archives = [n for n in names if is_archive(n)]

            if not archives:
                # Einzeldatei (kein Archiv): direkt zum Ziel, Download bleibt liegen
                direct = [dl_dir / n for n in names
                          if (dl_dir / n).is_file() and (dl_dir / n).suffix.lower() in wanted_exts]
                if direct and target:
                    best_direct = max(direct, key=lambda f: f.stat().st_size)
                    if not to_target(best_direct, target):
                        raise RuntimeError(f"ziel-kopie fehlgeschlagen: {best_direct.name}")
                store.update_package(pid, status="postprocessed")
                return

            starts = _archive_starts(archives)
            if not starts:
                raise RuntimeError("kein Archiv-Startteil gefunden")

            extract_dir = dl_dir / f"extracted_{pid}"
            for s in starts:
                extract(dl_dir / s, extract_dir)

            found = [f for f in extract_dir.rglob("*")
                     if f.is_file() and f.suffix.lower() in wanted_exts]
            if not found:
                raise RuntimeError(f"keine datei für kategorie '{category}' im archiv")
            best = max(found, key=lambda f: f.stat().st_size)

            if not to_target(best, target):
                raise RuntimeError(f"ziel-kopie fehlgeschlagen: {best.name}")

            cleanup([dl_dir / n for n in archives if (dl_dir / n).exists()])
            cleanup([extract_dir])
            store.update_package(pid, status="postprocessed")
        except Exception as e:
            store.update_package(pid, status="error", comment=f"postprocess: {e}")


def get_hoster_safe(url: str) -> str:
    from .urls import get_hoster
    return get_hoster(url) or "?"


def _eta(done, total, speed):
    if not total or not speed or done >= total:
        return 0
    return int((total - done) / speed)