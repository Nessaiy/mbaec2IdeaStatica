"""Grafische Vorschau der Lasten: IFC-Bauteile in 3D, daran je Position die Kraefte (gruen) und Momente (rot)
in den lokalen Bauteilachsen, wie sie in IDEA importiert werden. Je Kombination waehlbar."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Tuple

from .axispick import BASE_SEL, GRAY_FILL, GRAY_LINE, View3D, _cross, _shade
from .ifcaxes import ifc_to_idea, is_connector, member_segment

FORCE_COL, MOM_COL = "#2e9d00", "#c00000"
EXT_COL = "#e07000"
TOL_F = 0.5            # kN: darunter gilt eine Komponente als im Gleichgewicht
TOL_M = 1.0            # kNm
BAL = ("Fx", "Fy", "Fz", "Mx", "My", "Mz")
BAL_DEFAULT = {"Fx": True, "Fy": True, "Fz": True, "Mx": False, "My": False, "Mz": True}
COMP = ("N", "Vy", "Vz", "Mx", "My", "Mz")


def group_rows(rows) -> Dict[str, list]:
    """Zeilen je Lasteinwirkung (nur die erste Zeile traegt den Namen)."""
    out: Dict[str, list] = {}
    cur = None
    for r in rows:
        if r.name:
            cur = r.name
            out.setdefault(cur, [])
        if cur is not None:
            out[cur].append(r)
    return out


class LoadView(tk.Toplevel):
    def __init__(self, app, rows):
        super().__init__(app)
        self.app = app
        self.groups = group_rows(rows)
        self.title("Lasten grafisch – IFC-Ansicht (Kräfte grün, Momente rot, lokale Bauteilachsen)")
        self.geometry("1100x760")
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Lasteinwirkung:").pack(side="left")
        self.sel = tk.StringVar(value=next(iter(self.groups), ""))
        cb = ttk.Combobox(top, textvariable=self.sel, values=list(self.groups), state="readonly", width=24)
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self.v.redraw())
        ttk.Button(top, text="◀", width=3, command=lambda: self._step(-1)).pack(side="left")
        ttk.Button(top, text="▶", width=3, command=lambda: self._step(1)).pack(side="left", padx=(0, 10))
        self.labels = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Werte anzeigen", variable=self.labels, command=lambda: self.v.redraw()).pack(side="left", padx=6)
        self.src = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Herkunft im Bild", variable=self.src, command=lambda: self.v.redraw()).pack(side="left", padx=6)
        self.ext = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Externe Punktlast", variable=self.ext, command=lambda: self.v.redraw()).pack(side="left", padx=6)
        ttk.Button(top, text="Gleichgewicht aller Kombinationen…", command=self._balance_table).pack(side="left", padx=6)
        self.axes = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Bauteilachsen", variable=self.axes, command=lambda: self.v.redraw()).pack(side="left", padx=6)
        ttk.Label(top, text="Ziehen = drehen, rechte Maustaste = verschieben, Rad = Zoom   (kN, kNm; positiv = in Richtung der lokalen Achse)",
                  foreground="#666").pack(side="right")
        bal = ttk.Frame(self, padding=(8, 0, 8, 6))
        bal.pack(fill="x")
        ttk.Label(bal, text="Für das Gleichgewicht berücksichtigen:").pack(side="left")
        self.bal = {k: tk.BooleanVar(value=BAL_DEFAULT[k]) for k in BAL}
        self._table_fill = None
        for k in BAL:
            ttk.Checkbutton(bal, text=k, variable=self.bal[k], command=self._bal_changed).pack(side="left", padx=4)
        ttk.Label(bal, text="(abgewählte Spalten werden ignoriert; Momente = Summe der Stabend-Momente ohne Hebelarme)",
                  foreground="#666").pack(side="left", padx=10)
        self._prepare()
        side = ttk.Frame(self)
        side.pack(side="right", fill="y", padx=(0, 8), pady=(0, 8))
        ttk.Label(side, text="Herkunft der Werte (Summanden)", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.txt = tk.Text(side, width=58, wrap="word", font=("Consolas", 9), background="#fafafa")
        sb = ttk.Scrollbar(side, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side="left", fill="y")
        sb.pack(side="left", fill="y")
        self.txt.tag_configure("h", font=("Consolas", 9, "bold"), spacing1=8)
        self.txt.tag_configure("sum", foreground="#8b0000")
        self.txt.tag_configure("warn", foreground="#b00000", font=("Consolas", 9, "bold"))
        self._panel_key = None
        self.v = View3D(self, lambda spec: None, self._draw)
        self.v.cv.pack(side="left", fill="both", expand=True, padx=8, pady=(0, 8))
        self.v.set_fit(self._pts, 2.6)

    def _step(self, d):
        names = list(self.groups)
        if not names:
            return
        i = (names.index(self.sel.get()) + d) % len(names)
        self.sel.set(names[i])
        self.v.redraw()

    # ------------------------------------------------------------------ Daten
    def _prepare(self):
        app, tr = self.app, self.app.ifc_tr
        self.items: List[Tuple[object, list]] = []
        self.by_name: Dict[str, object] = {}
        pts = []
        for m in app.ifc_members:
            if m.npoints < 4:
                continue
            faces = [[ifc_to_idea(p, tr) for p in poly] for poly in m.faces]
            self.items.append((m, faces))
            if not is_connector(m):
                self.by_name.setdefault(m.name, m)
            for poly in faces:
                pts.extend(poly)
        self._pts = pts or [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)]
        r = max(max(p[i] for p in self._pts) - min(p[i] for p in self._pts) for i in range(3))
        self.size = r if r > 1e-6 else 1.0

    def _end_point(self, m, position):
        p0, p1, _o = member_segment(m, self.app.ifc_tr)
        ex = self.app.frame_for(m).ex
        d0 = sum(p0[i] * ex[i] for i in range(3))
        d1 = sum(p1[i] * ex[i] for i in range(3))
        lo, hi = (p0, p1) if d0 <= d1 else (p1, p0)
        return lo if position == "Anfang" else hi

    # ------------------------------------------------------------------ Zeichnen
    def _draw(self, v: View3D):
        c = v.cv
        light = (0.35, -0.55, 0.75)
        polys = []
        for m, faces in self.items:
            if is_connector(m):
                fill0 = "#c9a227"
            else:
                fill0 = "#7b9ac8"
            for poly in faces:
                pts = [v.s(p) for p in poly]
                d = sum(q[2] for q in pts) / len(pts)
                n = _cross(tuple(poly[1][i] - poly[0][i] for i in range(3)), tuple(poly[2][i] - poly[0][i] for i in range(3)))
                ln = math.sqrt(sum(t * t for t in n)) or 1.0
                nv = v._vec((n[0] / ln, n[1] / ln, n[2] / ln))
                lam = abs(nv[0] * light[0] + nv[1] * light[2] + nv[2] * light[1])
                polys.append((d, [(q[0], q[1]) for q in pts], _shade(fill0, 0.6 + 0.5 * min(1.0, lam))))
        polys.sort(key=lambda t: -t[0])
        for d, pts, fill in polys:
            c.create_polygon(*[t for q in pts for t in q], fill=fill, outline="#53698c", width=1)
        rows = self.groups.get(self.sel.get(), [])
        self._fill_panel(rows)
        vmax = max([abs(x) for r in rows for x in r.values[:3]] + [1e-9])
        mmax = max([abs(x) for r in rows for x in r.values[3:]] + [1e-9])
        L = 0.17 * min(max(c.winfo_width(), 300), max(c.winfo_height(), 300))
        if self.ext.get() and rows:
            R = self._resultant(rows)
            f = [-t if self.bal[c].get() else 0.0 for t, c in zip(R["F"], ("Fx", "Fy", "Fz"))]   # fehlende externe Last = -(Summe)
            mag = math.sqrt(sum(t * t for t in f))
            if mag > TOL_F:
                u = tuple(t / mag for t in f)
                self._force(v, (0.0, 0.0, 0.0), u, mag, min(1.6 * L, mag / max(vmax, 1e-9) * L + 20), "Ext. Punktlast", EXT_COL, "#a04500",
                            f"{mag:.1f} kN  (X {f[0]:.1f}, Y {f[1]:.1f}, Z {f[2]:.1f})")
        for r in rows:
            m = self.by_name.get(r.member)
            if m is None:
                continue
            fr = self.app.frame_for(m)
            P = self._end_point(m, r.position)
            ax = (fr.ex, fr.ey, fr.ez)
            ox, oy, _ = v.s(P)
            if self.axes.get():
                self._axes(v, P, ax)
            c.create_text(ox + 6, oy + 14, text=f"{r.member} / {r.position}", anchor="nw", fill="#222", font=("Segoe UI", 9, "bold"))
            for i in range(3):                                   # Kraefte
                val = r.values[i]
                if abs(val) < 5e-3:
                    continue
                self._force(v, P, ax[i], val, abs(val) / vmax * L + 14, COMP[i] + self._src(r, i))
            for i in range(3):                                   # Momente
                val = r.values[3 + i]
                if abs(val) < 5e-3:
                    continue
                self._moment(v, P, ax[i], val, 16 + 14 * abs(val) / mmax, COMP[3 + i] + self._src(r, 3 + i))

    def _axes(self, v, P, ax):
        c = v.cv
        ox, oy, _ = v.s(P)
        for i, col in enumerate(("#d00000", "#008a00", "#0033cc")):
            vx, vy, _d = v._vec(ax[i])
            c.create_line(ox, oy, ox + vx * 38, oy - vy * 38, fill=col, width=1, dash=(3, 2))
            c.create_text(ox + vx * 46, oy - vy * 46, text="xyz"[i], fill=col, font=("Segoe UI", 8))

    def _force(self, v, P, axis, val, px, label, col=FORCE_COL, tcol="#1b5e00", text=None):
        c = v.cv
        vx, vy, _d = v._vec(axis)
        n = math.hypot(vx, vy)
        if n < 1e-6:
            ux, uy = 0.7, -0.7
            n = 0.35
        else:
            ux, uy = vx / n, -vy / n
        px = px * max(n, 0.35)
        sg = 1.0 if val > 0 else -1.0
        hx, hy, _ = v.s(P)
        tx, ty = hx - sg * ux * px, hy - sg * uy * px              # Pfeil zeigt in Kraftrichtung und endet am Lastpunkt
        c.create_line(tx, ty, hx, hy, fill=col, width=4 if text is None else 6, arrow="last", arrowshape=(13, 15, 5))
        if text is not None:
            c.create_text(tx - sg * ux * 6, ty - sg * uy * 6, text=f"{label} {text}", fill=tcol,
                          font=("Segoe UI", 10, "bold"), anchor="e" if tx < hx else "w")
        elif self.labels.get():
            c.create_text(tx - sg * ux * 6, ty - sg * uy * 6, text=self._lbl(label, val), fill=tcol,
                          font=("Segoe UI", 9, "bold"), anchor="e" if tx < hx else "w")

    def _moment(self, v, P, axis, val, rpx, label):
        c = v.cv
        a = axis if val > 0 else tuple(-t for t in axis)           # Rechte-Hand-Regel um die Momentenachse
        helper = (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0)
        u = _cross(a, helper)
        lu = math.sqrt(sum(t * t for t in u)) or 1.0
        u = tuple(t / lu for t in u)
        w = _cross(a, u)
        r = rpx / v.scale
        pts = []
        for k in range(0, 271, 15):
            t = math.radians(k)
            p = tuple(P[i] + r * (math.cos(t) * u[i] + math.sin(t) * w[i]) for i in range(3))
            x, y, _ = v.s(p)
            pts += [x, y]
        c.create_line(*pts, fill=MOM_COL, width=3, arrow="last", arrowshape=(11, 13, 5), smooth=True)
        if self.labels.get():
            c.create_text(pts[0] + 4, pts[1] - 10, text=self._lbl(label, val), fill="#8b0000", font=("Segoe UI", 9, "bold"), anchor="w")

    # ------------------------------------------------------------------ Herkunft
    @staticmethod
    def _grouped(row, i):
        """Summanden einer Komponente, nach Kurzname zusammengefasst: [(Kurzname, Wert)] (nur ungleich 0)."""
        g: Dict[str, float] = {}
        for short, _d, vals in row.parts:
            g[short] = g.get(short, 0.0) + vals[i]
        return [(k, v) for k, v in g.items() if abs(v) >= 5e-3]

    def _src(self, row, i) -> str:
        """Marker im Label: Kurzname(n) der Quellen; Wert wird in _lbl dahinter eingesetzt."""
        if not self.src.get():
            return ""
        parts = self._grouped(row, i)
        if not parts:
            return ""
        if len(parts) == 1:
            return "\x00 (" + parts[0][0] + ")"
        return "\x00 = " + " + ".join(f"{v:.1f} {k}" for k, v in parts)

    @staticmethod
    def _lbl(label, val) -> str:
        if "\x00" in label:
            a, b = label.split("\x00", 1)
            return f"{a} {val:.1f}{b}"
        return f"{label} {val:.1f}"

    def _fill_panel(self, rows):
        key = (self.sel.get(), id(rows), tuple(self.bal[k].get() for k in BAL))
        if key == self._panel_key:
            return
        self._panel_key = key
        t = self.txt
        t.configure(state="normal")
        t.delete("1.0", "end")
        if rows:
            R = self._resultant(rows)
            ext, extm = [-x for x in R["F"]], [-x for x in R["M"]]
            bad = self._bad(R)
            t.insert("end", "Gleichgewicht (IDEA global)\n", "h")
            t.insert("end", f"  Externe Punktlast: X {ext[0]:.1f}  Y {ext[1]:.1f}  Z {ext[2]:.1f} kN\n", "warn" if bad else "")
            t.insert("end", f"  Externe Momente:   X {extm[0]:.1f}  Y {extm[1]:.1f}  Z {extm[2]:.1f} kNm\n")
            t.insert("end", "  " + ("⚠ unbalanciert in " + ", ".join(bad) + " – wirkt hier wirklich eine Last im Knoten?" if bad
                                    else "✓ im Gleichgewicht") + "\n")
            off = [k for k in BAL if not self.bal[k].get()]
            if off:
                t.insert("end", "  ignoriert: " + ", ".join(off) + "\n")
            if R["unconfirmed"]:
                t.insert("end", "  Achsen nicht bestätigt: " + ", ".join(R["unconfirmed"]) + " (Roll um Stabachse geraten)\n", "warn")
        for r in rows:
            nz = [(k, d, v) for k, d, v in r.parts if any(abs(x) >= 5e-3 for x in v)]
            t.insert("end", f"{r.member} / {r.position}\n", "h")
            tot = "  ".join(f"{c} {x:.1f}" for c, x in zip(COMP, r.values) if abs(x) >= 5e-3) or "alle Werte 0"
            t.insert("end", f"  Summe: {tot}\n", "sum" if len(nz) > 1 else "")
            if not nz:
                t.insert("end", "  (keine Last zugeordnet)\n")
            for k, d, v in nz:
                vs = "  ".join(f"{c} {x:.1f}" for c, x in zip(COMP, v) if abs(x) >= 5e-3)
                t.insert("end", f"   • {d}\n       → {vs}\n", "warn" if "⚠" in d else "")
        t.configure(state="disabled")

    # ------------------------------------------------------------------ Gleichgewicht
    def _resultant(self, rows):
        """Summe aller Zeilen in IDEA-Globalkoordinaten: Kraft F, Moment M (nur Momente), Moment inkl. Hebelarme um den Ursprung (0,0,0)."""
        F = [0.0, 0.0, 0.0]
        M = [0.0, 0.0, 0.0]
        MR = [0.0, 0.0, 0.0]
        unconfirmed = []
        for r in rows:
            m = self.by_name.get(r.member)
            if m is None:
                continue
            fr = self.app.frame_for(m)
            if not self.app.is_confirmed(m) and r.member not in unconfirmed:
                unconfirmed.append(r.member)
            ax = (fr.ex, fr.ey, fr.ez)
            f = [sum(r.values[i] * ax[i][k] for i in range(3)) for k in range(3)]
            mo = [sum(r.values[3 + i] * ax[i][k] for i in range(3)) for k in range(3)]
            P = self._end_point(m, r.position)
            arm = _cross(P, tuple(f))
            for k in range(3):
                F[k] += f[k]
                M[k] += mo[k]
                MR[k] += mo[k] + arm[k]
        return {"F": F, "M": M, "MR": MR, "unconfirmed": unconfirmed}

    def _bad(self, R):
        """Komponenten (nur die angehakten), die nicht im Gleichgewicht sind."""
        vals = list(R["F"]) + list(R["M"])
        tol = [TOL_F] * 3 + [TOL_M] * 3
        return [k for k, x, tl in zip(BAL, vals, tol) if self.bal[k].get() and abs(x) > tl]

    def _bal_changed(self):
        self._panel_key = None
        self.v.redraw()
        if self._table_fill:
            try:
                self._table_fill()
            except tk.TclError:
                self._table_fill = None

    def _balance_table(self):
        win = tk.Toplevel(self)
        win.title("Gleichgewicht je Kombination – externe Punktlast im Knoten (IDEA global)")
        win.geometry("1060x560")
        ttk.Label(win, justify="left", wraplength=1020, foreground="#444", text=(
            "Summe aller Zeilen der Importtabelle in globalen IDEA-Koordinaten; angezeigt wird die fehlende externe Last (= negative Summe). "
            "Nur wenn dort tatsächlich eine Last angreift, darf sie ≠ 0 sein – sonst stimmen Achsen/Vorzeichen/Stellen nicht. "
            f"Rot = angehakte Komponente über {TOL_F:g} kN bzw. {TOL_M:g} kNm. Abgewählte Spalten (Haken im Hauptfenster oben) werden ignoriert und grau gezeigt.")
                  ).pack(fill="x", padx=8, pady=6)
        cols = ("Kombination",) + tuple(f"Ext. {k}" for k in BAL) + ("Hinweis",)
        t = ttk.Treeview(win, columns=cols, show="headings")
        t.tag_configure("bad", background="#ffd0d0")
        t.tag_configure("ok", background="#e6f4e6")
        sb = ttk.Scrollbar(win, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        sb.pack(side="left", fill="y", pady=(0, 8))

        def fill():
            t.delete(*t.get_children())
            for k, c in zip(("Kombination",) + BAL + ("Hinweis",), cols):
                head = c if (k in ("Kombination", "Hinweis") or self.bal[k].get()) else f"({c}: ignoriert)"
                unit = "" if k in ("Kombination", "Hinweis") else (" [kN]" if k.startswith("F") else " [kNm]")
                t.heading(c, text=head + (unit if self.bal.get(k) is None or self.bal[k].get() else ""))
                t.column(c, width=330 if c == "Hinweis" else (110 if c == "Kombination" else 95),
                         anchor="w" if c in ("Kombination", "Hinweis") else "e")
            for name, rows in self.groups.items():
                R = self._resultant(rows)
                ext = [-x for x in R["F"]] + [-x for x in R["M"]]
                bad = self._bad(R)
                hint = ("unbalanciert in " + ", ".join(bad)) if bad else "im Gleichgewicht"
                if R["unconfirmed"]:
                    hint += "  (Achsen nicht bestätigt: " + ", ".join(R["unconfirmed"]) + ")"
                t.insert("", "end", values=[name] + [f"{x:.2f}" for x in ext] + [hint], tags=("bad" if bad else "ok",))

        fill()
        self._table_fill = fill
        win.bind("<Destroy>", lambda e: setattr(self, "_table_fill", None) if e.widget is win else None)
