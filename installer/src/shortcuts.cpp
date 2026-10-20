// shortcuts.cpp — .lnk-Dateien über COM (IShellLink)
#include "shortcuts.h"
#include <shobjidl.h>
#include <objbase.h>
#include <windows.h>

namespace Install {

bool makeShortcut(const std::wstring& target, const std::wstring& linkPath,
                  const std::wstring& description) {
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    IShellLinkW* pLink = nullptr;
    IPersistFile* pFile = nullptr;
    bool ok = false;

    if (SUCCEEDED(CoCreateInstance(CLSID_ShellLink, nullptr, CLSCTX_INPROC_SERVER,
                                   IID_IShellLinkW, (void**)&pLink))) {
        pLink->SetPath(target.c_str());
        pLink->SetDescription(description.c_str());
        // Arbeitsverzeichnis = Zielordner (web/ liegt daneben)
        size_t pos = target.find_last_of(L"\\/");
        if (pos != std::wstring::npos) {
            pLink->SetWorkingDirectory(target.substr(0, pos).c_str());
        }
        if (SUCCEEDED(pLink->QueryInterface(IID_IPersistFile, (void**)&pFile))) {
            if (SUCCEEDED(pFile->Save(linkPath.c_str(), TRUE))) {
                ok = true;
            }
            pFile->Release();
        }
        pLink->Release();
    }
    CoUninitialize();
    return ok;
}

} // namespace Install