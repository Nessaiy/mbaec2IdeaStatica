"""Bildliche Achsenzuordnung: links das IDEA-Bauteil in 3D (andere Bauteile grau) mit seinen lokalen Achsen,
rechts das Achsenkreuz des Baustatik-Stabes. Erst eine Achsenspitze (+ oder -) links anklicken, dann die
passende Achsenspitze rechts: Das Vorzeichen ergibt sich aus der angeklickten Seite. Zwei Paare genuegen."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, List, Optional, Tuple

from .axispair import AxisPairs
from .geometry import member_geometry, point_on_member
from .ifcaxes import flip_x, flip_y, ifc_to_idea, is_connector, member_segment, rotate90

AXCOL = {"x": "#d00000", "y": "#008a00", "z": "#0033cc"}
AXLIGHT = {"x": "#e8a0a0", "y": "#90c890", "z": "#9fb4ee"}
HANDLE_PX = 17
SEL_FILL = "#ffc233"
BASE_SEL = "#e6a050"
GRAY_FILL, GRAY_LINE = "#dcdcdc", "#b4b4b4"


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _shade(hexcol: str, f: float) -> str:
    r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (min(255, int(r * f)), min(255, int(g * f)), min(255, int(b * f)))


class View3D:
    """Kleine 3D-Zeichenflaeche (Orthogonalprojektion, drehbar). Welt: x rechts, y in die Tiefe, z oben."""

    def __init__(self, parent, on_handle: Callable[[str], None], draw: Callable[["View3D"], None]):
        self.cv = tk.Canvas(parent, background="white", highlightthickness=1, highlightbackground="#aaaaaa",
                            width=520, height=440)
        self.yaw, self.pitch = -38.0, 24.0
        self.scale, self.ox, self.oy = 1.0, 0.0, 0.0
        self.center = (0.0, 0.0, 0.0)
        self.on_handle, self.draw = on_handle, draw
        self.handles: List[Tuple[float, float, str]] = []
        self._fit_pts: list = []
        self._fit_k = 4.2
        self._press = None
        self._button = 1
        self._moved = False
        cv = self.cv
        cv.bind("<Configure>", lambda e: self.fit())
        cv.bind("<ButtonPress-1>", lambda e: self._on_press(e, 1))
        cv.bind("<ButtonPress-3>", lambda e: self._on_press(e, 3))
        cv.bind("<ButtonPress-2>", lambda e: self._on_press(e, 3))
        for b in ("<B1-Motion>", "<B3-Motion>", "<B2-Motion>"):
            cv.bind(b, self._on_motion)
        for b in ("<ButtonRelease-1>", "<ButtonRelease-3>", "<ButtonRelease-2>"):
            cv.bind(b, self._on_release)
        cv.bind("<MouseWheel>", lambda e: self._zoom(e.x, e.y, 1.2 ** (e.delta / 120.0)))
        cv.bind("<Button-4>", lambda e: self._zoom(e.x, e.y, 1.2))
        cv.bind("<Button-5>", lambda e: self._zoom(e.x, e.y, 1 / 1.2))

    # --- Kamera
    def rot(self, p):
        x, y, z = (p[0] - self.center[0], p[1] - self.center[1], p[2] - self.center[2])
        return self._vec((x, y, z))

    def _vec(self, v):
        a, e = math.radians(self.yaw), math.radians(self.pitch)
        x1 = v[0] * math.cos(a) - v[1] * math.sin(a)
        y1 = v[0] * math.sin(a) + v[1] * math.cos(a)
        return x1, v[2] * math.cos(e) + y1 * math.sin(e), y1 * math.cos(e) - v[2] * math.sin(e)

    def s(self, p):
        x, y, d = self.rot(p)
        return self.ox + x * self.scale, self.oy - y * self.scale, d

    def set_fit(self, pts, k: float = 4.2):
        self._fit_pts, self._fit_k = list(pts), k
        self.fit()

    def fit(self):
        pts = self._fit_pts
        if not pts:
            self.redraw()
            return
        lo = [min(p[i] for p in pts) for i in range(3)]
        hi = [max(p[i] for p in pts) for i in range(3)]
        self.center = tuple((lo[i] + hi[i]) / 2 for i in range(3))      # type: ignore
        r = max(math.sqrt(sum((hi[i] - lo[i]) ** 2 for i in range(3))) / 2, 1e-3)
        W, H = max(self.cv.winfo_width(), 200), max(self.cv.winfo_height(), 200)
        self.scale = max(min(W, H) / (self._fit_k * r), 1e-3)
        self.ox, self.oy = W / 2, H / 2
        self.redraw()

    def arm_px(self) -> float:
        return 0.2 * min(max(self.cv.winfo_width(), 200), max(self.cv.winfo_height(), 200))

    # --- Zeichnen
    def redraw(self):
        self.cv.delete("all")
        self.handles = []
        self.draw(self)

    def triad(self, origin, vecs, labels: Dict[str, Tuple[str, str]], names: str, selected: Optional[str],
              prefix_upper: bool):
        """Achsenkreuz mit beiden Richtungen (+ ausgezogen/dick mit Pfeil, - gestrichelt/duenn); die Spitzen
        sind anklickbar. labels: Spitze ('+x') -> (Text, Farbe) fuer bereits zugeordnete Spitzen."""
        c = self.cv
        ox, oy, _ = self.s(origin)
        L = self.arm_px()
        for i, a in enumerate("xyz"):
            v = vecs[i]
            vx, vy, _d = self._vec(v)
            ln = math.hypot(vx, vy)
            if ln < 0.3:                                   # Achse zeigt (fast) in/aus der Bildebene: sichtbar versetzen
                if ln > 1e-6:
                    vx, vy = vx / ln * 0.3, vy / ln * 0.3
                else:
                    vx, vy = (0.3, -0.12) if i == 0 else ((-0.12, 0.3) if i == 1 else (0.12, 0.3))
            for sg in (1, -1):
                spec = ("+" if sg > 0 else "-") + a
                ex, ey = ox + sg * vx * L, oy - sg * vy * L
                if sg > 0:
                    c.create_line(ox, oy, ex, ey, fill=AXCOL[a], width=5, arrow="last", arrowshape=(14, 16, 6))
                else:
                    c.create_line(ox, oy, ex, ey, fill=AXLIGHT[a], width=3, dash=(6, 4))
                sel = selected == spec
                r = 11
                c.create_oval(ex - r, ey - r, ex + r, ey + r, fill=SEL_FILL if sel else "white",
                              outline="#e67e00" if sel else AXCOL[a], width=3 if sel else 2)
                txt = ("+" if sg > 0 else "−") + (a.upper() if prefix_upper else a)
                c.create_text(ex, ey, text=txt, fill=AXCOL[a], font=("Segoe UI", 9, "bold"))
                self.handles.append((ex, ey, spec))
                if spec in labels:
                    t, col = labels[spec]
                    c.create_text(ex + (r + 4) * (1 if ex >= ox else -1), ey + 16, text=t, fill=col,
                                  anchor="w" if ex >= ox else "e", font=("Segoe UI", 9, "bold"))
        c.create_oval(ox - 4, oy - 4, ox + 4, oy + 4, fill="black")

    # --- Eingaben
    def _on_press(self, e, button):
        self._press, self._button, self._moved = (e.x, e.y), button, False

    def _on_motion(self, e):
        if not self._press:
            return
        dx, dy = e.x - self._press[0], e.y - self._press[1]
        if not self._moved and math.hypot(dx, dy) < 4:
            return
        self._moved = True
        if self._button == 3 or (getattr(e, "state", 0) & 1):
            self.ox += dx
            self.oy += dy
        else:
            self.yaw += dx * 0.5
            self.pitch = max(-90.0, min(90.0, self.pitch - dy * 0.5))
        self._press = (e.x, e.y)
        self.redraw()

    def _on_release(self, e):
        if self._press and not self._moved and self._button == 1:
            best, bd = None, HANDLE_PX + 1.0
            for hx, hy, spec in self.handles:
                d = math.hypot(hx - e.x, hy - e.y)
                if d < bd:
                    best, bd = spec, d
            if best is not None:
                self.on_handle(best)
        self._press = None

    def _zoom(self, mx, my, f):
        new = max(1e-3, min(self.scale * f, 1e6))
        f = new / self.scale
        self.ox = mx - (mx - self.ox) * f
        self.oy = my - (my - self.oy) * f
        self.scale = new
        self.redraw()


class AxisPickDialog(tk.Toplevel):
    """Ergebnis: self.result = {'x': '+z', 'y': '-x', 'z': '+y'} (Baustatik-Achse -> IDEA-Achse, lokal) oder None."""

    def __init__(self, app, m, stab: Optional[int], station: str, initial: Optional[Dict[str, str]] = None):
        super().__init__(app)
        self.app, self.m, self.stab, self.station = app, m, stab, station
        self.result: Optional[Dict[str, str]] = None
        self.initial = dict(initial) if initial else None
        self.pairs = AxisPairs(self.initial)
        self.sel_idea: Optional[str] = None
        self.sel_bs: Optional[str] = None
        what = f"Stab {stab}" if stab is not None else f"Knotenlast Kn. {station}"
        self.title(f"Koordinaten zuweisen: {m.name} (IDEA)  ←  {what} (Baustatik)")
        self.transient(app)
        self.fr = app.frame_for(m)
        self._prepare()

        top = ttk.Frame(self, padding=(10, 8, 10, 0))
        top.pack(fill="x")
        ttk.Label(top, text="So geht's:  1. Eine Achsenspitze am IDEA-Bauteil anklicken (links) – + oder − je nachdem, "
                            "welche Seite.   2. Die gleiche Richtung im Baustatik-Bild anklicken (rechts).   "
                            "Zwei Paare genügen, die dritte Achse ergibt sich.",
                  wraplength=1040, justify="left", foreground="#333").pack(anchor="w")

        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        lf = ttk.LabelFrame(body, text=f"IDEA: {m.name} [{m.profile}] – lokale Achsen X Y Z", padding=4)
        lf.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        rf = ttk.LabelFrame(body, text=("Baustatik: " + (f"Stab {stab} (Knoten {self.n_from} → {self.n_to})" if stab is not None
                                                          else f"Knotenlast Kn. {station} (x rechts, z nach unten)")
                                        + " – lokale Achsen x y z"), padding=4)
        rf.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.vi = View3D(lf, self._click_idea, self._draw_idea)
        self.vi.cv.pack(fill="both", expand=True)
        fb = ttk.Frame(lf)
        fb.pack(fill="x", pady=(4, 0))
        ttk.Label(fb, text="Stimmen X Y Z mit IDEA überein? Wenn nicht:", foreground="#b35c00").pack(side="left")
        for txt, fn in (("X umkehren", flip_x), ("Y und Z umkehren", flip_y), ("Profil 90° drehen", rotate90)):
            ttk.Button(fb, text=txt, command=lambda f=fn: self._fix_frame(f)).pack(side="left", padx=3)
        self.vb = View3D(rf, self._click_bs, self._draw_bs)
        self.vb.cv.pack(fill="both", expand=True)
        self.vi.set_fit(self._pts_idea, 4.6)
        self.vb.set_fit(self._pts_bs, 3.4)

        self.prompt = tk.StringVar()
        ttk.Label(self, textvariable=self.prompt, font=("Segoe UI", 10, "bold"), foreground="#b35c00",
                  padding=(10, 0)).pack(anchor="w")
        self.rows = [tk.StringVar() for _ in range(3)]
        pf = ttk.LabelFrame(self, text="Zuordnung Baustatik → IDEA (lokal)", padding=6)
        pf.pack(fill="x", padx=10, pady=6)
        for i, v in enumerate(self.rows):
            ttk.Label(pf, textvariable=v, font=("Consolas", 10)).grid(row=0, column=i, padx=16, sticky="w")
        self.note = tk.StringVar()
        ttk.Label(pf, textvariable=self.note, foreground="#b00020", wraplength=1000).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        bf = ttk.Frame(self, padding=(10, 0, 10, 10))
        bf.pack(fill="x")
        self.ok_btn = ttk.Button(bf, text="Übernehmen", command=self._ok)
        self.ok_btn.pack(side="left", padx=4)
        ttk.Button(bf, text="Zurücksetzen", command=self._reset).pack(side="left", padx=4)
        self.sug_btn = ttk.Button(bf, text="Vorschlag", command=self._suggest)
        self.sug_btn.pack(side="left", padx=4)
        ttk.Button(bf, text="Rechte Ansicht wie links", command=self._sync_view).pack(side="left", padx=4)
        ttk.Button(bf, text="Abbrechen", command=self.destroy).pack(side="left", padx=4)
        ttk.Label(bf, text="Ziehen = drehen, rechte Maustaste = verschieben, Rad = Zoom", foreground="#666").pack(side="right")
        if not self.initial:
            self.sug_btn.state(["disabled"])
        self._refresh()
        self.update_idletasks()
        self.geometry("1100x700")
        self.grab_set()
        self.wait_window(self)

    # ------------------------------------------------------------------ Daten
    def _prepare(self):
        app, tr = self.app, self.app.ifc_tr
        self.items = []                                         # (IfcMember, [Flaechen in IDEA-Global])
        for mm in app.ifc_members:
            if mm.npoints < 4:
                continue
            self.items.append((mm, [[ifc_to_idea(p, tr) for p in poly] for poly in mm.faces]))
        p0, p1, o = member_segment(self.m, tr)
        self.origin = o
        pts = [p for mm, faces in self.items if mm is self.m for poly in faces for p in poly] or [p0, p1]
        self._pts_idea = pts + [o]
        # Baustatik-Seite: Welt (x rechts, Tiefe, oben) aus 2D (x, z oben)
        res = app.result
        self.n_from = self.n_to = None
        geo = member_geometry(res)
        self.bs_lines: List[Tuple[Tuple[float, float, float], Tuple[float, float, float], int]] = []
        for n, (a, b, L, ex) in geo.items():
            self.bs_lines.append(((a[0], 0.0, a[1]), (b[0], 0.0, b[1]), n))
        self.bs_nodes = {k: (v[0], 0.0, v[1]) for k, v in res.nodes.items()}
        if self.stab is not None and self.stab in geo:
            a, b, L, ex = geo[self.stab]
            mi = res.members[self.stab]
            self.n_from, self.n_to = mi.node_start, mi.node_end
            if self.station in ("Anfang", "Ende"):
                s = 0.0 if self.station == "Anfang" else L
            else:
                try:
                    s = float(self.station.replace("L", "").replace("R", "").split("=")[-1])
                except ValueError:
                    s = 0.0
            q = point_on_member(res, self.stab, s) or a
            self.bs_origin = (q[0], 0.0, q[1])
            self.bs_ex2 = ex
            hi = [(a[0], 0.0, a[1]), (b[0], 0.0, b[1])]
            self._pts_bs = hi + [self.bs_origin]
        else:                                                    # Knotenlast: globale Richtungen
            node = int(self.station) if str(self.station).isdigit() else None
            q = res.nodes.get(node, (0.0, 0.0)) if node is not None else (0.0, 0.0)
            self.bs_origin = (q[0], 0.0, q[1])
            self.bs_ex2 = (1.0, 0.0)
            sz = 1.5
            self._pts_bs = [(q[0] - sz, 0.0, q[1] - sz), (q[0] + sz, 0.0, q[1] + sz)]
        ux, uz = self.bs_ex2
        # lokale Baustatik-Achsen in Welt (x rechts, Tiefe, oben): x = Stabrichtung, z = x um 90 Grad im Uhrzeigersinn,
        # y = aus dem Bild heraus zum Betrachter (= negative Tiefe)
        self.bs_vecs = ((ux, 0.0, uz), (0.0, -1.0, 0.0), (uz, 0.0, -ux))

    # ------------------------------------------------------------------ Zeichnen
    def _draw_idea(self, v: View3D):
        c = v.cv
        polys = []
        light = (0.35, -0.55, 0.75)
        for mm, faces in self.items:
            sel = mm is self.m
            if is_connector(mm) and not sel:
                continue
            for poly in faces:
                pts = [v.s(p) for p in poly]
                d = sum(q[2] for q in pts) / len(pts)
                if sel:
                    n = _cross(tuple(poly[1][i] - poly[0][i] for i in range(3)),
                               tuple(poly[2][i] - poly[0][i] for i in range(3)))
                    ln = math.sqrt(sum(t * t for t in n)) or 1.0
                    nv = v._vec((n[0] / ln, n[1] / ln, n[2] / ln))
                    lam = abs(nv[0] * light[0] + nv[1] * light[2] + nv[2] * light[1])
                    fill, line = _shade(BASE_SEL, 0.55 + 0.5 * min(1.0, lam)), "#8a4a00"
                else:
                    fill, line = GRAY_FILL, GRAY_LINE
                polys.append((d, [(q[0], q[1]) for q in pts], fill, line))
        polys.sort(key=lambda t: -t[0])
        for d, pts, fill, line in polys:
            c.create_polygon(*[t for q in pts for t in q], fill=fill, outline=line, width=1)
        marks = {spec: (f"= Bst. {b}", "#2e7d32") for spec, b in self.pairs.idea_marks().items()}
        v.triad(self.origin, (self.fr.ex, self.fr.ey, self.fr.ez), marks, "XYZ", self.sel_idea, True)
        c.create_text(8, 8, anchor="nw", text=f"IDEA lokal:  {self.fr.describe()}", fill="#444", font=("Segoe UI", 9))
        c.create_text(8, 26, anchor="nw", text="(" + ("✓ bestätigt" if self.app.is_confirmed(self.m)
                                                        else "aus IFC vorgeschlagen, nicht bestätigt") + ")",
                      fill="#888", font=("Segoe UI", 9))

    def _draw_bs(self, v: View3D):
        c = v.cv
        for a, b, n in self.bs_lines:
            this = n == self.stab
            (x0, y0, _), (x1, y1, _) = v.s(a), v.s(b)
            c.create_line(x0, y0, x1, y1, fill="#8d9db3" if this else "#c8c8c8", width=10 if this else 4,
                          capstyle="round")
            if this:
                dx, dy = x1 - x0, y1 - y0
                ln = math.hypot(dx, dy)
                if ln > 40:
                    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
                    c.create_text(mx + 14, my - 10, text=f"Stab {n}", fill="#4a5a73", font=("Segoe UI", 10, "bold"))
        for k, p in self.bs_nodes.items():
            x, y, _ = v.s(p)
            hot = k in (self.n_from, self.n_to)
            c.create_oval(x - 3, y - 3, x + 3, y + 3, fill="black" if hot else "#999", outline="")
            c.create_text(x - 6, y + 8, text=str(k), fill="black" if hot else "#999", anchor="ne",
                          font=("Segoe UI", 9, "bold" if hot else "normal"))
        marks = {spec: (f"= IDEA {i.replace('-', '−').upper()}", "#2e7d32") for spec, i in self.pairs.bs_marks().items()}
        v.triad(self.bs_origin, self.bs_vecs, marks, "xyz", self.sel_bs, False)
        c.create_text(8, 8, anchor="nw", fill="#444", font=("Segoe UI", 9),
                      text="x = Stabrichtung,  z = x um 90° im Uhrzeigersinn gedreht,  y = aus dem Bild heraus (zum Betrachter)")
        c.create_text(8, 26, anchor="nw", fill="#888", font=("Segoe UI", 9),
                      text="(Bei Stab nach rechts zeigt z nach unten, bei Stab nach oben nach rechts.)")

    # ------------------------------------------------------------------ Bedienung
    def _click_idea(self, spec: str):
        self.sel_idea = None if self.sel_idea == spec else spec
        self._after_select()

    def _click_bs(self, spec: str):
        self.sel_bs = None if self.sel_bs == spec else spec
        self._after_select()

    def _after_select(self):
        if self.sel_idea and self.sel_bs:
            self.pairs.connect(self.sel_idea, self.sel_bs)
            self.sel_idea = self.sel_bs = None
        self._refresh()

    def _fix_frame(self, fn):
        """IDEA-Achsen des Bauteils korrigieren (Vergleich mit der Anzeige in IDEA); bisherige Klicks werden verworfen."""
        self.fr = fn(self.fr)
        self.app.set_frame(self.m, self.fr, confirmed=False)
        self.pairs.clear()
        self.sel_idea = self.sel_bs = None
        self._refresh()

    def _reset(self):
        self.pairs.clear()
        self.sel_idea = self.sel_bs = None
        self._refresh()

    def _suggest(self):
        if self.initial:
            self.pairs.set_all(self.initial, suggested=True)
            self.sel_idea = self.sel_bs = None
            self._refresh()

    def _sync_view(self):
        self.vb.yaw, self.vb.pitch = self.vi.yaw, self.vi.pitch
        self.vb.redraw()

    def _refresh(self):
        for v, (a, i, src) in zip(self.rows, self.pairs.lines()):
            v.set(f"Baustatik {a}  =  IDEA {i}" + (f"   ({src})" if src else ""))
        if self.sel_idea:
            self.prompt.set(f"IDEA-Achse {self.sel_idea.replace('-', '−').upper()} gewählt – jetzt die passende Achsenspitze im "
                            "Baustatik-Bild (rechts) anklicken.")
        elif self.sel_bs:
            self.prompt.set(f"Baustatik-Achse {self.sel_bs.replace('-', '−')} gewählt – jetzt die passende Achsenspitze am "
                            "IDEA-Bauteil (links) anklicken.")
        elif self.pairs.complete():
            self.prompt.set("Fertig. Mit 'Übernehmen' bestätigen – oder weitere Paare anklicken, um etwas zu ändern.")
        else:
            self.prompt.set("Beginne mit einer Achsenspitze am IDEA-Bauteil (links).")
        self.note.set("Achtung: Diese Zuordnung spiegelt das Koordinatensystem (Linkssystem) – bitte prüfen."
                      if self.pairs.is_mirror() else "")
        self.ok_btn.state(["!disabled"] if self.pairs.complete() else ["disabled"])
        self.vi.redraw()
        self.vb.redraw()

    def _ok(self):
        if not self.pairs.complete():
            return
        self.result = self.pairs.axes()
        self.app.set_frame(self.m, self.fr, confirmed=True)       # Achsen wurden mit IDEA verglichen
        self.destroy()
