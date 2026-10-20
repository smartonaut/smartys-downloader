#!/usr/bin/env python3
"""Smartys Downloader — Einstiegspunkt (PyInstaller-builds)"""
import sys
from pathlib import Path

from smartdl.api import app

if __name__ == "__main__":
    # CNL2-Empfänger (JD2-kompatibel, Port 9666) — erlaubt den
    # "Klick to download with JD2"-Buttons auf Webseiten, UNSER Panel zu füttern
    try:
        from smartdl.cnl2_receiver import start_receiver
        start_receiver()
        print("CNL2-Empfänger: http://127.0.0.1:9666 (JD2-kompatibel)")
    except OSError as e:
        print(f"CNL2-Empfänger: Port 9666 belegt ({e})")
    import uvicorn
    print("SmartDownloader: http://127.0.0.1:8765")
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
