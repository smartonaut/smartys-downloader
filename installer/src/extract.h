#pragma once
#include <string>
namespace Extract {
    // entpackt das eingebettete Archiv (resources/payload.bin → miniz/zip)
    bool run(const std::wstring& targetDir);
}
