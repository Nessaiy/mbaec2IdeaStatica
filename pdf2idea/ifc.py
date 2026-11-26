"""Minimaler IFC-Leser (reines Python, keine Zusatzpakete) fuer IDEA-StatiCa-Connection-Exporte.

Liest Stab-Bauteile (IfcBeam / IfcColumn / IfcMember) mit ihrer Geometrie (Brep, auch als MappedItem) und
ermittelt je Bauteil:
  - die Stabachse (Linie, aus den Eckpunkten per Hauptachsenanalyse),
  - die Lage des Koerpers bezogen auf den Bauteil-Ursprung (Koerper auf der + oder - Seite oder beidseitig),
  - bei Profilen die Richtung der groesseren Querschnittsabmessung (Profilhoehe bei I-Profilen),
  - Name, Profil und Profiltyp (aus den IDEA-Property-Sets).
Alle Angaben im IFC-Koordinatensystem; die Umrechnung ins IDEA-System steht in ifcaxes.py.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

Vec3 = Tuple[float, float, float]
Mat = List[List[float]]          # 4x4, Zeilen


class Ref(int):
    """Verweis auf eine Entitaet (#123)."""


_TOK = re.compile(
    r"\s*(?:('(?:[^']|'')*')|(#\d+)|([-+]?(?:\d+\.?\d*|\.\d+)(?:[Ee][-+]?\d+)?)|(\.[A-Z_0-9]+\.)|(\$)|(\*)"
    r"|([A-Z][A-Z0-9_]*)\s*\(|(\()|(\))|(,))")


def decode_step_string(s: str) -> str:
    s = s[1:-1].replace("''", "'")
    s = re.sub(r"\\X2\\([0-9A-Fa-f]+)\\X0\\",
               lambda m: "".join(chr(int(m.group(1)[i:i + 4], 16)) for i in range(0, len(m.group(1)), 4)), s)
    s = re.sub(r"\\X\\([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), s)
    return s


def parse_args(text: str) -> list:
    """Argumentliste einer Entitaet ('a,b,(c,d)') als verschachtelte Liste."""
    stack: List[list] = [[]]
    names: List[Optional[str]] = [None]
    pos = 0
    n = len(text)
    while pos < n:
        m = _TOK.match(text, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
        st, ref, num, enum, dollar, star, typed, op, cl, comma = m.groups()
        cur = stack[-1]
        if st is not None:
            cur.append(decode_step_string(st))
        elif ref is not None:
            cur.append(Ref(int(ref[1:])))
        elif num is not None:
            cur.append(float(num))
        elif enum is not None:
            cur.append(enum)
        elif dollar is not None or star is not None:
            cur.append(None)
        elif typed is not None:
            stack.append([])
            names.append(typed)
        elif op is not None:
            stack.append([])
            names.append(None)
        elif cl is not None:
            if len(stack) > 1:
                done = stack.pop()
                nm = names.pop()
                stack[-1].append((nm, done) if nm else done)
    return stack[0]


class IfcFile:
    def __init__(self, path: str):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        i = text.find("DATA;")
        self.raw: Dict[int, Tuple[str, str]] = {}
        for m in re.finditer(r"#(\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*?)\)\s*;[ \t]*(?:\r?\n|$)", text[i:], re.S):
            self.raw[int(m.group(1))] = (m.group(2), m.group(3))
        self._cache: Dict[int, list] = {}

    def type(self, i: int) -> str:
        return self.raw[i][0]

    def args(self, i: int) -> list:
        a = self._cache.get(i)
        if a is None:
            a = self._cache[i] = parse_args(self.raw[i][1])
        return a

    def ids(self, *types: str) -> List[int]:
        return [i for i, (t, _) in self.raw.items() if t in types]


# ------------------------------------------------------------------ Lineare Algebra (klein)
def _norm(v):
    l = math.sqrt(sum(c * c for c in v))
    return tuple(c / l for c in v) if l > 1e-12 else tuple(v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _ident() -> Mat:
    return [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]


def _mul(a: Mat, b: Mat) -> Mat:
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _from_axes(x, y, z, o, scale=1.0) -> Mat:
    return [[x[0] * scale, y[0] * scale, z[0] * scale, o[0]],
            [x[1] * scale, y[1] * scale, z[1] * scale, o[1]],
            [x[2] * scale, y[2] * scale, z[2] * scale, o[2]],
            [0.0, 0.0, 0.0, 1.0]]


def _inverse_rigid(m: Mat, scale: float = 1.0) -> Mat:
    """Inverse einer Matrix aus orthogonalen Spalten (ggf. mit Massstab)."""
    r = [[m[j][i] / (scale * scale) for j in range(3)] for i in range(3)]      # R^T / s^2
    t = [-sum(r[i][k] * m[k][3] for k in range(3)) for i in range(3)]
    return [r[0] + [t[0]], r[1] + [t[1]], r[2] + [t[2]], [0.0, 0.0, 0.0, 1.0]]


def _apply(m: Mat, p) -> Vec3:
    return tuple(m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3] for i in range(3))   # type: ignore


def _eig_sym3(c):
    """Eigenwerte/-vektoren einer symmetrischen 3x3-Matrix (Jacobi). Rueckgabe: [(wert, vektor)] absteigend."""
    a = [list(r) for r in c]
    v = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]
    for _ in range(60):
        p, q, big = 0, 1, 0.0
        for i in range(3):
            for j in range(i + 1, 3):
                if abs(a[i][j]) > big:
                    p, q, big = i, j, abs(a[i][j])
        if big < 1e-14:
            break
        th = 0.5 * math.atan2(2 * a[p][q], a[q][q] - a[p][p])
        cs, sn = math.cos(th), math.sin(th)
        for k in range(3):
            akp, akq = a[k][p], a[k][q]
            a[k][p], a[k][q] = cs * akp - sn * akq, sn * akp + cs * akq
        for k in range(3):
            apk, aqk = a[p][k], a[q][k]
            a[p][k], a[q][k] = cs * apk - sn * aqk, sn * apk + cs * aqk
        for k in range(3):
            vkp, vkq = v[k][p], v[k][q]
            v[k][p], v[k][q] = cs * vkp - sn * vkq, sn * vkp + cs * vkq
    res = [(a[i][i], (v[0][i], v[1][i], v[2][i])) for i in range(3)]
    res.sort(key=lambda t: -t[0])
    return res


def _snap(v: Vec3, tol: float = 1e-4) -> Vec3:
    out = tuple(0.0 if abs(c) < tol else c for c in v)
    out = tuple(math.copysign(1.0, c) if abs(abs(c) - 1.0) < tol else c for c in out)
    return _norm(out)  # type: ignore


# ------------------------------------------------------------------ Platzierung und Geometrie
def _point(f: IfcFile, ref) -> Vec3:
    return tuple(f.args(ref)[0])           # type: ignore


def _axis2placement(f: IfcFile, ref) -> Mat:
    if ref is None:
        return _ident()
    a = f.args(ref)
    loc = _point(f, a[0])
    loc = tuple(list(loc) + [0.0] * (3 - len(loc)))
    if f.type(ref) == "IFCAXIS2PLACEMENT2D":
        return _ident()
    z = _norm(tuple(f.args(a[1])[0])) if len(a) > 1 and a[1] is not None else (0.0, 0.0, 1.0)
    xr = tuple(f.args(a[2])[0]) if len(a) > 2 and a[2] is not None else (1.0, 0.0, 0.0)
    d = _dot(xr, z)
    x = _norm(tuple(xr[i] - d * z[i] for i in range(3)))
    y = _cross(z, x)
    return _from_axes(x, y, z, loc)


def _local_placement(f: IfcFile, ref) -> Mat:
    if ref is None:
        return _ident()
    a = f.args(ref)
    parent = _local_placement(f, a[0]) if a[0] is not None else _ident()
    return _mul(parent, _axis2placement(f, a[1]))


def _operator(f: IfcFile, ref) -> Tuple[Mat, float]:
    a = f.args(ref)                         # Axis1, Axis2, LocalOrigin, Scale, Axis3
    d = lambda i: tuple(f.args(a[i])[0]) if len(a) > i and a[i] is not None else None
    x = _norm(d(0)) if d(0) else (1.0, 0.0, 0.0)
    z = _norm(d(4)) if d(4) else None
    y = _norm(d(1)) if d(1) else None
    if z is None:
        z = _norm(_cross(x, y)) if y else (0.0, 0.0, 1.0)
    if y is None:
        y = _cross(z, x)
    o = _point(f, a[2]) if a[2] is not None else (0.0, 0.0, 0.0)
    s = float(a[3]) if len(a) > 3 and a[3] is not None else 1.0
    return _from_axes(x, y, z, o, s), s


def _collect(f: IfcFile, item, m: Mat, out: List[Vec3], depth: int = 0, polys: Optional[list] = None) -> None:
    if depth > 8 or item is None:
        return
    t = f.type(item)
    a = f.args(item)
    if t == "IFCMAPPEDITEM":
        src = f.args(a[0])                  # IfcRepresentationMap(MappingOrigin, MappedRepresentation)
        op, s = _operator(f, a[1])
        origin = _axis2placement(f, src[0])
        mm = _mul(m, _mul(op, _inverse_rigid(origin)))
        _collect(f, src[1], mm, out, depth + 1, polys)
    elif t == "IFCSHAPEREPRESENTATION":
        for it in a[3]:
            _collect(f, it, m, out, depth + 1, polys)
    elif t == "IFCPRODUCTDEFINITIONSHAPE":
        for r in a[2]:
            _collect(f, r, m, out, depth + 1, polys)
    elif t in ("IFCFACETEDBREP", "IFCADVANCEDBREP"):
        _collect(f, a[0], m, out, depth + 1, polys)
    elif t == "IFCCLOSEDSHELL" or t == "IFCOPENSHELL":
        for fc in a[0]:
            for bd in f.args(fc)[0]:
                loop = f.args(bd)[0]
                if f.type(loop) == "IFCPOLYLOOP":
                    poly = [_apply(m, _point(f, p)) for p in f.args(loop)[0]]
                    out.extend(poly)
                    if polys is not None and len(poly) >= 3:
                        polys.append(poly)
    elif t in ("IFCBOOLEANRESULT", "IFCBOOLEANCLIPPINGRESULT"):
        _collect(f, a[1], m, out, depth + 1, polys)          # FirstOperand; Zweiter Operand = Ausschnitt


# ------------------------------------------------------------------ Ergebnis
@dataclass
class IfcMember:
    name: str
    profile: str = ""                 # z.B. 'I300' (Beschreibung)
    section_type: str = ""            # z.B. 'RolledI'
    ifc_type: str = "IFCBEAM"
    origin: Vec3 = (0.0, 0.0, 0.0)    # Bauteil-Ursprung (IFC-Koordinaten)
    axis: Vec3 = (1.0, 0.0, 0.0)      # Stabachse (Linie, Vorzeichen beliebig)
    t_min: float = 0.0                # Ausdehnung des Koerpers entlang axis relativ zum Ursprung
    t_max: float = 0.0
    height_dir: Vec3 = (0.0, 0.0, 1.0)   # Richtung der groesseren Querschnittsabmessung (Linie)
    height: float = 0.0
    width: float = 0.0
    npoints: int = 0
    faces: List[List[Vec3]] = field(default_factory=list)      # Flaechen (Polygone) in IFC-Koordinaten
    warnings: List[str] = field(default_factory=list)


def _psets(f: IfcFile) -> Dict[int, Dict[str, Dict[str, object]]]:
    sets: Dict[int, Tuple[str, Dict[str, object]]] = {}
    for i in f.ids("IFCPROPERTYSET"):
        a = f.args(i)
        props: Dict[str, object] = {}
        for p in a[4]:
            if f.type(p) == "IFCPROPERTYSINGLEVALUE":
                pa = f.args(p)
                v = pa[2]
                if isinstance(v, tuple) and v[1]:
                    v = v[1][0]
                props[str(pa[0])] = v
        sets[i] = (str(a[2]), props)
    out: Dict[int, Dict[str, Dict[str, object]]] = {}
    for i in f.ids("IFCRELDEFINESBYPROPERTIES"):
        a = f.args(i)
        ps = a[5]
        if ps in sets:
            for obj in a[4]:
                out.setdefault(obj, {})[sets[ps][0]] = sets[ps][1]
    return out


def read_members(path: str) -> List[IfcMember]:
    f = IfcFile(path)
    psets = _psets(f)
    res: List[IfcMember] = []
    for pid in f.ids("IFCBEAM", "IFCCOLUMN", "IFCMEMBER"):
        a = f.args(pid)
        m = IfcMember(name=str(a[2] or ""), profile=str(a[3] or ""), ifc_type=f.type(pid))
        cs = psets.get(pid, {}).get("IDEA_CrossSection", {})
        if cs:
            m.section_type = str(cs.get("Type", ""))
            m.profile = str(cs.get("Name", m.profile))
        place = _local_placement(f, a[5])
        pts: List[Vec3] = []
        if a[6] is not None:
            _collect(f, a[6], place, pts, 0, m.faces)
        if len(pts) < 4:
            m.warnings.append("Keine Geometrie gefunden")
            res.append(m)
            continue
        pts = list(set(pts))
        m.npoints = len(pts)
        m.origin = _apply(place, (0.0, 0.0, 0.0))
        c = tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))
        cov = [[sum((p[i] - c[i]) * (p[j] - c[j]) for p in pts) / len(pts) for j in range(3)] for i in range(3)]
        ev = _eig_sym3(cov)
        axis = _snap(ev[0][1])
        m.axis = axis
        ts = [_dot((p[0] - m.origin[0], p[1] - m.origin[1], p[2] - m.origin[2]), axis) for p in pts]
        m.t_min, m.t_max = min(ts), max(ts)
        # Querschnitt: Hauptachsen in der Ebene senkrecht zur Stabachse
        e1 = _snap(_cross(axis, _norm(_cross(axis, (0.0, 0.0, 1.0)) if abs(axis[2]) < 0.9 else _cross(axis, (1.0, 0.0, 0.0)))))
        e2 = _snap(_cross(axis, e1))
        uv = [(_dot(p, e1), _dot(p, e2)) for p in pts]
        cu = sum(u for u, _ in uv) / len(uv)
        cv = sum(v for _, v in uv) / len(uv)
        suu = sum((u - cu) ** 2 for u, _ in uv)
        svv = sum((v - cv) ** 2 for _, v in uv)
        suv = sum((u - cu) * (v - cv) for u, v in uv)
        th = 0.5 * math.atan2(2 * suv, suu - svv)
        d1 = _snap(tuple(math.cos(th) * e1[i] + math.sin(th) * e2[i] for i in range(3)))
        d2 = _snap(_cross(axis, d1))
        ext1 = max(_dot(p, d1) for p in pts) - min(_dot(p, d1) for p in pts)
        ext2 = max(_dot(p, d2) for p in pts) - min(_dot(p, d2) for p in pts)
        if ext1 >= ext2:
            m.height_dir, m.height, m.width = d1, ext1, ext2
        else:
            m.height_dir, m.height, m.width = d2, ext2, ext1
        res.append(m)
    return res
