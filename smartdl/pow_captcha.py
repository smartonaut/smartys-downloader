"""Filecrypt PoW-Captcha-Solver (Python).

Filecrypt nutzt ein Proof-of-Work-Captcha:
  1. POST /captchasession/<id>.json {pow_x, pow_y, pow_yn, tz, wt}
     → {challenge: {id, challenge, difficulty}, autosolve}
  2. Worker löst: sha1(f"{challenge}:{nonce}") muss >= difficulty führende Nullbits haben
     (Math.clz32-Logik: erste 32-bit-Wort zählt führende Nullen, dann h1...)
  3. Formular submit mit: pow_id, pow_nonce, pow_elapsed, pow_pauses, pow_data, pow_x

Der SHA1 hier ist Spezial: charCodeAt & 0xff (Latin-1-Bytes, kein UTF-8!),
Bit-Länge nur 32-bit (max ~536 MB Input — für Nonces egal).
"""
import hashlib
import time
import httpx


def _sha1_leading_zeros_latin1(s: str) -> int:
    """Nachbau des Worker-sha1lz: führende Nullbits des SHA1 (Latin-1-Bytes).

    Python: hashlib macht das Gleiche, wenn wir den String als Latin-1 encoden
    — charCodeAt & 0xff == Latin-1-Byte. clz32-Kette über die 5 32-bit-Wörter
    == führende Nullbits des 160-bit-Hashes.
    """
    h = hashlib.sha1(s.encode("latin-1", errors="replace")).digest()
    # führende Nullbits im 160-bit-Digest
    val = int.from_bytes(h, "big")
    if val == 0:
        return 160
    return 160 - val.bit_length()


def solve_pow(challenge: str, difficulty: int, report_cb=None) -> dict:
    """Findet Nonce so dass sha1(f"{challenge}:{nonce}") >= difficulty Nullbits hat.

    Liefert {nonce, ms, pauses:0}.
    """
    prefix = f"{challenge}:"
    start = time.time()
    nonce = 0
    expected = 2 ** difficulty
    last_report = 0
    while True:
        if _sha1_leading_zeros_latin1(prefix + str(nonce)) >= difficulty:
            ms = int((time.time() - start) * 1000)
            return {"nonce": nonce, "ms": ms, "pauses": 0}
        nonce += 1
        if report_cb and nonce % 50_000 == 0:
            now = time.time()
            if now - last_report > 0.15:
                last_report = now
                report_cb(1 - pow(2.718281828, -nonce / expected))


class FilecryptPoW:
    """Der komplette PoW-Flow gegen filecrypt.cc."""

    def __init__(self, cookies: dict, user_agent: str):
        self.client = httpx.Client(
            base_url="https://www.filecrypt.cc",
            headers={"User-Agent": user_agent,
                     "Referer": "https://www.filecrypt.cc/"},
            cookies=cookies, timeout=30)

    def get_challenge(self, session_path: str) -> dict:
        """POST auf /captchasession/<id>.json — session_path aus data-session Attribut."""
        body = {"pow_x": "", "pow_y": "", "pow_yn": "",
                "tz": "Europe/Berlin", "wt": "0"}
        r = self.client.post(session_path, data=body)
        if r.status_code != 200:
            raise RuntimeError(f"captchasession HTTP {r.status_code}")
        j = r.json()
        c = (j or {}).get("challenge")
        if not c or "challenge" not in c:
            raise RuntimeError(f"kein challenge in Antwort: {str(j)[:200]}")
        return c

    def solve(self, c: dict) -> dict:
        return solve_pow(c["challenge"], int(c["difficulty"]))

    def submit_fields(self, c: dict, solution: dict,
                      pow_x: str = "", pow_data: str = "") -> dict:
        """Formular-Felder für den cform-POST."""
        return {
            "pow_id": c.get("id", ""),
            "pow_nonce": str(solution["nonce"]),
            "pow_elapsed": str(solution["ms"]),
            "pow_pauses": str(solution.get("pauses", 0)),
            "pow_data": pow_data,
            "pow_x": pow_x,
        }


def gen_pow_browser_fields() -> dict:
    """pow_x + pow_data über die Node-Laufzeit (m.js/s.js) erzeugen."""
    import json as _json
    import subprocess as _sp
    from pathlib import Path as _P
    js_dir = _P(__file__).resolve().parent / "js"
    node = _P.home() / ".hermes/tools/node-26.7.0-linux-x64/bin/node"
    r = _sp.run([str(node), str(js_dir / "powgen.mjs")],
                 capture_output=True, timeout=30, cwd=str(js_dir))
    out = r.stdout.decode("utf-8", errors="replace").strip()
    for line in out.splitlines():
        if line.startswith('{"pow_x"'):
            d = _json.loads(line)
            return {"pow_x": d.get("pow_x", ""),
                    "pow_data": d.get("pow_data", "")}
    raise RuntimeError(f"powgen fehlgeschlagen: {r.stderr.decode()[:200]}")