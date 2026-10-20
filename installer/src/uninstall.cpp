// Uninstall.exe — entfernt Smartys Downloader sauber:
// fragt nach, löscht Ordner, Shortcuts, Autostart + Registry-Eintrag
#include <windows.h>
#include <shlobj.h>
#include <string>

static void delRegUninstall() {
    RegDeleteKeyW(HKEY_CURRENT_USER,
                  L"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\SmartysDownloader");
    HKEY h;
    if (RegOpenKeyExW(HKEY_CURRENT_USER,
                      L"Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                      0, KEY_WRITE, &h) == ERROR_SUCCESS) {
        RegDeleteValueW(h, L"SmartysDownloader");
        RegCloseKey(h);
    }
}

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    // sicherheitsfrage (echte windows-dialog-box, kein console-look):
    int rc = MessageBoxW(nullptr,
        L"Smartys Downloader wirklich deinstallieren?\n\n"
        L"Programmdateien, Verknüpfungen und Einstellungen-Verweise werden entfernt.\n"
        L"(Downloads und die Konfiguration in %APPDATA% bleiben erhalten.)",
        L"Smartys Downloader deinstallieren",
        MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2);
    if (rc != IDYES) return 0;

    // eigenen installationsordner ermitteln (uninstall.exe liegt darin)
    wchar_t self[MAX_PATH] = {};
    GetModuleFileNameW(nullptr, self, MAX_PATH);
    std::wstring dir = self;
    size_t p = dir.find_last_of(L"\\\\/");
    dir = dir.substr(0, p);

    // registry + autostart zuerst
    delRegUninstall();

    // shortcuts
    wchar_t* ptr = nullptr;
    if (SUCCEEDED(SHGetKnownFolderPath(FOLDERID_Programs, 0, nullptr, &ptr))) {
        std::wstring lnk = std::wstring(ptr) + L"\\Smartys Downloader.lnk";
        DeleteFileW(lnk.c_str());
        CoTaskMemFree(ptr);
    }
    if (SUCCEEDED(SHGetKnownFolderPath(FOLDERID_Desktop, 0, nullptr, &ptr))) {
        std::wstring lnk = std::wstring(ptr) + L"\\Smartys Downloader.lnk";
        DeleteFileW(lnk.c_str());
        CoTaskMemFree(ptr);
    }

    // installationsordner löschen (rekursiv; uninstall.exe löscht sich selbst mit —
    // windows erlaubt das löschen einer laufenden exe auf NTFS via MOVEDELAYED)
    std::vector<wchar_t> from(dir.begin(), dir.end());
    from.push_back(L'\0');
    from.push_back(L'\0');
    SHFILEOPSTRUCTW op = {};
    op.wFunc = FO_DELETE;
    op.pFrom = from.data();
    op.fFlags = FOF_NOCONFIRMATION | FOF_SILENT;
    SHFileOperationW(&op);

    MessageBoxW(nullptr, L"Smartys Downloader wurde deinstalliert.",
                L"Deinstallation", MB_OK | MB_ICONINFORMATION);
    return 0;
}
