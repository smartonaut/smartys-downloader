#!/usr/bin/env bash
# Baut das .rpm (Fedora / RHEL / openSUSE) aus dem aktuellen Quellstand.
# Voraussetzung: rpmbuild (rpm-build), fertiges PyInstaller-Bundle in dist/.
# Reihenfolge: bash build_deb.sh  (erzeugt dist/)  →  bash build_rpm.sh
set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"
VER=$(grep -m1 '^Version:' packaging/control | awk '{print $2}')
TOP="${TMPDIR:-/tmp}/smartdl-rpmbuild"

echo "[1/2] rpmbuild-Topdir: $TOP (Version $VER)"
mkdir -p "$TOP"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

rpmbuild -bb \
    --define "_topdir $TOP" \
    --define "srcroot $ROOT" \
    --define "ver $VER" \
    packaging/smartys-downloader-rpm.spec

mkdir -p releases
cp "$TOP/RPMS/x86_64/smartys-downloader-${VER}-1.x86_64.rpm" "releases/smartys-downloader-${VER}-1.x86_64.rpm"
echo "[2/2] Fertig: releases/smartys-downloader-${VER}-1.x86_64.rpm"
