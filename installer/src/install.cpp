// install.cpp — Zielordner + Verknüpfungen + Registry-Eintrag
#include "install.h"
#include "shortcuts.h"
#include <shlobj.h>
#include <windows.h>
#include <string>
#include <vector>

namespace Install {

std::wstring defaultInstallDir() {
    wchar_t* base = nullptr;
    SHGetKnownFolderPath(FOLDERID_LocalAppData, 0, nullptr, &base);
    std::wstring dir = std::wstring(base) + L"\\SmartDownloader";
    CoTaskMemFree(base);
    return dir;
}

bool createShortcuts(const std::wstring& targetDir) {
    // Startmenü
    wchar_t* startPtr = nullptr;
    SHGetKnownFolderPath(FOLDERID_Programs, 0, nullptr, &startPtr);
    std::wstring startMenu = std::wstring(startPtr) + L"\\Smartys Downloader.lnk";
    CoTaskMemFree(startPtr);

    // Desktop
    wchar_t* deskPtr = nullptr;
    SHGetKnownFolderPath(FOLDERID_Desktop, 0, nullptr, &deskPtr);
    std::wstring desktop = std::wstring(deskPtr) + L"\\Smartys Downloader.lnk";
    CoTaskMemFree(deskPtr);

    bool ok = true;
    ok &= makeShortcut(targetDir + L"\\SmartDownloader.exe", startMenu,
                       L"Smartys Downloader — Download-Manager");
    ok &= makeShortcut(targetDir + L"\\SmartDownloader.exe", desktop,
                       L"Smartys Downloader — Download-Manager");
    return ok;
}

void registerUninstaller(const std::wstring& targetDir) {
    HKEY hKey;
    if (RegCreateKeyExW(HKEY_CURRENT_USER,
                        L"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\SmartysDownloader",
                        0, nullptr, 0, KEY_WRITE, nullptr, &hKey, nullptr)
        != ERROR_SUCCESS) {
        return;
    }
    auto set = [&](const wchar_t* name, const std::wstring& value) {
        RegSetValueExW(hKey, name, 0, REG_SZ,
                       (const BYTE*)value.c_str(),
                       (DWORD)((value.size() + 1) * sizeof(wchar_t)));
    };
    set(L"DisplayName", L"Smartys Downloader");
    set(L"DisplayVersion", L"0.2.0");
    set(L"Publisher", L"Smarty");
    set(L"InstallLocation", targetDir);
    set(L"DisplayIcon", targetDir + L"\\SmartDownloader.exe");
    set(L"UninstallString",
        L"\"" + targetDir + L"\\Uninstall.exe\"");
    set(L"NoModify", L"1");
    set(L"NoRepair", L"1");
    RegCloseKey(hKey);
}

} // namespace Install

bool createStartMenuShortcut(const std::wstring& targetDir) {
    wchar_t* startPtr = nullptr;
    SHGetKnownFolderPath(FOLDERID_Programs, 0, nullptr, &startPtr);
    std::wstring startMenu = std::wstring(startPtr) + L"\Smartys Downloader.lnk";
    CoTaskMemFree(startPtr);
    return makeShortcut(targetDir + L"\SmartDownloader.exe", startMenu,
                       L"Smartys Downloader — Download-Manager");
}

void setAutostart(bool enable, const std::wstring& targetDir) {
    HKEY hKey;
    if (RegOpenKeyExW(HKEY_CURRENT_USER,
                      L"Software\Microsoft\Windows\CurrentVersion\Run",
                      0, KEY_WRITE, &hKey) != ERROR_SUCCESS) {
        return;
    }
    if (enable) {
        std::wstring cmd = L"\"" + targetDir + L"\SmartDownloader.exe\"";
        RegSetValueExW(hKey, L"SmartysDownloader", 0, REG_SZ,
                       (const BYTE*)cmd.c_str(),
                       (DWORD)((cmd.size() + 1) * sizeof(wchar_t)));
    } else {
        RegDeleteValueW(hKey, L"SmartysDownloader");
    }
    RegCloseKey(hKey);
}

void removeExtensionFolder(const std::wstring& targetDir) {
    std::wstring ext = targetDir + L"\extension";
    std::vector<wchar_t> from(ext.begin(), ext.end());
    from.push_back(L'\0');
    from.push_back(L'\0');  // doppel-null-terminiert für SHFileOperation
    SHFILEOPSTRUCTW op = {};
    op.wFunc = FO_DELETE;
    op.pFrom = from.data();
    op.fFlags = FOF_NOCONFIRMATION | FOF_SILENT;
    SHFileOperationW(&op);
}