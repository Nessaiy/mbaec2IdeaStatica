"""Startpunkt fuer PyInstaller / Doppelklick: ohne Argumente -> GUI, mit Argumenten -> CLI."""
import sys

if __name__ == "__main__":
    if len(sys.argv) > 1:
        from pdf2idea.cli import main
        raise SystemExit(main())
    from pdf2idea.gui import run
    run()
