"""mb AEC Baustatik S601.de (Stabwerk) - Tabelle 'Schnittgroessen (massgebende)'.

Aufbau der Tabelle im PDF (je Kombination):
    Komb. 1   <Stab>  x  Nx,d  My,d  Vz,d      <- erste Zeile mit Kombinationsname
              x  Nx,d  My,d  Vz,d              <- weitere Stellen desselben Stabes
              <Stab>  x  ...                   <- naechster Stab
Die Spalten werden aus der Kopfzeile gelesen (2D: N, My, Vz; 3D-Ausgaben
mit Vy, Mx, Mz werden ebenfalls erkannt). '*' markiert Extremwerte und wird ignoriert.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

import pdfplumber

from ..model import ForceRow, LoadCase, MemberInfo, NodeLoad, ParseResult
from .base import ModuleParser, Progress

_NUM = re.compile(r"^[-+]?\d+(?:[.,]\d+)?$")
_INT = re.compile(r"^\d+$")
_LABELS = ("Komb.", "Einw.")
_SUB = re.compile(r"^[xyz],[A-Za-z]+$")
_MERGED = re.compile(r"^([NVM])([xyz]),[A-Za-z]+$")
_TERM = re.compile(r"(\d+(?:\.\d+)?)\*([A-Za-z][\w.]*)")
_COMBO_HEAD = re.compile(r"(?:^|\s)(\d+)\s+(\d+(?:\.\d+)?\*[A-Za-z].*)$")
_DEF_LIST = re.compile(r"^\d+(?:\s*,\s*\d+)+$")
_DEF_TAIL = re.compile(r"^(\d+)\s+(\d+)\s+(\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(.*)$")
_DEF_ROW = re.compile(r"^(\d+)\s+(\d+)\s+(\d+)\s+(\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(.*)$")


def _num(t: str) -> float:
    return float(t.replace(",", "."))


def _lines(page) -> List[list]:
    """Woerter einer Seite zu Zeilen gruppieren (links -> rechts, oben -> unten)."""
    # Gedrehten Randtext (z.B. "mb Software GmbH" am Seitenrand) ausblenden
    words = [w for w in page.extract_words(extra_attrs=["upright"])
             if w.get("upright", True) and w["x0"] > 20]
    words.sort(key=lambda w: (w["top"], w["x0"]))
    lines: List[list] = []
    cur: list = []
    ref = None
    for w in words:
        if ref is None or abs(w["top"] - ref) <= 2.5:
            if ref is None:
                ref = w["top"]
            cur.append(w)
        else:
            lines.append(sorted(cur, key=lambda a: a["x0"]))
            cur, ref = [w], w["top"]
    if cur:
        lines.append(sorted(cur, key=lambda a: a["x0"]))
    return lines


def _columns(head: list, nxt: Optional[list]) -> Optional[List[str]]:
    """Komponentennamen (N, Vy, Vz, Mx, My, Mz) aus der Kopfzeile ableiten."""
    words = list(head[2:]) + (list(nxt) if nxt else [])  # 'Stab', 'x' ueberspringen
    cols = []
    # Fall A: schon zusammengesetzt, z.B. 'Nx,d'
    merged = [w for w in head[2:] if _MERGED.match(w["text"])]
    if merged:
        for w in merged:
            letter, axis = _MERGED.match(w["text"]).groups()
            cols.append("N" if letter == "N" else letter + axis)
        return cols
    # Fall B: Buchstabe in der Kopfzeile, Index (x,d / y,d / z,d) darunter
    letters = [w for w in head[2:] if w["text"] in ("N", "M", "V")]
    subs = [w for w in words if _SUB.match(w["text"])]
    for lt in letters:
        xc = (lt["x0"] + lt["x1"]) / 2
        if lt["text"] == "N":
            cols.append("N")
            continue
        if not subs:
            return None
        sub = min(subs, key=lambda s: abs((s["x0"] + s["x1"]) / 2 - xc))
        cols.append(lt["text"] + sub["text"][0])
    return cols or None


class MbaecS601(ModuleParser):
    id = "mbaec_s601"
    label = "mb AEC Baustatik S601.de (Stabwerk)"

    def parse(self, pdf_path: str, progress: Progress = None) -> ParseResult:
        cases: Dict[str, LoadCase] = {}
        order: List[str] = []
        members: Dict[int, MemberInfo] = {}
        nodes: Dict[int, tuple] = {}
        cur_case: Optional[LoadCase] = None
        cur_stab: Optional[int] = None
        pending: List[int] = []
        node_loads: List[NodeLoad] = []
        combos: Dict[int, List[tuple]] = {}
        cur_einw: Optional[str] = None
        cur_combo: Optional[int] = None
        in_loads = in_combos = False
        load_cols = [404.0, 489.0, 567.0]          # rechte Kanten der Spalten F(x), F(z), M

        with pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)
            for pi, page in enumerate(pdf.pages):
                if progress:
                    progress(pi + 1, total)
                lines = _lines(page)
                cols: Optional[List[str]] = None
                in_def = False
                in_nodes = False
                for li, line in enumerate(lines):
                    texts = [w["text"] for w in line]
                    if not texts:
                        continue
                    # --- Knotenlasten (Punktlasten je Einwirkung) ----------
                    if "Kommentar" in texts and texts.count("F") == 2 and "M" in texts:
                        in_loads = True
                        fs = [w for w in line if w["text"] in ("F", "M")]
                        if len(fs) == 3:
                            load_cols = [w["x1"] for w in fs]
                        continue
                    if in_loads:
                        if all(t.startswith("(") or t.endswith(")") for t in texts):
                            continue                                  # nur Kommentarmarken (a), (j,k) ...
                        if texts[0].startswith("(") or texts[0] in ("Kombinationen", "Einwirkung", "Knoten"):
                            in_loads = False
                        else:
                            ws = [w for w in line if not w["text"].startswith("(") and not w["text"].endswith(")")]
                            tx = [w["text"] for w in ws]
                            if tx and tx[0] == "Einw.":
                                if len(tx) < 3:
                                    in_loads = False
                                    continue
                                cur_einw = tx[1]
                                ws = ws[2:]
                            if ws and cur_einw and _INT.match(ws[0]["text"]) and all(_NUM.match(w["text"]) for w in ws):
                                vals = [0.0, 0.0, 0.0]
                                for w in ws[1:]:
                                    k = min(range(3), key=lambda j: abs(w["x1"] - load_cols[j]))
                                    vals[k] = _num(w["text"])
                                node_loads.append(NodeLoad(cur_einw, int(ws[0]["text"]), *vals))
                            continue
                    # --- Kombinationsvorschriften (Faktor*Einwirkung) ------
                    joined0 = " ".join(texts)
                    if texts[0] == "Kombinationen" or joined0.startswith("Ek ("):
                        in_combos = True
                        continue
                    if in_combos:
                        if joined0.startswith("Einwirkungsmuster") or joined0.startswith("Muster"):
                            in_combos = False
                        else:
                            mm = _COMBO_HEAD.search(joined0)
                            if mm and "*" in joined0:
                                cur_combo = int(mm.group(1))
                                combos[cur_combo] = [(float(f), e) for f, e in _TERM.findall(mm.group(2))]
                                continue
                            if cur_combo is not None and joined0.startswith("+") and "*" in joined0:
                                combos[cur_combo].extend((float(f), e) for f, e in _TERM.findall(joined0))
                                continue
                    # --- Knotendefinition (x, z) --------------------------
                    t0 = texts[1:] if texts[0] == "Knotendefinition" else texts
                    if t0[:3] == ["Knoten", "x", "z"]:
                        in_nodes = True
                        continue
                    if in_nodes:
                        if len(t0) == 3 and _INT.match(t0[0]) and all(_NUM.match(t) for t in t0[1:]):
                            nodes[int(t0[0])] = (_num(t0[1]), _num(t0[2]))
                            continue
                        if not all(_NUM.match(t) or t.startswith("[") for t in t0):
                            in_nodes = False
                    # --- Stabdefinition -----------------------------------
                    if texts[0] == "Stabdefinition":
                        texts = texts[1:]
                    if len(texts) >= 3 and texts[:3] == ["Stab", "von", "bis"]:
                        in_def = True
                        continue
                    if in_def:
                        joined = " ".join(texts)
                        if _DEF_LIST.match(joined):  # "52, 53" - Daten stehen in der Folgezeile
                            pending = [int(n) for n in re.split(r"\s*,\s*", joined)]
                            continue
                        if pending:
                            t = _DEF_TAIL.match(joined)
                            if t:
                                a, b, l, _, rest = t.groups()
                                for n in pending:
                                    members[n] = MemberInfo(n, int(a), int(b), float(l), rest.strip())
                                pending = []
                                continue
                            pending = []
                        m = _DEF_ROW.match(joined)
                        if m:
                            n, a, b, l, _, rest = m.groups()
                            members[int(n)] = MemberInfo(int(n), int(a), int(b), float(l), rest.strip())
                            continue
                        if texts[0].startswith("Stab") or texts[0] in ("Grafik", "Einwirkung"):
                            in_def = False
                    # --- Tabelle mit Schnittgroessen ----------------------
                    if len(line) >= 3 and texts[0] == "Stab" and texts[1] == "x":
                        nxt = lines[li + 1] if li + 1 < len(lines) else None
                        c = _columns(line, nxt)
                        if c:
                            cols = c
                        continue
                    if not cols:
                        continue
                    toks = [t.rstrip("*") for t in texts if t != "*"]
                    toks = [t for t in toks if t]
                    ncol = len(cols)
                    tail = ncol + 2  # Stab, x, Werte
                    if toks[0] in _LABELS:
                        rest = toks[1:]
                        if (len(rest) >= tail + 1 and all(_NUM.match(t) for t in rest[-tail:])
                                and _INT.match(rest[-tail])):
                            name = f"{toks[0]} {' '.join(rest[:-tail])}"
                            cur_case = self._case(cases, order, name)
                            cur_stab = int(rest[-tail])
                            self._add(cur_case, cur_stab, rest[-tail + 1:], cols)
                        else:
                            cur_case = self._case(cases, order, " ".join(toks))
                            cur_stab = None
                        continue
                    if cur_case is None or not all(_NUM.match(t) for t in toks):
                        continue
                    if len(toks) == tail and _INT.match(toks[0]):
                        cur_stab = int(toks[0])
                        self._add(cur_case, cur_stab, toks[1:], cols)
                    elif len(toks) == ncol + 1 and cur_stab is not None:
                        self._add(cur_case, cur_stab, toks, cols)

        if not order:
            raise ValueError(
                "Keine Tabelle 'Schnittgroessen (massgebende)' im PDF gefunden. "
                "Wurde die Position mit Schnittgroessen-Tabelle ausgegeben?")
        return ParseResult(self.id, [cases[n] for n in order], members, nodes, node_loads, combos)

    @staticmethod
    def _case(cases, order, name) -> LoadCase:
        if name not in cases:
            cases[name] = LoadCase(name)
            order.append(name)
        return cases[name]

    @staticmethod
    def _add(case: LoadCase, stab: int, nums: List[str], cols: List[str]) -> None:
        x = _num(nums[0])
        vals = {c: _num(v) for c, v in zip(cols, nums[1:])}
        case.members.setdefault(stab, []).append(ForceRow(x, vals))
