"""Reine Geometrie-Helfer fuer die Modellansicht (ohne tkinter, damit testbar).

Koordinaten: Welt (x, z) mit z nach oben, wie in der Knotendefinition des PDFs.
Lokale Achsen der Baustatik (am Beispiel S601.de per Knotengleichgewicht geprueft):
    x lokal = Richtung von Knoten 'von' nach Knoten 'bis'
    z lokal = x lokal um 90 Grad im Uhrzeigersinn gedreht (x nach rechts -> z nach unten)
"""
from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Tuple

from .model import ParseResult

Vec = Tuple[float, float]


def local_axes(ex: Vec) -> Tuple[Vec, Vec]:
    """(x lokal, z lokal) in Weltkoordinaten (z oben)."""
    return ex, (ex[1], -ex[0])


def member_geometry(result: ParseResult) -> Dict[int, Tuple[Vec, Vec, float, Vec]]:
    """stab -> (Punkt a, Punkt b, Laenge, Einheitsvektor a->b); nur Staebe mit bekannten Knoten."""
    out = {}
    for n, m in result.members.items():
        if m.node_start in result.nodes and m.node_end in result.nodes:
            a, b = result.nodes[m.node_start], result.nodes[m.node_end]
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if L > 1e-9:
                out[n] = (a, b, L, ((b[0] - a[0]) / L, (b[1] - a[1]) / L))
    return out


def node_members(result: ParseResult, node: int) -> List[Tuple[int, str]]:
    """Staebe an einem Knoten: (Stab, 'Anfang' | 'Ende') = welches Stabende am Knoten liegt."""
    out = []
    for n in sorted(result.members):
        m = result.members[n]
        if m.node_start == node:
            out.append((n, "Anfang"))
        if m.node_end == node:
            out.append((n, "Ende"))
    return out


def members_through_node(result: ParseResult, node: int, tol: float = 0.01) -> List[Tuple[int, float]]:
    """Staebe, die durch den Knoten laufen, ohne dort zu enden (Knoten liegt zwischen den Stabenden).

    Rueckgabe: (Stab, Strecke s vom Stabanfang in Stabrichtung)."""
    if node not in result.nodes:
        return []
    px, pz = result.nodes[node]
    out = []
    for n, (a, b, L, ex) in sorted(member_geometry(result).items()):
        m = result.members[n]
        if node in (m.node_start, m.node_end):
            continue
        d, t = distance_point_segment(px, pz, a[0], a[1], b[0], b[1])
        s = t * L
        if d <= tol and tol < s < L - tol:
            out.append((n, s))
    return out


def station_key_from_distance(s: float, length: float, tol: float = 0.005) -> str:
    if s <= tol:
        return "Anfang"
    if s >= length - tol:
        return "Ende"
    return f"x={s:.2f}"


def station_distance(key: str, length: float) -> Optional[float]:
    if key == "Anfang":
        return 0.0
    if key == "Ende":
        return length
    m = re.fullmatch(r"x=(-?\d+(?:\.\d+)?)[LR]?", key)
    return float(m.group(1)) if m else None


def point_on_member(result: ParseResult, stab: int, s: float) -> Optional[Vec]:
    g = member_geometry(result).get(stab)
    if not g:
        return None
    a, _, L, ex = g
    s = max(0.0, min(L, s))
    return (a[0] + ex[0] * s, a[1] + ex[1] * s)


def distance_point_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> Tuple[float, float]:
    """(Abstand, t in [0,1]) des Punktes zur Strecke a-b."""
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(px - qx, py - qy), t
