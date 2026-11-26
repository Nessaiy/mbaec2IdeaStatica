"""Dialog 'Achsen aus IFC': IFC aus IDEA Connection einlesen, lokale IDEA-Achsen je Bauteil bestimmen
und die Achsenzuordnung Baustatik -> IDEA je Stab vorschlagen."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional

from .axes import describe
from .ifc import IfcMember, read_members
from .ifcaxes import (CHOICES, GLOBAL_DEFAULT, IFC_TO_IDEA_DEFAULT, Suggestion, idea_frame, ifc_det,
                      match_member, suggest_axes, validate_ifc_axes)


class IfcDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Achsen aus IFC (IDEA Connection) ermitteln")
        self.geometry("1100x640")
        self.members: List[IfcMember] = []
        self.sugg: Dict[str, Suggestion] = {}          # Treeview-Item -> Vorschlag
        self.item_index: Dict[str, int] = {}           # Treeview-Item -> Index in app.assignments

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Button(top, text="IFC-Datei wählen…", command=self.choose).grid(row=0, column=0, padx=(0, 8))
        self.path_lbl = ttk.Label(top, text="(keine Datei)")
        self.path_lbl.grid(row=0, column=1, sticky="w")

        f1 = ttk.LabelFrame(self, text="IFC-Koordinaten → IDEA-Global (Drehung der IFC gegenüber IDEA; "
                                       "Vorgabe aus dem Beispiel C1-D1)", padding=6)
        f1.pack(fill="x", padx=8, pady=2)
        self.tr_vars: Dict[str, tk.StringVar] = {}
        for i, a in enumerate("xyz"):
            ttk.Label(f1, text=f"IDEA {a} =").grid(row=0, column=2 * i, padx=(6, 2))
            v = tk.StringVar(value=app.ifc_tr[a])
            self.tr_vars[a] = v
            ttk.Combobox(f1, textvariable=v, values=list(CHOICES), width=4, state="readonly").grid(
                row=0, column=2 * i + 1, padx=(0, 10))
        ttk.Label(f1, text="(± IFC-Achse)", foreground="#666").grid(row=0, column=6)

        f2 = ttk.LabelFrame(self, text="Baustatik → IDEA-Global (einmalig; y der Baustatik ergibt sich aus z × x)",
                            padding=6)
        f2.pack(fill="x", padx=8, pady=2)
        self.gl_vars: Dict[str, tk.StringVar] = {}
        for i, (a, txt) in enumerate((("x", "Baustatik x (nach rechts) ="), ("z", "Baustatik z (nach oben) ="))):
            ttk.Label(f2, text=txt).grid(row=0, column=2 * i, padx=(6, 2))
            v = tk.StringVar(value=app.ifc_glob[a])
            self.gl_vars[a] = v
            ttk.Combobox(f2, textvariable=v, values=list(CHOICES), width=4, state="readonly").grid(
                row=0, column=2 * i + 1, padx=(0, 14))
        ttk.Label(f2, text="= Richtung in IDEA-Global", foreground="#666").grid(row=0, column=4)
        ttk.Button(f2, text="Neu berechnen", command=self.compute).grid(row=0, column=5, padx=20)
        self.msg = ttk.Label(self, text="", foreground="#b00020")
        self.msg.pack(fill="x", padx=10)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=4)
        t1 = ttk.Frame(nb)
        t2 = ttk.Frame(nb)
        nb.add(t1, text="Zuordnungen (Vorschlag)")
        nb.add(t2, text="IFC-Bauteile (Kontrolle)")
        cols = ("name", "stab", "idea", "axes", "map", "note")
        self.tv = ttk.Treeview(t1, columns=cols, show="headings", selectmode="extended")
        for c, t, w in (("name", "Bauteil", 200), ("stab", "PDF-Stab", 70), ("idea", "Lokale IDEA-Achsen (global)", 270),
                        ("axes", "Vorschlag Achsen", 150), ("map", "Komponenten IDEA ← Baustatik", 230),
                        ("note", "Hinweise", 320)):
            self.tv.heading(c, text=t)
            self.tv.column(c, width=w, anchor="w")
        self.tv.pack(fill="both", expand=True)
        self.tv.bind("<Double-1>", self.pick_member)
        self.tv2 = ttk.Treeview(t2, columns=("name", "prof", "axes", "body"), show="headings")
        for c, t, w in (("name", "Bauteil", 260), ("prof", "Profil", 120), ("axes", "Lokale Achsen in IDEA-Global", 330),
                        ("body", "Körper relativ zum Ursprung (Stabachse)", 260)):
            self.tv2.heading(c, text=t)
            self.tv2.column(c, width=w, anchor="w")
        self.tv2.pack(fill="both", expand=True)

        bf = ttk.Frame(self, padding=8)
        bf.pack(fill="x")
        ttk.Button(bf, text="Auswahl übernehmen", command=lambda: self.apply(False)).pack(side="left", padx=2)
        ttk.Button(bf, text="Alle Vorschläge übernehmen", command=lambda: self.apply(True)).pack(side="left", padx=2)
        ttk.Button(bf, text="Schließen", command=self.destroy).pack(side="right", padx=2)
        self.info = ttk.Label(bf, text="Übernommen wird als eigene Achsenzuordnung je Bauteil (überschreibt die bisherige).",
                              foreground="#666")
        self.info.pack(side="left", padx=14)
        if app.ifc_path and os.path.exists(app.ifc_path):
            self.load(app.ifc_path)

    # --------------------------------------------------------------
    def choose(self):
        p = filedialog.askopenfilename(title="IFC aus IDEA Connection wählen", parent=self,
                                       filetypes=[("IFC", "*.ifc"), ("Alle Dateien", "*.*")])
        if p:
            self.load(p)

    def load(self, path: str):
        try:
            self.members = read_members(path)
        except Exception as e:          # noqa: BLE001
            messagebox.showerror("IFC", f"Datei konnte nicht gelesen werden:\n{e}", parent=self)
            return
        self.app.ifc_path = path
        self.app.ifc_members = self.members
        self.path_lbl.config(text=f"{os.path.basename(path)}   ({len(self.members)} Stabbauteile)")
        self.compute()

    def _read_settings(self) -> Optional[tuple]:
        tr = {a: v.get() for a, v in self.tr_vars.items()}
        gl = {a: v.get() for a, v in self.gl_vars.items()}
        try:
            validate_ifc_axes(tr)
        except ValueError as e:
            self.msg.config(text=str(e))
            return None
        if gl["x"][1] == gl["z"][1]:
            self.msg.config(text="Baustatik x und z müssen verschiedene IDEA-Achsen sein.")
            return None
        txt = ""
        if ifc_det(tr) < 0:
            txt = "Achtung: Diese IFC-Zuordnung spiegelt das Modell (keine Drehung) – vermutlich falsch."
        self.msg.config(text=txt)
        self.app.ifc_tr, self.app.ifc_glob = tr, gl
        return tr, gl

    def compute(self):
        st = self._read_settings()
        if st is None or not self.members:
            return
        tr, gl = st
        for tv in (self.tv, self.tv2):
            tv.delete(*tv.get_children())
        self.sugg.clear()
        self.item_index.clear()
        for m in self.members:
            if m.ifc_type not in ("IFCBEAM", "IFCCOLUMN", "IFCMEMBER"):
                continue
            fr = idea_frame(m, tr)
            side = ("beidseitig" if m.t_min < -0.0005 and m.t_max > 0.0005
                    else ("auf + Seite" if m.t_min >= -0.0005 else "auf - Seite"))
            self.tv2.insert("", "end", values=(m.name, m.profile, fr.describe(),
                                               f"{side}  [{m.t_min:.2f} … {m.t_max:.2f} m]"))
        res = self.app.result
        for i, a in enumerate(self.app.assignments):
            if a.stab is None:
                continue
            m = None
            chosen = self.app.ifc_names.get(a.idea_name)
            if chosen:
                m = next((x for x in self.members if x.name == chosen), None)
            if m is None:
                m = match_member(a.idea_name, self.members)
            if m is None:
                iid = self.tv.insert("", "end", values=(a.idea_name, a.stab, "–", "–", "–",
                                                        "Kein IFC-Bauteil mit diesem Namen – Doppelklick: Bauteil wählen"))
                self.item_index[iid] = i
                continue
            fr = self.app.frame_for(m) if tr == self.app.ifc_tr else idea_frame(m, tr)
            s = suggest_axes(res, a.stab, fr, gl)
            ax = ", ".join(f"{k}={v}" for k, v in s.axes.items()) if s.axes else "–"
            cm = ", ".join(f"{k}←{v}" for k, v in s.component_map.items()) if s.component_map else "–"
            iid = self.tv.insert("", "end", values=(a.idea_name, a.stab, fr.describe(), ax, cm,
                                                    " | ".join([f"IFC: {m.name}"] + s.notes)))
            self.sugg[iid] = s
            self.item_index[iid] = i
        if not self.item_index:
            self.info.config(text="Keine Zuordnung mit PDF-Stab und passendem IFC-Namen gefunden.")

    def pick_member(self, event=None):
        sel = self.tv.selection()
        if not sel or not self.members:
            return
        iid = sel[0]
        a = self.app.assignments[self.item_index[iid]]
        win = tk.Toplevel(self)
        win.title(f"IFC-Bauteil für '{a.idea_name}'")
        win.transient(self)
        lb = tk.Listbox(win, width=70, height=min(20, len(self.members)), exportselection=False)
        names = [m.name for m in self.members if m.ifc_type in ("IFCBEAM", "IFCCOLUMN", "IFCMEMBER")]
        for n in names:
            lb.insert("end", n)
        lb.pack(padx=8, pady=8)

        def ok(_e=None):
            if lb.curselection():
                self.app.ifc_names[a.idea_name] = names[lb.curselection()[0]]
                win.destroy()
                self.compute()
        lb.bind("<Double-1>", ok)
        ttk.Button(win, text="Zuordnen", command=ok).pack(pady=(0, 8))
        win.grab_set()

    def apply(self, all_: bool):
        ids = list(self.sugg) if all_ else [i for i in self.tv.selection() if i in self.sugg]
        ids = [i for i in ids if self.sugg[i].axes]
        if not ids:
            messagebox.showinfo("IFC", "Kein übernehmbarer Vorschlag ausgewählt.", parent=self)
            return
        flagged = [i for i in ids if self.sugg[i].notes]
        if flagged and not messagebox.askyesno(
                "Hinweise", f"{len(flagged)} von {len(ids)} Vorschlägen haben Hinweise (Spalte 'Hinweise').\n"
                            "Trotzdem übernehmen?", parent=self):
            return
        for iid in ids:
            a = self.app.assignments[self.item_index[iid]]
            a.axes = dict(self.sugg[iid].axes)
            a.component_map = dict(self.sugg[iid].component_map)
        self.app._refresh()
        self.info.config(text=f"{len(ids)} Zuordnung(en) übernommen.")
