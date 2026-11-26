"""Modellansicht: Stabwerk aus dem PDF zeichnen, Knoten oder Stab anklicken."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import messagebox, ttk
from typing import List, Optional, Tuple

from .export import station_options
from .geometry import (distance_point_segment, local_axes, member_geometry, members_through_node, node_members,
                       point_on_member, station_distance, station_key_from_distance)
from .model import ParseResult

NODE_PICK_PX = 10
MEMBER_PICK_PX = 8


def node_station_keys(result: ParseResult, stab: int, s: float, length: float, tol: float = 0.015) -> List[Tuple[str, str]]:
    """Stellen-Schluessel (+ Text) fuer die Position s auf einem durchlaufenden Stab.

    Gibt es im PDF an dieser Stelle eine Ausgabe (ggf. Sprung links/rechts), wird sie verwendet;
    sonst wird eine eigene Stelle gebildet (Werte werden dann zwischen den PDF-Stellen interpoliert)."""
    opts = []
    for key, text in station_options(result, stab):
        d = station_distance(key, length)
        if d is not None and abs(d - s) <= tol:
            opts.append((key, f"Stelle im PDF vorhanden: {text}"))
    if opts:
        return opts
    return [(f"x={s:.2f}", f"x = {s:.2f} m (im PDF nicht ausgegeben, Werte werden interpoliert)".replace(".", ",", 1))]


def side_of_station(key: str) -> int:
    """Seite, von der die Schnittgroessen uebernommen werden: +1 = Stabkoerper in Stabrichtung hinter der Stelle
    (Stabanfang bzw. rechts vom Sprung), -1 = davor (Stabende bzw. links vom Sprung), 0 = Stelle ohne Sprung."""
    if key == "Anfang" or key.endswith("R"):
        return 1
    if key == "Ende" or key.endswith("L"):
        return -1
    return 0


def station_short(key: str) -> str:
    if key in ("Anfang", "Ende"):
        return key
    k = key.replace("x=", "x=").replace(".", ",")
    if key.endswith("L"):
        return k[:-1] + " (links)"
    if key.endswith("R"):
        return k[:-1] + " (rechts)"
    return k


class NodeDialog(tk.Toplevel):
    """Welche Staebe (bzw. Stabenden) am Knoten sollen zugewiesen werden?"""

    def __init__(self, master, result: ParseResult, node: int, single: bool = False):
        super().__init__(master)
        self.title(f"Knoten {node}")
        self.transient(master)
        self.selected: List[Tuple[int, str]] = []
        self.node_load = False
        self._items: List[Tuple[int, str]] = []          # (Stab, Stellen-Schluessel)
        texts: List[str] = []
        for stab, side in node_members(result, node):
            m = result.members[stab]
            other = m.node_end if side == "Anfang" else m.node_start
            what = "Stabanfang" if side == "Anfang" else "Stabende"
            l = f", l = {m.length:g} m" if m.length is not None else ""
            self._items.append((stab, side))
            texts.append(f"Stab {stab}  –  Knoten {node} ist das {what} ({side})  "
                         f"–  Gegenknoten {other}{l}  {m.description}")
        for stab, s in members_through_node(result, node):
            m = result.members[stab]
            L = member_geometry(result)[stab][2]
            for key, text in node_station_keys(result, stab, s, L):
                self._items.append((stab, key))
                texts.append(f"Stab {stab}  –  läuft durch Knoten {node} (Stab {m.node_start}→{m.node_end}, "
                             f"Knoten liegt bei x = {s:.2f} m von {L:.2f} m)  –  {text}")
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=f"Knoten {node}: Welche Stäbe sollen zugewiesen werden?\n"
                            "(Mehrfachauswahl möglich; je Stab wird gefragt, welches IDEA-Bauteil.)"
                  ).pack(anchor="w")
        self.lb = tk.Listbox(frm, selectmode="browse" if single else "extended", width=120, height=max(4, min(12, len(texts))),
                             exportselection=False)
        self.lb.pack(fill="both", expand=True, pady=6)
        for t in texts:
            self.lb.insert("end", t)
        if len(self._items) == 1:
            self.lb.select_set(0)
        loads = [l for l in result.node_loads if l.node == node]
        if loads:
            ttk.Label(frm, text="Knotenlasten am Knoten (charakteristisch, aus den Einwirkungen): "
                      + ";  ".join(f"{l.einw}: Fx={l.fx:g}, Fz={l.fz:g}, M={l.m:g}" for l in loads),
                      wraplength=900, foreground="#444").pack(anchor="w")
        bf = ttk.Frame(frm)
        bf.pack(anchor="e", pady=(4, 0))
        if loads:
            ttk.Button(bf, text="Knotenlast je Kombination (z. B. Kran) …", command=self._node_load).pack(
                side="left", padx=4)
        ttk.Button(bf, text="Weiter", command=self._ok).pack(side="left", padx=4)
        ttk.Button(bf, text="Abbrechen", command=self.destroy).pack(side="left")
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.wait_window(self)

    def _ok(self):
        self.selected = [self._items[i] for i in self.lb.curselection()]
        self.destroy()

    def _node_load(self):
        self.node_load = True
        self.destroy()


class DistanceDialog(tk.Toplevel):
    """Strecke vom Stabanfang-Knoten in Stabrichtung."""

    def __init__(self, master, stab: int, node_a: int, node_b: int, length: float, suggestion: float):
        super().__init__(master)
        self.title(f"Stab {stab}")
        self.transient(master)
        self.resizable(False, False)
        self.length = length
        self.result: Optional[float] = None
        frm = ttk.Frame(self, padding=12)
        frm.pack()
        ttk.Label(frm, text=f"Stab {stab}: Knoten {node_a} → Knoten {node_b},  Stablänge {length:.2f} m").pack(anchor="w")
        ttk.Label(frm, text=f"Strecke vom Knoten {node_a} in Stabrichtung [m]:").pack(anchor="w", pady=(8, 2))
        self.var = tk.StringVar(value=f"{suggestion:.2f}".replace(".", ","))
        e = ttk.Entry(frm, textvariable=self.var, width=12)
        e.pack(anchor="w")
        e.focus_set()
        bf = ttk.Frame(frm)
        bf.pack(anchor="e", pady=(10, 0))
        ttk.Button(bf, text="OK", command=self._ok).pack(side="left", padx=4)
        ttk.Button(bf, text="Abbrechen", command=self.destroy).pack(side="left")
        self.bind("<Return>", lambda ev: self._ok())
        self.bind("<Escape>", lambda ev: self.destroy())
        self.grab_set()
        self.wait_window(self)

    def _ok(self):
        try:
            s = float(self.var.get().strip().replace(",", "."))
        except ValueError:
            messagebox.showwarning("Eingabe", "Bitte eine Zahl eingeben.", parent=self)
            return
        if not -0.005 <= s <= self.length + 0.005:
            messagebox.showwarning("Eingabe", f"Die Strecke muss zwischen 0 und {self.length:.2f} m liegen.", parent=self)
            return
        self.result = max(0.0, min(self.length, s))
        self.destroy()


class ModelView(tk.Toplevel):
    def __init__(self, app, result: ParseResult):
        super().__init__(app)
        self.app = app
        self.res = result
        self.geom = member_geometry(result)
        self.title("Modellansicht – Knoten oder Stab anklicken")
        self.geometry("1050x720")
        self.scale, self.ox, self.oy = 1.0, 0.0, 0.0
        self._fitted = False
        self._press = None
        self._moved = False
        self.marker: Optional[Tuple[float, float, Tuple[float, float]]] = None   # (Klickpunkt x, z, ex)

        tb = ttk.Frame(self, padding=(6, 4))
        tb.pack(fill="x")
        ttk.Button(tb, text="Alles anzeigen", command=self.fit).pack(side="left", padx=2)
        self.show_nodes = tk.BooleanVar(value=True)
        self.show_members = tk.BooleanVar(value=True)
        ttk.Checkbutton(tb, text="Knotennummern", variable=self.show_nodes, command=self.redraw).pack(side="left", padx=8)
        ttk.Checkbutton(tb, text="Stabnummern", variable=self.show_members, command=self.redraw).pack(side="left")
        self.show_axes = tk.BooleanVar(value=True)
        ttk.Checkbutton(tb, text="Stabachsen x y z", variable=self.show_axes, command=self.redraw).pack(side="left", padx=8)
        ttk.Label(tb, text="   Knoten Nr.:").pack(side="left")
        self.node_var = tk.StringVar()
        ne = ttk.Entry(tb, textvariable=self.node_var, width=6)
        ne.pack(side="left", padx=2)
        ne.bind("<Return>", lambda e: self.pick_node_by_number())
        ttk.Button(tb, text="Wählen", command=self.pick_node_by_number).pack(side="left")
        ttk.Label(tb, text="   Mausrad = Zoom, Ziehen = Verschieben, Klick = auswählen", foreground="#666").pack(side="left", padx=10)

        self.cv = tk.Canvas(self, background="white", highlightthickness=0)
        self.cv.pack(fill="both", expand=True)
        self.legend = tk.StringVar(value="Achsen je Stab (Baustatik, Farben wie in der IFC-Ansicht):  x (rot) = Stabrichtung, von Knoten 'von' nach 'bis'.  "
                                         "z (blau) = x um 90° im Uhrzeigersinn gedreht (bei Stab nach rechts: nach unten).  "
                                         "y (grün, Kreis mit Punkt) = aus dem Bild heraus, zum Betrachter.")
        ttk.Label(self, textvariable=self.legend, foreground="#444", wraplength=1000).pack(fill="x", padx=8, pady=4)
        self.status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status_var, foreground="#b35c00", wraplength=1000).pack(fill="x", padx=8)

        self.cv.bind("<Configure>", self._configure)
        self.cv.bind("<ButtonPress-1>", self._on_press)
        self.cv.bind("<B1-Motion>", self._on_motion)
        self.cv.bind("<ButtonRelease-1>", self._on_release)
        self.cv.bind("<MouseWheel>", self._on_wheel)
        self.cv.bind("<Button-4>", lambda e: self._zoom(e.x, e.y, 1.2))
        self.cv.bind("<Button-5>", lambda e: self._zoom(e.x, e.y, 1 / 1.2))

    # ------------------------------------------------------- Transformation
    def _s(self, x: float, z: float) -> Tuple[float, float]:
        return self.ox + x * self.scale, self.oy - z * self.scale

    def _w(self, sx: float, sy: float) -> Tuple[float, float]:
        return (sx - self.ox) / self.scale, (self.oy - sy) / self.scale

    def fit(self):
        pts = list(self.res.nodes.values())
        if not pts:
            return
        W, H = max(self.cv.winfo_width(), 200), max(self.cv.winfo_height(), 200)
        minx, maxx = min(p[0] for p in pts), max(p[0] for p in pts)
        minz, maxz = min(p[1] for p in pts), max(p[1] for p in pts)
        dx, dz = max(maxx - minx, 1e-6), max(maxz - minz, 1e-6)
        self.scale = max(min((W - 80) / dx, (H - 80) / dz), 1e-3)
        self.ox = 40 - minx * self.scale + ((W - 80) - dx * self.scale) / 2
        self.oy = (H - 40 - ((H - 80) - dz * self.scale) / 2) + minz * self.scale
        self.redraw()

    def _configure(self, event):
        if not self._fitted and event.width > 100:
            self._fitted = True
            self.fit()

    # ------------------------------------------------------------ Zeichnen
    def _triad(self, ox: float, oy: float, ex) -> None:
        """Lokale Stabachsen der Baustatik: x = Stabrichtung, z = x um 90 Grad im Uhrzeigersinn gedreht (bei Stab nach rechts
        nach unten), y = aus der Bildebene heraus (zum Betrachter, Kreis mit Punkt). Farben wie in der IFC-Ansicht."""
        c = self.cv
        ux, uy = ex[0], -ex[1]                      # x im Bild
        zx, zy = -uy, ux                            # z im Bild (90 Grad im Uhrzeigersinn)
        L = 30
        for (dx, dy), col, name in (((ux, uy), "#d00000", "x"), ((zx, zy), "#0033cc", "z")):
            c.create_line(ox, oy, ox + dx * L, oy + dy * L, fill=col, width=3, arrow="last", arrowshape=(9, 11, 4))
            c.create_text(ox + dx * (L + 9), oy + dy * (L + 9), text=name, fill=col, font=("Segoe UI", 10, "bold"))
        c.create_oval(ox - 6, oy - 6, ox + 6, oy + 6, outline="#008a00", width=2, fill="white")
        c.create_oval(ox - 2, oy - 2, ox + 2, oy + 2, fill="#008a00", outline="#008a00")
        c.create_text(ox - ux * 12 - zx * 12, oy - uy * 12 - zy * 12, text="y", fill="#008a00", font=("Segoe UI", 10, "bold"))

    def redraw(self):
        c = self.cv
        c.delete("all")
        if getattr(self.app, "ifc_members", None):
            self.status_var.set(self.app.pair_status())
        for n, (a, b, L, ex) in self.geom.items():
            x1, y1 = self._s(*a)
            x2, y2 = self._s(*b)
            c.create_line(x1, y1, x2, y2, fill="#1f4e9c", width=2)
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            if math.hypot(x2 - x1, y2 - y1) > 18:     # Richtungspfeil
                ux, uy = ex[0], -ex[1]
                c.create_line(mx - ux * 7, my - uy * 7, mx + ux * 7, my + uy * 7, fill="#1f4e9c", width=2,
                              arrow="last", arrowshape=(10, 12, 4))
            if self.show_members.get():
                c.create_text(mx + ex[1] * 12, my + ex[0] * 12, text=f"S{n}", fill="#2a7fff", font=("Segoe UI", 8))
            if self.show_axes.get() and math.hypot(x2 - x1, y2 - y1) > 70:
                self._triad(x1 + (x2 - x1) * 0.27, y1 + (y2 - y1) * 0.27, ex)
        for n, (x, z) in self.res.nodes.items():
            sx, sy = self._s(x, z)
            c.create_oval(sx - 3, sy - 3, sx + 3, sy + 3, fill="black", outline="black")
            if self.show_nodes.get():
                c.create_text(sx + 7, sy - 8, text=str(n), fill="#222", font=("Segoe UI", 8, "bold"))
        # bereits zugewiesene Stellen: orange Kreis + Strich auf der Seite, von der die Schnittgroessen stammen
        for i, a in enumerate(self.app.assignments):
            if a.is_node and a.node in self.res.nodes:
                sx, sy = self._s(*self.res.nodes[a.node])
                c.create_oval(sx - 9, sy - 9, sx + 9, sy + 9, outline="#e67e00", width=3)
                c.create_text(sx + 12, sy + 10, text=f"#{i + 1}  Kn.{a.node} Last", fill="#e67e00",
                              font=("Segoe UI", 9, "bold"), anchor="nw")
                continue
            if a.stab is None:
                continue
            g = self.geom.get(a.stab)
            if not g:
                continue
            s = station_distance(a.station, g[2])
            p = point_on_member(self.res, a.stab, s) if s is not None else None
            if not p:
                continue
            ex = g[3]
            sx, sy = self._s(*p)
            c.create_oval(sx - 7, sy - 7, sx + 7, sy + 7, outline="#e67e00", width=2)
            side = side_of_station(a.station)           # +1 = in Stabrichtung, -1 = gegen Stabrichtung, 0 = beidseitig
            if side:
                ux, uy = ex[0] * side, -ex[1] * side
                c.create_line(sx + ux * 7, sy + uy * 7, sx + ux * 40, sy + uy * 40, fill="#e67e00", width=4,
                              arrow="last", arrowshape=(9, 11, 4))
            label = f"#{i + 1}  S{a.stab} {station_short(a.station)}"
            c.create_text(sx + 11, sy + 12, text=label, fill="#e67e00", font=("Segoe UI", 9, "bold"), anchor="nw")
        pend = getattr(self.app, "pending_bs", None)
        if pend and pend[0] is None and pend[1] in self.res.nodes:
            sx, sy = self._s(*self.res.nodes[pend[1]])
            c.create_oval(sx - 11, sy - 11, sx + 11, sy + 11, outline="#e67e00", width=3, dash=(4, 3))
            c.create_text(sx + 14, sy - 14, text=f"Knotenlast Kn.{pend[1]} → IFC-Bauteil wählen", fill="#e67e00",
                          anchor="sw", font=("Segoe UI", 9, "bold"))
        elif pend:
            g = self.geom.get(pend[0])
            s = station_distance(pend[1], g[2]) if g else None
            p = point_on_member(self.res, pend[0], s) if (g and s is not None) else None
            if p:
                sx, sy = self._s(*p)
                c.create_oval(sx - 11, sy - 11, sx + 11, sy + 11, outline="#e67e00", width=3, dash=(4, 3))
                c.create_text(sx + 14, sy - 14, text=f"S{pend[0]} {station_short(pend[1])} → IFC-Bauteil wählen",
                              fill="#e67e00", anchor="sw", font=("Segoe UI", 9, "bold"))
        # lokale Achsen am zuletzt angeklickten Stab
        if self.marker:
            x, z, ex = self.marker
            sx, sy = self._s(x, z)
            lx, lz = local_axes(ex)
            for (vx, vz), col, name in ((lx, "#d00000", "x"), (lz, "#008a00", "z")):
                c.create_line(sx, sy, sx + vx * 45, sy - vz * 45, fill=col, width=2, arrow="last")
                c.create_text(sx + vx * 56, sy - vz * 56, text=name, fill=col, font=("Segoe UI", 10, "bold"))

    # ------------------------------------------------------------ Eingaben
    def _on_press(self, e):
        self._press = (e.x, e.y)
        self._moved = False

    def _on_motion(self, e):
        if not self._press:
            return
        dx, dy = e.x - self._press[0], e.y - self._press[1]
        if not self._moved and math.hypot(dx, dy) < 4:
            return
        self._moved = True
        self.ox += dx
        self.oy += dy
        self._press = (e.x, e.y)
        self.redraw()

    def _on_release(self, e):
        if self._press and not self._moved:
            self.click(e.x, e.y)
        self._press = None

    def _on_wheel(self, e):
        self._zoom(e.x, e.y, 1.2 ** (e.delta / 120.0))

    def _zoom(self, mx, my, f):
        new = max(1e-3, min(self.scale * f, 20000.0))
        f = new / self.scale
        self.ox = mx - (mx - self.ox) * f
        self.oy = my - (my - self.oy) * f
        self.scale = new
        self.redraw()

    # -------------------------------------------------------------- Klicks
    def click(self, sx: float, sy: float):
        node, nd = None, NODE_PICK_PX + 1.0
        for n, (x, z) in self.res.nodes.items():
            px, py = self._s(x, z)
            d = math.hypot(px - sx, py - sy)
            if d < nd:
                node, nd = n, d
        if node is not None and nd <= NODE_PICK_PX:
            self.pick_node(node)
            return
        best, bd, bt = None, MEMBER_PICK_PX + 1.0, 0.0
        for n, (a, b, L, ex) in self.geom.items():
            ax, ay = self._s(*a)
            bx, by = self._s(*b)
            d, t = distance_point_segment(sx, sy, ax, ay, bx, by)
            if d < bd:
                best, bd, bt = n, d, t
        if best is not None and bd <= MEMBER_PICK_PX:
            self.pick_member(best, bt * self.geom[best][2])

    def pick_node_by_number(self):
        try:
            n = int(self.node_var.get().strip())
        except ValueError:
            return
        if n not in self.res.nodes:
            messagebox.showinfo("Knoten", f"Knoten {n} gibt es im PDF nicht.", parent=self)
            return
        self.pick_node(n)

    def pick_node(self, node: int):
        if (not node_members(self.res, node) and not members_through_node(self.res, node)
                and not any(l.node == node for l in self.res.node_loads)):
            messagebox.showinfo("Knoten", f"An Knoten {node} hängt kein Stab.", parent=self)
            return
        self.marker = None
        self.redraw()
        d = NodeDialog(self, self.res, node, single=bool(getattr(self.app, "ifc_members", None)))
        for stab, side in d.selected:
            self.app.add_from_model(stab, side)
        if d.node_load:
            self.app.add_node_load(node)
        self.redraw()

    def pick_member(self, stab: int, s: float):
        a, b, L, ex = self.geom[stab]
        m = self.res.members[stab]
        p = point_on_member(self.res, stab, s)
        self.marker = (p[0], p[1], ex)
        self.redraw()
        d = DistanceDialog(self, stab, m.node_start, m.node_end, L, s)
        if d.result is not None:
            self.app.add_from_model(stab, station_key_from_distance(d.result, L))
        self.redraw()

