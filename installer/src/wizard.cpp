// wizard.cpp — der Setup-Wizard: native Win32-UI im Dark-Theme der Web-GUI
// Seiten: Begrüßung → Lizenz/Komponenten → Zielordner → Installation (Progress) → Fertig
#include <windows.h>
#include <commctrl.h>
#include <shlobj.h>
#include <string>
#include <vector>
#include "wizard.h"
#include "install.h"
#include "extract.h"

#pragma comment(lib, "comctl32.lib")

// ---- Theme (gleich wie Web-GUI) ----
static const COLORREF CLR_BG     = RGB(0x0b, 0x0d, 0x12);
static const COLORREF CLR_CARD   = RGB(0x15, 0x17, 0x20);
static const COLORREF CLR_TEXT   = RGB(0xf2, 0xf5, 0xfa);
static const COLORREF CLR_MUTED  = RGB(0x8b, 0x90, 0x9e);
static const COLORREF CLR_ACCENT = RGB(0x5b, 0x8c, 0xff);
static const COLORREF CLR_ACCENT2= RGB(0x7c, 0x5b, 0xff);

namespace Wizard {

struct State {
    int page = 0;                    // 0=begrüßung 1=komponenten 2=ziel 3=progress 4=fertig
    std::wstring installDir;
    bool compCore = true;            // immer an
    bool compExt  = true;            // browser-extension
    bool compDesk = true;            // desktop-link
    bool compAuto = false;           // autostart mit windows
    bool runAfter = true;            // nach abschluss starten
    int progress = 0;
    std::wstring progressText;
    bool installing = false;
    bool done = false;
    HWND hwnd = nullptr;
};
static State g_state;

static const wchar_t* PAGES[] = { L"Willkommen", L"Komponenten", L"Zielordner",
                                  L"Installation", L"Fertig" };

// ---------- UI-Elemente (pro seite neu aufgebaut) ----------
static void buildPage(HWND hwnd) {
    // alle kinder weg
    EnumChildWindows(hwnd, [](HWND h, LPARAM l) -> BOOL {
        DestroyWindow(h); return TRUE;
    }, 0);

    HFONT hTitle = CreateFontW(24, 0, 0, 0, FW_BOLD, 0, 0, 0,
        DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");
    HFONT hBody  = CreateFontW(15, 0, 0, 0, FW_NORMAL, 0, 0, 0,
        DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");
    HFONT hLink  = CreateFontW(15, 0, 0, 0, FW_SEMIBOLD, 0, 0, 0,
        DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");

    State& s = g_state;
    int W = 640, pad = 28;

    auto addText = [&](const wchar_t* txt, int y, HFONT f, COLORREF c, int x = pad) {
        HWND h = CreateWindowW(L"STATIC", txt, WS_CHILD | WS_VISIBLE | SS_LEFT,
                               x, y, W - 2 * pad, 60, hwnd, nullptr, nullptr, nullptr);
        SendMessageW(h, WM_SETFONT, (WPARAM)f, TRUE);
        return h;
    };

    auto addCheck = [&](const wchar_t* txt, int y, bool& val, bool disabled = false) {
        HWND h = CreateWindowW(L"BUTTON", txt,
                               WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX,
                               pad, y, W - 2 * pad, 26, hwnd, nullptr, nullptr, nullptr);
        SendMessageW(h, WM_SETFONT, (WPARAM)hBody, TRUE);
        if (disabled) EnableWindow(h, FALSE);
        return h;
    };

    // kopfzeile (auf jeder seite):
    wchar_t header[128];
    swprintf(header, 128, L"Smartys Downloader  —  %s", PAGES[s.page]);
    HWND hh = addText(header, 22, hTitle, CLR_TEXT);
    // schritt-anzeige
    wchar_t steps[64];
    swprintf(steps, 64, L"Schritt %d von 4", s.page < 4 ? s.page : 4);
    HWND hs = CreateWindowW(L"STATIC", steps, WS_CHILD | WS_VISIBLE | SS_RIGHT,
                            W - 220, 30, 190, 24, hwnd, nullptr, nullptr, nullptr);
    SendMessageW(hs, WM_SETFONT, (WPARAM)hBody, TRUE);

    switch (s.page) {
    case 0: {  // Willkommen
        addText(L"Willkommen beim Installer von Smartys Downloader.", 100, hBody, CLR_TEXT);
        addText(L"Der schlanke Download-Manager: Container- und Hoster-Links, "
                L"Debrid-Dienste, DLC & Click'n'Load, Kategorie-Ziele.\n\n"
                L"Klicke auf „Weiter“ um zu beginnen.",
                140, hBody, CLR_MUTED);
        break;
    }
    case 1: {  // Komponenten
        addText(L"Welche Komponenten sollen installiert werden?", 96, hBody, CLR_TEXT);
        HWND c1 = addCheck(L"Programm (immer erforderlich)", 140, s.compCore, true);
        SendMessageW(c1, BM_SETCHECK, BST_CHECKED, 0);
        HWND c2 = addCheck(L"Browser-Erweiterung (DLC-Klicks & Click'n'Load)", 175, s.compExt);
        SendMessageW(c2, BM_SETCHECK, s.compExt ? BST_CHECKED : BST_UNCHECKED, 0);
        HWND c3 = addCheck(L"Desktop-Verknüpfung", 210, s.compDesk);
        SendMessageW(c3, BM_SETCHECK, s.compDesk ? BST_CHECKED : BST_UNCHECKED, 0);
        HWND c4 = addCheck(L"Mit Windows automatisch starten", 245, s.compAuto);
        SendMessageW(c4, BM_SETCHECK, s.compAuto ? BST_CHECKED : BST_UNCHECKED, 0);
        break;
    }
    case 2: {  // Zielordner + erweitert
        addText(L"Wohin soll Smartys Downloader installiert werden?", 96, hBody, CLR_TEXT);
        HWND hDir = CreateWindowW(L"EDIT", s.installDir.c_str(),
                                  WS_CHILD | WS_VISIBLE | WS_BORDER | ES_AUTOHSCROLL,
                                  pad, 140, W - 2 * pad - 110, 30, hwnd, nullptr, nullptr, nullptr);
        SendMessageW(hDir, WM_SETFONT, (WPARAM)hBody, TRUE);
        HWND hBrw = CreateWindowW(L"BUTTON", L"Durchsuchen…",
                                 WS_CHILD | WS_VISIBLE,
                                 W - pad - 100, 138, 100, 32, hwnd, (HMENU)2001, nullptr, nullptr);
        SendMessageW(hBrw, WM_SETFONT, (WPARAM)hLink, TRUE);
        addText(L"„Erweitert”: eigene Verknüpfungen, Autostart, Firewall — "
                L"Standard reicht für die meisten.", 200, hBody, CLR_MUTED);
        break;
    }
    case 3: {  // Progress
        addText(s.progressText.c_str(), 100, hBody, CLR_TEXT);
        HWND hProg = CreateWindowW(PROGRESS_CLASSW, nullptr,
                                   WS_CHILD | WS_VISIBLE | PBS_SMOOTH,
                                   pad, 150, W - 2 * pad, 18, hwnd, (HMENU)3001, nullptr, nullptr);
        SendMessageW(hProg, PBM_SETRANGE, 0, MAKELPARAM(0, 100));
        SendMessageW(hProg, PBM_SETPOS, s.progress, 0);
        break;
    }
    case 4: {  // Fertig
        addText(L"Installation abgeschlossen!", 100, hTitle, CLR_TEXT);
        addText(L"Smartys Downloader ist einsatzbereit.\n\n"
                L"Das Panel läuft nach dem Start auf http://127.0.0.1:8765 — "
                L"die Click'n'Load-Bridge auf Port 9666.",
                150, hBody, CLR_MUTED);
        HWND hRun = CreateWindowW(L"BUTTON", L"Smartys Downloader jetzt starten",
                                  WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX,
                                  pad, 260, W - 2 * pad, 26, hwnd, nullptr, nullptr, nullptr);
        SendMessageW(hRun, WM_SETFONT, (WPARAM)hBody, TRUE);
        SendMessageW(hRun, BM_SETCHECK, s.runAfter ? BST_CHECKED : BST_UNCHECKED, 0);
        break;
    }
    }

    // ---- navigations-leiste unten ----
    int by = 330;
    if (s.page < 3) {
        HWND hNext = CreateWindowW(L"BUTTON", s.page == 2 ? L"Installieren" : L"Weiter",
                                   WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
                                   W - pad - 110, by, 110, 36, hwnd, (HMENU)1001, nullptr, nullptr);
        SendMessageW(hNext, WM_SETFONT, (WPARAM)hLink, TRUE);
        if (s.page > 0) {
            HWND hBack = CreateWindowW(L"BUTTON", L"Zurück",
                                       WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
                                       W - pad - 220, by, 100, 36, hwnd, (HMENU)1002, nullptr, nullptr);
            SendMessageW(hBack, WM_SETFONT, (WPARAM)hBody, TRUE);
        }
    } else if (s.page == 4) {
        HWND hFin = CreateWindowW(L"BUTTON", L"Fertigstellen",
                                  WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
                                  W - pad - 110, by, 110, 36, hwnd, (HMENU)1003, nullptr, nullptr);
        SendMessageW(hFin, WM_SETFONT, (WPARAM)hLink, TRUE);
    }
}

// ---------- Installation (eigener thread) ----------
static DWORD WINAPI installThread(LPVOID) {
    State& s = g_state;
    s.installing = true;
    // 1. entpacken (60%)
    s.progressText = L"Dateien werden entpackt…";
    if (!Extract::run(s.installDir)) {
        s.progressText = L"Fehler beim Entpacken!";
        s.done = false;
        return 1;
    }
    s.progress = 60;
    // 2. shortcuts (10%) — nur wenn gewählt
    s.progressText = L"Verknüpfungen werden angelegt…";
    if (s.compDesk) Install::createShortcuts(s.installDir);
    s.progress = 70;
    // 3. startmenü immer
    Install::createStartMenuShortcut(s.installDir);
    s.progress = 80;
    // 4. extension-hinweis in installationsordner kopieren (10%)
    s.progressText = L"Komponenten werden eingerichtet…";
    if (!s.compExt) Install::removeExtensionFolder(s.installDir);
    s.progress = 90;
    // 5. autostart (10%)
    Install::setAutostart(s.compAuto, s.installDir);
    // 6. registry
    Install::registerUninstaller(s.installDir);
    s.progress = 100;
    s.progressText = L"Installation abgeschlossen.";
    s.done = true;
    s.page = 4;
    buildPage(s.hwnd);
    return 0;
}

// ---------- Window-Proc ----------
static LRESULT CALLBACK wndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_CREATE:
        g_state.hwnd = hwnd;
        g_state.installDir = Install::defaultInstallDir();
        buildPage(hwnd);
        return 0;
    case WM_CTLCOLORSTATIC: {
        HDC hdc = (HDC)wp;
        SetBkColor(hdc, CLR_BG);
        SetTextColor(hdc, CLR_TEXT);
        return (LRESULT)GetStockObject(BLACK_BRUSH);
    }
    case WM_COMMAND: {
        int id = LOWORD(wp);
        if (id == 1001) {  // weiter/installieren
            // checkbox-zustände der komponenten-seite einsammeln:
            if (g_state.page == 1) {
                // (die handles sind frisch aufgebaut — zustand via BM_GETCHECK der kinder)
                struct { const wchar_t* label; bool* val; } checks[] = {
                    { L"Browser-Erweiterung", &g_state.compExt },
                    { L"Desktop-Verknüpfung", &g_state.compDesk },
                    { L"Mit Windows", &g_state.compAuto },
                };
                HWND h = GetWindow(hwnd, GW_CHILD);
                while (h) {
                    wchar_t txt[128] = {};
                    GetWindowTextW(h, txt, 128);
                    for (auto& c : checks) {
                        if (wcsstr(txt, c.label)) {
                            *c.val = SendMessageW(h, BM_GETCHECK, 0, 0) == BST_CHECKED;
                        }
                    }
                    h = GetWindow(h, GW_HWNDNEXT);
                }
            }
            if (g_state.page == 2) {
                // zielordner aus dem edit-feld lesen:
                HWND h = GetWindow(hwnd, GW_CHILD);
                while (h) {
                    wchar_t cls[64] = {};
                    GetClassNameW(h, cls, 64);
                    if (wcscmp(cls, L"Edit") == 0) {
                        wchar_t buf[MAX_PATH] = {};
                        GetWindowTextW(h, buf, MAX_PATH);
                        if (buf[0]) g_state.installDir = buf;
                    }
                    h = GetWindow(h, GW_HWNDNEXT);
                }
                g_state.page = 3;
                buildPage(hwnd);
                CreateThread(nullptr, 0, installThread, nullptr, 0, nullptr);
            } else if (g_state.page < 2) {
                g_state.page++;
                buildPage(hwnd);
            }
        } else if (id == 1002) {  // zurück
            if (g_state.page > 0) { g_state.page--; buildPage(hwnd); }
        } else if (id == 2001) {  // durchsuchen…
            BROWSEINFOW bi = {};
            bi.hwndOwner = hwnd;
            bi.lpszTitle = L"Installationsordner wählen";
            bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE;
            PIDLIST_ABSOLUTE pidl = SHBrowseForFolderW(&bi);
            if (pidl) {
                wchar_t buf[MAX_PATH] = {};
                SHGetPathFromIDListW(pidl, buf);
                CoTaskMemFree(pidl);
                if (buf[0]) {
                    g_state.installDir = buf;
                    g_state.installDir += L"\SmartDownloader";
                    buildPage(hwnd);
                }
            }
        } else if (id == 1003) {  // fertig
            // „jetzt starten" checkbox lesen:
            HWND h = GetWindow(hwnd, GW_CHILD);
            while (h) {
                wchar_t txt[128] = {};
                GetWindowTextW(h, txt, 128);
                if (wcsstr(txt, L"jetzt starten")) {
                    g_state.runAfter = SendMessageW(h, BM_GETCHECK, 0, 0) == BST_CHECKED;
                }
                h = GetWindow(h, GW_HWNDNEXT);
            }
            if (g_state.runAfter) {
                std::wstring exe = g_state.installDir + L"\SmartDownloader.exe";
                ShellExecuteW(hwnd, L"open", exe.c_str(), nullptr, nullptr, SW_SHOW);
            }
            PostQuitMessage(0);
        }
        return 0;
    }
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

int run(HINSTANCE hInst) {
    INITCOMMONCONTROLSEX icex = { sizeof(icex), ICC_WIN95_CLASSES };
    InitCommonControlsEx(&icex);

    WNDCLASSW wc = {};
    wc.lpfnWndProc = wndProc;
    wc.hInstance = hInst;
    wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
    wc.hbrBackground = CreateSolidBrush(CLR_BG);
    wc.lpszClassName = L"SmartDLSetup";
    RegisterClassW(&wc);

    // fenster zentriert, 640x420
    RECT r = { 0, 0, 640, 420 };
    AdjustWindowRect(&r, WS_OVERLAPPEDWINDOW & ~(WS_THICKFRAME | WS_MAXIMIZEBOX), FALSE);
    int sw = GetSystemMetrics(SM_CXSCREEN), sh = GetSystemMetrics(SM_CYSCREEN);
    HWND hwnd = CreateWindowW(L"SmartDLSetup",
        L"Smartys Downloader Setup", WS_OVERLAPPEDWINDOW & ~(WS_THICKFRAME | WS_MAXIMIZEBOX),
        (sw - (r.right - r.left)) / 2, (sh - (r.bottom - r.top)) / 2,
        r.right - r.left, r.bottom - r.top,
        nullptr, nullptr, hInst, nullptr);

    HICON hIcon = LoadIconW(hInst, MAKEINTRESOURCEW(101));
    if (hIcon) SendMessageW(hwnd, WM_SETICON, ICON_BIG, (LPARAM)hIcon);

    ShowWindow(hwnd, SW_SHOW);
    UpdateWindow(hwnd);

    MSG m;
    while (GetMessageW(&m, nullptr, 0, 0)) {
        TranslateMessage(&m);
        DispatchMessageW(&m);
    }
    return 0;
}

} // namespace Wizard