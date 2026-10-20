#!/usr/bin/env python3
"""SmartDownloader starten: API-Server + Web-UI auf http://127.0.0.1:8765"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn
from smartdl.api import app

if __name__ == "__main__":
    # Click'n'Load-2-Empfänger (JD2-kompatibel, Port 9666) — erlaubt den
    # "Klick to download with JD2"-Buttons auf Webseiten, UNSER Panel zu füttern
    try:
        from smartdl.cnl2_receiver import start_receiver
        start_receiver()
        print("CNL2-Empfänger: http://127.0.0.1:9666 (JD2-kompatibel)")
    except OSError as e:
        print(f"CNL2-Empfänger: Port 9666 belegt ({e}) — JD2 läuft?")
    print("SmartDownloader: http://127.0.0.1:8765")
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")