"""Einfache Oberflaeche (tkinter - in Python enthalten, laeuft ohne Admin-Installation)."""
from __future__ import annotations

import os
import queue
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Tuple

from . import __version__
from .axes import AXES, AXIS_CHOICES, IDENTITY_AXES, IDENTITY_MAP, SOURCE_CHOICES, component_map_from_axes, validate_component_map
from .ifcaxes import IFC_TO_IDEA_DEFAULT
from .export import missing_stations, missing_text, HEADERS, build_rows, fmt_tsv, station_options, write_excel
from .mapping import Assignment, ManualLoad, Profile, parse_case_spec
from .model import COMPONENTS, POSITIONS, UNITS, ParseResult
from .modelview import ModelView
from .modules import all_modules, get_module
from .tooltip import install as install_tooltips, tip


class AxesEditor(ttk.Frame):
    """Achsenzuordnung Baustatik -> IDEA (lokal) mit abgeleiteter Komponenten-Tabelle."""

    def __init__(self, master, axes: Optional[Dict[str, str]] = None, cmap: Optional[Dict[str, str]] = None):
        super().__init__(master)
        self.axis_vars: Dict[str, tk.StringVar] = {}
        self.map_vars: Dict[str, tk.StringVar] = {}
        af = ttk.Frame(self)
        af.grid(row=0, column=0, sticky="w")
        for i, a in enumerate(AXES):
            ttk.Label(af, text=f"{a} (Baustatik) =").grid(row=0, column=2 * i, padx=(4, 2))
            v = tk.StringVar(value=IDENTITY_AXES[a])
            self.axis_vars[a] = v
            cb = ttk.Combobox(af, textvariable=v, values=list(AXIS_CHOICES), width=4, state="readonly")
            cb.grid(row=0, column=2 * i + 1, padx=(0, 10))
            cb.bind("<<ComboboxSelected>>", lambda e: self._changed())
        ttk.Button(af, text="Standard", width=9, command=self.reset).grid(row=0, column=6, padx=4)
        self.msg = ttk.Label(self, text="", foreground="#b00020")
        self.msg.grid(row=1, column=0, sticky="w")
        self.summary = ttk.Label(self, text="", foreground="#444444")
        self.summary.grid(row=2, column=0, sticky="w", pady=(2, 0))
        self.adv_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="Erweitert: Komponenten einzeln \u00e4ndern", variable=self.adv_var,
                        command=self._toggle_adv).grid(row=3, column=0, sticky="w")
        self.cf = ttk.Frame(self)
        ttk.Label(self.cf, text="IDEA-Komponente \u2190 Baustatik-Komponente:").grid(row=0, column=0, columnspan=6, sticky="w")
        for i, c in enumerate(COMPONENTS):
            ttk.Label(self.cf, text=c).grid(row=1, column=i, padx=4)
            v = tk.StringVar(value=IDENTITY_MAP[c])
            v.trace_add("write", lambda *a: self._update_summary())
            self.map_vars[c] = v
            ttk.Combobox(self.cf, textvariable=v, values=SOURCE_CHOICES, width=5, state="readonly"
                         ).grid(row=2, column=i, padx=4)
        self.set(axes or IDENTITY_AXES, cmap)

    def _toggle_adv(self):
        if self.adv_var.get():
            self.cf.grid(row=4, column=0, sticky="w")
        else:
            self.cf.grid_remove()

    def _update_summary(self):
        try:
            self.summary.config(text="IDEA \u2190 Baustatik:  " + ",  ".join(
                f"{c}\u2190{self.map_vars[c].get()}" for c in COMPONENTS))
        except Exception:
            pass

    def _changed(self):
        try:
            cmap = component_map_from_axes({a: v.get() for a, v in self.axis_vars.items()})
        except ValueError as e:
            self.msg.config(text=str(e))
            return
        self.msg.config(text="")
        for c, v in self.map_vars.items():
            v.set(cmap[c])

    def reset(self):
        self.set(IDENTITY_AXES, None)

    def set(self, axes: Dict[str, str], cmap: Optional[Dict[str, str]] = None):
        for a, v in self.axis_vars.items():
            v.set(axes.get(a, IDENTITY_AXES[a]))
        self.msg.config(text="")
        try:
            cm = cmap or component_map_from_axes({a: v.get() for a, v in self.axis_vars.items()})
        except ValueError:
            cm = IDENTITY_MAP
        for c, v in self.map_vars.items():
            v.set(cm.get(c, IDENTITY_MAP[c]))
        try:
            derived = component_map_from_axes({a: v.get() for a, v in self.axis_vars.items()})
        except ValueError:
            derived = IDENTITY_MAP
        custom = any(cm.get(c) != derived.get(c) for c in COMPONENTS)
        self.adv_var.set(custom)
        self._toggle_adv()
        self._update_summary()

    def get(self) -> Tuple[Dict[str, str], Dict[str, str]]:
        axes = {a: v.get() for a, v in self.axis_vars.items()}
        try:
            component_map_from_axes(axes)               # jede IDEA-Achse genau einmal
            cmap = {c: v.get() for c, v in self.map_vars.items()}
            validate_component_map(cmap)
        except ValueError as e:
            raise ValueError(f"Achsenzuordnung: {e}")
        return axes, cmap


class AssignmentDialog(tk.Toplevel):
    """Ein IDEA-Bauteil zuweisen: entweder Stab + Stelle aus dem PDF oder manuell eingegebene Lasten."""

    def __init__(self, master, result: ParseResult, known_names: List[str],
                 initial: Optional[Assignment] = None,
                 default_axes: Optional[Dict[str, str]] = None, default_map: Optional[Dict[str, str]] = None):
        super().__init__(master)
        self.default_axes = default_axes or dict(IDENTITY_AXES)
        self.default_map = default_map or dict(IDENTITY_MAP)
        self.title("Bauteil zuweisen")
        self.transient(master)
        self.result_obj = result
        self.result: Optional[Assignment] = None
        self._nums = result.member_numbers()
        self._st_map = {}          # Anzeigetext -> Stellen-Schluessel
        init_manual = bool(initial and initial.is_manual)

        frm = ttk.Frame(self, padding=10)
        frm.grid(sticky="nsew")
        ttk.Label(frm, text="Bauteil in IDEA (Name):").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=initial.idea_name if initial else "")
        name_cb = ttk.Combobox(frm, textvariable=self.name_var, values=sorted(set(known_names)), width=48)
        name_cb.grid(row=1, column=0, sticky="we", pady=(0, 8))
        name_cb.focus_set()
        ttk.Label(frm, text="Position im IDEA-Bauteil:").grid(row=2, column=0, sticky="w")
        self.pos_var = tk.StringVar(value=initial.position if initial else "Ende")
        pf = ttk.Frame(frm)
        pf.grid(row=3, column=0, sticky="w", pady=(0, 8))
        for p in POSITIONS:
            ttk.Radiobutton(pf, text=p, value=p, variable=self.pos_var).pack(side="left", padx=(0, 12))
        self.neg_var = tk.BooleanVar(value=bool(initial and not initial.is_manual and initial.sign < 0))
        ttk.Checkbutton(pf, text="Vorzeichen umkehren", variable=self.neg_var).pack(side="left", padx=(20, 0))

        self.nb = ttk.Notebook(frm)
        self.nb.grid(row=4, column=0, sticky="nsew")
        # --- Reiter 1: Stab aus dem PDF
        t1 = ttk.Frame(self.nb, padding=8)
        self.nb.add(t1, text="Stab aus PDF")
        ttk.Label(t1, text="Stab im PDF:").grid(row=0, column=0, sticky="w")
        labels = [(result.members[n].label() if n in result.members else f"Stab {n}") for n in self._nums]
        self.stab_var = tk.StringVar()
        self.stab_cb = ttk.Combobox(t1, textvariable=self.stab_var, values=labels, width=72, state="readonly")
        self.stab_cb.grid(row=1, column=0, sticky="we", pady=(0, 8))
        self.stab_cb.bind("<<ComboboxSelected>>", lambda e: self._fill_stations(None))
        ttk.Label(t1, text="Schnittgr\u00f6\u00dfen an Stelle x [m] (frei eingebbar):").grid(row=2, column=0, sticky="w")
        self.st_var = tk.StringVar()
        self.st_cb = ttk.Combobox(t1, textvariable=self.st_var, width=72)
        self.st_cb.grid(row=3, column=0, sticky="we")
        self.st_cb.bind("<<ComboboxSelected>>", self._station_chosen)
        ttk.Label(t1, text="[n/m Komb.] = Stelle kommt nur in n von m Kombinationen vor; sonst wird linear "
                           "interpoliert (gelb markiert).", foreground="#666", wraplength=520
                  ).grid(row=4, column=0, sticky="w", pady=(6, 0))
        self.hint_var = tk.StringVar(value="")
        ttk.Label(t1, textvariable=self.hint_var, foreground="#b00020").grid(row=5, column=0, sticky="w")
        ttk.Label(t1, text="Lokale Achsenzuordnung Baustatik \u2192 dieses IDEA-Bauteil:").grid(
            row=6, column=0, sticky="w", pady=(10, 0))
        own_axes = initial.axes if (initial and not init_manual and initial.axes) else self.default_axes
        own_map = initial.component_map if (initial and not init_manual and initial.component_map) else (
            None if own_axes is not self.default_axes else self.default_map)
        self.axes_ed = AxesEditor(t1, own_axes, own_map)
        self.axes_ed.grid(row=7, column=0, sticky="w")
        if self._nums:
            idx = self._nums.index(initial.stab) if (initial and not init_manual and initial.stab in self._nums) else 0
            self.stab_cb.current(idx)
            self._fill_stations(initial.station if (initial and not init_manual) else None)

        # --- Reiter 2: manuell
        t2 = ttk.Frame(self.nb, padding=8)
        self.nb.add(t2, text="Manuell (nicht im PDF)")
        ttk.Label(t2, text="Kombinationen: z. B. 1-20 oder 21-35, 40 oder alle. Nicht genannte Kombinationen "
                           "und leere Felder = 0.", wraplength=620, foreground="#444"
                  ).grid(row=0, column=0, columnspan=8, sticky="w", pady=(0, 6))
        heads = ["Kombinationen"] + [f"{c} [{UNITS[c]}]" for c in COMPONENTS]
        for i, h in enumerate(heads):
            ttk.Label(t2, text=h).grid(row=1, column=i, padx=2)
        self.rows_frame = ttk.Frame(t2)
        self.rows_frame.grid(row=2, column=0, columnspan=8, sticky="w")
        self.man_rows = []
        for m in (initial.manual if init_manual else [ManualLoad()]):
            self._add_row(m)
        bf2 = ttk.Frame(t2)
        bf2.grid(row=3, column=0, columnspan=8, sticky="w", pady=(6, 0))
        ttk.Button(bf2, text="Zeile +", command=lambda: self._add_row(ManualLoad(""))).pack(side="left", padx=2)
        ttk.Button(bf2, text="Zeile \u2212", command=self._del_row).pack(side="left", padx=2)
        if init_manual:
            self.nb.select(1)

        bf = ttk.Frame(frm)
        bf.grid(row=5, column=0, sticky="e", pady=(10, 0))
        ttk.Button(bf, text="OK", command=self._ok).pack(side="left", padx=4)
        ttk.Button(bf, text="Abbrechen", command=self.destroy).pack(side="left")
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.wait_window(self)

    # --- Stellen
    def _fill_stations(self, wanted_key):
        idx = self.stab_cb.current()
        if idx < 0:
            return
        opts = station_options(self.result_obj, self._nums[idx])
        self._st_map = {label: key for key, label in opts}
        labels = [label for _, label in opts]
        self.st_cb.configure(values=labels)
        pick = 0
        if wanted_key:
            keys = [k for k, _ in opts]
            if wanted_key in keys:
                pick = keys.index(wanted_key)
            else:
                cand = [i for i, k in enumerate(keys) if k.startswith(wanted_key) and k[len(wanted_key):] in ("L", "R")]
                if cand:                                  # Sprung an dieser Stelle -> links/rechts waehlen
                    pick = cand[0]
                    self.hint_var.set("An dieser Stelle gibt es einen Sprung \u2013 bitte links oder rechts w\u00e4hlen.")
                else:
                    self.st_var.set(wanted_key[2:].rstrip("LR").replace(".", ",") if wanted_key.startswith("x=") else "")
                    return
        elif len(opts) > 1:
            pick = len(opts) - 1          # Standard: Stabende
        if labels:
            self.st_cb.current(pick)
            if not wanted_key:            # beim Bearbeiten die gespeicherte IDEA-Position nicht ueberschreiben
                self._station_chosen()

    def _station_chosen(self, event=None):
        key = self._st_map.get(self.st_var.get())
        if key in POSITIONS:              # Anfang/Ende des Stabes -> IDEA-Position passend vorbelegen
            self.pos_var.set(key)

    def _station_key(self) -> Optional[str]:
        txt = self.st_var.get().strip()
        if txt in self._st_map:
            return self._st_map[txt]
        m = re.match(r"^(-?\d+(?:[.,]\d+)?)", txt)
        if not m:
            return None
        return f"x={float(m.group(1).replace(',', '.')):.2f}"

    # --- manuelle Zeilen
    def _add_row(self, m: ManualLoad):
        r = len(self.man_rows)
        cv = tk.StringVar(value=m.cases)
        ttk.Entry(self.rows_frame, textvariable=cv, width=16).grid(row=r, column=0, padx=2, pady=1)
        vs = {}
        for i, c in enumerate(COMPONENTS, start=1):
            v = tk.StringVar(value=("" if not m.values.get(c) else f"{m.values[c]:g}".replace(".", ",")))
            ttk.Entry(self.rows_frame, textvariable=v, width=9, justify="right").grid(row=r, column=i, padx=2, pady=1)
            vs[c] = v
        self.man_rows.append((cv, vs))

    def _del_row(self):
        if len(self.man_rows) <= 1:
            return
        self.man_rows.pop()
        last = max(w.grid_info()["row"] for w in self.rows_frame.winfo_children())
        for w in self.rows_frame.winfo_children():
            if w.grid_info()["row"] == last:
                w.destroy()

    # --- OK
    def _ok(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Eingabe", "Bitte den Bauteilnamen angeben.", parent=self)
            return
        if self.nb.index(self.nb.select()) == 0:
            idx = self.stab_cb.current()
            key = self._station_key()
            if idx < 0 or not key:
                messagebox.showwarning("Eingabe", "Bitte Stab und Stelle w\u00e4hlen (oder x als Zahl eingeben).", parent=self)
                return
            try:
                axes, cmap = self.axes_ed.get()
            except ValueError as e:
                messagebox.showwarning("Eingabe", str(e), parent=self)
                return
            own = (axes != self.default_axes) or (cmap != self.default_map)
            self.result = Assignment(name, self.pos_var.get(), stab=self._nums[idx], station=key,
                                     axes=axes if own else None, component_map=cmap if own else None,
                                     sign=-1.0 if self.neg_var.get() else 1.0)
        else:
            loads = []
            try:
                for cv, vs in self.man_rows:
                    if not cv.get().strip():
                        continue
                    parse_case_spec(cv.get())
                    vals = {}
                    for c, v in vs.items():
                        t = v.get().strip().replace(",", ".")
                        if t:
                            vals[c] = float(t)
                    loads.append(ManualLoad(cv.get().strip(), vals))
            except ValueError as e:
                messagebox.showwarning("Eingabe", f"Ung\u00fcltige Eingabe: {e}", parent=self)
                return
            if not loads:
                messagebox.showwarning("Eingabe", "Bitte mindestens eine Zeile mit Kombinationen ausf\u00fcllen.", parent=self)
                return
            self.result = Assignment(name, self.pos_var.get(), stab=None, manual=loads)
        self.destroy()


def parse_einw_factors(text: str) -> Dict[str, float]:
    """'Qk.HS=0,3; Qk.K=0,6' -> {'Qk.HS': 0.3, 'Qk.K': 0.6}"""
    out: Dict[str, float] = {}
    for part in re.split(r"[;\n]+", text):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"'{part}': bitte als Einwirkung=Faktor angeben, z. B. Qk.HS=0,3")
        k, v = part.split("=", 1)
        out[k.strip()] = float(v.strip().replace(",", "."))
    return out


def fmt_einw_factors(d: Dict[str, float]) -> str:
    return "; ".join(f"{k}={v:g}".replace(".", ",") for k, v in d.items())


class NodeLoadDialog(tk.Toplevel):
    """Knotenlast (Summe Faktor x charakteristische Einwirkung je Kombination) einem IDEA-Bauteil zuweisen."""

    def __init__(self, app, node: int, axes, cmap, initial: Optional[Assignment] = None):
        super().__init__(app)
        self.result: Optional[Assignment] = None
        self.title(f"Knotenlast Kn. {node}")
        self.transient(app)
        frm = ttk.Frame(self, padding=12)
        frm.pack()
        loads = [l for l in app.result.node_loads if l.node == node]
        ttk.Label(frm, text="Charakteristische Knotenlasten (global x/z, Moment um y):").grid(row=0, column=0,
                                                                                       columnspan=2, sticky="w")
        ttk.Label(frm, text="\n".join(f"{l.einw:10s} Fx = {l.fx:8.2f} kN   Fz = {l.fz:8.2f} kN   M = {l.m:7.2f} kNm"
                                      for l in loads), font=("Consolas", 9)).grid(row=1, column=0, columnspan=2,
                                                                                   sticky="w", pady=4)
        ttk.Label(frm, text="IDEA-Bauteil (Name):").grid(row=2, column=0, sticky="w")
        self.name = tk.StringVar(value=initial.idea_name if initial else "")
        ttk.Entry(frm, textvariable=self.name, width=40).grid(row=2, column=1, sticky="w", pady=2)
        ttk.Label(frm, text="Position:").grid(row=3, column=0, sticky="w")
        self.pos = tk.StringVar(value=initial.position if initial else "Ende")
        pcb = ttk.Combobox(frm, textvariable=self.pos, values=list(POSITIONS), width=10, state="readonly")
        pcb.grid(row=3, column=1, sticky="w", pady=2)
        pcb.bind("<<ComboboxSelected>>", lambda e: self.neg.set(self.pos.get() == "Anfang"))
        self.neg = tk.BooleanVar(value=False if initial is None else initial.node_sign < 0)
        ttk.Checkbutton(frm, text="Gegenkraft (Vorzeichen umkehren)", variable=self.neg).grid(
            row=4, column=1, sticky="w")
        ttk.Label(frm, text="Anteil an der Knotenlast (z. B. 0,5 bei zwei Kranbahnen):").grid(row=5, column=0, sticky="w")
        self.fac = tk.StringVar(value=f"{initial.node_factor:g}".replace(".", ",") if initial else "1")
        ttk.Entry(frm, textvariable=self.fac, width=10).grid(row=5, column=1, sticky="w", pady=2)
        ttk.Label(frm, text="Abweichend je Einwirkung (z. B. Qk.HS=0,3; Qk.K=0,6):").grid(row=6, column=0, sticky="w")
        self.ein = tk.StringVar(value=fmt_einw_factors(initial.node_einw) if initial else "")
        ttk.Entry(frm, textvariable=self.ein, width=40).grid(row=6, column=1, sticky="w", pady=2)
        ttk.Label(frm, text="Achsen (Baustatik global x/y/z → IDEA lokal):").grid(row=7, column=0, columnspan=2,
                                                                                sticky="w", pady=(8, 0))
        self.ed = AxesEditor(frm, (initial.axes if initial and initial.axes else axes),
                             (initial.component_map if initial and initial.component_map else cmap))
        self.ed.grid(row=8, column=0, columnspan=2, sticky="w")
        bf = ttk.Frame(frm)
        bf.grid(row=9, column=0, columnspan=2, pady=8)
        ttk.Button(bf, text="OK", command=lambda: self._ok(node)).pack(side="left", padx=4)
        ttk.Button(bf, text="Abbrechen", command=self.destroy).pack(side="left")
        self.grab_set()
        self.wait_window(self)

    def _ok(self, node: int):
        name = self.name.get().strip()
        if not name:
            messagebox.showerror("Knotenlast", "Bitte den IDEA-Bauteilnamen eingeben.", parent=self)
            return
        try:
            axes, cmap = self.ed.get()
        except ValueError as e:
            messagebox.showerror("Achsen", str(e), parent=self)
            return
        try:
            fac = float(self.fac.get().strip().replace(",", ".") or "1")
            ein = parse_einw_factors(self.ein.get())
            a = Assignment(name, self.pos.get(), node=node, axes=axes, component_map=cmap,
                           node_sign=-1.0 if self.neg.get() else 1.0, node_factor=fac, node_einw=ein)
            a.validate()
        except ValueError as e:
            messagebox.showerror("Knotenlast", str(e), parent=self)
            return
        self.result = a
        self.destroy()


class PairDialog(tk.Toplevel):
    """Bestaetigung der Zuordnung IFC-Bauteil <- Baustatik-Stab/Knotenlast. Die Achsen werden im Bild zugewiesen
    (AxisPickDialog); Position und Vorzeichen folgen daraus."""

    def __init__(self, app, m, stab, station):
        super().__init__(app)
        self.app, self.m, self.stab, self.station = app, m, stab, station
        self.result = None
        self.sign = 1.0
        self.factor = 1.0
        self.einw: Dict[str, float] = {}
        self._neg_touched = False
        self._pos_touched = False
        self.picked: Optional[Dict[str, str]] = None
        what = f"Stab {stab} @ {station}" if stab is not None else f"Knotenlast Kn. {station}"
        self.title(f"Zuordnung bestätigen: {m.name} ← {what}")
        self.transient(app)
        self.resizable(False, False)
        self.fr = app.frame_for(m)
        pad = dict(padx=10, pady=3, sticky="w")
        ttk.Label(self, text=f"IDEA-Bauteil: {m.name}  [{m.profile}]", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, columnspan=2, **pad)
        ttk.Label(self, text="Lokale Achsen in IDEA: " + self.fr.describe()
                  + ("   ✓ bestätigt" if app.is_confirmed(m) else "   (nur Vorschlag – nicht bestätigt)")).grid(
            row=1, column=0, columnspan=2, **pad)
        kf = ttk.Frame(self)
        kf.grid(row=2, column=0, columnspan=2, **pad)
        ttk.Button(kf, text="Koordinaten zuweisen …", command=self._pick_axes).pack(side="left")
        self.ax_txt = tk.StringVar(value="")
        ttk.Label(kf, textvariable=self.ax_txt, font=("Consolas", 10)).pack(side="left", padx=10)
        self.det_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="Technische Details anzeigen", variable=self.det_var, command=self._toggle_det).grid(
            row=3, column=0, columnspan=2, **pad)
        self.det = ttk.Frame(self)
        self.axes_ed = AxesEditor(self.det)
        self.axes_ed.grid(row=0, column=0, columnspan=2, **pad)
        pf = ttk.Frame(self.det)
        pf.grid(row=1, column=0, columnspan=2, **pad)
        ttk.Label(pf, text="IDEA-Position:").pack(side="left")
        self.pos = tk.StringVar(value="Ende")
        pcb = ttk.Combobox(pf, textvariable=self.pos, values=list(POSITIONS), width=10, state="readonly")
        pcb.pack(side="left", padx=6)
        pcb.bind("<<ComboboxSelected>>", lambda e: self._pos_changed())
        self.neg = tk.BooleanVar(value=False)
        self.fac = tk.StringVar(value="1")
        self.ein = tk.StringVar(value="")
        ttk.Checkbutton(pf, text="Gegenkraft (Vorzeichen umkehren)" if stab is None else "Vorzeichen umkehren",
                        variable=self.neg, command=lambda: setattr(self, "_neg_touched", True)).pack(side="left", padx=12)
        self.sumtxt = tk.StringVar()
        ttk.Label(self, textvariable=self.sumtxt, font=("Segoe UI", 10, "bold")).grid(row=5, column=0, columnspan=2, **pad)
        if stab is None:
            af = ttk.Frame(self)
            af.grid(row=6, column=0, columnspan=2, sticky="w", padx=10)
            ttk.Label(af, text="Anteil:").pack(side="left")
            ttk.Entry(af, textvariable=self.fac, width=6).pack(side="left", padx=4)
            ttk.Label(af, text="je Einwirkung:").pack(side="left")
            ttk.Entry(af, textvariable=self.ein, width=22).pack(side="left", padx=4)
        bf = ttk.Frame(self)
        bf.grid(row=7, column=0, columnspan=2, pady=8)
        ttk.Button(bf, text="Übernehmen", command=self._ok).pack(side="left", padx=6)
        ttk.Button(bf, text="Abbrechen", command=self.destroy).pack(side="left", padx=6)
        self._update_pos_sign()
        self.grab_set()
        self.after(150, self._pick_axes)
        self.wait_window(self)

    def _toggle_det(self):
        if self.det_var.get():
            self.det.grid(row=4, column=0, columnspan=2, sticky="w")
        else:
            self.det.grid_remove()

    def _pick_axes(self):
        from .axispick import AxisPickDialog
        dlg = AxisPickDialog(self.app, self.m, self.stab, self.station, self.picked)
        if dlg.result:
            self.picked = dict(dlg.result)
            self.axes_ed.set(self.picked, None)
            self.ax_txt.set("   ".join(f"Baustatik {a} = IDEA {v.replace('-', '−').upper()}" for a, v in self.picked.items()))
            self._pos_touched = self._neg_touched = False
            self._update_pos_sign()

    def _update_pos_sign(self):
        from .ifcaxes import position_from_axes, sign_from_axes
        st = self.station if self.stab is not None else ""
        axes = self.picked or {}
        if not self._pos_touched:
            self.pos.set(position_from_axes(self.stab, st, axes, self.m))
        sg = sign_from_axes(self.stab, st, axes, self.pos.get())
        if not self._neg_touched:
            self.neg.set(sg < 0)
        self.sumtxt.set(f"Die Last wirkt am {self.pos.get()} von {self.m.name}  "
                        f"(IDEA-Importtabelle: Zeile „{self.m.name} / {self.pos.get()}“)")

    def _pos_changed(self):
        self._pos_touched = True
        self._update_pos_sign()

    def _ok(self):
        if self.picked is None:
            messagebox.showinfo("Koordinaten", "Bitte zuerst „Koordinaten zuweisen …“ ausführen.", parent=self)
            return
        try:
            axes, cmap = self.axes_ed.get()
        except ValueError as e:
            messagebox.showerror("Achsen", str(e), parent=self)
            return
        try:
            self.factor = float(self.fac.get().strip().replace(",", ".") or "1")
            self.einw = parse_einw_factors(self.ein.get())
        except ValueError as e:
            messagebox.showerror("Anteil", str(e), parent=self)
            return
        self.sign = -1.0 if self.neg.get() else 1.0
        self.result = (self.pos.get(), axes, cmap)
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        try:                                           # eigenes Icon statt der Tk-Feder (gilt auch fuer alle Unterfenster)
            from .icon_data import PNG_B64
            self._icon = tk.PhotoImage(data=PNG_B64)
            self.iconphoto(True, self._icon)
        except Exception:
            pass
        self.title(f"PDF → IDEA StatiCa Lasten-Import  (v{__version__})")
        self.geometry("1150x760")
        self.minsize(900, 520)
        self.pdf_path = ""
        self.result: Optional[ParseResult] = None
        self.assignments: List[Assignment] = []
        self.ifc_path = ""
        self.ifc_members: list = []                   # gelesene IFC-Bauteile
        self.pending_ifc = None                       # gewaehltes IFC-Bauteil (wartet auf Stab)
        self.pending_bs = None                        # gewaehlter (Stab, Stelle) (wartet auf IFC-Bauteil)
        self.ifc_names: Dict[str, str] = {}           # IDEA-Bauteilname -> Name des IFC-Bauteils (manuell gewaehlt)
        self.ifc_tr = dict(IFC_TO_IDEA_DEFAULT)       # IFC -> IDEA global (Achsen aus IFC)
        self.ifc_frames: Dict[str, dict] = {}         # IFC-Name -> {"ex","ey","ez","confirmed"} (angepasste/bestaetigte Achsen)
        self._q: "queue.Queue" = queue.Queue()
        self._build()
        install_tooltips(self)
        tip(self.lb, "Kombinationen, die in die Ausgabe sollen (Mehrfachauswahl mit Strg/Umschalt).")
        tip(self.tree, "Alle Zuordnungen in Importreihenfolge. Doppelklick = bearbeiten.")

    # ---------------------------------------------------------------- UI
    def _build(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Baustatik-Modul:").grid(row=0, column=0, sticky="w")
        self.mods = all_modules()
        self.mod_var = tk.StringVar(value=self.mods[0].label)
        ttk.Combobox(top, textvariable=self.mod_var, values=[m.label for m in self.mods],
                     state="readonly", width=42).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Button(top, text="PDF öffnen…", command=self.open_pdf).grid(row=0, column=2, padx=6)
        self.pdf_lbl = ttk.Label(top, text="(kein PDF geladen)")
        self.pdf_lbl.grid(row=0, column=3, sticky="w")
        self.pb = ttk.Progressbar(top, length=160, mode="determinate")
        self.pb.grid(row=0, column=4, padx=10)
        ttk.Button(top, text="Neu", command=self.new_project, width=8).grid(row=0, column=5, padx=(20, 0))

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=4)

        # links: Bauteile
        left = ttk.LabelFrame(body, text="Zeilen der Importtabelle in IDEA – genau diese Reihenfolge muss in IDEA stehen (automatisch: Bauteile wie in IDEA, Anfang vor Ende)", padding=6)
        body.add(left, weight=3)
        cols = ("name", "src", "pos", "axes", "info")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse", height=14)
        for c, t, w in (("name", "Bauteil (IDEA)", 200), ("src", "Quelle (PDF-Stab @ Stelle)", 190),
                        ("pos", "IDEA-Position", 90), ("axes", "Achsen", 110), ("info", "Info", 240)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self.edit_assignment())
        self.order_var = tk.StringVar(value="")
        self.order_lbl = ttk.Label(left, textvariable=self.order_var, foreground="#2e7d32", wraplength=760, justify="left")
        self.order_lbl.pack(fill="x", pady=(4, 0))
        bl = ttk.Frame(left)
        bl.pack(fill="x", pady=(6, 0))
        for text, cmd in (("Hinzufügen…", self.add_assignment), ("Bearbeiten…", self.edit_assignment),
                          ("Entfernen", self.remove_assignment), ("▲", lambda: self.move(-1)),
                          ("▼", lambda: self.move(1))):
            ttk.Button(bl, text=text, command=cmd, width=12 if len(text) > 2 else 4).pack(side="left", padx=2)
        ttk.Button(bl, text="Modellansicht\u2026", command=self.open_model, width=14).pack(side="left", padx=(12, 2))
        ttk.Button(bl, text="Grafische Zuordnung (IFC)\u2026", command=self.open_graphic, width=26).pack(
            side="left", padx=2)
        ttk.Button(bl, text="Zuordnung laden…", command=self.load_profile).pack(side="right", padx=2)
        ttk.Button(bl, text="Zuordnung speichern…", command=self.save_profile).pack(side="right", padx=2)

        # rechts: Kombinationen + Optionen
        right = ttk.Frame(body)
        body.add(right, weight=2)
        cf = ttk.LabelFrame(right, text="Kombinationen / Einwirkungen", padding=6)
        cf.pack(fill="both", expand=True)
        self.lb = tk.Listbox(cf, selectmode="extended", exportselection=False, height=10)
        sb = ttk.Scrollbar(cf, orient="vertical", command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        cb = ttk.Frame(cf)
        cb.pack(side="left", fill="y", padx=4)
        ttk.Button(cb, text="Alle", command=lambda: self.lb.select_set(0, "end"), width=7).pack(pady=2)
        ttk.Button(cb, text="Keine", command=lambda: self.lb.select_clear(0, "end"), width=7).pack(pady=2)

        of = ttk.LabelFrame(right, text="Ausgabe", padding=6)
        of.pack(fill="x", pady=(6, 0))
        ttk.Label(of, text="Name der Lasteinwirkung:").grid(row=0, column=0, sticky="w")
        self.pat_var = tk.StringVar(value="{name}")
        ttk.Entry(of, textvariable=self.pat_var, width=18).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(of, text="{name} = 'Komb. 1', {nr} = '1'", foreground="#666").grid(row=0, column=2, sticky="w")
        ttk.Label(of, text="Standard-Achsenzuordnung Baustatik \u2192 IDEA (lokal; gilt f\u00fcr Bauteile ohne eigene Zuordnung):"
                  ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.axes_ed = AxesEditor(of)
        self.axes_ed.grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Label(of, text="Vorzeichenfaktor je IDEA-Komponente (nach der Zuordnung):").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        sf = ttk.Frame(of)
        sf.grid(row=4, column=0, columnspan=3, sticky="w")
        self.sign_vars = {}
        for i, c in enumerate(COMPONENTS):
            ttk.Label(sf, text=c).grid(row=0, column=i, padx=4)
            v = tk.StringVar(value="1")
            self.sign_vars[c] = v
            ttk.Entry(sf, textvariable=v, width=5, justify="center").grid(row=1, column=i, padx=4)

        bot = ttk.Frame(self, padding=8)
        bot.pack(fill="x")
        ttk.Button(bot, text="Vorschau", command=self.preview).pack(side="left", padx=2)
        ttk.Button(bot, text="In Zwischenablage", command=self.copy_clip).pack(side="left", padx=2)
        ttk.Button(bot, text="Excel speichern…", command=self.export_excel).pack(side="left", padx=2)
        ttk.Button(bot, text="Fehlende Stellen…", command=self.show_missing).pack(side="left", padx=2)
        self.status = tk.StringVar(value="Bitte ein PDF öffnen.")
        ttk.Label(bot, textvariable=self.status, foreground="#444").pack(side="left", padx=14)

    def new_project(self):
        """Alles zuruecksetzen (PDF, IFC, Zuordnungen, Achsen) – wie ein frischer Programmstart, ohne Neustart."""
        if (self.assignments or self.result or self.ifc_members) and not messagebox.askyesno(
                "Neu", "Alles zurücksetzen (PDF, IFC-Modell und Zuordnungen)?\n\n"
                       "Nicht gespeicherte Zuordnungen gehen verloren (vorher „Zuordnung speichern…“)."):
            return
        for w in list(self.winfo_children()):                      # alle offenen Unterfenster schliessen
            if isinstance(w, tk.Toplevel):
                try:
                    w.destroy()
                except tk.TclError:
                    pass
        for name in ("_mv", "_iv"):
            if hasattr(self, name):
                delattr(self, name)
        self.pdf_path = ""
        self.result = None
        self.assignments = []
        self.ifc_path = ""
        self.ifc_members = []
        self.pending_ifc = self.pending_bs = None
        self.ifc_names = {}
        self.ifc_tr = dict(IFC_TO_IDEA_DEFAULT)
        self.ifc_frames = {}
        self.auto_sort = True
        self.pdf_lbl.config(text="(kein PDF geladen)")
        self.pb["value"] = 0
        self.lb.delete(0, "end")
        self.pat_var.set("{name}")
        for v in self.sign_vars.values():
            v.set("1")
        self._refresh()
        self.status.set("Neu begonnen. Bitte ein PDF öffnen.")

    # ---------------------------------------------------------- PDF laden
    def _module(self):
        for m in self.mods:
            if m.label == self.mod_var.get():
                return m
        return self.mods[0]

    def open_pdf(self):
        p = filedialog.askopenfilename(title="Schnittgrößen-PDF wählen",
                                       filetypes=[("PDF", "*.pdf"), ("Alle Dateien", "*.*")])
        if not p:
            return
        self.pdf_path = p
        self.pdf_lbl.config(text=os.path.basename(p))
        self.status.set("Lese PDF …")
        self.pb["value"] = 0
        mod = self._module()

        def work():
            try:
                res = mod.parse(p, lambda i, n: self._q.put(("prog", i, n)))
                self._q.put(("done", res))
            except Exception as e:  # noqa: BLE001
                self._q.put(("err", str(e)))

        threading.Thread(target=work, daemon=True).start()
        self.after(100, self._poll)

    def _poll(self):
        try:
            while True:
                msg = self._q.get_nowait()
                if msg[0] == "prog":
                    self.pb["maximum"], self.pb["value"] = msg[2], msg[1]
                elif msg[0] == "done":
                    self._loaded(msg[1])
                    return
                else:
                    self.status.set("Fehler beim Lesen.")
                    messagebox.showerror("PDF lesen", msg[1])
                    return
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _loaded(self, res: ParseResult):
        mv = getattr(self, "_mv", None)
        try:
            if mv is not None and mv.winfo_exists():
                mv.destroy()
        except tk.TclError:
            pass
        self.result = res
        self.lb.delete(0, "end")
        for n in res.case_names():
            self.lb.insert("end", n)
        self.lb.select_set(0, "end")
        self._refresh()
        self.status.set(f"{len(res.load_cases)} Kombinationen, {len(res.member_numbers())} Stäbe eingelesen.")

    # ------------------------------------------------------- Zuordnungen
    def _refresh(self):
        if getattr(self, "auto_sort", True):
            self.sort_like_idea()
        try:
            txt, ok = self.order_check()
            self.order_var.set(txt)
            self.order_lbl.configure(foreground="#2e7d32" if ok else "#b35c00")
        except Exception:      # noqa: BLE001
            pass
        self.tree.delete(*self.tree.get_children())
        for i, a in enumerate(self.assignments):
            info = ""
            if a.is_node:
                loads = sorted({l.einw for l in self.result.node_loads if l.node == a.node}) if self.result else []
                info = "Einwirkungen: " + ", ".join(loads)
            elif a.is_manual:
                info = " | ".join(f"Komb. {m.cases}" for m in a.manual)
            elif self.result and a.stab in self.result.members:
                m = self.result.members[a.stab]
                info = f"Kn. {m.node_start}\u2192{m.node_end}, l={m.length:g} m, {m.description}"
            if a.is_node and not a.axes:
                ax = "Standard" if not a.component_map else "eigene"
            elif a.is_manual:
                ax = "manuell"
            elif a.axes:
                ax = ", ".join(f"{k}\u2192{v}" for k, v in a.axes.items())
            else:
                ax = "eigene" if a.component_map else "Standard"
            if sum(1 for b in self.assignments if (b.idea_name, b.position) == (a.idea_name, a.position)) > 1:
                info = "Σ wird mit den anderen Zeilen dieses Bauteils/dieser Position addiert.  " + info
            self.tree.insert("", "end", iid=str(i), values=(a.idea_name, a.describe(), a.position, ax, info))
        self._redraw_views()

    def _sel(self) -> Optional[int]:
        s = self.tree.selection()
        return int(s[0]) if s else None

    def _need_pdf(self) -> bool:
        if not self.result:
            messagebox.showinfo("Hinweis", "Bitte zuerst ein PDF öffnen.")
            return False
        return True

    def add_assignment(self):
        if not self._need_pdf():
            return
        d = AssignmentDialog(self, self.result, [a.idea_name for a in self.assignments], None, *self._defaults())
        if d.result:
            self.assignments.append(d.result)
            self._refresh()

    def edit_assignment(self):
        i = self._sel()
        if i is None or not self._need_pdf():
            return
        cur = self.assignments[i]
        if cur.is_node:
            d = NodeLoadDialog(self, cur.node, *self._defaults(), initial=cur)
        else:
            d = AssignmentDialog(self, self.result, [a.idea_name for a in self.assignments], cur,
                                 *self._defaults())
        if d.result:
            self.assignments[i] = d.result
            self._refresh()
            self.tree.selection_set(str(i))

    def _defaults(self):
        try:
            return self.axes_ed.get()
        except ValueError:
            return dict(IDENTITY_AXES), dict(IDENTITY_MAP)

    def add_from_model(self, stab: int, station: str) -> bool:
        """Von der Modellansicht aufgerufen.

        Mit geladener IFC (grafische Zuordnung): Stab/Stelle merken, bis ein IFC-Bauteil gewaehlt ist (oder umgekehrt).
        Ohne IFC: Dialog mit Bauteilname und Achsen."""
        if self.ifc_members:
            self.pending_bs = (stab, station)
            if self.pending_ifc is not None:
                self._assign_pair(self.pending_ifc, stab, station)
            else:
                self._redraw_views()
            return True
        pos = station if station in POSITIONS else ("Anfang" if station.endswith("R") else "Ende")
        init = Assignment("", pos, stab=stab, station=station)
        d = AssignmentDialog(self, self.result, [a.idea_name for a in self.assignments], init, *self._defaults())
        if d.result:
            self.assignments.append(d.result)
            self._refresh()
            return True
        return False

    def add_node_load(self, node: int) -> bool:
        """Knotenlast (Summe Faktor x charakteristische Einwirkung je Kombination) einem IDEA-Bauteil zuweisen."""
        if self.ifc_members:
            self.pending_bs = (None, node)
            if self.pending_ifc is not None:
                self._assign_pair(self.pending_ifc, None, node)
            else:
                self._redraw_views()
            return True
        d = NodeLoadDialog(self, node, *self._defaults())
        if d.result:
            self.assignments.append(d.result)
            self._refresh()
            return True
        return False

    # ------------------------------------------------- grafische Zuordnung (IFC)
    def pick_ifc(self, m) -> None:
        """Von der IFC-Ansicht aufgerufen: Bauteil gewaehlt."""
        self.pending_ifc = m
        if self.pending_bs is not None:
            stab, station = self.pending_bs
            self._assign_pair(m, stab, station)
        else:
            self._redraw_views()

    def pair_status(self) -> str:
        a = self.pending_ifc
        b = self.pending_bs
        if b is not None and b[0] is None:
            b = (f"Knotenlast Kn. {b[1]}", "")
        if a is None and b is None:
            return "Schritt 1: IFC-Bauteil anklicken (hier), Schritt 2: Stab oder Knoten in der Modellansicht anklicken (oder umgekehrt)."
        if a is not None and b is None:
            return f"Gewählt: IFC-Bauteil '{a.name}'. Jetzt in der Modellansicht den zugehörigen Knoten oder Stab anklicken."
        if a is None:
            return (f"Gewählt: {b[0]}" if isinstance(b[0], str) else f"Gewählt: Stab {b[0]} @ {b[1]}") + \
                ". Jetzt das zugehörige IFC-Bauteil anklicken."
        return "Zuordnung wird angelegt …"

    # --- lokale IDEA-Achsen je IFC-Bauteil (Vorschlag, angepasst, bestaetigt)
    def frame_for(self, m):
        from .ifcaxes import IdeaFrame, idea_frame
        d = self.ifc_frames.get(m.name)
        base = idea_frame(m, self.ifc_tr)
        if d and "ex" in d:
            fr = IdeaFrame.from_dict(m.name, d)
            fr.notes = list(base.notes)
            return fr
        return base

    def is_confirmed(self, m) -> bool:
        return bool(self.ifc_frames.get(m.name, {}).get("confirmed"))

    def is_modified(self, m) -> bool:
        return "ex" in self.ifc_frames.get(m.name, {})

    def set_frame(self, m, fr, confirmed: bool = False) -> None:
        d = fr.to_dict()
        d["confirmed"] = confirmed
        self.ifc_frames[m.name] = d

    def reset_frame(self, m) -> None:
        self.ifc_frames.pop(m.name, None)

    def _assign_pair(self, m, stab: int, station: str) -> None:
        from .ifcaxes import idea_position
        dlg = PairDialog(self, m, stab, station)
        res = dlg.result
        if res is None:
            self.pending_bs = None
            self._redraw_views()
            return
        pos, axes, cmap = res
        if stab is None:
            a = Assignment(m.name, pos, node=int(station), axes=dict(axes), component_map=dict(cmap),
                           node_sign=dlg.sign, node_factor=dlg.factor, node_einw=dlg.einw)
        else:
            a = Assignment(m.name, pos, stab=stab, station=station, axes=dict(axes), component_map=dict(cmap),
                           sign=dlg.sign)
        a.validate()
        dup = any((b.idea_name, b.position) == (a.idea_name, a.position) for b in self.assignments)
        self.assignments.append(a)
        self.sort_like_idea()
        self.pending_ifc = self.pending_bs = None
        self._refresh()
        self.status.set(f"#{len(self.assignments)}: {m.name} \u2190 {a.describe()}, IDEA-Position {pos}, Achsen "
                        + ", ".join(f"{k}={v}" for k, v in axes.items())
                        + (f"  –  {m.name}/{pos} war schon belegt: Werte werden addiert (Σ)." if dup else ""))

    def sort_like_idea(self) -> None:
        """Importtabelle in IDEA: Bauteile in der Reihenfolge der IFC/IDEA-Bauteilliste, je Bauteil Anfang vor Ende.
        Die Zeilen werden beim Einfuegen *nach Position* zugeordnet, deshalb muss die Reihenfolge genau stimmen."""
        order = {}
        for mm in self.ifc_members or []:
            if not mm.name.strip().startswith("(") and mm.name not in order:
                order[mm.name] = len(order)
        if not order:
            return
        big = len(order) + 1
        self.assignments.sort(key=lambda a: (order.get(a.idea_name, big), 0 if a.position == "Anfang" else 1))

    def expected_rows(self):
        from .ifcaxes import idea_rows
        return idea_rows(self.ifc_members or [])

    def order_check(self):
        """(Text, vollstaendig?) Vergleich der Zuordnungen mit den Zeilen der IDEA-Importtabelle laut IFC."""
        exp = self.expected_rows()
        if not exp:
            return "", True
        have = {(a.idea_name, a.position) for a in self.assignments}
        parts = [f"{n}/{p} {'✓' if (n, p) in have else '✗ fehlt'}" for n, p in exp]
        extra = [f"{a.idea_name}/{a.position}" for a in self.assignments if (a.idea_name, a.position) not in set(exp)]
        txt = "IDEA-Tabelle laut IFC:  " + "   ".join(parts)
        if extra:
            txt += "\nGibt es in IDEA nicht: " + ", ".join(extra)
        missing = any("fehlt" in t for t in parts)
        if missing:
            txt += "\nFehlende Zeilen werden mit Nullen aufgefüllt, damit nichts verrutscht."
        return txt, not missing and not extra

    def filled_assignments(self):
        """Zuordnungen in IDEA-Reihenfolge; fehlende IDEA-Zeilen als Nullzeilen, damit die Positionen beim Einfuegen stimmen."""
        a = list(self.assignments)
        exp = self.expected_rows()
        if not exp or not getattr(self, "auto_sort", True):
            return a
        have = {(x.idea_name, x.position) for x in a}
        for n, p in exp:
            if (n, p) not in have:
                a.append(Assignment(n, p))
        order = {}
        for i, (n, p) in enumerate(exp):
            order[(n, p)] = i
        a.sort(key=lambda x: order.get((x.idea_name, x.position), len(order)))
        return a

    def load_ifc(self, path: str) -> bool:
        from .ifc import read_members
        try:
            self.ifc_members = read_members(path)
        except Exception as e:      # noqa: BLE001
            messagebox.showerror("IFC", f"Datei konnte nicht gelesen werden:\n{e}")
            return False
        self.ifc_path = path
        return True

    def open_graphic(self):
        """Grafische Zuordnung: Modellansicht (Baustatik) + IFC-Ansicht nebeneinander."""
        if not self._need_pdf():
            return
        if not self.ifc_members:
            p = filedialog.askopenfilename(title="IFC aus IDEA Connection wählen",
                                           filetypes=[("IFC", "*.ifc"), ("Alle Dateien", "*.*")])
            if not p or not self.load_ifc(p):
                return
        self.pending_ifc = self.pending_bs = None
        self.open_model()
        from .ifcview import IfcView
        iv = getattr(self, "_iv", None)
        try:
            if iv is not None and iv.winfo_exists():
                iv.reload()
                iv.lift()
                return
        except tk.TclError:
            pass
        self._iv = IfcView(self)

    def _redraw_views(self):
        for name in ("_mv", "_iv"):
            v = getattr(self, name, None)
            if v is None:
                continue
            try:
                if v.winfo_exists():
                    v.redraw()
            except tk.TclError:
                pass

    def open_model(self):
        if not self._need_pdf():
            return
        if not self.result.nodes:
            messagebox.showinfo("Modellansicht", "Im PDF wurde keine Knotendefinition gefunden.")
            return
        mv = getattr(self, "_mv", None)
        try:
            if mv is not None and mv.winfo_exists():
                mv.lift()
                return
        except tk.TclError:
            pass
        self._mv = ModelView(self, self.result)

    def remove_assignment(self):
        i = self._sel()
        if i is not None:
            del self.assignments[i]
            self._refresh()

    def move(self, d: int):
        i = self._sel()
        if i is None or not 0 <= i + d < len(self.assignments):
            return
        a = self.assignments
        a[i], a[i + d] = a[i + d], a[i]
        self.auto_sort = False                      # von Hand sortiert: nicht mehr automatisch
        self._refresh()
        self.tree.selection_set(str(i + d))

    # ------------------------------------------------------------ Profil
    def _profile(self, export: bool = False) -> Profile:
        signs = {}
        for c, v in self.sign_vars.items():
            try:
                signs[c] = float(v.get().replace(",", "."))
            except ValueError:
                raise ValueError(f"Vorzeichenfaktor '{c}' ist keine Zahl.")
        axes, cmap = self.axes_ed.get()
        sel = [self.lb.get(i) for i in self.lb.curselection()]
        return Profile(axes=axes, component_map=cmap, module_id=self._module().id,
                       assignments=self.filled_assignments() if export else list(self.assignments),
                       name_pattern=self.pat_var.get() or "{name}", signs=signs,
                       selected_cases=sel, ifc_axes=dict(self.ifc_tr),
                       ifc_frames=dict(self.ifc_frames))

    def save_profile(self):
        try:
            p = self._profile()
        except ValueError as e:
            messagebox.showerror("Zuordnung", str(e))
            return
        p.selected_cases = []
        path = filedialog.asksaveasfilename(title="Zuordnung speichern", defaultextension=".json",
                                            filetypes=[("Zuordnung (JSON)", "*.json")])
        if path:
            p.save(path)
            self.status.set(f"Zuordnung gespeichert: {os.path.basename(path)}")

    def load_profile(self):
        path = filedialog.askopenfilename(title="Zuordnung laden", filetypes=[("Zuordnung (JSON)", "*.json")])
        if not path:
            return
        try:
            p = Profile.load(path)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Zuordnung", f"Datei konnte nicht gelesen werden:\n{e}")
            return
        self.assignments = p.assignments
        self.pat_var.set(p.name_pattern)
        for c, v in self.sign_vars.items():
            v.set(f"{p.signs.get(c, 1.0):g}")
        self.axes_ed.set(p.axes, p.component_map)
        if p.ifc_axes:
            self.ifc_tr = dict(p.ifc_axes)
        self.ifc_frames = dict(p.ifc_frames)
        for m in self.mods:
            if m.id == p.module_id:
                self.mod_var.set(m.label)
        self._refresh()
        self.status.set(f"Zuordnung geladen: {os.path.basename(path)}")

    # ------------------------------------------------------------ Ausgabe
    def _rows(self):
        if not self._need_pdf():
            return None
        try:
            rows, warns = build_rows(self.result, self._profile(export=True))
        except ValueError as e:
            messagebox.showwarning("Ausgabe", str(e))
            return None
        if warns:
            messagebox.showwarning("Warnung", "\n\n".join(warns[:8]) + ("\n…" if len(warns) > 8 else ""))
        return rows

    def show_missing(self):
        """Welche Stellen (Stab, x) fehlen im PDF und muessen in der Baustatik zusaetzlich ausgegeben werden?"""
        if not self._need_pdf():
            return
        try:
            miss = missing_stations(self.result, self._profile(export=True))
        except ValueError as e:
            messagebox.showwarning("Fehlende Stellen", str(e))
            return
        if not miss:
            messagebox.showinfo("Fehlende Stellen", "Alle zugeordneten Stellen stehen in allen gewählten Kombinationen im PDF.\n"
                                "Es wird nichts interpoliert.")
            return
        txt = missing_text(miss)
        win = tk.Toplevel(self)
        win.title("Zusätzliche Ausgabe in der Baustatik")
        win.geometry("760x380")
        t = tk.Text(win, wrap="word", font=("Consolas", 10))
        t.insert("1.0", txt)
        t.configure(state="disabled")
        t.pack(fill="both", expand=True, padx=8, pady=8)

        def copy():
            self.clipboard_clear()
            self.clipboard_append(txt)
        ttk.Button(win, text="Kopieren", command=copy).pack(pady=(0, 8))

    def _load_view(self, rows):
        if not self.ifc_members:
            messagebox.showinfo("Grafische Vorschau", "Bitte zuerst eine IFC-Datei laden („Grafische Zuordnung (IFC)…“).")
            return
        from .loadview import LoadView
        LoadView(self, rows)

    def preview(self):
        rows = self._rows()
        if rows is None:
            return
        win = tk.Toplevel(self)
        win.title(f"Vorschau ({len(rows)} Zeilen)")
        win.geometry("980x520")
        bar = ttk.Frame(win)
        bar.pack(fill="x", padx=6, pady=4)
        ttk.Button(bar, text="Grafisch in IFC-Ansicht …", command=lambda: self._load_view(rows)).pack(side="left")
        t = ttk.Treeview(win, columns=HEADERS, show="headings")
        for h in HEADERS:
            t.heading(h, text=h)
            t.column(h, width=170 if h == "Bauteil" else 90, anchor="w" if h in HEADERS[:3] else "e")
        t.tag_configure("warn", background="#ffd9a8")
        for r in rows:
            t.insert("", "end", values=[r.name, r.member, r.position] + [f"{v:.2f}" for v in r.values],
                     tags=("warn",) if "interpoliert" in r.warning else ())
        sb = ttk.Scrollbar(win, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")

    def copy_clip(self):
        rows = self._rows()
        if rows is None:
            return
        self.clipboard_clear()
        self.clipboard_append(fmt_tsv(rows))
        self.status.set(f"{len(rows)} Zeilen in der Zwischenablage (nur N, Vy, Vz, Mx, My, Mz; ohne Kopfzeile, Dezimalkomma).")

    def export_excel(self):
        rows = self._rows()
        if rows is None:
            return
        base = os.path.splitext(os.path.basename(self.pdf_path))[0]
        path = filedialog.asksaveasfilename(title="Excel speichern", defaultextension=".xlsx",
                                            initialfile=f"{base}_IDEA.xlsx",
                                            initialdir=os.path.dirname(self.pdf_path) or None,
                                            filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        try:
            write_excel(path, rows, self._profile(export=True), self.pdf_path, self._module().label)
        except PermissionError:
            messagebox.showerror("Excel", "Datei kann nicht geschrieben werden (ist sie in Excel geöffnet?).")
            return
        self.status.set(f"{len(rows)} Zeilen gespeichert: {os.path.basename(path)}")


def run():
    App().mainloop()
