#!/usr/bin/env bash
# Baut das .deb aus dem aktuellen Quellstand.
# Vorraussetzung: pyinstaller im venv, dann: bash build_deb.sh
set -e
cd "$(dirname "$0")"
echo "[1/3] PyInstaller-build…"
.venv/bin/pyinstaller smartys-downloader.spec --noconfirm --clean
echo "[2/3] deb-root anlegen…"
rm -rf /tmp/debroot
mkdir -p /tmp/debroot/{DEBIAN,opt/smartys-downloader,usr/bin,usr/share/applications,usr/share/smartys-downloader}
cp -r dist/SmartDownloader/* /tmp/debroot/opt/smartys-downloader/
# Browser-Extension mit ins Paket:
cp -r extension /tmp/debroot/opt/smartys-downloader/extension
# version im manifest dokumentieren:
cat >> /tmp/debroot/usr/share/doc_header.txt <<VERHDR
Smartys Downloader $(grep -m1 '^Version:' packaging/control | awk '{print $2}')
VERHDR
cat > /tmp/debroot/usr/bin/smartys-downloader <<'LAUNCHER'
#!/bin/bash
exec /opt/smartys-downloader/SmartDownloader "$@"
LAUNCHER
chmod 755 /tmp/debroot/usr/bin/smartys-downloader
cat > /tmp/debroot/usr/share/applications/smartys-downloader.desktop <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Smartys Downloader
Comment=Download-Manager mit Multihoster-Support (Panel: http://127.0.0.1:8765)
Exec=smartys-downloader
Icon=download
Terminal=true
Categories=Network;FileTransfer;
DESKTOP
cp packaging/control /tmp/debroot/DEBIAN/control
cat > /tmp/debroot/DEBIAN/postinst <<'POSTINST'
#!/bin/bash
echo ""
echo "Smartys Downloader installiert."
echo "  Panel:      http://127.0.0.1:8765"
echo "  CNL2-Bridge: http://127.0.0.1:9666 (JD2-kompatibel)"
echo ""
echo "Browser-Extension liegt hier:"
echo "  /opt/smartys-downloader/extension/"
echo "  Chrome:   chrome://extensions → Entwicklermodus → Entpackt laden"
echo "  Firefox:  about:debugging → Temporäres Add-on → manifest.json"
echo ""
POSTINST
chmod 755 /tmp/debroot/DEBIAN/postinst
echo "[3/3] .deb bauen…"
VER=$(grep -m1 '^Version:' packaging/control | awk '{print $2}')
dpkg-deb --build --root-owner-group /tmp/debroot "releases/smartys-downloader_${VER}_amd64.deb"
echo "Fertig: releases/smartys-downloader_${VER}_amd64.deb"
