"""Filecrypt via Playwright-Chromium: Cloudflare + Passwort + PoW-Captcha + CNL2.

Warum Playwright statt FlareSolverr:
  - Filecrypts PoW-Captcha braucht pow_x (Browser-Fingerprint aus /js/m.js)
    und reale Klicks — FlareSolverr kann nicht klicken.
  - Playwright-Chromium löst Cloudflare (headless=new), klickt "I am a human",
    das PoW läuft im Browser-JS, danach steht die CNL2-Seite offen.

Pipeline:
  1. Chromium öffnet Container-URL (Cloudflare-Challenge wartet automatisch ab)
  2. Passwort-Feld füllen + continue (falls "Password Required")
  3. PoW-Checkbox klicken ("I am a human") und "Confirmed" abwarten
  4. CNL2-Formular extrahieren (jk + crypted) → AES-CBC → Hoster-Links
"""
import asyncio
from playwright.async_api import async_playwright

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")


async def _resolve_pw_playwright(url: str, passwords: list[str],
                                 timeout_total: int = 120) -> str:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"])
        ctx = await browser.new_context(user_agent=UA, locale="en-US")
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            # Cloudflare-Challenge? Kurz abwarten bis Inhalt da ist
            for _ in range(30):
                content = await page.content()
                if "Just a moment" not in content and "cf-chl" not in content:
                    break
                await page.wait_for_timeout(2000)

            html = await page.content()

            # Passwort-Formular?
            if "Password Required" in html or 'name="password"' in html:
                pw_field = page.locator('input[name="password"]')
                if await pw_field.count() > 0:
                    for pw_try in passwords:
                        await pw_field.fill(pw_try)
                        continue_btn = page.locator('button.pff, button:has-text("continue")')
                        if await continue_btn.count() > 0:
                            await continue_btn.first.click()
                        else:
                            await page.keyboard.press("Enter")
                        # warten auf po-captcha oder cnl2 oder wrong-password
                        for _ in range(20):
                            await page.wait_for_timeout(1000)
                            html = await page.content()
                            if "wrong password" in html.lower():
                                break
                            if "pow-captcha" in html or 'name="crypted"' in html:
                                break
                        html = await page.content()
                        if "wrong password" not in html.lower():
                            break
                        # nochmal: pw-feld neu füllen (seite reloaded)
                        pw_field = page.locator('input[name="password"]')
                        if await pw_field.count() == 0:
                            break

            # PoW-Captcha: Checkbox klicken
            html = await page.content()
            pow_box = page.locator("#pow-captcha .pow-captcha__box")
            if "pow-captcha" in html and await pow_box.count() > 0:
                try:
                    await pow_box.click()
                except Exception:
                    pass
                # auf "Confirmed" / done warten (pow dauert ein paar sekunden)
                for _ in range(60):
                    await page.wait_for_timeout(1000)
                    state = await pow_box.get_attribute("data-state") \
                        if await pow_box.count() > 0 else "done"
                    if state == "done" or 'name="crypted"' in await page.content():
                        break
                # form wird automatisch gesubmitted (submitForm nach 850ms)
                for _ in range(20):
                    await page.wait_for_timeout(1000)
                    html = await page.content()
                    if 'name="crypted"' in html or "pow-captcha" not in html:
                        break

            html = await page.content()
            return html
        finally:
            await browser.close()


def resolve_container_playwright(url: str, password: str | None = None) -> list[str]:
    """Container → Hoster-Links via echtem Chromium."""
    from .filecrypt import _parse_cnl2, _cnl2_unpack_jk, _cnl2_decrypt, FilecryptError
    from .urls import is_filecrypt, extract_urls

    if not is_filecrypt(url):
        raise FilecryptError(f"Kein Filecrypt-Link: {url}")

    passwords = ([password] if password else []) + ["funxd", "serienfans.org",
                                                   "filecrypt", "ddl"]
    html = asyncio.run(_resolve_pw_playwright(url, passwords))

    cnl = _parse_cnl2(html)
    if cnl:
        crypted, jk = cnl
        key = _cnl2_unpack_jk(jk)
        return _cnl2_decrypt(crypted, key)

    # Fallback: direkte Hoster-Links
    links = extract_urls(html)
    hoster_links = [l for l in links
                    if not any(x in l for x in (
                        "filecrypt", "static.filecrypt",
                        "challenges.cloudflare", "google", "facebook",
                        "aclib", "visit.php", "cutcaptcha", "pow."))]
    if hoster_links:
        return hoster_links

    raise FilecryptError("CNL2 nicht gefunden — PoW/Captcha evtl. gescheitert. "
                         f"HTML-Ende: {html[-400:]}")