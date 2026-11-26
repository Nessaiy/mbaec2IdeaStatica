"""Gemeinsames Datenmodell - unabhaengig vom Baustatik-Modul."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Reihenfolge wie im IDEA-Dialog "Import von Lasten"
COMPONENTS = ("N", "Vy", "Vz", "Mx", "My", "Mz")
UNITS = {"N": "kN", "Vy": "kN", "Vz": "kN", "Mx": "kNm", "My": "kNm", "Mz": "kNm"}
POSITIONS = ("Anfang", "Ende")


@dataclass
class ForceRow:
    """Schnittgroessen an einer Stelle x eines Stabes."""
    x: float
    values: Dict[str, float]


@dataclass
class MemberInfo:
    """Stabdefinition aus dem PDF (nur zur Orientierung bei der Zuordnung)."""
    number: int
    node_start: Optional[int] = None
    node_end: Optional[int] = None
    length: Optional[float] = None
    description: str = ""

    def label(self) -> str:
        parts = [f"Stab {self.number}"]
        if self.node_start is not None and self.node_end is not None:
            parts.append(f"Kn. {self.node_start}→{self.node_end}")
        if self.length is not None:
            parts.append(f"l={self.length:g} m")
        if self.description:
            parts.append(self.description)
        return "  |  ".join(parts)


@dataclass
class LoadCase:
    """Eine Kombination / Einwirkung mit den Schnittgroessen je Stab."""
    name: str
    members: Dict[int, List[ForceRow]] = field(default_factory=dict)


@dataclass
class NodeLoad:
    """Charakteristische Knotenlast einer Einwirkung (global x/z, Moment um y)."""
    einw: str
    node: int
    fx: float = 0.0
    fz: float = 0.0
    m: float = 0.0


@dataclass
class ParseResult:
    module_id: str
    load_cases: List[LoadCase]
    members: Dict[int, MemberInfo]
    nodes: Dict[int, Tuple[float, float]] = field(default_factory=dict)   # Knoten -> (x, z) in m
    node_loads: List[NodeLoad] = field(default_factory=list)              # Punktlasten je Einwirkung (charakteristisch)
    combinations: Dict[int, List[Tuple[float, str]]] = field(default_factory=dict)   # Komb.-Nr -> [(Faktor, Einwirkung)]

    def load_nodes(self) -> List[int]:
        return sorted({l.node for l in self.node_loads})

    def node_load_sum(self, node: int, case_name: str, factor: float = 1.0, einw_factors=None):
        """Summe Faktor x charakteristische Knotenlast an einem Knoten fuer eine Kombination -> (Fx, Fz, M) oder None."""
        nr = case_name.split()[-1] if case_name.split() else case_name
        if not nr.isdigit() or int(nr) not in self.combinations:
            return None
        fx = fz = m = 0.0
        ef = einw_factors or {}
        for f, einw in self.combinations[int(nr)]:
            f = f * ef.get(einw, factor)       # Anteil: je Einwirkung oder allgemein
            for l in self.node_loads:
                if l.node == node and l.einw == einw:
                    fx += f * l.fx
                    fz += f * l.fz
                    m += f * l.m
        return fx, fz, m

    def node_load_parts(self, node: int, case_name: str, factor: float = 1.0, einw_factors=None):
        """Einzelbeitraege der Knotenlast je Einwirkung: [(Einwirkung, Faktor gesamt, Fx, Fz, M)] (Werte schon mit Faktor) oder None."""
        nr = case_name.split()[-1] if case_name.split() else case_name
        if not nr.isdigit() or int(nr) not in self.combinations:
            return None
        ef = einw_factors or {}
        out = []
        for f, einw in self.combinations[int(nr)]:
            f = f * ef.get(einw, factor)
            fx = fz = m = 0.0
            hit = False
            for l in self.node_loads:
                if l.node == node and l.einw == einw:
                    fx, fz, m, hit = fx + f * l.fx, fz + f * l.fz, m + f * l.m, True
            if hit:
                out.append((einw, f, fx, fz, m))
        return out

    def member_numbers(self) -> List[int]:
        nums = set(self.members)
        for lc in self.load_cases:
            nums.update(lc.members)
        return sorted(nums)

    def case_names(self) -> List[str]:
        return [lc.name for lc in self.load_cases]
