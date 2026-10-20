cmake_minimum_required(VERSION 3.16)
project(SmartDownloaderInstaller LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(WIN32)
    # --- Setup.exe (der Wizard) ---
    add_executable(SmartDownloaderSetup WIN32
        src/main.cpp
        src/wizard.cpp
        src/install.cpp
        src/extract.cpp
        src/shortcuts.cpp
        src/miniz.c
        resources/smartdl.rc
    )
    target_link_libraries(SmartDownloaderSetup PRIVATE shell32 ole32 advapi32 comctl32)

    # --- Uninstall.exe (parallel gebaut, kommt ins payload mit rein) ---
    add_executable(SmartDownloaderUninstall WIN32
        src/uninstall.cpp
        resources/smartdl.rc
    )

    # payload-archiv (der downloader selbst) als ressourci in die setup-exe:
    if(PAYLOAD)
        configure_file(src/payload.rc.in ${CMAKE_BINARY_DIR}/payload.rc)
        target_sources(SmartDownloaderSetup PRIVATE ${CMAKE_BINARY_DIR}/payload.rc)
        message(STATUS "Payload: ${PAYLOAD}")
    endif()
endif()
