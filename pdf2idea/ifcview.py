"""IFC-Ansicht (3D): Bauteile aus der IFC (IDEA Connection) zeichnen, anklicken und die lokalen IDEA-Achsen
abgleichen. Zusammen mit der Modellansicht (Baustatik) ergibt das die grafische Zuordnung:
  1. IFC-Bauteil anklicken, lokale Achsen mit IDEA vergleichen, ggf. anpassen, bestaetigen
  2. Stab/Knoten in der Modellansicht anklicken -> Umrechnung wird vorgeschlagen und bestaetigt.

Reines tkinter (keine Zusatzpakete): Orthogonalprojektion, Flaechen nach Tiefe sortiert (Painter-Algorithmus)."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional, Tuple

from .geometry import distance_point_segment
from .ifc import IfcMember
from .ifcaxes import (IdeaFrame, flip_x, flip_y, ifc_to_idea, is_connector, is_continuous, member_segment,
                      rotate90)

PICK_PX = 10
# Ansichten: (Name -> (Gierwinkel, Nickwinkel) in Grad); None = frei
PRESETS = {"3D (drehbar)": None, "Vorne (x–z)": (0.0, 0.0), "Seite (y–z)": (-90.0, 0.0), "Oben (x–y)": (0.0, 90.0)}
BASE = "#7a9cc6"
BASE_CONN = "#3a4a73"
BASE_SEL = "#e6a050"


def _shade(hexcol: str, f: float) -> str:
    r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (min(255, int(r * f)), min(255, int(g * f)), min(255, int(b * f)))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _inside(px: float, py: float, poly: List[Tuple[float, float]]) -> bool:
    ins = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / ((yj - yi) or 1e-12) + xi:
            ins = not ins
        j = i
    return ins


class IfcView(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("IFC-Ansicht (3D) – Bauteil anklicken, Achsen abgleichen")
        self.geometry("1100x780")
        self.items: List[dict] = []
        self.yaw, self.pitch = -38.0, 24.0
        self.scale, self.ox, self.oy = 1.0, 0.0, 0.0
        self.center = (0.0, 0.0, 0.0)
        self._fitted = False
        self._press = None
        self._button = 1
        self._moved = False
        self._drawn: List[Tuple[float, list, object]] = []       # (Tiefe, Polygon, Bauteil), sortiert

        tb = ttk.Frame(self, padding=(6, 4))
        tb.pack(fill="x")
        ttk.Label(tb, text="Ansicht:").pack(side="left")
        self.view_var = tk.StringVar(value=list(PRESETS)[0])
        cb = ttk.Combobox(tb, textvariable=self.view_var, values=list(PRESETS), width=13, state="readonly")
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self._preset())
        ttk.Button(tb, text="Alles anzeigen", command=self.fit).pack(side="left", padx=2)
        self.show_names = tk.BooleanVar(value=True)
        self.show_conn = tk.BooleanVar(value=True)
        self.show_triads = tk.BooleanVar(value=True)
        ttk.Checkbutton(tb, text="Namen", variable=self.show_names, command=self.redraw).pack(side="left", padx=6)
        ttk.Checkbutton(tb, text="Achsenkreuze", variable=self.show_triads, command=self.redraw).pack(side="left")
        ttk.Checkbutton(tb, text="Anschlussteile (Bleche, Winkel …)", variable=self.show_conn,
                        command=self.reload).pack(side="left", padx=6)
        ttk.Label(tb, text="Ziehen = drehen, rechte Maustaste/Umschalt+Ziehen = verschieben, Rad = Zoom",
                  foreground="#666").pack(side="right", padx=6)

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        body.add(left, weight=1)
        self.lb = tk.Listbox(left, exportselection=False, width=34)
        self.lb.pack(fill="both", expand=True)
        self.lb.bind("<<ListboxSelect>>", self._on_list)
        self.cv = tk.Canvas(body, background="white", highlightthickness=0)
        body.add(self.cv, weight=5)

        # Achsen abgleichen
        af = ttk.LabelFrame(self, text="Lokale IDEA-Achsen des gewählten Bauteils (mit IDEA vergleichen, ggf. anpassen)",
                            padding=6)
        af.pack(fill="x", padx=8, pady=(4, 0))
        self.frame_var = tk.StringVar(value="Kein Bauteil gewählt.")
        ttk.Label(af, textvariable=self.frame_var, font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=6,
                                                                                         sticky="w")
        self.state_var = tk.StringVar(value="")
        ttk.Label(af, textvariable=self.state_var, foreground="#b35c00").grid(row=1, column=0, columnspan=6, sticky="w")
        for i, (txt, cmd) in enumerate((("x umkehren", self.do_flip_x), ("y umkehren (z folgt)", self.do_flip_y),
                                        ("Profil 90° drehen", self.do_rot), ("Zurücksetzen", self.do_reset),
                                        ("✓ Bestätigen", self.do_confirm))):
            ttk.Button(af, text=txt, command=cmd).grid(row=2, column=i, padx=3, pady=3, sticky="w")
        self.info = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.info, foreground="#333", wraplength=1060, justify="left").pack(
            fill="x", padx=8, pady=4)

        self.cv.bind("<Configure>", self._configure)
        self.cv.bind("<ButtonPress-1>", lambda e: self._on_press(e, 1))
        self.cv.bind("<ButtonPress-3>", lambda e: self._on_press(e, 3))
        self.cv.bind("<ButtonPress-2>", lambda e: self._on_press(e, 3))
        self.cv.bind("<B1-Motion>", self._on_motion)
        self.cv.bind("<B3-Motion>", self._on_motion)
        self.cv.bind("<B2-Motion>", self._on_motion)
        self.cv.bind("<ButtonRelease-1>", self._on_release)
        self.cv.bind("<ButtonRelease-3>", self._on_release)
        self.cv.bind("<ButtonRelease-2>", self._on_release)
        self.cv.bind("<MouseWheel>", lambda e: self._zoom(e.x, e.y, 1.2 ** (e.delta / 120.0)))
        self.cv.bind("<Button-4>", lambda e: self._zoom(e.x, e.y, 1.2))
        self.cv.bind("<Button-5>", lambda e: self._zoom(e.x, e.y, 1 / 1.2))
        self.reload()

    # --------------------------------------------------------------- Daten
    def reload(self):
        tr = self.app.ifc_tr
        self.items = []
        names: List[str] = []
        for m in self.app.ifc_members:
            if m.npoints < 4 or (is_connector(m) and not self.show_conn.get()):
                continue
            p0, p1, o = member_segment(m, tr)
            faces = [[ifc_to_idea(p, tr) for p in poly] for poly in m.faces]
            self.items.append({"m": m, "p0": p0, "p1": p1, "o": o, "faces": faces})
            names.append(m.name)
        self.lb.delete(0, "end")
        for n in names:
            self.lb.insert("end", n)
        self.fit()

    def _frame(self, m: IfcMember) -> IdeaFrame:
        return self.app.frame_for(m)

    # --------------------------------------------------------- Kamera / Projektion
    def _rot(self, p) -> Tuple[float, float, float]:
        """Weltpunkt -> (Bild x, Bild y [oben], Tiefe [gross = fern]) vor Skalierung."""
        x, y, z = (p[0] - self.center[0], p[1] - self.center[1], p[2] - self.center[2])
        a, e = math.radians(self.yaw), math.radians(self.pitch)
        x1 = x * math.cos(a) - y * math.sin(a)
        y1 = x * math.sin(a) + y * math.cos(a)
        sy = z * math.cos(e) + y1 * math.sin(e)
        depth = y1 * math.cos(e) - z * math.sin(e)
        return x1, sy, depth

    def _vec(self, v) -> Tuple[float, float, float]:
        a, e = math.radians(self.yaw), math.radians(self.pitch)
        x1 = v[0] * math.cos(a) - v[1] * math.sin(a)
        y1 = v[0] * math.sin(a) + v[1] * math.cos(a)
        return x1, v[2] * math.cos(e) + y1 * math.sin(e), y1 * math.cos(e) - v[2] * math.sin(e)

    def _s(self, p) -> Tuple[float, float, float]:
        x, y, d = self._rot(p)
        return self.ox + x * self.scale, self.oy - y * self.scale, d

    def fit(self):
        pts = []
        for it in self.items:
            for poly in it["faces"]:
                pts.extend(poly)
            pts.extend((it["p0"], it["p1"], it["o"]))
        if not pts:
            self.redraw()
            return
        lo = [min(p[i] for p in pts) for i in range(3)]
        hi = [max(p[i] for p in pts) for i in range(3)]
        self.center = tuple((lo[i] + hi[i]) / 2 for i in range(3))     # type: ignore
        r = max(math.sqrt(sum((hi[i] - lo[i]) ** 2 for i in range(3))) / 2, 1e-3)
        W, H = max(self.cv.winfo_width(), 200), max(self.cv.winfo_height(), 200)
        self.scale = max(min(W, H) / (2.3 * r), 1e-3)
        self.ox, self.oy = W / 2, H / 2
        self.redraw()

    def _preset(self):
        v = PRESETS.get(self.view_var.get())
        if v:
            self.yaw, self.pitch = v
        self.fit()

    def _configure(self, event):
        if not self._fitted and event.width > 100:
            self._fitted = True
            self.fit()

    # ------------------------------------------------------------- Zeichnen
    def redraw(self):
        c = self.cv
        c.delete("all")
        sel: Optional[IfcMember] = getattr(self.app, "pending_ifc", None)
        assigned: Dict[str, List[Tuple[int, object]]] = {}
        for i, a in enumerate(self.app.assignments):
            if a.stab is not None or a.is_node:
                assigned.setdefault(a.idea_name, []).append((i, a))
        polys = []
        light = (0.35, -0.55, 0.75)
        for it in self.items:
            m = it["m"]
            is_sel = sel is not None and m is sel
            base = BASE_SEL if is_sel else (BASE_CONN if is_connector(m) else BASE)
            for poly in it["faces"]:
                pts = [self._s(p) for p in poly]
                d = sum(q[2] for q in pts) / len(pts)
                n = _cross((poly[1][0] - poly[0][0], poly[1][1] - poly[0][1], poly[1][2] - poly[0][2]),
                           (poly[2][0] - poly[0][0], poly[2][1] - poly[0][1], poly[2][2] - poly[0][2]))
                ln = math.sqrt(sum(t * t for t in n)) or 1.0
                nv = self._vec((n[0] / ln, n[1] / ln, n[2] / ln))
                lam = abs(nv[0] * light[0] + nv[1] * light[2] + nv[2] * light[1])
                fill = _shade(base, 0.55 + 0.5 * min(1.0, lam))
                polys.append((d, [(q[0], q[1]) for q in pts], m, fill, is_sel))
        polys.sort(key=lambda t: -t[0])               # fern zuerst
        self._drawn = [(d, pts, m) for d, pts, m, _f, _s in polys]
        for d, pts, m, fill, is_sel in polys:
            flat = [v for q in pts for v in q]
            c.create_polygon(*flat, fill=fill, outline="#1d2b44" if not is_sel else "#8a4a00", width=1)
        for it in self.items:
            m = it["m"]
            is_sel = sel is not None and m is sel
            ox, oy, _d = self._s(it["o"])
            if self.show_triads.get() and (not is_connector(m) or is_sel):
                self._triad(ox, oy, self._frame(m), 80 if is_sel else 42, bold=is_sel,
                            confirmed=self.app.is_confirmed(m))
            if self.show_names.get() and not is_connector(m) or is_sel:
                x1, y1, _ = self._s(it["p1"])
                x0, y0, _ = self._s(it["p0"])
                c.create_text((x0 + x1) / 2 + 10, (y0 + y1) / 2, text=m.name, anchor="w",
                              fill="#8a4a00" if is_sel else "#1d2b44",
                              font=("Segoe UI", 9, "bold" if is_sel else "normal"))
            for i, a in assigned.get(m.name, []):
                c.create_oval(ox - 12, oy - 12, ox + 12, oy + 12, outline="#e67e00", width=3)
                c.create_text(ox + 14, oy + 14, anchor="nw", fill="#e67e00", font=("Segoe UI", 9, "bold"),
                              text=(f"#{i + 1}  Kn.{a.node} Last" if a.is_node
                                    else f"#{i + 1}  S{a.stab} {_short(a.station)}"))
        self._update_panel(sel)

    def _triad(self, ox: float, oy: float, fr: IdeaFrame, length: float, bold: bool = False, confirmed: bool = False):
        c = self.cv
        for vec, col, name in ((fr.ex, "#d00000", "x"), (fr.ey, "#008a00", "y"), (fr.ez, "#0033cc", "z")):
            vx, vy, _d = self._vec(vec)
            if math.hypot(vx, vy) < 0.22:                      # Achse zeigt (fast) in/aus der Bildebene
                c.create_oval(ox - 7, oy - 7, ox + 7, oy + 7, outline=col, width=2)
                c.create_text(ox + 12, oy - 12, text=name.upper(), fill=col, font=("Segoe UI", 9, "bold"))
                continue
            c.create_line(ox, oy, ox + vx * length, oy - vy * length, fill=col, width=3 if bold else 2, arrow="last")
            c.create_text(ox + vx * (length + 11), oy - vy * (length + 11), text=name.upper(), fill=col,
                          font=("Segoe UI", 10 if bold else 9, "bold"))
        c.create_oval(ox - 3, oy - 3, ox + 3, oy + 3, fill="#2e8b57" if confirmed else "white", outline="black")

    def _update_panel(self, sel: Optional[IfcMember]):
        if sel is None:
            self.frame_var.set("Kein Bauteil gewählt.")
            self.state_var.set("")
            self.info.set(self.app.pair_status())
            return
        fr = self._frame(sel)
        self.frame_var.set(f"{sel.name}  [{sel.profile}]:   {fr.describe()}")
        conf = self.app.is_confirmed(sel)
        mod = self.app.is_modified(sel)
        side = "durchlaufend" if is_continuous(sel) else "endet am Ursprung"
        self.state_var.set(("✓ bestätigt" if conf else "Vorschlag – noch nicht bestätigt")
                           + (" (von dir angepasst)" if mod else "") + f"   |   {side}")
        notes = " | ".join(fr.notes)
        self.info.set(self.app.pair_status() + (("\nHinweis: " + notes) if notes else ""))

    # --------------------------------------------------------- Achsen anpassen
    def _apply(self, fn):
        m = getattr(self.app, "pending_ifc", None)
        if m is None:
            return
        self.app.set_frame(m, fn(self._frame(m)), confirmed=False)
        self.redraw()

    def do_flip_x(self):
        self._apply(flip_x)

    def do_flip_y(self):
        self._apply(flip_y)

    def do_rot(self):
        self._apply(rotate90)

    def do_reset(self):
        m = getattr(self.app, "pending_ifc", None)
        if m is not None:
            self.app.reset_frame(m)
            self.redraw()

    def do_confirm(self):
        m = getattr(self.app, "pending_ifc", None)
        if m is not None:
            self.app.set_frame(m, self._frame(m), confirmed=True)
            self.redraw()

    # -------------------------------------------------------------- Eingaben
    def _on_press(self, e, button: int):
        self._press = (e.x, e.y)
        self._button = button
        self._moved = False

    def _on_motion(self, e):
        if not self._press:
            return
        dx, dy = e.x - self._press[0], e.y - self._press[1]
        if not self._moved and math.hypot(dx, dy) < 4:
            return
        self._moved = True
        shift = bool(getattr(e, "state", 0) & 0x0001)
        if self._button == 3 or shift:
            self.ox += dx
            self.oy += dy
        else:
            self.yaw += dx * 0.5
            self.pitch = max(-90.0, min(90.0, self.pitch - dy * 0.5))
            self.view_var.set(list(PRESETS)[0])
        self._press = (e.x, e.y)
        self.redraw()

    def _on_release(self, e):
        if self._press and not self._moved and self._button == 1:
            self.click(e.x, e.y)
        self._press = None

    def _zoom(self, mx, my, f):
        new = max(1e-3, min(self.scale * f, 1e6))
        f = new / self.scale
        self.ox = mx - (mx - self.ox) * f
        self.oy = my - (my - self.oy) * f
        self.scale = new
        self.redraw()

    def click(self, sx: float, sy: float):
        hit = None
        for d, pts, m in reversed(self._drawn):              # nah zuerst
            if _inside(sx, sy, pts):
                if is_connector(m) and self.show_conn.get():
                    hit = hit or m                           # Hauptbauteil darunter bevorzugen
                    continue
                hit = m
                break
        if hit is None:
            best, bd = None, PICK_PX + 1.0
            for it in self.items:
                ax, ay, _ = self._s(it["p0"])
                bx, by, _ = self._s(it["p1"])
                dd, _t = distance_point_segment(sx, sy, ax, ay, bx, by)
                if is_connector(it["m"]):
                    dd += 3.0
                if dd < bd:
                    best, bd = it, dd
            if best is not None and bd <= PICK_PX:
                hit = best["m"]
        if hit is not None:
            self.select(hit)

    def _on_list(self, _e=None):
        sel = self.lb.curselection()
        if sel:
            self.select(self.items[sel[0]]["m"])

    def select(self, m: IfcMember):
        self.app.pick_ifc(m)
        self.redraw()


def _short(station: str) -> str:
    if station in ("Anfang", "Ende"):
        return station
    s = station.replace(".", ",")
    if station.endswith("L"):
        return s[:-1] + " (links)"
    if station.endswith("R"):
        return s[:-1] + " (rechts)"
    return s
