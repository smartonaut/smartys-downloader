// Smartys Downloader — C++-Installer (Windows)
// Zuständig für: Entpacken, Verknüpfungen, Registry (Add/Remove Programs),
// Deinstaller. Die Programmdaten selbst kommen als eingebettetes 7z/zip-Archiv.
#include <iostream>
#include <string>
#include "wizard.h"

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE, PWSTR, int nCmdShow) {
    return Wizard::run(hInst);
}
