// extract.cpp — eingebettetes ZIP (payload.bin) entpacken
// Wir nutzen miniz (eine Header-/C-Datei, keine Abhängigkeiten) — beim Build
// wird dist/SmartDownloader als zip in die Ressource kompiliert:
//   cmake -DPAYLOAD=/pfad/zum/SmartDownloader-windows.zip ..
#include "extract.h"
#include <windows.h>
#include <string>
#include <fstream>

// miniz als eingebettete quelle (beim ersten build: vendor/miniz.h + miniz.c)
extern "C" {
#include "miniz.h"
}

namespace {

// eingebettetes payload-archiv (rc.exe: payload.bin → IDB_PAYLOAD)
// fallback für entwicklung: datei neben der setup-exe lesen
bool loadPayload(std::string& out) {
    HRSRC hRes = FindResourceW(nullptr, MAKEINTRESOURCEW(101), L"PAYLOAD");
    if (hRes) {
        HGLOBAL hData = LoadResource(nullptr, hRes);
        void* p = LockResource(hData);
        DWORD size = SizeofResource(nullptr, hRes);
        out.assign((const char*)p, size);
        return true;
    }
    // dev-fallback: payload.bin im selben ordner
    std::ifstream f("payload.bin", std::ios::binary);
    if (!f) return false;
    out.assign((std::istreambuf_iterator<char>(f)),
               std::istreambuf_iterator<char>());
    return true;
}

void createDirs(const std::wstring& path) {
    // rekursive verzeichnis-anlage (SHCreateDirectory legt den ganzen baum)
    SHCreateDirectoryExW(nullptr, path.c_str(), nullptr);
}

} // namespace

namespace Extract {

bool run(const std::wstring& targetDir) {
    std::string payload;
    if (!loadPayload(payload)) {
        return false;
    }

    mz_zip_archive zip = {};
    if (!mz_zip_reader_init_mem(&zip, payload.data(), payload.size(), 0)) {
        return false;
    }

    int n = mz_zip_reader_get_num_files(&zip);
    for (int i = 0; i < n; ++i) {
        mz_zip_archive_file_stat st;
        if (!mz_zip_reader_file_stat(&zip, i, &st)) continue;

        // zip-inhalt ist utf-8 → windows-utf-16
        int wlen = MultiByteToWideChar(CP_UTF8, 0, st.m_filename, -1, nullptr, 0);
        std::wstring rel(st.m_filename, st.m_filename + (wlen ? wlen - 1 : 0));
        std::wstring full = targetDir + L"\\" + rel;

        if (st.m_is_directory) {
            createDirs(full);
            continue;
        }
        // ordner für die datei sicherstellen
        size_t slash = full.find_last_of(L"\\/");
        if (slash != std::wstring::npos) {
            createDirs(full.substr(0, slash));
        }
        mz_zip_reader_extract_to_wfile(&zip, i, full.c_str(), nullptr);
    }
    mz_zip_reader_end(&zip);
    return n > 0;
}

} // namespace Extract