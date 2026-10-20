#pragma once
#include <string>
namespace Install {
    // implementation in shortcuts.cpp (IShellLink via COM)
    bool makeShortcut(const std::wstring& target, const std::wstring& linkPath,
                      const std::wstring& description);
}
