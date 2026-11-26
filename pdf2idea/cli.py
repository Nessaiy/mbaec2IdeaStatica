"""Kommandozeile (Batch / Test):
    python -m pdf2idea --pdf X.pdf --list
    python -m pdf2idea --pdf X.pdf --profile zuordnung.json --out ergebnis.xlsx
"""
from __future__ import annotations

import argparse
import sys

from .export import build_rows, write_excel
from .mapping import Profile
from .modules import all_modules, get_module


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pdf2idea")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--module", default=None, help="Modul-ID (Standard: aus Profil bzw. mbaec_s601)")
    ap.add_argument("--profile", help="Zuordnung (JSON)")
    ap.add_argument("--out", help="Excel-Ausgabe (.xlsx)")
    ap.add_argument("--list", action="store_true", help="Kombinationen und Staebe auflisten")
    a = ap.parse_args(argv)

    profile = Profile.load(a.profile) if a.profile else Profile()
    mod = get_module(a.module or profile.module_id)
    res = mod.parse(a.pdf)
    if a.list or not a.out:
        print(f"Modul: {mod.label}")
        print(f"Kombinationen ({len(res.load_cases)}): " + ", ".join(res.case_names()))
        for n in res.member_numbers():
            info = res.members.get(n)
            print("  " + (info.label() if info else f"Stab {n}"))
        if not a.out:
            return 0
    rows, warns = build_rows(res, profile)
    write_excel(a.out, rows, profile, a.pdf, mod.label)
    for w in warns:
        print("WARNUNG:", w, file=sys.stderr)
    print(f"{len(rows)} Zeilen -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
