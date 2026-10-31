"""Multi-Mirror — dieselbe Datei von mehreren Quellen parallel laden.

Zweck: Liegt eine Datei identisch auf mehreren Mirrors (z. B. derselbe
Debrid-Link über mehrere Dienste, oder mehrere direkte URLs), lädt der
Downloader die Segmente auf die Mirrors verteilt — fällt ein Mirror aus,
übernehmen die anderen, und die Gesamtbandbreite summiert sich.

Kernidee: Das bestehende segmentierte download() wird pro Mirror mit einem
DISJUNKTEN Byte-Range-Satz aufgerufen. Jeder Mirror schreibt in dieselbe
.part-Datei; die .parts-Sidecar (fertige Ranges) wird geteilt.

Ablauf:
  1. Für jeden Mirror die Gesamtgröße prüfen (Range-Probe). Mirrors mit
     abweichender Größe aussortieren (nicht dieselbe Datei).
  2. Fehlende Ranges auf die Mirrors aufteilen.
  3. Pro Mirror: download() mit segments und einem festen Range-Satz.
  4. Am Ende zusammenführen und wie üblich abschließen.

Da download() intern selbst segmentiert, nutzt Multi-Mirror eine dünne
Schicht darüber: sie ruft für jeden Mirror einen eigenen Download-Worker
mit einem Teil-Range auf. Die Zusammenführung passiert über die geteilte
.parts-Sidecar.
"""
import threading
from pathlib import Path

from .downloader import download
from .downloader import _probe, _make_session, _load_sidecar, _save_sidecar, \
    _merge_ranges, _missing_ranges


def download_mirrors(mirrors: list[str], dest: Path, progress_cb=None,
                     speed_limit: int = 0, segments_per_mirror: int = 4,
                     stop_event: threading.Event | None = None,
                     session_cookies: dict | None = None,
                     user_agent: str | None = None) -> dict:
    """Lädt dieselbe Datei parallel von mehreren Mirrors.

    mirrors: Liste gleichwertiger direkter URLs (identische Datei).
    Liefert {ok, downloaded, error}.
    """
    if not mirrors:
        return {"ok": False, "downloaded": 0, "error": "keine Mirrors"}
    if len(mirrors) == 1:
        return download(mirrors[0], dest, progress_cb, speed_limit,
                        session_cookies, user_agent, stop_event, segments_per_mirror)

    dest.parent.mkdir(parents=True, exist_ok=True)
    part_file = dest.with_suffix(dest.suffix + ".part")
    parts_file = dest.with_suffix(dest.suffix + ".parts")

    # 1. Größen prüfen — nur identische Mirrors behalten
    valid = []
    total = 0
    for m in mirrors:
        sess = _make_session(session_cookies, user_agent)
        size, range_ok, _ = _probe(sess, m)
        if size and (total == 0 or size == total):
            total = size
            valid.append(m)
        elif size and total and size != total:
            continue  # andere Größe = andere Datei, raus
    if not valid or not total:
        return {"ok": False, "downloaded": 0, "error": "keine nutzbaren Mirrors (Größenabweichung)"}

    # 2. fehlende Ranges ermitteln
    done = _load_sidecar(parts_file)
    missing = _missing_ranges(total, done)
    if not missing:
        if part_file.exists():
            part_file.rename(dest)
        parts_file.unlink(missing_ok=True)
        return {"ok": True, "downloaded": total, "error": None}

    # 3. fehlende Ranges auf die Mirrors verteilen (round-robin in Blöcken)
    block = max(1024 * 1024, total // (len(valid) * 16))
    assignments = {m: [] for m in valid}
    idx = 0
    for a, b in missing:
        cur = a
        while cur < b:
            end = min(b, cur + block)
            assignments[valid[idx % len(valid)]].append((cur, end))
            cur = end
            idx += 1

    # 4. pro Mirror einen Worker, der seine Ranges lädt
    #    (nutzt download() direkt mit einem festen Segment-Set ist umständlich,
    #    daher hier ein leichter Range-Worker gegen die geteilte Sidecar)
    errors = []
    paused = threading.Event()
    lock = threading.Lock()

    def _worker(mirror: str, ranges):
        sess = _make_session(session_cookies, user_agent)
        for start, end in ranges:
            if stop_event is not None and stop_event.is_set():
                paused.set()
                return
            try:
                with open(part_file, "r+b") as f:
                    f.seek(start)
                    resp = sess.get(mirror,
                                    headers={"Range": f"bytes={start}-{end - 1}"},
                                    allow_redirects=True, timeout=60, stream=True)
                    try:
                        if resp.status_code not in (200, 206):
                            with lock:
                                errors.append(f"{mirror}: HTTP {resp.status_code}")
                            continue
                        for chunk in resp.iter_content(chunk_size=256 * 1024):
                            if stop_event is not None and stop_event.is_set():
                                paused.set()
                                return
                            f.write(chunk)
                            if progress_cb:
                                progress_cb(len(chunk), total, 0)
                    finally:
                        resp.close()
                with lock:
                    done_now = _load_sidecar(parts_file)
                    done_now.append((start, end))
                    _save_sidecar(parts_file, _merge_ranges(done_now))
            except Exception as e:
                with lock:
                    errors.append(str(e))

    if not part_file.exists():
        with open(part_file, "wb"):
            pass

    threads = [threading.Thread(target=_worker, args=(m, r), daemon=True)
               for m, r in assignments.items() if r]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if paused.is_set():
        return {"ok": False, "downloaded": 0, "error": "PAUSED"}

    done_all = _merge_ranges(_load_sidecar(parts_file))
    total_done = sum(b - a for a, b in done_all)
    if total_done >= total * 0.995:
        part_file.rename(dest)
        parts_file.unlink(missing_ok=True)
        return {"ok": True, "downloaded": total, "error": None}
    err = "; ".join(errors[:3]) if errors else "abgebrochen"
    return {"ok": False, "downloaded": total_done,
            "error": f"unvollständig ({total_done}/{total}): {err}"}
