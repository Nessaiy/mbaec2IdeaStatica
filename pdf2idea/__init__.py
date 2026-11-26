"""PDF (Baustatik-Ausgabe) -> Excel (IDEA StatiCa Import von Lasten)."""
import os
import time

VERSION = "0.12.0"
try:
    from ._build import BUILD          # wird von build_exe.bat beim Bauen der EXE geschrieben
except ImportError:                    # Start aus dem Quellcode: Zeitpunkt der letzten Aenderung
    try:
        BUILD = time.strftime("%d.%m.%Y %H:%M", time.localtime(os.path.getmtime(__file__))) + " (Quellcode)"
    except OSError:
        BUILD = "unbekannt"
__version__ = f"{VERSION} – Build {BUILD}"
