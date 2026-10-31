// powgen.mjs — erzeugt pow_x (m.js R()) und pow_data (s.js S.collect())
// für Filecrypts PoW-Captcha. Läuft headless in Node mit Browser-API-Shims.
const screen = { width: 1920, height: 1080, availWidth: 1920, availHeight: 1040,
                 colorDepth: 24, pixelDepth: 24 };
Object.defineProperty(globalThis, "screen", { value: screen, configurable: true });

function makePlugins() {
    const arr = [];
    arr.item = (i) => arr[i] || null;
    arr.namedItem = (n) => arr.find(p => p.name === n) || null;
    arr.refresh = () => {};
    return arr;
}

const UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36";
const nav = {
    userAgent: UA, language: "en-US", languages: ["en-US","en"],
    platform: "Linux x86_64", hardwareConcurrency: 8, deviceMemory: 8,
    maxTouchPoints: 0, webdriver: false, cookieEnabled: true, onLine: true,
    plugins: makePlugins(), mimeTypes: makePlugins(),
    connection: { effectiveType: "4g", rtt: 50, downlink: 10 },
};
Object.defineProperty(globalThis, "navigator", { value: nav, configurable: true });

const win = {
    innerWidth: 1280, innerHeight: 800, outerWidth: 1280, outerHeight: 900,
    devicePixelRatio: 1, screenX: 0, screenY: 0,
    navigator: nav, screen,
    document: { referrer: "https://www.filecrypt.cc/", hidden: false, visibilityState: "visible" },
    location: { href: "https://www.filecrypt.cc/", protocol: "https:", host: "www.filecrypt.cc", hostname: "www.filecrypt.cc" },
    performance: { now: () => Date.now(), timing: { navigationStart: Date.now() - 5000 } },
    addEventListener: () => {}, removeEventListener: () => {},
    localStorage: { getItem: () => null, setItem: () => {} },
    sessionStorage: { getItem: () => null, setItem: () => {} },
    requestAnimationFrame: (cb) => setTimeout(() => cb(Date.now()), 16),
    matchMedia: () => ({ matches: false, addListener: () => {}, addEventListener: () => {} }),
    setTimeout, clearTimeout, setInterval, clearInterval, Date, Math,
    Object, Array, JSON, Promise, console,
};
Object.defineProperty(globalThis, "window", { value: win, configurable: true });
Object.defineProperty(globalThis, "document", { value: win.document, configurable: true });
Object.defineProperty(globalThis, "location", { value: win.location, configurable: true });

const m = await import(new URL("./m.js", import.meta.url));
const s = await import(new URL("./s.js", import.meta.url));
const R = m.R || (m.default && m.default.R);
const S = s.S || (s.default && s.default.S);

const powX = R ? await R() : "";
let powData = "";
if (S) {
    try { S.start(); } catch (e) {}
    try { S.recordPointer({ clientX: 640, clientY: 400, type: "pointerdown", isTrusted: true }); } catch (e) {}
    try { S.recordClick({ clientX: 640, clientY: 400, type: "click", isTrusted: true }); } catch (e) {}
    try { powData = S.collect() || ""; } catch (e) {}
}

console.log(JSON.stringify({ pow_x: powX, pow_data: powData }));