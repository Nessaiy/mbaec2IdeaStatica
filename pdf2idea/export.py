"""Zeilen im IDEA-Format erzeugen und als Excel schreiben."""
from __future__ import annotations

import datetime
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .axes import apply_component_map, describe
from .mapping import Assignment, Profile, parse_case_spec
from .model import COMPONENTS, POSITIONS, UNITS, ForceRow, ParseResult

HEADERS = ["Name", "Bauteil", "Position"] + [f"{c} [{UNITS[c]}]" for c in COMPONENTS]


@dataclass
class ExportRow:
    name: str            # nur in der ersten Zeile einer Lasteinwirkung gefuellt
    member: str
    position: str
    values: Tuple[float, ...]
    warning: str = ""
    # Herkunft der Werte: [(Kurzname, Beschreibung, 6 Werte)] - bei Summen mehrere Eintraege
    parts: List[Tuple[str, str, Tuple[float, ...]]] = field(default_factory=list)


TOL = 0.005  # m - Toleranz beim Vergleich von Stellen x
NEAR = 0.02  # m - Zeilen knapp neben der Stelle (z. B. x-0,01 fuer die linke Seite einer Sprungstelle)
LEFT_OFFSET = 0.01  # m - so weit links der Sprungstelle soll die Zusatzausgabe liegen


def pick_row(rows: List[ForceRow], position: str) -> ForceRow:
    """Anfang = erste Zeile bei kleinstem x, Ende = letzte Zeile bei groesstem x."""
    if position == "Anfang":
        xmin = min(r.x for r in rows)
        return next(r for r in rows if r.x == xmin)
    xmax = max(r.x for r in rows)
    return [r for r in rows if r.x == xmax][-1]


def resolve_station(rows: List[ForceRow], station: str) -> Tuple[Dict[str, float], str]:
    """Schnittgroessen an einer Stelle des Stabes. Zweiter Rueckgabewert: Hinweistext ('' = exakt)."""
    if station in POSITIONS:
        return pick_row(rows, station).values, ""
    m = re.fullmatch(r"x=(-?\d+(?:\.\d+)?)([LR]?)", station)
    if not m:
        raise ValueError(f"Unbekannte Stelle '{station}'")
    xs, side = float(m.group(1)), m.group(2)
    rows = sorted(rows, key=lambda r: r.x)          # stabil: Reihenfolge bei Spruengen bleibt
    same = [r for r in rows if abs(r.x - xs) <= TOL]
    if side == "L":
        near_l = [r for r in rows if xs - NEAR - 1e-9 <= r.x < xs - TOL]
        if near_l:                                        # Zusatzausgabe knapp links der Sprungstelle
            return near_l[-1].values, ""
        if len(same) == 1:                                # nur ein Wert (rechte Seite): links evtl. anderer Wert
            left = [r for r in rows if r.x < xs - TOL]
            if left and any(abs(same[0].values.get(k, 0.0) - left[-1].values.get(k, 0.0)) > 0.5 for k in ("N", "Vz")):
                return same[0].values, "einseitig"
    elif side == "R" and not same:
        near_r = [r for r in rows if xs + TOL < r.x <= xs + NEAR + 1e-9]
        if near_r:
            return near_r[0].values, ""
    if same:
        return (same[0] if side == "L" else same[-1]).values, ""
    below = [r for r in rows if r.x < xs - TOL]
    above = [r for r in rows if r.x > xs + TOL]
    if not below or not above:
        near = above[0] if above else below[-1]
        return near.values, f"x={xs:g} m liegt ausserhalb des Stabes - Randwert verwendet"
    lo, hi = below[-1], above[0]
    t = (xs - lo.x) / (hi.x - lo.x)
    keys = set(lo.values) | set(hi.values)
    vals = {k: lo.values.get(k, 0.0) + t * (hi.values.get(k, 0.0) - lo.values.get(k, 0.0)) for k in keys}
    return vals, "interpoliert"


def station_options(result: ParseResult, stab: int) -> List[Tuple[str, str]]:
    """(Schluessel, Anzeigetext) aller Stellen eines Stabes ueber alle Kombinationen."""
    cases = [c for c in result.load_cases if stab in c.members]
    n = len(cases)
    xs: Dict[float, List] = {}
    for c in cases:
        cnt = Counter(round(r.x, 2) for r in c.members[stab])
        for x, k in cnt.items():
            e = xs.setdefault(x, [0, False])
            e[0] += 1
            e[1] = e[1] or k > 1
    if not xs:
        return []
    xmin, xmax = min(xs), max(xs)
    info = result.members.get(stab)

    def de(x: float) -> str:
        return f"{x:.2f}".replace(".", ",")

    out: List[Tuple[str, str]] = []
    for x in sorted(xs):
        cnt, dup = xs[x]
        suffix = "" if cnt == n else f"   [{cnt}/{n} Komb.]"
        if x == xmin:
            kn = f" \u2013 Knoten {info.node_start}" if info and info.node_start is not None else ""
            out.append(("Anfang", f"{de(x)}{kn} (Anfang)"))
        elif x == xmax:
            kn = f" \u2013 Knoten {info.node_end}" if info and info.node_end is not None else ""
            out.append(("Ende", f"{de(x)}{kn} (Ende)"))
        elif dup:
            out.append((f"x={x:.2f}L", f"{de(x)} (links vom Sprung){suffix}"))
            out.append((f"x={x:.2f}R", f"{de(x)} (rechts vom Sprung){suffix}"))
        else:
            out.append((f"x={x:.2f}", f"{de(x)}{suffix}"))
    return out


def _de(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".").replace(".", ",") if x else "0"


def short_station(a: Assignment) -> str:
    st = a.station
    if st.startswith("x="):
        return f"x={st[2:].rstrip('LR')}" + {"L": " links", "R": " rechts"}.get(st[-1], "")
    return st


def missing_stations(result: ParseResult, profile: Profile) -> List[Tuple[int, float, List[str], int, str]]:
    """Stellen x, fuer die in der Baustatik eine zusaetzliche Ausgabe noetig ist:
    - zugeordnete Stelle fehlt in manchen Kombinationen (-> sonst Interpolation),
    - linke Seite einer Sprungstelle fehlt (Ausgabe liefert nur den rechten Wert) -> Ausgabe knapp links (x-0,01 m).
    Rueckgabe: [(Stab, x, [Kombinationen], Anzahl Kombinationen, Art)], Art = '' oder 'links:<Stelle>'."""
    wanted = set(profile.selected_cases)
    cases = [c for c in result.load_cases if not wanted or c.name in wanted]
    found: Dict[Tuple[int, float, str], List[str]] = {}
    for a in profile.assignments:
        if a.stab is None or not a.station.startswith("x="):
            continue
        xs = float(a.station[2:].rstrip("LR"))
        key = (a.stab, round(xs, 2), "")
        miss = found.setdefault(key, [])
        left = found.setdefault((a.stab, round(xs - LEFT_OFFSET, 2), f"links:{xs:.2f}"), []) if a.station.endswith("L") else None
        for c in cases:
            rows = c.members.get(a.stab)
            if not rows:
                continue
            if not any(abs(r.x - xs) <= TOL for r in rows):
                if c.name not in miss:
                    miss.append(c.name)
            elif left is not None and resolve_station(rows, a.station)[1] == "einseitig" and c.name not in left:
                left.append(c.name)
    return [(st, x, cs, len(cases), k) for (st, x, k), cs in sorted(found.items()) if cs]


def missing_text(miss) -> str:
    """Anweisung fuer die Baustatik: je Stab die zusaetzlichen Ausgabestellen."""
    by: Dict[int, List[float]] = {}
    for st, x, _cs, _n, _k in miss:
        by.setdefault(st, []).append(x)
    lines = ["In der Baustatik (mb AEC) zusätzliche Ausgabe der Schnittgrößen an diesen Stellen erzeugen.",
             "Fehlt eine Stelle, wird linear interpoliert; an Sprungstellen (Knotenlast, Anschlüsse) ist das meist falsch.",
             "Liefert die Zusatzausgabe an einer Sprungstelle nur den rechten Wert, braucht man zusätzlich eine Ausgabe",
             f"knapp links davon (x − {LEFT_OFFSET:.2f} m), sonst stimmt das Gleichgewicht im Anschluss nicht.".replace(".", ","), ""]
    for st, xs in sorted(by.items()):
        lines.append(f"  Stab {st}:  x = " + ";  x = ".join(f"{x:.2f}".replace(".", ",") + " m" for x in sorted(set(xs))))
    lines.append("")
    for st, x, cs, n, k in miss:
        nums = ", ".join(c.replace("Komb. ", "") for c in cs[:15]) + (" …" if len(cs) > 15 else "")
        what = (f"fehlt (links der Sprungstelle {k[6:].replace('.', ',')} m)" if k else "fehlt")
        lines.append(f"  Stab {st}, x = {x:.2f} m".replace(".", ",", 1) + f" {what} in {len(cs)} von {n} Komb. (Komb. {nums})")
    return "\n".join(lines)


def case_number(name: str) -> str:
    return name.split()[-1] if name.split() else name


def manual_values(a: Assignment, case_name: str) -> Tuple[Tuple[float, ...], str]:
    """Werte eines manuellen Stabes fuer eine Kombination (spaeterer Bereich gewinnt, sonst 0)."""
    nr = case_number(case_name)
    vals: Optional[Dict[str, float]] = None
    hits = 0
    for m in a.manual:
        spec = parse_case_spec(m.cases)
        if spec is None or (nr.isdigit() and int(nr) in spec):
            vals, hits = m.values, hits + 1
    warn = f"{case_name}: '{a.idea_name}' in mehreren Bereichen - letzter gilt" if hits > 1 else ""
    v = vals or {}
    return tuple(float(v.get(c, 0.0)) for c in COMPONENTS), warn


def build_rows(result: ParseResult, profile: Profile) -> Tuple[List[ExportRow], List[str]]:
    if not profile.assignments:
        raise ValueError("Keine Bauteile zugeordnet.")
    wanted = set(profile.selected_cases)
    cases = [c for c in result.load_cases if not wanted or c.name in wanted]
    if not cases:
        raise ValueError("Keine Kombination ausgewaehlt.")
    out: List[ExportRow] = []
    warnings: List[str] = []
    interp: Dict[str, Dict[str, List[str]]] = {}
    onesided: Dict[str, Dict[str, List[str]]] = {}
    for case in cases:
        label = profile.name_pattern.format(name=case.name, nr=case_number(case.name))
        first_of_case = len(out)
        slot: Dict[Tuple[str, str], int] = {}          # (Bauteil, Position) -> Index der Zeile in out
        for a in profile.assignments:
            warn = ""
            parts: List[Tuple[str, str, Tuple[float, ...]]] = []
            if a.is_node:
                s = result.node_load_sum(a.node, case.name, a.node_factor, a.node_einw)
                if s is None:
                    vals = (0.0,) * len(COMPONENTS)
                    warn = f"{case.name}: Keine Kombinationsvorschrift im PDF -> Nullwerte"
                    warnings.append(warn)
                else:
                    fx, fz, mm = s
                    cmap = a.component_map or profile.component_map
                    comp = {"N": fx, "Vz": fz, "My": mm}      # globale Last x/z/Moment um y in Baustatik-Komponenten
                    mapped = apply_component_map(comp, cmap)
                    vals = tuple(x * a.node_sign + 0.0 for x in mapped)
                    for einw, f, px, pz, pm in result.node_load_parts(a.node, case.name, a.node_factor, a.node_einw) or []:
                        pv = tuple(x * a.node_sign + 0.0 for x in apply_component_map({"N": px, "Vz": pz, "My": pm}, cmap))
                        raw = ", ".join(f"{n} {_de(v)}" for n, v in (("Fx", px), ("Fz", pz), ("M", pm)) if abs(v) > 1e-9)
                        parts.append((f"Kn.{a.node}", f"Knoten {a.node}: Faktor {_de(f)} × {einw}  ({raw} kN/kNm, mit Faktor)"
                                      + (" Vorz. –" if a.node_sign < 0 else ""), pv))
            elif a.is_manual:
                vals, warn = manual_values(a, case.name)      # Vorzeichenfaktoren gelten nur fuer PDF-Werte
                if warn:
                    warnings.append(warn)
                if any(vals):
                    parts.append(("manuell", "manuell eingegebene Last", vals))
            else:
                rows = case.members.get(a.stab)
                if rows:
                    v, note = resolve_station(rows, a.station)
                    mapped = apply_component_map(v, a.component_map or profile.component_map)
                    vals = tuple(x * profile.signs.get(c, 1.0) * a.sign + 0.0 for x, c in zip(mapped, COMPONENTS))
                    parts.append((f"S{a.stab} {short_station(a)}" + (" ≈interp.!" if note == "interpoliert" else
                                                                    " ≈nur rechter Wert!" if note == "einseitig" else ""),
                                  a.describe() + (f"  ⚠ {note}: Stelle fehlt in dieser Kombination" if note == "interpoliert" else
                                                  "  ⚠ nur ein Wert an der Sprungstelle (rechte Seite) – linke Seite fehlt" if note == "einseitig" else
                                                  f"  [{note}]" if note else ""), vals))
                    if note:
                        warn = f"{case.name}: Stab {a.stab} {note}"
                        if note == "interpoliert":
                            interp.setdefault(a.idea_name, {}).setdefault(f"Stab {a.stab} {a.station}", []).append(case.name)
                        elif note == "einseitig":
                            onesided.setdefault(a.idea_name, {}).setdefault(f"Stab {a.stab} {a.station}", []).append(case.name)
                else:
                    vals = (0.0,) * len(COMPONENTS)
                    warn = f"{case.name}: Stab {a.stab} nicht im PDF -> Nullwerte"
                    warnings.append(warn)
            key = (a.idea_name, a.position)
            if key in slot:                               # gleiche IDEA-Zeile mehrfach belegt -> Summe
                r = out[slot[key]]
                r.values = tuple(x + y + 0.0 for x, y in zip(r.values, vals))
                r.warning = "; ".join(w for w in (r.warning, warn) if w)
                r.parts.extend(parts)
            else:
                slot[key] = len(out)
                out.append(ExportRow(label if len(out) == first_of_case else "", a.idea_name, a.position, vals, warn,
                                      list(parts)))
    for name, d in interp.items():
        for st, cs in d.items():
            nums = ", ".join(c.replace("Komb. ", "") for c in cs[:12]) + (" …" if len(cs) > 12 else "")
            warnings.append(f"ACHTUNG '{name}': {st} fehlt im PDF in {len(cs)} Kombination(en) (Komb. {nums}) und wurde "
                            f"linear interpoliert. An Sprungstellen (Knotenlast, Anschlüsse) ist das meist FALSCH. "
                            f"Besser eine Stelle wählen, die in allen Kombinationen vorkommt (z. B. Stab-Ende), oder PDF mit mehr Stellen ausgeben.")
    for name, d in onesided.items():
        for st, cs in d.items():
            nums = ", ".join(c.replace("Komb. ", "") for c in cs[:12]) + (" …" if len(cs) > 12 else "")
            warnings.append(f"ACHTUNG '{name}': {st} hat in {len(cs)} Kombination(en) (Komb. {nums}) an der Sprungstelle nur EINEN Wert "
                            f"(rechte Seite). Der linke Wert unterscheidet sich dort -> Gleichgewicht stimmt nicht. "
                            f"Zusatzausgabe knapp links der Stelle anlegen (Knopf „Fehlende Stellen…“).")
    miss = missing_stations(result, profile)
    if miss:
        by: Dict[int, List[str]] = {}
        for st, x, _c, _n, _k in miss:
            by.setdefault(st, []).append(f"{x:.2f}".replace(".", ",") + " m")
        warnings.insert(0, "ZUSATZAUSGABE in der Baustatik nötig (sonst Interpolation bzw. nur rechter Wert an der Sprungstelle): "
                        + "; ".join(f"Stab {st} bei x = " + " und ".join(xs) for st, xs in sorted(by.items()))
                        + "  (Liste mit allen Kombinationen: Knopf „Fehlende Stellen…“)")
    return out, warnings


def fmt_tsv(rows: List[ExportRow], decimal: str = ",", header: bool = False, with_names: bool = False) -> str:
    """Tab-getrennter Text fuer die Zwischenablage (Einfuegen in IDEA).

    Standard: nur die sechs Kraftspalten N, Vy, Vz, Mx, My, Mz (ohne Name/Bauteil/Position)."""
    lines = ["\t".join(HEADERS if with_names else HEADERS[3:])] if header else []
    for r in rows:
        nums = [f"{v:.2f}".replace(".", decimal) for v in r.values]
        lines.append("\t".join(([r.name, r.member, r.position] if with_names else []) + nums))
    return "\n".join(lines)


def write_excel(path: str, rows: List[ExportRow], profile: Profile,
                pdf_path: str = "", module_label: str = "") -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "IDEA-Import"
    ws.append(HEADERS)
    bold = Font(bold=True)
    fill = PatternFill("solid", fgColor="D9E1F2")
    warn_fill = PatternFill("solid", fgColor="FFF2CC")
    for c in range(1, len(HEADERS) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font, cell.fill = bold, fill
        cell.alignment = Alignment(horizontal="center")
    for r in rows:
        ws.append([r.name, r.member, r.position] + [round(v, 4) for v in r.values])
        if r.warning:
            for c in range(1, len(HEADERS) + 1):
                ws.cell(row=ws.max_row, column=c).fill = warn_fill
            ws.cell(row=ws.max_row, column=1).comment = Comment(r.warning, "pdf2idea")
    for row in ws.iter_rows(min_row=2, min_col=4, max_col=len(HEADERS)):
        for cell in row:
            cell.number_format = "0.00"
    widths = [14, 32, 11] + [12] * len(COMPONENTS)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"

    # Nur Zahlen (falls IDEA beim Einfuegen nur die 6 Werte je Zeile braucht)
    wv = wb.create_sheet("Nur Werte")
    wv.append(HEADERS[3:])
    for r in rows:
        wv.append([round(v, 4) for v in r.values])
    for row in wv.iter_rows(min_row=2):
        for cell in row:
            cell.number_format = "0.00"

    wi = wb.create_sheet("Info")
    info = [
        ("Erstellt", datetime.datetime.now().strftime("%d.%m.%Y %H:%M")),
        ("PDF", pdf_path),
        ("Modul", module_label or profile.module_id),
        ("Namensschema", profile.name_pattern),
        ("Achsenzuordnung Baustatik->IDEA", ", ".join(f"{k}\u2192{v}" for k, v in profile.axes.items())),
        ("IDEA-Komponente = Baustatik", describe(profile.component_map)),
        ("Vorzeichenfaktoren (auf IDEA-Werte)", ", ".join(f"{k}={v:g}" for k, v in profile.signs.items())),
        ("", ""),
        ("Bauteil (IDEA)", "PDF-Stab / Position"),
    ]
    for a in profile.assignments:
        if a.is_manual:
            parts = [f"Komb. {m.cases}: " + ", ".join(f"{c}={m.values.get(c, 0):g}" for c in COMPONENTS if m.values.get(c))
                     for m in a.manual]
            info.append((f"{a.idea_name} ({a.position})", "manuell | " + " | ".join(parts)))
        else:
            own = f" | Achsen: {describe(a.component_map)}" if a.component_map else ""
            info.append((f"{a.idea_name} ({a.position})", a.describe() + own))
    for row in info:
        wi.append(list(row))
    wi.column_dimensions["A"].width = 30
    wi.column_dimensions["B"].width = 60
    wb.save(path)
