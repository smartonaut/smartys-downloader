Name:           smartys-downloader
Version:        %{?ver}%{!?ver:0.0.0}
Release:        1
Summary:        Smartys Downloader - Download-Manager mit Multihoster-Support
License:        MIT
URL:            https://downloader.smartys.tech
BuildArch:      x86_64
AutoReqProv:    no
Requires:       bash

%global debug_package %{nil}
%define __strip /bin/true
%define _build_id_links none

%description
Schlanker Download-Manager fuer Container und One-Click-Hoster:
Multi-Segment-Downloads, Resume, Scheduler, Reconnect, Multi-Mirror,
Torrent-Support und Paket-Post-Processing. Web-Panel auf
http://127.0.0.1:8765, CNL2-Bridge (JD2-kompatibel) auf Port 9666.

%prep

%build

%install
rm -rf %{buildroot}
mkdir -p %{buildroot}/opt/smartys-downloader
mkdir -p %{buildroot}/usr/bin
mkdir -p %{buildroot}/usr/share/applications
cp -r %{?srcroot:.}/dist/SmartDownloader/. %{buildroot}/opt/smartys-downloader/
cp -r %{?srcroot:.}/extension %{buildroot}/opt/smartys-downloader/extension

cat > %{buildroot}/usr/bin/smartys-downloader <<'LAUNCHER'
#!/bin/bash
exec /opt/smartys-downloader/SmartDownloader "$@"
LAUNCHER
chmod 755 %{buildroot}/usr/bin/smartys-downloader

cat > %{buildroot}/usr/share/applications/smartys-downloader.desktop <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Smartys Downloader
Comment=Download-Manager mit Multihoster-Support (Panel: http://127.0.0.1:8765)
Exec=smartys-downloader
Icon=download
Terminal=true
Categories=Network;FileTransfer;
DESKTOP

%files
/opt/smartys-downloader
/usr/bin/smartys-downloader
/usr/share/applications/smartys-downloader.desktop

%post
echo ""
echo "Smartys Downloader installiert."
echo "  Panel:       http://127.0.0.1:8765"
echo "  CNL2-Bridge: http://127.0.0.1:9666 (JD2-kompatibel)"
echo "  Extension:   /opt/smartys-downloader/extension/"
echo ""
