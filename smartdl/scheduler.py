"""Zeitplan (Scheduler) — Downloads zeitgesteuert starten/pausieren.

Regeln liegen als JSON in der settings-Tabelle unter 'schedule_rules'.
Pro Regel: entweder ein Zeitfenster pro Paket oder globale Fenster.

Struktur einer Regel:
{
  "package_id": 0,          # 0 = gilt fuer ALLE Pakete (global)
  "window_start": "22:00",  # HH:MM (lokal) — Downloads in diesem Zeitraum starten
  "window_end":   "06:00",  # HH:MM — danach pausieren
  "days": [0,1,2,3,4,5,6], # optional; leere Liste = taeglich
  "enabled": true
}

Semantik (FDM-ähnlich, einfach):
  - Innerhalb des Fensters werden die Downloads des Pakets (bzw. alle) auf
    'queued' gesetzt (bzw. bei global: neue Downloads freigegeben).
  - Ausserhalb des Fensters werden laufende Downloads pausiert und neue
    NICHT gestartet (auf 'scheduled' gesetzt).

Der Scheduler läuft als Daemon-Thread und prüft jede Minute. Die Engine
beachtet den Status 'scheduled': sie behandelt ihn wie 'new' (nicht anfassen),
bis der Scheduler ihn auf 'queued' freigibt.
"""
import json
import threading
import time
from datetime import datetime

from . import store

KEY = "schedule_rules"
_active_window: dict[int, bool] = {}  # package_id -> aktuell im Fenster


def _now() -> datetime:
    return datetime.now()


def _inside_window(rule: dict, now: datetime) -> bool:
    if not rule.get("enabled", True):
        return True  # deaktiviert = keine Einschränkung
    days = rule.get("days") or []
    if days and now.weekday() not in days:
        return False
    try:
        sh, sm = map(int, rule["window_start"].split(":"))
        eh, em = map(int, rule["window_end"].split(":"))
    except (KeyError, ValueError):
        return True
    start = sh * 60 + sm
    end = eh * 60 + em
    cur = now.hour * 60 + now.minute
    if start <= end:
        return start <= cur <= end
    # über Mitternacht (z.B. 22:00–06:00)
    return cur >= start or cur <= end


def load_rules() -> list[dict]:
    raw = store.get_setting(KEY, "")
    if not raw:
        return []
    try:
        return json.loads(raw)
    except Exception:
        return []


def save_rules(rules: list[dict]):
    store.set_setting(KEY, json.dumps(rules))


def _rule_for(pid: int, rules: list[dict]) -> dict | None:
    """Passende Regel für ein Paket: paket-spezifisch gewinnt vor global."""
    specific = [r for r in rules if r.get("package_id") == pid]
    if specific:
        return specific[0]
    globals_ = [r for r in rules if r.get("package_id", 0) == 0]
    return globals_[0] if globals_ else None


def _sync_once():
    """Einmaliger Durchlauf: Pakete je nach Fenster starten/pausieren."""
    rules = load_rules()
    now = _now()
    pkgs = store.rows("SELECT id, status FROM packages")
    for p in pkgs:
        pid = p["id"]
        rule = _rule_for(pid, rules)
        if not rule:
            continue
        inside = _inside_window(rule, now)
        _active_window[pid] = inside
        if inside:
            # Fenster aktiv: 'scheduled' freigeben → 'queued'
            store.q("UPDATE downloads SET status='queued' "
                    "WHERE package_id=? AND status='scheduled'", (pid,))
        else:
            # Ausserhalb: laufende pausieren, wartende auf 'scheduled'
            store.q("UPDATE downloads SET status='scheduled' "
                    "WHERE package_id=? AND status IN ('new','queued')", (pid,))
            # laufende/claiming → pausieren über engine (best effort: nur status)
            store.q("UPDATE downloads SET status='scheduled' "
                    "WHERE package_id=? AND status IN ('downloading','claiming','resolving')", (pid,))


def start():
    """Startet den Scheduler-Daemon-Thread (idempotent)."""
    def loop():
        while True:
            try:
                _sync_once()
            except Exception:
                pass
            time.sleep(60)

    threading.Thread(target=loop, name="smartdl-scheduler", daemon=True).start()


def is_package_active(pid: int) -> bool:
    """True wenn das Paket aktuell im erlaubten Fenster liegt (oder keine Regel)."""
    rules = load_rules()
    rule = _rule_for(pid, rules)
    if not rule:
        return True
    return _inside_window(rule, _now())
