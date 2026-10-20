// Smartys Downloader — Extension (MV3)
// Fängt ab:
//  1. .dlc-Download-Klicks → DLC-Inhalt an den Downloader
//  2. Click'n'Load-Formulare (addcrypted2 → 127.0.0.1:9666) → leitet mit
//     unserem eigenen Key-Handling weiter (Content-Script Injection)
//  3. Kontextmenü "An Smartys Downloader senden" für Links & markierten Text

const API = "http://127.0.0.1:9666";   // CNL2/DLC-Empfänger des Downloaders
let settings = { interceptDlc: true, interceptCnl: true };

chrome.storage.local.get(["interceptDlc", "interceptCnl"], (s) => {
  settings.interceptDlc = s.interceptDlc !== false;
  settings.interceptCnl = s.interceptCnl !== false;
});

// ---------- 1. DLC-Downloads abfangen ----------
chrome.downloads.onDeterminingFilename.addListener((item, suggest) => {
  try {
    if (!settings.interceptDlc) { suggest({}); return; }
    const fname = (item.filename || "").toLowerCase();
    const furl = (item.finalUrl || "").toLowerCase();
    const isDlc = fname.endsWith(".dlc") || furl.includes(".dlc");
    if (!isDlc) { suggest({}); return; }
    if (!/^https?:/.test(item.finalUrl || "")) { suggest({}); return; }

    // Download abbrechen und die DLC selbst holen
    chrome.downloads.cancel(item.id);
    suggest({ cancel: true });
    sendDlcToDownloader(item.finalUrl, item.filename || "DLC-Paket");
    notifyPanel(`DLC "${item.filename}" an Smartys Downloader übergeben`);
  } catch (e) {
    console.warn("[SmartDL] dlc-intercept:", e);
    suggest({});
  }
});

async function sendDlcToDownloader(url, name) {
  // DLC im BROWSER-KONTEXT laden (mit Cookies = gelöste CF/PoW-Session!)
  // und INHALT + URL beide an den Downloader schicken.
  // Filecrypt liefert DLCs nur an die gelöste Session — der Downloader
  // alleine bekommt sie nicht. Der Inhalt ist der primäre Weg, die URL
  // nur der Fallback (für Seiten ohne Session-Zwang).
  let content = "";
  try {
    const resp = await fetch(url, { credentials: "include" });
    content = await resp.text();
  } catch (e) {
    console.warn("[SmartDL] DLC-Fetch fehlgeschlagen:", e);
  }
  try {
    const body = new URLSearchParams();
    if (content && content.length > 50) body.set("dlc", content);
    body.set("url", url);
    body.set("name", name || "DLC-Paket");
    const r = await fetch(`${API}/flash/dlc`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });
    if (!r.ok) throw new Error(`receiver ${r.status}`);
    notifyPanel(content
      ? `DLC übergeben (${content.length} Bytes Inhalt)`
      : `Nur DLC-URL übergeben (Inhalt fehlgeschlagen)`);
  } catch (e) {
    console.warn("[SmartDL] DLC-Übergabe fehlgeschlagen:", e);
    notifyPanel(`✗ DLC-Übergabe fehlgeschlagen: ${e.message}`);
  }
}

// ---------- 2. Click'n'Load-Formulare umlenken ----------
// Webseiten feuern CNL2 an http://127.0.0.1:9666/flash/addcrypted2 —
// das ist genau unser Empfänger. Wir müssen NICHT umlenken, wenn der
// Downloader läuft. Das Content-Script prüft nur, ob der Port reagiert,
// und patcht sonst nichts.

// ---------- 3. Kontextmenü ----------
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "smartdl-link",
    title: "An Smartys Downloader senden",
    contexts: ["link"],
  });
  chrome.contextMenus.create({
    id: "smartdl-selection",
    title: "Auswahl an Smartys Downloader senden",
    contexts: ["selection"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  let urls = [];
  if (info.menuItemId === "smartdl-link" && info.linkUrl) {
    urls = [info.linkUrl];
  } else if (info.menuItemId === "smartdl-selection" && info.selectionText) {
    urls = (info.selectionText.match(/https?:\/\/\S+/g) || []);
  }
  for (const u of urls) {
    await fetch(`${API}/flash/link`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: `url=${encodeURIComponent(u)}&name=${encodeURIComponent(tab ? tab.title : "Link")}`,
    }).catch(() => {});
  }
  if (urls.length) notifyPanel(`${urls.length} Link(s) an Smartys Downloader`);
});

// ---------- CNL2-Formular-Weiterleitung vom Content-Script ----------
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    try {
      if (msg.type === "cnl2") {
        // crypted + jk aus dem abgefangenen formular:
        const body = new URLSearchParams();
        body.set("crypted", msg.crypted);
        body.set("jk", msg.jk);
        if (msg.source) body.set("source", msg.source);
        if (msg.package) body.set("package", msg.package);
        if (msg.passwords) body.set("passwords", msg.passwords);
        const r = await fetch(`${API}/flash/addcrypted2`, {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: body.toString(),
        });
        notifyPanel(`Click'n'Load übergeben (${msg.crypted.length} Bytes verschlüsselt)`);
        sendResponse({ ok: r.ok });
      } else if (msg.type === "links") {
        const body = new URLSearchParams();
        msg.urls.forEach((u, i) => body.set(i === 0 ? "url" : `url${i}`, u));
        if (msg.name) body.set("name", msg.name);
        const r = await fetch(`${API}/flash/link`, {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: body.toString(),
        });
        sendResponse({ ok: r.ok });
      }
    } catch (e) {
      console.warn("[SmartDL] message-handler:", e);
      sendResponse({ ok: false, error: String(e) });
    }
  })();
  return true;  // async response
});

function notifyPanel(msg) {
  try {
    chrome.notifications.create({
      type: "basic",
      iconUrl: "icon128.png",
      title: "Smartys Downloader",
      message: msg,
    });
  } catch (e) {
    console.log("[SmartDL]", msg);
  }
}