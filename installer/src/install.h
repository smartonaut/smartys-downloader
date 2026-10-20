#pragma once
#include <string>
namespace Install {
    std::wstring defaultInstallDir();
    bool createShortcuts(const std::wstring& targetDir);   // startmenü + desktop
    bool createStartMenuShortcut(const std::wstring& targetDir);
    void registerUninstaller(const std::wstring& targetDir);
    void setAutostart(bool enable, const std::wstring& targetDir);
    void removeExtensionFolder(const std::wstring& targetDir);
}
