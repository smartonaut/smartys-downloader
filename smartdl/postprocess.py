"""Post-Processing: Entpacken (RAR/7z/zip) + Move zum Jellyfin (RAIDEN via SSH).

Regeln (Smartys Vorgabe 04.10.2026):
  1. Nach Download: Archiv entpacken (RAR-Multipart mit Passwort-Liste)
  2. Videodatei (größte .mkv/.mp4/.avi) ins Jellyfin-Filme-Verzeichnis auf RAIDEN
  3. Danach: Archive + Downloads löschen — NUR der Film bleibt im Jellyfin
"""
import subprocess
import shutil
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

# Datei-Endungen je Kategorie (größte Datei dieser Endungen gewinnt)
CATEGORY_EXTS = {
    "movie":     (".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".ts", ".iso"),
    "series":    (".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".ts"),
    "software":  (".exe", ".zip", ".7z", ".rar", ".apk", ".msi", ".dmg", ".deb", ".AppImage", ".iso"),
    "music":     (".mp3", ".flac", ".wav", ".m4a", ".ogg", ".opus", ".wma"),
    "audiobook": (".mp3", ".m4a", ".m4b", ".flac", ".ogg", ".opus"),
    "kids":      (".mkv", ".mp4", ".avi", ".mov", ".m4v"),
    "other":     (".mkv", ".mp4", ".avi", ".zip", ".rar", ".7z", ".exe", ".mp3",
                  ".pdf", ".epub", ".iso", ".tar", ".gz"),
}
# Rückwärts-Kompatibilität:
VIDEO_EXTS = CATEGORY_EXTS["movie"]
ARCHIVE_EXTS = (".rar", ".zip", ".7z")

# SSH-Ziel für Jellyfin-Filme auf RAIDEN
from .config import JELLYFIN_TARGET, PASSWORD_FILE

# Passwort-Liste für Archive (Datei pro Zeile, erste Zeile = Default)



def _passwords() -> list[str]:
    if PASSWORD_FILE.exists():
        return [l.strip() for l in PASSWORD_FILE.read_text().splitlines() if l.strip()]
    return []


def is_archive(filename: str) -> bool:
    low = filename.lower()
    return low.endswith(ARCHIVE_EXTS) or ".part" in low or low.endswith(".r00")


def extract(archive: Path, dest_dir: Path) -> list[Path]:
    """Entpackt .zip/.7z/.rar (auch Multipart) nach dest_dir.

    Dispatch nach Typ, damit kein Feature still ausfällt:
      .zip -> stdlib zipfile (plattformneutral, kein externes Binary)
      .7z  -> 7z (auch .7z.001-Volumes)
      .rar -> unrar, Fallback 7z
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    attempts = [None] + _passwords()
    name_low = archive.name.lower()

    if name_low.endswith(".zip"):
        return _extract_zip(archive, dest_dir, attempts)
    if name_low.endswith(".7z") or ".7z." in name_low:
        return _extract_with("7z", archive, dest_dir, attempts)
    try:
        return _extract_with("unrar", archive, dest_dir, attempts)
    except FileNotFoundError:
        return _extract_with("7z", archive, dest_dir, attempts)


def _extract_zip(archive: Path, dest_dir: Path, attempts) -> list[Path]:
    import zipfile

    last = ""
    for pw in attempts:
        try:
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(dest_dir, pwd=pw.encode("utf-8") if pw else None)
            files = _new_files(dest_dir)
            if files:
                return files
            last = "keine Dateien extrahiert"
        except RuntimeError as exc:          # verschlüsselt / falsches Passwort
            last = str(exc)
            continue
        except Exception as exc:
            raise RuntimeError(f"ZIP entpacken fehlgeschlagen: {exc}") from exc
    raise RuntimeError(f"ZIP entpacken fehlgeschlagen: {last}")


def _extract_with(binary: str, archive: Path, dest_dir: Path, attempts) -> list[Path]:
    """Externen Entpacker mit der Passwort-Liste durchprobieren."""
    last_err = ""
    for pw in attempts:
        if binary == "unrar":
            cmd = ["unrar", "x", "-o-", "-y", f"-p{pw}" if pw else "-p-",
                   str(archive), str(dest_dir) + "/"]
        else:
            cmd = ["7z", "x", "-y", "-o" + str(dest_dir), f"-p{pw}" if pw else "-p-",
                   str(archive)]
        r = subprocess.run(cmd, capture_output=True, timeout=3600)  # FileNotFoundError an Aufrufer
        out = (r.stdout + r.stderr).decode("utf-8", errors="replace")
        if r.returncode == 0:
            files = _new_files(dest_dir)
            if files:
                return files
            last_err = "keine Dateien extrahiert"
            continue
        last_err = out.strip()[-300:]
        low = out.lower()
        if "wrong password" in low or "password" in low or "passwort" in low:
            continue
        raise RuntimeError(last_err)
    raise RuntimeError(f"Entpacken fehlgeschlagen: {last_err}")


def _needs_password(unrar_output: str) -> bool:
    return "password" in unrar_output.lower()


def _new_files(dest_dir: Path, before: set | None = None) -> list[Path]:
    """Alle Dateien im extract-dir nach dem Entpacken."""
    return [p for p in dest_dir.rglob("*") if p.is_file()]


def find_video(files: list[Path] | Path) -> Path | None:
    """Größte Videodatei aus Menge finden."""
    files = [files] if isinstance(files, Path) else list(files)
    vids = [f for f in files if f.is_file() and f.suffix.lower() in VIDEO_EXTS]
    if not vids:
        return None
    return max(vids, key=lambda f: f.stat().st_size)


def to_target(file: Path, target: str) -> bool:
    """Datei zum Ziel kopieren. Leeres Ziel -> nur lokal (ok).

    Linux/SSH-Ziel: rsync. Windows: robocopy (UNC-fähig), Fallback shutil.copy2.
    Ein fehlendes Binary ist KEIN Crash, sondern false — der Aufrufer meldet
    den Fehler und lässt die Archive stehen.
    """
    if not target:
        return True

    if IS_WINDOWS:
        dest = Path(target)
        if not dest.is_dir():
            return False
        try:
            r = subprocess.run(
                ["robocopy", str(file.parent), str(dest), file.name,
                 "/COPY:DAT", "/R:2", "/W:2", "/NFL", "/NDL", "/NJH", "/NJS"],
                capture_output=True, timeout=7200)
            if r.returncode < 8:  # 0–7 = Erfolg, >=8 = Fehler
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        try:
            shutil.copy2(file, dest / file.name)
            return True
        except Exception:
            return False

    try:
        r = subprocess.run(["rsync", "-a", "--info=progress2", str(file), target],
                           capture_output=True, timeout=7200)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def to_jellyfin(video: Path) -> bool:
    """Legacy-Wrapper: Video zum film-ziel."""
    return to_target(video, JELLYFIN_TARGET)


def cleanup(files: list[Path]):
    """Downloads + Archive löschen — Jellyfin-Kopie bleibt unberührt."""
    for f in files:
        try:
            if f.is_file():
                f.unlink()
            elif f.is_dir():
                shutil.rmtree(f)
        except Exception:
            pass


def process_package(download_dir: Path, filename: str) -> dict:
    """Komplette Nachverarbeitung für eine fertige Datei.
    Liefert {extracted, video, moved, cleaned}."""
    src = download_dir / filename
    result = {"extracted": [], "video": None, "moved": False, "cleaned": False}
    extract_dir: Path | None = None

    if is_archive(filename):
        extract_dir = download_dir / ("extracted_" + src.stem[:40])
        files = extract(src, extract_dir)
        result["extracted"] = [str(f) for f in files]
        video = find_video(files)
    else:
        video = src if src.suffix.lower() in VIDEO_EXTS else None

    if not video:
        # Sample/Trailer-only-Archiv? Dateien rausrücken, kein Video = Fehler
        raise RuntimeError("keine Videodatei gefunden (nur Samples/Extras?)")

    result["video"] = video.name
    moved = to_jellyfin(video)
    if not moved:
        raise RuntimeError(f"Kopieren zum Jellyfin fehlgeschlagen: {video}")

    # aufräumen: Archiv + extrahierte Dateien + extract-dir
    all_files = []
    if is_archive(filename):
        all_files.append(src)
        if extract_dir is not None and extract_dir.exists():
            all_files.append(extract_dir)
    cleanup(all_files)
    result["cleaned"] = True
    return result