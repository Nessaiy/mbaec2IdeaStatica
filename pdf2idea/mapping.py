"""Zuordnung: IDEA-Bauteil (Name + Position) <-> PDF-Stab (+ Stelle x) bzw. manuelle Lasten."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Set

from .axes import IDENTITY_AXES, IDENTITY_MAP, component_map_from_axes, validate_component_map
from .model import COMPONENTS, POSITIONS


@dataclass
class ManualLoad:
    """Schnittgroessen fuer einen Bereich von Kombinationen (Stab ohne PDF-Werte)."""
    cases: str = "alle"                     # z.B. "1-20", "21-35, 40", "alle"
    values: Dict[str, float] = field(default_factory=dict)   # nicht genannte Komponenten = 0


@dataclass
class Assignment:
    idea_name: str                          # Name des Bauteils wie in IDEA StatiCa
    position: str                           # Position im IDEA-Bauteil: "Anfang" | "Ende"
    stab: Optional[int] = None              # PDF-Stab; None = manuell eingegebener Stab
    # Stelle im PDF-Stab: "Anfang" | "Ende" | "x=6.28" | "x=6.15L" | "x=6.15R"
    # (L/R = links/rechts der Stelle, wenn dort ein Sprung ist)
    station: str = "Ende"
    manual: List[ManualLoad] = field(default_factory=list)
    # Eigene lokale Achsenzuordnung Baustatik -> IDEA-Bauteil; None = Standard aus dem Profil
    axes: Optional[Dict[str, str]] = None
    component_map: Optional[Dict[str, str]] = None
    sign: float = 1.0                       # Vorzeichen aller PDF-Schnittgroessen dieser Zuordnung (-1 = umkehren)
    # Knotenlast aus den Einwirkungen im PDF (z.B. Kranlasten): Knotennummer; Summe Faktor x charakteristische Last je Kombination
    node: Optional[int] = None
    node_sign: float = 1.0                  # Vorzeichen der Knotenlast (+1: Last wie am Knoten, -1: Gegenkraft)
    node_factor: float = 1.0                # Anteil der Knotenlast (z. B. 0,5 bei Aufteilung auf zwei Kranbahnen)
    node_einw: Dict[str, float] = field(default_factory=dict)   # abweichender Anteil je Einwirkung, z. B. {"Qk.HS": 0.3}

    @property
    def is_node(self) -> bool:
        return self.node is not None

    @property
    def is_manual(self) -> bool:
        return self.stab is None and self.node is None

    def validate(self) -> None:
        if self.position not in POSITIONS:
            raise ValueError(f"Position muss {POSITIONS} sein, nicht '{self.position}'")
        if not self.idea_name.strip():
            raise ValueError("Bauteilname fehlt")
        for m in self.manual:
            parse_case_spec(m.cases)
        if self.node_factor < 0:
            raise ValueError("Anteil der Knotenlast darf nicht negativ sein (Vorzeichen separat umkehren)")
        if self.axes is not None:
            component_map_from_axes(self.axes)
        if self.component_map is not None:
            validate_component_map(self.component_map)

    def describe(self) -> str:
        if self.is_node:
            extra = f" × {self.node_factor:g}" if self.node_factor != 1.0 else ""
            if self.node_einw:
                extra += " (" + ", ".join(f"{k}×{v:g}" for k, v in self.node_einw.items()) + ")"
            return f"Knotenlast Kn. {self.node}{extra}" + (" (Vorz. –)" if self.node_sign < 0 else "")
        if self.is_manual:
            return "manuell"
        neg = " (Vorz. –)" if self.sign < 0 else ""
        st = self.station
        if st.startswith("x="):
            side = {"L": " (links)", "R": " (rechts)"}.get(st[-1], "")
            return f"Stab {self.stab} @ x={st[2:].rstrip('LR')} m{side}{neg}"
        return f"Stab {self.stab} {st}{neg}"


def parse_case_spec(text: str) -> Optional[Set[int]]:
    """'1-20, 25' -> {1..20, 25}; 'alle' / '*' -> None (= alle Kombinationen)."""
    t = text.strip().lower()
    if t in ("", "alle", "*", "all"):
        return None
    out: Set[int] = set()
    for part in re.split(r"[;,]", t):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*(?:-|bis)\s*(\d+)", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                raise ValueError(f"Bereich '{part}' ist rückwärts.")
            out.update(range(a, b + 1))
        elif part.isdigit():
            out.add(int(part))
        else:
            raise ValueError(f"Kombinationsangabe '{part}' nicht verständlich (Beispiel: 1-20, 25).")
    return out


@dataclass
class Profile:
    """Wird als JSON gespeichert, damit eine Zuordnung wiederverwendbar ist."""
    module_id: str = "mbaec_s601"
    assignments: List[Assignment] = field(default_factory=list)
    name_pattern: str = "{name}"          # {name} = z.B. "Komb. 1"; {nr} = "1"
    signs: Dict[str, float] = field(default_factory=lambda: {c: 1.0 for c in COMPONENTS})
    selected_cases: List[str] = field(default_factory=list)   # leer = alle
    # Achsenzuordnung Baustatik -> IDEA (nur fuer PDF-Werte), siehe axes.py
    axes: Dict[str, str] = field(default_factory=lambda: dict(IDENTITY_AXES))
    component_map: Dict[str, str] = field(default_factory=lambda: dict(IDENTITY_MAP))
    # IFC / grafische Zuordnung: Drehung IFC -> IDEA, Baustatik -> IDEA-Global, bestaetigte IDEA-Achsen je Bauteil
    ifc_axes: Dict[str, str] = field(default_factory=dict)
    global_axes: Dict[str, str] = field(default_factory=dict)
    ifc_frames: Dict[str, dict] = field(default_factory=dict)       # Name -> {"ex","ey","ez","confirmed"}

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @staticmethod
    def from_json(text: str) -> "Profile":
        d = json.loads(text)
        assignments = []
        for a in d.get("assignments", []):
            a = dict(a)
            a["manual"] = [ManualLoad(**m) for m in a.get("manual", [])]
            if a.get("stab") is not None and "station" not in a:
                a["station"] = a.get("position", "Ende")   # alte Dateien: Position = PDF-Stelle
            assignments.append(Assignment(**a))
        axes = {**IDENTITY_AXES, **d.get("axes", {})}
        if "component_map" in d:
            cmap = {**IDENTITY_MAP, **d["component_map"]}
        else:
            cmap = component_map_from_axes(axes) if "axes" in d else dict(IDENTITY_MAP)
        validate_component_map(cmap)
        p = Profile(
            axes=axes, component_map=cmap,
            module_id=d.get("module_id", "mbaec_s601"),
            assignments=assignments,
            name_pattern=d.get("name_pattern", "{name}"),
            signs={**{c: 1.0 for c in COMPONENTS}, **d.get("signs", {})},
            selected_cases=list(d.get("selected_cases", [])),
            ifc_axes=dict(d.get("ifc_axes", {})),
            global_axes=dict(d.get("global_axes", {})),
            ifc_frames=dict(d.get("ifc_frames", {})),
        )
        for a in p.assignments:
            a.validate()
        return p

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())

    @staticmethod
    def load(path: str) -> "Profile":
        with open(path, "r", encoding="utf-8") as f:
            return Profile.from_json(f.read())
