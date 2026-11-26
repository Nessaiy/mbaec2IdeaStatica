"""Achsenzuordnung Baustatik (z. B. ebenes x-z-Modell) -> IDEA StatiCa (3D x-y-z).

Beispiel-Schema:   Baustatik x = -y (IDEA),  y = x,  z = z
    axes = {"x": "-y", "y": "+x", "z": "+z"}      # Baustatik-Achse -> IDEA-Achse

Kraefte folgen der Achse direkt (Vorzeichen s). Momente sind Pseudovektoren:
bei einer Drehung (det = +1) folgen sie ebenfalls direkt, bei einer Spiegelung
(det = -1) kommt zusaetzlich ein Vorzeichenwechsel hinzu.
Ergebnis ist eine Tabelle "IDEA-Komponente <- +/-Baustatik-Komponente" (component_map),
die in der Oberflaeche noch einzeln geaendert werden kann.
"""
from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

from .model import COMPONENTS

AXES = ("x", "y", "z")
AXIS_CHOICES = ("+x", "-x", "+y", "-y", "+z", "-z")
FORCE = {"x": "N", "y": "Vy", "z": "Vz"}
MOMENT = {"x": "Mx", "y": "My", "z": "Mz"}
SOURCE_CHOICES = ["0"] + [f"{s}{c}" for c in COMPONENTS for s in ("+", "-")]

IDENTITY_AXES = {"x": "+x", "y": "+y", "z": "+z"}
IDENTITY_MAP = {c: f"+{c}" for c in COMPONENTS}

_AX = re.compile(r"^([+-]?)([xyz])$")
_SRC = re.compile(r"^([+-]?)(N|Vy|Vz|Mx|My|Mz)$")


def parse_axes(axes: Dict[str, str]) -> Dict[str, Tuple[int, str]]:
    """{"x": "-y", ...} -> {"x": (-1, "y"), ...}; wirft ValueError bei ungueltiger Belegung."""
    out: Dict[str, Tuple[int, str]] = {}
    for a in AXES:
        m = _AX.match(str(axes.get(a, "")).strip())
        if not m:
            raise ValueError(f"Achse '{a}': ungültiger Wert '{axes.get(a)}' (erlaubt: {', '.join(AXIS_CHOICES)})")
        out[a] = (-1 if m.group(1) == "-" else 1, m.group(2))
    if sorted(t for _, t in out.values()) != sorted(AXES):
        raise ValueError("Jede IDEA-Achse darf nur einmal vorkommen (x, y und z je einmal).")
    return out


def determinant(axes: Dict[str, str]) -> int:
    """+1 = Drehung (rechtshaendig bleibt rechtshaendig), -1 = Spiegelung."""
    p = parse_axes(axes)
    det = 1
    for s, _ in p.values():
        det *= s
    order = [AXES.index(p[a][1]) for a in AXES]
    inv = sum(1 for i in range(3) for j in range(i + 1, 3) if order[i] > order[j])
    return det * (-1 if inv % 2 else 1)


def component_map_from_axes(axes: Dict[str, str]) -> Dict[str, str]:
    """IDEA-Komponente -> '+/-Baustatik-Komponente' (z. B. {'Vy': '-N', 'Mx': '+My', ...})."""
    p = parse_axes(axes)
    det = determinant(axes)
    cmap: Dict[str, str] = {}
    for src_axis, (s, tgt) in p.items():
        sf = "+" if s > 0 else "-"
        mf = "+" if s * det > 0 else "-"
        cmap[FORCE[tgt]] = f"{sf}{FORCE[src_axis]}"
        cmap[MOMENT[tgt]] = f"{mf}{MOMENT[src_axis]}"
    return {c: cmap[c] for c in COMPONENTS}


def validate_component_map(cmap: Dict[str, str]) -> None:
    for c in COMPONENTS:
        v = str(cmap.get(c, "")).strip()
        if v != "0" and not _SRC.match(v):
            raise ValueError(f"Komponente {c}: ungültige Quelle '{v}' (erlaubt: {', '.join(SOURCE_CHOICES)})")


def apply_component_map(values: Dict[str, float], cmap: Optional[Dict[str, str]]) -> Tuple[float, ...]:
    """Baustatik-Werte (N, Vy, Vz, Mx, My, Mz; fehlend = 0) -> IDEA-Werte in COMPONENTS-Reihenfolge."""
    cmap = cmap or IDENTITY_MAP
    out = []
    for c in COMPONENTS:
        src = str(cmap.get(c, f"+{c}")).strip()
        if src == "0":
            out.append(0.0)
            continue
        m = _SRC.match(src)
        if not m:
            raise ValueError(f"Komponente {c}: ungültige Quelle '{src}'")
        v = values.get(m.group(2), 0.0) * (-1.0 if m.group(1) == "-" else 1.0)
        out.append(v + 0.0)                 # -0.0 -> 0.0
    return tuple(out)


def describe(cmap: Dict[str, str]) -> str:
    return ", ".join(f"{c} = {str(cmap.get(c, '+' + c)).replace('+', '')}" for c in COMPONENTS)
