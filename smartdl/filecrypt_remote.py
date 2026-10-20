"""Filecrypt-Auflösung über den bewährten UC-Weg: remote/filecrypt_uc2.py
läuft im FlareSolverr-Container auf sickram (echter Chrome, TAB/SPACE-Turnstile-
Trick, PoW nativ im Browser). Der alte Weg (FlareSolverr-HTTP-API + PoW in
Python, siehe filecrypt.py) scheitert an CF-Turnstiles — nur der Browser-Weg
kommt nachweislich durch (E2E 8 Links, 05.10.2026).

Aufrufkette (alles von thinky aus):
  1. Deploy (hash-verglichen): scp filecrypt_uc2.py → sickram:/tmp/
     + docker cp → flaresolverr:/app/
  2. ssh sickram docker exec flaresolverr python /app/filecrypt_uc2.py <url> [<pw>]
  3. stdout = JSON: {"links": [...]} | {"error": "..."} → list[str]
"""
import hashlib
import json
import subprocess
from pathlib import Path

from .filecrypt import FilecryptError

SICKRAM = "sickram"
CONTAINER = "flaresolverr"
REMOTE_PATH = "/app/filecrypt_uc2.py"
TIMEOUT = 420  # PoW pro Link-Unterseite, mehrere Seiten → großzügig


def _uc2_local() -> Path:
    return Path(__file__).resolve().parent.parent / "remote" / "filecrypt_uc2.py"


def _run(cmd: list[str], timeout: int = 60) -> str:
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", errors="replace")[:200]
        raise FilecryptError(f"remote-fehler ({cmd[0]} {cmd[1] if len(cmd)>1 else ''}): {err}")
    return r.stdout.decode("utf-8", errors="replace").strip()


def _deploy_if_needed() -> None:
    """filecrypt_uc2.py nur neu in den Container schieben, wenn sich der
    Inhalt geändert hat (sha256-Vergleich lokal vs. Container)."""
    local = _uc2_local()
    if not local.exists():
        raise FilecryptError(f"filecrypt_uc2.py fehlt: {local}")
    local_sha = hashlib.sha256(local.read_bytes()).hexdigest()

    try:
        remote_sha = _run(
            ["ssh", "-o", "BatchMode=yes", SICKRAM,
             f"docker exec {CONTAINER} sha256sum {REMOTE_PATH}"]).split()[0]
    except (FilecryptError, IndexError):
        remote_sha = ""
    if remote_sha == local_sha:
        return

    tmp_remote = "/tmp/filecrypt_uc2.py"
    r = subprocess.run(["scp", "-q", str(local), f"{SICKRAM}:{tmp_remote}"],
                       capture_output=True, timeout=120)
    if r.returncode != 0:
        raise FilecryptError("scp nach sickram fehlgeschlagen")
    _run(["ssh", "-o", "BatchMode=yes", SICKRAM,
          f"docker cp {tmp_remote} {CONTAINER}:{REMOTE_PATH}"])


def resolve_container_remote(url: str, password: str | None = None) -> list[str]:
    """Filecrypt-Container via UC-Resolver im FlareSolverr-Container auflösen.

    Rückgabe: Liste direkter Hoster-Links (dedupliziert, filecrypt-interne
    Domains filtert der Resolver selbst).
    Raise: FilecryptError bei Deploy-/Aufruf-/Decode-Fehlern.
    """
    _deploy_if_needed()
    cmd = ["ssh", "-o", "BatchMode=yes", SICKRAM,
           f"docker exec {CONTAINER} python {REMOTE_PATH} {url}"]
    if password:
        cmd.append(password)
    r = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT)
    out = r.stdout.decode("utf-8", errors="replace").strip()
    if r.returncode != 0 or not out:
        err = r.stderr.decode("utf-8", errors="replace")[-400:]
        raise FilecryptError(f"uc-resolver fehlgeschlagen: {err or 'keine Ausgabe'}")
    try:
        data = json.loads(out.splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        raise FilecryptError(f"uc-resolver: unlesbare Ausgabe: {out[:200]}")
    if data.get("error"):
        raise FilecryptError(f"uc-resolver: {data['error']}")
    links = data.get("links") or []
    if not links:
        raise FilecryptError("uc-resolver: keine Links (kein CNL2 gefunden)")
    return links