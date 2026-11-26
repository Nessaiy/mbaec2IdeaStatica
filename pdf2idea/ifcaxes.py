"""Aus IFC (IDEA-Connection-Export) die lokalen IDEA-Achsen der Bauteile bestimmen und daraus die
Achsenzuordnung Baustatik -> IDEA je Stab vorschlagen.

Regeln (an Beobachtungen in IDEA geprueft: Stuetzen innen/mittig/aussen, Auskreuzung oben/unten):
  x (lokal)  = Stabachse, vom Bauteil-Ursprung in Richtung des Koerpers. Laeuft das Bauteil beidseitig
               durch den Ursprung, ist die Richtung nicht bestimmbar -> Vorgabe: nach +Z, sonst +X, sonst +Y
               (Hinweis 'Richtung pruefen').
  Standardlage (Drehung 0, wie in IDEA vorbelegt):
     senkrechter Stab:     y = +X(global), z = x kreuz y
     sonstiger Stab:       z = Anteil von +Z(global) senkrecht zu x, y = z kreuz x
  Bei I-Profilen liegt die Profilhoehe in lokal z; weicht die IFC davon ab (Profil gedreht), gibt es einen Hinweis.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .axes import component_map_from_axes
from .geometry import member_geometry
from .ifc import IfcMember
from .model import ParseResult

Vec3 = Tuple[float, float, float]

IFC_TO_IDEA_DEFAULT = {"x": "+y", "y": "-x", "z": "+z"}     # IDEA-Koordinate = +/- IFC-Koordinate
GLOBAL_DEFAULT = {"x": "+x", "z": "+z"}                     # Baustatik-Achse -> IDEA global (y ergibt sich)
CHOICES = ("+x", "-x", "+y", "-y", "+z", "-z")
_IDX = {"x": 0, "y": 1, "z": 2}
_NAMES = ("x", "y", "z")


def _unit(s: str) -> Vec3:
    v = [0.0, 0.0, 0.0]
    v[_IDX[s[1]]] = 1.0 if s[0] == "+" else -1.0
    return tuple(v)  # type: ignore


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _norm(v):
    l = math.sqrt(sum(c * c for c in v))
    return tuple(c / l for c in v) if l > 1e-12 else tuple(v)


def _snap(v, tol=0.02):
    out = tuple(0.0 if abs(c) < tol else c for c in v)
    return _norm(out)


def validate_ifc_axes(m: Dict[str, str]) -> None:
    srcs = [m[a][1] for a in _NAMES]
    if sorted(srcs) != ["x", "y", "z"]:
        raise ValueError("IFC-Achsen: jede IFC-Achse muss genau einmal verwendet werden.")


def ifc_det(m: Dict[str, str]) -> int:
    """+1 = Drehung, -1 = Spiegelung (dann stimmt die Zuordnung vermutlich nicht)."""
    rows = []
    for a in _NAMES:
        r = [0.0, 0.0, 0.0]
        r[_IDX[m[a][1]]] = 1.0 if m[a][0] == "+" else -1.0
        rows.append(r)
    d = (rows[0][0] * (rows[1][1] * rows[2][2] - rows[1][2] * rows[2][1])
         - rows[0][1] * (rows[1][0] * rows[2][2] - rows[1][2] * rows[2][0])
         + rows[0][2] * (rows[1][0] * rows[2][1] - rows[1][1] * rows[2][0]))
    return 1 if d > 0 else -1


def ifc_to_idea(v: Vec3, m: Dict[str, str]) -> Vec3:
    out = []
    for a in _NAMES:
        s = 1.0 if m[a][0] == "+" else -1.0
        out.append(s * v[_IDX[m[a][1]]])
    return tuple(out)  # type: ignore


def describe_vec(v: Vec3) -> str:
    """Richtung in IDEA-Global, z.B. '+Z' oder '(+0.62X +0.79Z)'."""
    big = max(range(3), key=lambda i: abs(v[i]))
    if abs(v[big]) > 0.985:
        return ("+" if v[big] > 0 else "-") + "XYZ"[big]
    parts = [f"{v[i]:+.2f}{'XYZ'[i]}" for i in range(3) if abs(v[i]) > 0.05]
    return "(" + " ".join(parts) + ")"


@dataclass
class IdeaFrame:
    name: str
    ex: Vec3
    ey: Vec3
    ez: Vec3
    notes: List[str] = field(default_factory=list)

    def describe(self) -> str:
        return f"x={describe_vec(self.ex)}  y={describe_vec(self.ey)}  z={describe_vec(self.ez)}"

    def to_dict(self) -> Dict[str, List[float]]:
        return {"ex": [round(c, 6) for c in self.ex], "ey": [round(c, 6) for c in self.ey],
                "ez": [round(c, 6) for c in self.ez]}

    @staticmethod
    def from_dict(name: str, d: Dict[str, List[float]]) -> "IdeaFrame":
        return IdeaFrame(name, tuple(d["ex"]), tuple(d["ey"]), tuple(d["ez"]))   # type: ignore


def flip_x(fr: IdeaFrame) -> IdeaFrame:
    """x-Richtung umkehren (z folgt aus der Rechtshand-Regel)."""
    ex = tuple(-c for c in fr.ex)
    return IdeaFrame(fr.name, ex, fr.ey, _cross(ex, fr.ey), list(fr.notes))      # type: ignore


def flip_y(fr: IdeaFrame) -> IdeaFrame:
    ey = tuple(-c for c in fr.ey)
    return IdeaFrame(fr.name, fr.ex, ey, _cross(fr.ex, ey), list(fr.notes))      # type: ignore


def rotate90(fr: IdeaFrame) -> IdeaFrame:
    """Profil um 90 Grad um die Stabachse drehen: y' = z, z' = -y."""
    return IdeaFrame(fr.name, fr.ex, fr.ez, tuple(-c for c in fr.ey), list(fr.notes))   # type: ignore


def idea_frame(m: IfcMember, tr: Dict[str, str], tol_len: float = 0.0005) -> IdeaFrame:
    """Lokales Achsensystem (in IDEA-Global-Koordinaten) eines IFC-Bauteils."""
    notes: List[str] = []
    a = _snap(ifc_to_idea(m.axis, tr))
    if m.t_min >= -tol_len:
        ex = a
    elif m.t_max <= tol_len:
        ex = tuple(-c for c in a)  # type: ignore
    else:
        ex = a
        if abs(a[2]) > 1e-3:
            ex = a if a[2] > 0 else tuple(-c for c in a)  # type: ignore
        elif abs(a[0]) > 1e-3:
            ex = a if a[0] > 0 else tuple(-c for c in a)  # type: ignore
        else:
            ex = a if a[1] > 0 else tuple(-c for c in a)  # type: ignore
        notes.append("läuft durch den Ursprung – Richtung von x bitte in IDEA prüfen")
    if abs(abs(ex[2]) - 1.0) < 1e-3:                       # senkrechter Stab
        ey = (1.0, 0.0, 0.0)
        ez = _cross(ex, ey)
    else:
        zc = _dot((0.0, 0.0, 1.0), ex)
        ez = _norm(tuple((0.0, 0.0, 1.0)[i] - zc * ex[i] for i in range(3)))
        ey = _cross(ez, ex)
    if m.section_type == "RolledI":
        h = ifc_to_idea(m.height_dir, tr)
        if abs(_dot(h, ez)) < 0.95:
            if abs(_dot(h, ey)) >= 0.95:
                notes.append("I-Profil gegenüber der IDEA-Standardlage um 90° gedreht – y/z manuell prüfen")
            else:
                notes.append("Profillage nicht eindeutig – y/z manuell prüfen")
    else:
        notes.append(f"Profil {m.profile or m.section_type}: Lage der Achsen y/z in IDEA bitte prüfen")
    return IdeaFrame(m.name, ex, ey, ez, notes)


def baustatik_frame(res: ParseResult, stab: int, glob: Dict[str, str]) -> Optional[Tuple[Vec3, Vec3, Vec3]]:
    """Lokale Achsen des Baustatik-Stabes (x, y, z) in IDEA-Global-Koordinaten."""
    if stab is None:                                   # Knotenlast: globale Richtungen (x rechts, z oben)
        ex, ez = (1.0, 0.0, 0.0), (0.0, 0.0, -1.0)      # wie bei Staeben: z zeigt nach unten (Lasten Fz positiv = nach unten)
    else:
        g = member_geometry(res).get(stab)
        if not g:
            return None
        ex2 = g[3]
        ex = (ex2[0], 0.0, ex2[1])
        ez = (ex2[1], 0.0, -ex2[0])
    ey = _cross(ez, ex)
    gx, gz = _unit(glob["x"]), _unit(glob["z"])
    gy = _cross(gz, gx)

    def to_idea(v):
        return tuple(v[0] * gx[i] + v[1] * gy[i] + v[2] * gz[i] for i in range(3))
    return to_idea(ex), to_idea(ey), to_idea(ez)       # type: ignore


@dataclass
class Suggestion:
    axes: Optional[Dict[str, str]]
    component_map: Optional[Dict[str, str]]
    notes: List[str]
    frame: Optional[IdeaFrame] = None


def suggest_axes(res: ParseResult, stab: int, frame: IdeaFrame, glob: Dict[str, str],
                 tol: float = 0.95) -> Suggestion:
    bs = baustatik_frame(res, stab, glob)
    notes = list(frame.notes)
    if bs is None:
        return Suggestion(None, None, ["Stab hat keine Knotenkoordinaten im PDF"] + notes, frame)
    idea = (frame.ex, frame.ey, frame.ez)
    axes: Dict[str, str] = {}
    for name, v in zip(("x", "y", "z"), bs):
        dots = [_dot(v, w) for w in idea]
        k = max(range(3), key=lambda i: abs(dots[i]))
        if abs(dots[k]) < tol:
            ang = math.degrees(math.acos(min(1.0, abs(dots[k]))))
            return Suggestion(None, None, [f"Baustatik-{name} liegt nicht parallel zu einer IDEA-Achse "
                                           f"(Abweichung {ang:.0f}°) – Stab liegt im IDEA-Modell nicht in der "
                                           f"Rahmenebene?"] + notes, frame)
        axes[name] = ("+" if dots[k] > 0 else "-") + _NAMES[k]
    try:
        cmap = component_map_from_axes(axes)
    except ValueError as e:
        return Suggestion(None, None, [str(e)] + notes, frame)
    return Suggestion(axes, cmap, notes, frame)


def _plain(name: str) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", "", name)).strip().casefold()


def match_member(name: str, members: List[IfcMember]) -> Optional[IfcMember]:
    """Bauteil nach Name suchen: exakt, ohne Gross/Klein, ohne Klammerzusaetze, sonst eindeutiger Namensanfang."""
    n = name.strip()
    for m in members:
        if m.name.strip() == n:
            return m
    nl = n.casefold()
    for m in members:
        if m.name.strip().casefold() == nl:
            return m
    p = _plain(n)
    if p:
        hits = [m for m in members if _plain(m.name) == p]
        if len(hits) == 1:
            return hits[0]
        hits = [m for m in members if _plain(m.name).startswith(p) or p.startswith(_plain(m.name))]
        if len(hits) == 1:
            return hits[0]
    return None


# ------------------------------------------------------------------ Darstellung / Position
VIEWS = {"Vorne (x–z)": (0, 2), "Seite (y–z)": (1, 2), "Oben (x–y)": (0, 1)}      # (Achse nach rechts, Achse nach oben)


def member_segment(m: IfcMember, tr: Dict[str, str]) -> Tuple[Vec3, Vec3, Vec3]:
    """(Punkt a, Punkt b, Ursprung) des Bauteils als Strecke in IDEA-Global."""
    o = ifc_to_idea(m.origin, tr)
    a = ifc_to_idea(m.axis, tr)
    p0 = tuple(o[i] + m.t_min * a[i] for i in range(3))
    p1 = tuple(o[i] + m.t_max * a[i] for i in range(3))
    return p0, p1, o          # type: ignore


def is_connector(m: IfcMember) -> bool:
    """Anschlussteile (Bleche, Winkel ... mit Nummer in Klammern, z.B. '(1) Stuetzenkopfplatte')."""
    return m.name.strip().startswith("(")


def is_continuous(m: IfcMember, tol: float = 0.0005) -> bool:
    return m.t_min < -tol and m.t_max > tol


def idea_position(m: IfcMember, station: str) -> str:
    """Vorgabe fuer die IDEA-Position (Anfang/Ende) der Last.

    Bauteil mit Ursprung am Rand: x zeigt vom Ursprung (Anschlussknoten) in den Stab, der Knoten ist also der
    Stabanfang -> 'Anfang'. Durchlaufendes Bauteil: Stelle 'rechts vom Sprung'/Anfang -> 'Anfang', sonst 'Ende'."""
    if not is_continuous(m):
        return "Anfang"
    if station == "Anfang" or station.endswith("R"):
        return "Anfang"
    return "Ende"


# ----------------------------------------------------------------------------- Vorschlaege: Global / Position / Vorzeichen
def _side(station: str) -> int:
    """+1 = Stabkoerper liegt in Stabrichtung hinter der Stelle (Stabanfang, rechts vom Sprung), -1 = davor, 0 = Stelle ohne Sprung."""
    if station == "Anfang" or station.endswith("R"):
        return 1
    if station == "Ende" or station.endswith("L"):
        return -1
    return 0


def _axis_vec(spec: str) -> Tuple[float, float, float]:
    i = "xyz".index(spec[-1])
    v = [0.0, 0.0, 0.0]
    v[i] = -1.0 if spec[0] == "-" else 1.0
    return (v[0], v[1], v[2])


def suggest_global(res: ParseResult, stab: Optional[int], frame: IdeaFrame, glob: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Liegt der Stab waagerecht und die Bauteilachse x in IDEA ebenfalls waagerecht, aber nicht in Richtung der
    eingestellten globalen Achse, dann ist das Baustatik-Modell in IDEA anders ausgerichtet (z. B. Rahmenebene y-z statt x-z).
    Gibt dann eine neue Zuordnung (nur x) zurueck, sonst None."""
    if stab is None:
        return None
    g = member_geometry(res).get(stab)
    if not g:
        return None
    ex2 = g[3]
    if abs(ex2[1]) > 0.2 or abs(frame.ex[2]) > 0.2:
        return None
    k = 0 if abs(frame.ex[0]) >= abs(frame.ex[1]) else 1
    letter = "xy"[k]
    cur = glob.get("x", "+x")
    if cur[-1] == letter:
        return None
    sign = (1.0 if ex2[0] >= 0 else -1.0) * (1.0 if frame.ex[k] >= 0 else -1.0)
    return {"x": ("+" if sign > 0 else "-") + letter, "z": glob.get("z", "+z")}


def suggest_position(res: ParseResult, stab: Optional[int], station: str, frame: IdeaFrame, glob: Dict[str, str],
                     m: Optional[IfcMember] = None) -> str:
    """IDEA-Position der Last: 'Anfang' = Ende des Bauteils bei kleinstem lokalen x, 'Ende' = bei groesstem x.
    Massgebend ist, in welche Richtung (in IDEA) der Stabkoerper vom Schnitt aus liegt: zeigt sie entlang der lokalen
    x-Achse des Bauteils, liegt der belastete Bauteilrand bei 'Ende'."""
    if stab is None:                                       # Knotenlast: freies Bauteilende
        return "Ende"
    if m is not None and not is_continuous(m):             # Bauteil endet am Knoten: Last immer am freien Ende
        return "Ende"
    side = _side(station)
    bs = baustatik_frame(res, stab, glob)
    if side != 0 and bs is not None:
        d = side * _dot(bs[0], frame.ex)
        if abs(d) > 0.3:
            return "Ende" if d > 0 else "Anfang"
    return idea_position(m, station) if m is not None else ("Anfang" if side > 0 else "Ende")


def suggest_sign(res: ParseResult, stab: Optional[int], station: str, frame: IdeaFrame, glob: Dict[str, str],
                 position: str) -> float:
    """Vorzeichen (+1/-1), das nach der Achsenzuordnung auf alle sechs Werte anzuwenden ist.

    Schnittgroessen sind an der Schnittflaeche definiert (positiv = in Richtung der Flaechennormalen bzw. nach den
    Vorzeichenregeln der Baustatik). Liegt das Bauteil in IDEA auf der anderen Seite des Schnitts als der Stab in der
    Baustatik, kehren sich alle Vorzeichen um. Knotenlast (aeussere Kraft): am Bauteilende 'Anfang' Gegenkraft."""
    s_i = 1.0 if position == "Ende" else -1.0
    if stab is None:
        return s_i
    side = _side(station)
    bs = baustatik_frame(res, stab, glob)
    if bs is None:
        return 1.0
    align = 1.0 if _dot(bs[0], frame.ex) >= 0 else -1.0
    if side != 0:
        s_b = -float(side)
    else:                                                  # ohne Sprung: aus der gewaehlten Position ableiten
        s_b = -align if position == "Ende" else align
    return -s_b * s_i


# ----------------------------------------------------------------------------- Vorschlaege aus der bildlich gewaehlten Achsenzuordnung
def _align_from_axes(axes: Optional[Dict[str, str]]) -> int:
    """+1 / -1, wenn Baustatik-x in IDEA lokal +x / -x ist; 0, wenn Baustatik-x nicht in IDEA-x liegt."""
    a = (axes or {}).get("x", "")
    if len(a) == 2 and a[1] == "x":
        return 1 if a[0] == "+" else -1
    return 0


def position_from_axes(stab: Optional[int], station: str, axes: Dict[str, str], m: Optional[IfcMember] = None) -> str:
    """IDEA-Position aus der gewaehlten Zuordnung: Liegt der Stabkoerper (von der Stelle aus in Stabrichtung bzw. dagegen)
    in Richtung +x des IDEA-Bauteils, ist die belastete Stelle das Bauteilende mit dem kleinsten x ('Anfang'), sonst 'Ende'."""
    if stab is None:
        return "Ende"
    if m is not None and not is_continuous(m):             # Bauteil endet am Knoten: Last immer am freien Ende
        return "Ende"
    side, align = _side(station), _align_from_axes(axes)
    if side != 0 and align != 0:
        return "Ende" if side * align > 0 else "Anfang"
    return idea_position(m, station) if m is not None else ("Anfang" if side > 0 else "Ende")


def sign_from_axes(stab: Optional[int], station: str, axes: Dict[str, str], position: str) -> float:
    """Vorzeichen (+1/-1) fuer alle sechs Werte einer Stab-Zuordnung.

    IDEA-Lasten sind aeussere Kraefte auf das Bauteil (in lokalen Achsen, am Anfang wie am Ende in +x positiv).
    Der Knoten (= Anschluss) liegt am Stabanfang bzw. 'rechts vom Sprung' hinter der Stelle: Der Stab uebt dort +F aus.
    Am Stabende bzw. 'links vom Sprung' uebt der Stab -F aus (Schnittkraft am Ende wirkt vom Knoten auf den Stab).
    Ohne Seitenangabe (Stelle mitten im Stab) folgt die Seite aus IDEA-Position und Achsenrichtung.
    Geprueft am Knotengleichgewicht (Aktive_Position.pdf, Komb. 17): Summe der Kraefte und Momente = 0."""
    if stab is None:
        return 1.0 if position == "Ende" else -1.0
    side = _side(station)
    if side == 0:
        align = _align_from_axes(axes) or 1
        side = align * (-1 if position == "Anfang" else 1)
    return float(side)


def idea_rows(members: List[IfcMember]) -> List[Tuple[str, str]]:
    """Zeilen der IDEA-Importtabelle (Bauteil, Position) aus der IFC: Bauteile, die am Knoten enden, haben nur 'Ende'
    (Ursprung am Knoten, die Last wirkt am freien Ende); durchlaufende Bauteile haben 'Anfang' und 'Ende'."""
    out: List[Tuple[str, str]] = []
    seen = set()
    for m in members:
        if m.npoints < 4 or is_connector(m) or m.name in seen:
            continue
        seen.add(m.name)
        if is_continuous(m):
            out += [(m.name, "Anfang"), (m.name, "Ende")]
        else:
            out.append((m.name, "Ende"))
    return out
