"""Clipboard-Überwachung — findet Links in der Zwischenablage.

Wayland: `wl-paste --watch` (Event-getrieben, EINE persistente Verbindung —
kein Polling! Polling mit 1s-Intervall erzeugte Wayland-Client-Churn und
GNOME-Shell-Blinken, siehe Brain smartdownloader_wlpaste_bug_261004).
X11: xclip/xsel-Polling (xclip -o ohne neue Verbindung kritisch? X11 ist
harmlos dafür, aber wir nutzen dort ein sparsames 2s-Polling als Fallback).

Neue Links (die noch nicht in der DB sind) werden als Paket-Vorschlag gemeldet.
"""
import subprocess
import threading
from . import store
from .urls import extract_urls, get_hoster, is_filecrypt


def _extract_fresh(clip: str, seen: set[str]) -> list[dict]:
    """Neue Download-URLs aus Clipboard-Text. Aktualisiert `seen`."""
    fresh = []
    for u in extract_urls(clip):
        if u in seen:
            continue
        hoster = get_hoster(u)
        if hoster is None and not is_filecrypt(u):
            # unbekannt — nur vorschlagen wenn datei-artig oder direct-plugin
            from .urls import is_direct_file
            from .direct_hoster import can_resolve
            if not is_direct_file(u) and not can_resolve(u):
                continue  # keine Download-URL
        fresh.append({"url": u, "hoster": hoster or "datei",
                      "filecrypt": is_filecrypt(u)})
        seen.add(u)
    return fresh


def _read_clipboard_once() -> str:
    for cmd in (["wl-paste", "-n"], ["xclip", "-o", "-selection", "clipboard"],
                ["xsel", "-ob"]):
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=5)
            if r.returncode == 0:
                return r.stdout.decode("utf-8", errors="replace")
        except Exception:
            continue
    return ""


def _known_urls() -> set[str]:
    return {r["source_url"] for r in store.rows("SELECT source_url FROM downloads")}


def _watch_wayland(on_new_links, stop_event: threading.Event) -> bool:
    """Event-getriebenes Clipboard via `wl-paste --watch cat`.

    EIN wl-paste-Prozess, EINE Wayland-Verbindung, feuert nur bei Änderung.
    Liefert False wenn wl-paste nicht verfügbar ist (→ X11-Fallback).
    """
    try:
        proc = subprocess.Popen(
            ["wl-paste", "--watch", "cat"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except Exception:
        return False
    try:
        seen = _known_urls()
        assert proc.stdout is not None
        for line in proc.stdout:
            if stop_event.is_set():
                break
            clip = line.decode("utf-8", errors="replace").strip()
            if not clip:
                continue
            fresh = _extract_fresh(clip, seen)
            if fresh:
                on_new_links(fresh)
        return True
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


def _watch_x11(on_new_links, stop_event: threading.Event):
    """X11-Fallback: sparsames Polling alle 2s."""
    seen = _known_urls()
    last_clip = ""
    while not stop_event.is_set():
        clip = _read_clipboard_once()
        if clip and clip != last_clip:
            last_clip = clip
            fresh = _extract_fresh(clip, seen)
            if fresh:
                on_new_links(fresh)
        stop_event.wait(2.0)


def watch(on_new_links, stop_event: threading.Event):
    """Clipboard beobachten. on_new_links(links: list[dict]) bei neuen Links.

    dict: {url, hoster, filecrypt}. Wayland: event-getrieben (wl-paste --watch),
    X11: 2s-Polling.
    """
    if _watch_wayland(on_new_links, stop_event):
        return
    _watch_x11(on_new_links, stop_event)