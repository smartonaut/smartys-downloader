// Content-Script: fängt Click'n'Load-Formulare AB, bevor die Seite sie an
// 127.0.0.1:9666 feuert (wo der Browser das Popup blocken kann), und
// schickt die Daten über die Extension an den Downloader.
// Zusätzlich: Badge für erkannte CNL2-Formulare / DLC-Links.

(function () {
  "use strict";

  // ---------- CNL2-Formular-Abfangung ----------
  // Filecrypts "Klick to download with JD2"-Button submitted ein Formular
  // an http://127.0.0.1:9666/flash/addcrypted2. Browser blocken das Popup
  // evtl. — deshalb fangen wir das Formular HIER ab (capture-phase) und
  // leiten die Felder über den background weiter. Der Downloader kriegt
  // die Links garantiert, egal ob Popup geblockt wird.

  function interceptCnl2Forms(root) {
    const forms = (root || document).querySelectorAll("form");
    forms.forEach((f) => {
      const action = (f.getAttribute("action") || "").toLowerCase();
      const hasCrypted = !!f.querySelector('input[name="crypted"]');
      const isCnl = hasCrypted || action.includes("9666") || action.includes("addcrypted");
      if (!isCnl || f.dataset.smartdl) return;
      f.dataset.smartdl = "1";
      f.addEventListener("submit", (ev) => {
        try {
          const data = new FormData(f);
          const crypted = data.get("crypted");
          const jk = data.get("jk");
          if (crypted && jk) {
            ev.preventDefault();  // Popup gar nicht erst aufmachen
            chrome.runtime.sendMessage({
              type: "cnl2",
              crypted: String(crypted),
              jk: String(jk),
              source: location.href,
              package: String(data.get("package") || document.title || ""),
            }, (resp) => {
              if (chrome.runtime.lastError) {
                showBadge("✗ Extension-Verbindung fehlgeschlagen");
                return;
              }
              showBadge(resp && resp.ok
                ? "✓ Click'n'Load an Smartys Downloader übergeben"
                : "✗ Click'n'Load-Übergabe fehlgeschlagen");
            });
          }
          // ohne crypted/jk: submit normal durchlassen (kein CNL2)
        } catch (e) { /* nie das original-submit killen */ }
      }, true);  // capture-phase: VOR der seite selbst
    });
  }

  // dynamisch nachgeladene formulare (ajax) auch abfangen:
  const mo = new MutationObserver(() => interceptCnl2Forms());
  mo.observe(document.documentElement, { childList: true, subtree: true });

  // ---------- Badge ----------
  function findDlcLinks() {
    const links = [];
    document.querySelectorAll('a[href]').forEach((a) => {
      const href = (a.getAttribute("href") || "").toLowerCase();
      if (href.endsWith(".dlc") || href.includes(".dlc?")) links.push(a);
    });
    return links;
  }

  function hasCnl2Form() {
    return !!document.querySelector('form input[name="crypted"]');
  }

  let badge = null;
  function showBadge(text) {
    if (badge) { badge.textContent = text; return; }
    badge = document.createElement("div");
    badge.textContent = text;
    Object.assign(badge.style, {
      position: "fixed",
      bottom: "16px",
      right: "16px",
      zIndex: 2147483647,
      background: "linear-gradient(135deg,#5b8cff,#7c5bff)",
      color: "#fff",
      padding: "10px 16px",
      borderRadius: "12px",
      font: "600 13px system-ui, sans-serif",
      boxShadow: "0 6px 24px rgba(91,140,255,.4)",
      cursor: "default",
    });
    document.documentElement.appendChild(badge);
    setTimeout(() => { if (badge) { badge.remove(); badge = null; } }, 6000);
  }

  function scan() {
    interceptCnl2Forms();
    const dlc = findDlcLinks();
    if (dlc.length && !badge) showBadge(`⬇ ${dlc.length} DLC-Container erkannt → Smartys Downloader`);
    else if (hasCnl2Form() && !badge) showBadge("⬇ Click'n'Load erkannt → Smartys Downloader");
  }

  if (document.readyState === "complete") scan();
  else window.addEventListener("load", scan);

  // SPA-seiten: gelegentlich neu scannen
  setInterval(scan, 4000);
})();