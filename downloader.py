"""Segmentierter Downloader mit parallelen Verbindungen (Beschleuniger).

Kern-Upgrade gegenüber dem alten Single-Stream:
  - Datei wird in N Segmente geteilt und parallel geladen (Range-Requests).
  - Segment-Zustand wird in einer Sidecar-Datei persistiert -> Resume nach
    Crash/Neustart setzt genau bei den fehlenden Byte-Ranges an.
  - Fallback: Server ohne Range-Support -> automatisch Single-Stream.

Resume-Logik:
  - .part  = die Zieldatei (wachsend, Segmente schreiben an ihre Offsets).
  - .parts = JSON-Sidecar mit den bereits VOLLSTÄNDIG geladenen Byte-Ranges.
  Beim Neustart werden fehlende Ranges neu gesplittet und nur diese geladen.

Speed-Limit gilt GLOBAL (geteilt über alle Segmente), nicht pro Segment.
"""
import json
import threading
import time
from pathlib import Path

from curl_cffi import requests as creq

# Default: so viele Segmente; wird vom Server (Range) und der Dateigröße
# nach unten begrenzt. 0 = auto (anhand der Größe wählen).
DEFAULT_SEGMENTS = 8
MIN_SEGMENT_BYTES = 1024 * 1024  # unter ~1MB pro Segment lohnt Splitten nicht


def _make_session(session_cookies: dict | None, user_agent: str | None):
    session = creq.Session(impersonate="chrome")
    if session_cookies:
        for k, v in session_cookies.items():
            session.cookies.set(k, v)
    if user_agent:
        session.headers["User-Agent"] = user_agent
    return session


def _probe(session, url) -> tuple[int, bool, str]:
    """(total_bytes, range_supported, final_url) via HEAD, sonst GET-Probe.

    Viele CDNs beantworten HEAD gar nicht oder ohne Länge — dann entscheidet
    eine kleine GET-Anfrage mit Range: bytes=0-0, statt vorschnell auf
    Single-Stream zurückzufallen.
    """
    try:
        r = session.head(url, headers={"Range": "bytes=0-0"},
                         allow_redirects=True, timeout=25)
        final_url = str(r.url) if r.url else url
        cr = r.headers.get("Content-Range", "")
        if r.status_code == 206 and "/" in cr:
            return int(cr.split("/")[-1]), True, final_url
        cl = r.headers.get("Content-Length", "")
        if r.status_code in (200, 204) and cl.isdigit() and int(cl) > 0:
            return int(cl), False, final_url
    except Exception:
        pass

    try:
        r = session.get(url, headers={"Range": "bytes=0-0"},
                        allow_redirects=True, timeout=25, stream=True)
        final_url = str(r.url) if r.url else url
        cr = r.headers.get("Content-Range", "")
        status = r.status_code
        cl = r.headers.get("Content-Length", "")
        r.close()
        if status == 206 and "/" in cr:
            return int(cr.split("/")[-1]), True, final_url
        return (int(cl) if cl.isdigit() else 0), False, final_url
    except Exception:
        return 0, False, url


class _Throttle:
    """Globales Speed-Limit (Byte-Budget über alle Segmente)."""

    def __init__(self, limit_kb: int):
        self.limit = limit_kb * 1024 if limit_kb else 0
        self._lock = threading.Lock()
        self._window_start = time.time()
        self._window_bytes = 0

    def wait(self, nbytes: int):
        if not self.limit:
            return
        with self._lock:
            self._window_bytes += nbytes
            elapsed = time.time() - self._window_start
            if self._window_bytes >= self.limit:
                expected = self._window_bytes / self.limit
                if expected > elapsed:
                    time.sleep(expected - elapsed)
                self._window_start = time.time()
                self._window_bytes = 0


class _Progress:
    """Aggregiert Fortschritt über alle Segmente und meldet ~4x/s."""

    def __init__(self, total: int, cb):
        self.total = total
        self.cb = cb
        self.done = 0
        self._lock = threading.Lock()
        self._last = 0.0
        self._last_done = 0

    def add(self, nbytes: int):
        with self._lock:
            self.done += nbytes
            now = time.time()
            if self.cb and now - self._last > 0.4:
                speed = (self.done - self._last_done) / max(0.001, now - self._last)
                self._last = now
                self._last_done = self.done
                self.cb(self.done, self.total, speed)


def _load_sidecar(parts_file: Path) -> list[tuple[int, int]]:
    """Geladene [start,end)-Ranges aus der Sidecar-Datei."""
    if not parts_file.exists():
        return []
    try:
        data = json.loads(parts_file.read_text())
        return [(int(a), int(b)) for a, b in data.get("done", [])]
    except Exception:
        return []


def _save_sidecar(parts_file: Path, done: list[tuple[int, int]]):
    tmp = parts_file.with_suffix(".tmp")
    tmp.write_text(json.dumps({"done": sorted(done)}))
    tmp.replace(parts_file)


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    ranges = sorted(ranges)
    merged = []
    for a, b in ranges:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _missing_ranges(total: int, done: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Byte-Lücken zwischen 0..total, die noch nicht in `done` sind."""
    merged = _merge_ranges(done)
    missing = []
    pos = 0
    for a, b in merged:
        if a > pos:
            missing.append((pos, a))
        pos = max(pos, b)
    if pos < total:
        missing.append((pos, total))
    return missing


def download(direct_url: str, dest: Path, progress_cb=None, speed_limit: int = 0,
             session_cookies: dict | None = None, user_agent: str | None = None,
             stop_event: threading.Event | None = None,
             segments: int = DEFAULT_SEGMENTS) -> dict:
    """Lädt direct_url nach dest — segmentiert, parallel, resume-fähig.

    progress_cb(downloaded, total, speed_bytes)
    speed_limit in KB/s (0 = frei, gilt global)
    segments: parallele Verbindungen (0 = auto)
    Liefert {ok, downloaded, error}
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part_file = dest.with_suffix(dest.suffix + ".part")
    parts_file = dest.with_suffix(dest.suffix + ".parts")

    session = _make_session(session_cookies, user_agent)
    total, range_ok, final_url = _probe(session, direct_url)

    # Fertige Datei liegt schon da?
    if dest.exists() and not part_file.exists():
        if total and dest.stat().st_size >= total:
            return {"ok": True, "downloaded": total, "error": None}
        if not total and dest.stat().st_size > 0:
            return {"ok": True, "downloaded": dest.stat().st_size, "error": None}

    # Kein Range-Support -> Single-Stream (alter, bewährter Pfad)
    if not range_ok or not total:
        return _download_single(session, final_url, dest, part_file, total,
                                progress_cb, speed_limit, stop_event)

    done = _load_sidecar(parts_file)
    missing = _missing_ranges(total, done)
    if not missing:
        part_file.rename(dest)
        parts_file.unlink(missing_ok=True)
        return {"ok": True, "downloaded": total, "error": None}

    # Segment-Anzahl sinnvoll begrenzen
    n = segments or DEFAULT_SEGMENTS
    total_missing = sum(b - a for a, b in missing)
    n = max(1, min(n, total_missing // MIN_SEGMENT_BYTES or 1))

    # Fehlende Ranges in n gleichgroße Segmente aufteilen (ganzzahlig!)
    segs = []
    per = max(MIN_SEGMENT_BYTES, total_missing // n)
    for a, b in missing:
        cur = a
        while cur < b:
            end = min(b, cur + per)
            segs.append((int(cur), int(end)))
            cur = int(end)

    throttle = _Throttle(speed_limit)
    progress = _Progress(total, progress_cb)
    progress.done = sum(b - a for a, b in done)  # Resume: fertige Bytes mitzählen
    seg_lock = threading.Lock()
    completed: list[tuple[int, int]] = list(done)
    errors: list[str] = []
    paused = threading.Event()

    def _run_seg(start: int, end: int):
        # JEDES Segment bekommt seine eigene Session — curl_cffi-Sessions
        # sind NICHT thread-sicher; geteilte Session = nur ein Segment lädt.
        seg_session = _make_session(session_cookies, user_agent)
        want = end - start
        written = 0
        try:
            with open(part_file, "r+b") as f:
                f.seek(start)
                resp = seg_session.get(final_url,
                                       headers={"Range": f"bytes={start}-{end - 1}"},
                                       allow_redirects=True, timeout=60, stream=True)
                try:
                    if resp.status_code == 200:
                        # Server ignoriert Range: volle Datei würde an dieses Offset
                        # geschrieben -> stille Korruption. Abbruch + Single-Stream.
                        with seg_lock:
                            errors.append("RANGE_IGNORED")
                        return
                    if resp.status_code != 206:
                        with seg_lock:
                            errors.append(f"HTTP {resp.status_code}")
                        return
                    for chunk in resp.iter_content(chunk_size=256 * 1024):
                        if stop_event is not None and stop_event.is_set():
                            paused.set()
                            return
                        if written + len(chunk) > want:
                            chunk = chunk[:want - written]
                        if not chunk:
                            break
                        f.write(chunk)
                        written += len(chunk)
                        throttle.wait(len(chunk))
                        progress.add(len(chunk))
                        if written >= want:
                            break
                finally:
                    resp.close()
            if written != want:
                # früher Stream-Abbruch: Range NICHT als fertig eintragen
                with seg_lock:
                    errors.append(f"segment {start}-{end} unvollständig ({written}/{want})")
                return
            with seg_lock:
                completed.append((start, end))
                _save_sidecar(parts_file, completed)
        except Exception as e:
            with seg_lock:
                errors.append(str(e))

    # .part anlegen (falls leer)
    if not part_file.exists():
        with open(part_file, "wb"):
            pass

    threads = [threading.Thread(target=_run_seg, args=(s, e), daemon=True)
               for s, e in segs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if paused.is_set():
        return {"ok": False, "downloaded": progress.done, "error": "PAUSED"}

    if "RANGE_IGNORED" in errors and progress.done == 0:
        # Server liefert trotz Range-Probe die volle Datei -> linear laden
        return _download_single(session, final_url, dest, part_file, total,
                                progress_cb, speed_limit, stop_event)

    # Finale Prüfung: alles da?
    done_all = _merge_ranges(_load_sidecar(parts_file))
    total_done = sum(b - a for a, b in done_all)
    if total_done >= total:
        part_file.rename(dest)
        parts_file.unlink(missing_ok=True)
        return {"ok": True, "downloaded": total, "error": None}
    err = "; ".join(errors[:3]) if errors else "abgebrochen"
    return {"ok": False, "downloaded": total_done,
            "error": f"unvollständig ({total_done}/{total}): {err}"}


def _download_single(session, url, dest, part_file, total, progress_cb,
                     speed_limit, stop_event) -> dict:
    """Fallback: linearer Download ohne Range (Server unterstützt kein Range)."""
    part_file.unlink(missing_ok=True)
    downloaded = 0
    throttle = _Throttle(speed_limit)
    ok = False
    error = None
    last_report = 0.0
    window_bytes = 0
    window_start = time.time()

    with open(part_file, "wb") as f:
        r = session.get(url, allow_redirects=True, timeout=60, stream=True)
        try:
            if r.status_code not in (200, 206):
                error = f"HTTP {r.status_code}"
            else:
                ok = True
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if stop_event is not None and stop_event.is_set():
                        ok = False
                        error = "PAUSED"
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    throttle.wait(len(chunk))
                    window_bytes += len(chunk)
                    now = time.time()
                    if progress_cb and now - last_report > 0.4:
                        speed = window_bytes / max(0.001, now - window_start)
                        progress_cb(downloaded, total, speed)
                        window_bytes = 0
                        window_start = now
                        last_report = now
        finally:
            r.close()

    if ok:
        part_file.rename(dest)
        return {"ok": True, "downloaded": downloaded, "error": None}
    return {"ok": False, "downloaded": downloaded, "error": error}
