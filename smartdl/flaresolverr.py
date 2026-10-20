"""FlareSolverr-Client — Cloudflare-Bypass über FlareSolverr (sickram/VPS)."""
import httpx
from .config import FLARESOLVERR_URL


class FlareSolverrError(Exception):
    pass


def _call(payload: dict, timeout: float = 90) -> dict:
    with httpx.Client(timeout=timeout) as c:
        r = c.post(FLARESOLVERR_URL, json=payload)
        data = r.json()
    if data.get("status") != "ok":
        msg = data.get("message", "unbekannter Fehler")
        raise FlareSolverrError(f"FlareSolverr: {msg}")
    return data.get("solution", {})


def solve_get(url: str, session: str | None = None) -> dict:
    """GET durch echten Browser. Liefert {html, cookies, user_agent, url}."""
    payload = {"cmd": "request.get", "url": url, "maxTimeout": 60000}
    if session:
        payload["session"] = session
    sol = _call(payload)
    return {
        "html": sol.get("response", ""),
        "cookies": {c["name"]: c["value"] for c in sol.get("cookies", [])},
        "user_agent": sol.get("userAgent", ""),
        "url": sol.get("url", url),
    }


def solve_post(url: str, post_data: str, session: str | None = None) -> dict:
    """POST mit urlencoded-Daten durch echten Browser."""
    payload = {"cmd": "request.post", "url": url, "postData": post_data, "maxTimeout": 60000}
    if session:
        payload["session"] = session
    sol = _call(payload)
    return {
        "html": sol.get("response", ""),
        "cookies": {c["name"]: c["value"] for c in sol.get("cookies", [])},
        "user_agent": sol.get("userAgent", ""),
        "url": sol.get("url", url),
    }


def create_session() -> str:
    return _call({"cmd": "sessions.create"}).get("session", "")


def destroy_session(sid: str):
    try:
        _call({"cmd": "sessions.destroy", "session": sid})
    except Exception:
        pass