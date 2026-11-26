"""Mouseover-Hinweise (Tooltips) fuer alle Bedienelemente.

Die Texte stehen unten in TIPS. Schluessel = Beschriftung des Elements (Anfang des Textes genuegt).
Eingabefelder ohne eigene Beschriftung (Textfeld, Auswahlliste) erben den Hinweis der Beschriftung links davon.
Mit install(root) werden alle Fenster beim ersten Anzeigen automatisch ausgestattet."""
from __future__ import annotations

from typing import Dict, Optional

try:
    import tkinter as tk
    from tkinter import ttk
    _INPUT = (ttk.Entry, ttk.Combobox, ttk.Spinbox)
except ImportError:          # z. B. Testumgebung ohne tkinter
    tk = ttk = None          # type: ignore
    _INPUT = ()

DELAY_MS = 450

# (Anfang der Beschriftung, Hinweistext) - der erste passende Eintrag gilt
TIPS = [
    # --- Hauptfenster
    ("Baustatik-Modul", "Programm, aus dem das PDF stammt. Derzeit: mb AEC Baustatik S601.de (Stabwerk, 2D)."),
    ("Neu", "Setzt alles zurück (PDF, IFC-Modell, Zuordnungen) und schließt die Fenster – wie ein Neustart des Programms."),
    ("Fehlende Stellen", "Listet Stäbe und Stellen x, die im PDF nicht in allen Kombinationen stehen. Dafür in der Baustatik eine zusätzliche Ausgabe anlegen, sonst wird interpoliert."),
    ("PDF öffnen", "Liest das Baustatik-PDF ein: Stäbe, Knoten, Schnittgrößen je Kombination, Knotenlasten und Kombinationsvorschriften."),
    ("Hinzufügen", "Neue Zuordnung anlegen: ein IDEA-Bauteil bekommt Schnittgrößen eines PDF-Stabes (oder manuelle Lasten)."),
    ("Bearbeiten", "Markierte Zuordnung ändern (auch per Doppelklick auf die Zeile)."),
    ("Entfernen", "Markierte Zuordnung löschen."),
    ("▲", "Markierte Zuordnung in der Importreihenfolge nach oben schieben. Die Reihenfolge entspricht der Reihenfolge der Bauteile im IDEA-Import."),
    ("▼", "Markierte Zuordnung in der Importreihenfolge nach unten schieben."),
    ("Modellansicht", "Zeigt das Stabwerk aus dem PDF. Knoten oder Stab anklicken, um Schnittgrößen einem IDEA-Bauteil zuzuweisen."),
    ("Grafische Zuordnung (IFC)", "Öffnet die 3D-IFC-Ansicht aus IDEA Connection neben der Modellansicht: erst IFC-Bauteil anklicken, dann Stab/Knoten im Modell. Achsen werden vorgeschlagen."),
    ("Achsen aus IFC", "Tabelle: Schlägt für alle bestehenden Zuordnungen die lokalen Achsen aus der IFC-Datei vor und übernimmt sie auf Wunsch."),
    ("Zuordnung laden", "Lädt eine gespeicherte Zuordnung (Bauteile, Stellen, Achsen, bestätigte IFC-Achsen) aus einer JSON-Datei."),
    ("Zuordnung speichern", "Speichert alle Zuordnungen inkl. Achsen und bestätigter IFC-Achsen in einer JSON-Datei zur Wiederverwendung."),
    ("Alle", "Alle Kombinationen für die Ausgabe auswählen."),
    ("Keine", "Alle Kombinationen abwählen."),
    ("Name der Lasteinwirkung", "Bezeichnung der Lastfälle in IDEA. {name} = 'Komb. 1', {nr} = '1'."),
    ("Standard-Achsenzuordnung", "Gilt für alle Bauteile ohne eigene Achsenzuordnung. Gibt an, welche IDEA-Achse zu x/y/z der Baustatik gehört."),
    ("Vorzeichenfaktor", "Faktor je IDEA-Komponente, nach der Achsenzuordnung angewendet (z. B. -1 zum Umkehren). Gilt nur für PDF-Schnittgrößen."),
    ("Vorschau", "Zeigt die fertige Ausgabetabelle (Name, Bauteil, Position, N, Vy, Vz, Mx, My, Mz)."),
    ("In Zwischenablage", "Kopiert nur die sechs Kraftspalten ohne Kopfzeile (Dezimalkomma) zum Einfügen in 'Import von Lasten' in IDEA StatiCa."),
    ("Excel speichern", "Schreibt die Ausgabe als Excel-Datei (Blatt 'IDEA-Import', 'Nur Werte', 'Info')."),
    # --- Grafische Lastvorschau
    ("Grafisch in IFC-Ansicht", "Zeigt die Lasten der gewählten Kombination als Pfeile (Kräfte grün, Momente rot) an den Bauteilenden in der 3D-IFC-Ansicht, in den lokalen Achsen wie in IDEA. Mit ◀ ▶ blätterst du durch die Kombinationen."),
    # --- Bildliche Achsenzuordnung
    ("Koordinaten zuweisen", "Öffnet das Bild zum Zuordnen der Achsen: links das IDEA-Bauteil, rechts die Baustatik-Achsen. Erst eine Achsenspitze links anklicken, dann die gleiche Richtung rechts. Das Vorzeichen ergibt sich aus der angeklickten Seite (+ oder −)."),
    ("Technische Details", "Blendet die rechnerischen Einstellungen ein (globale Ausrichtung, Achsen-Auswahllisten, Komponenten). Normalerweise nicht nötig."),
    ("Rechte Ansicht wie links", "Dreht das Baustatik-Bild (rechts) in dieselbe Blickrichtung wie das IDEA-Bild (links) – erleichtert das Zuordnen."),
    ("Vorschlag", "Setzt die Zuordnung auf den Vorschlag des Programms zurück (aus der IFC-Lage berechnet)."),
    # --- Achsen
    ("Standard", "Setzt die Achsenzuordnung zurück: Baustatik x/y/z = IDEA x/y/z."),
    ("(Baustatik) =", "Welche IDEA-Achse entspricht dieser Achse der Baustatik? Beispiel: 'x (Baustatik) = +z' heißt: die Stabachse x liegt in IDEA entlang +z. Jede IDEA-Achse darf nur einmal vorkommen."),
    ("Erweitert", "Zeigt die Komponenten-Tabelle (N, Vy, Vz, Mx, My, Mz), die aus den Achsen berechnet wird, zum Einzelnen-Ändern. Nur für Sonderfälle."),
    ("IDEA-Komponente", "Für jede IDEA-Komponente: welche Baustatik-Komponente (mit Vorzeichen) wird dort eingesetzt, '0' = leer."),
    # --- Zuordnungsdialog
    ("Bauteil in IDEA", "Name des Bauteils exakt wie in IDEA StatiCa Connection."),
    ("IDEA-Bauteil (Name)", "Name des Bauteils exakt wie in IDEA StatiCa Connection (z. B. 'Kranbahnträger rechts')."),
    ("Position im IDEA", "'Anfang' oder 'Ende' des Bauteils in IDEA, an dem die Kräfte angesetzt werden (Ursprung des Bauteils = Anfang)."),
    ("IDEA-Position", "'Anfang' oder 'Ende' des Bauteils in IDEA, an dem die Kräfte angesetzt werden (Ursprung des Bauteils = Anfang)."),
    ("Position:", "'Anfang' oder 'Ende' des Bauteils in IDEA, an dem die Kräfte angesetzt werden."),
    ("Stab im PDF", "Welcher Stab der Baustatik liefert die Schnittgrößen?"),
    ("Schnittgrößen an Stelle", "Stelle x [m] entlang des Stabes. Bei Sprung (Einzellast/Stabende): L = links, R = rechts der Stelle."),
    ("Kombinationen:", "Für welche Kombinationen gelten diese Werte? Beispiele: 1-20  |  21-35, 40  |  alle."),
    ("Zeile +", "Weitere Zeile mit Werten für einen anderen Kombinationsbereich."),
    ("Zeile −", "Markierte Zeile entfernen."),
    # --- Knotenlast
    ("Knotenlast je Kombination", "Bildet aus den Einwirkungen am Knoten (z. B. Kranlasten Qk.K, Qk.HM, Qk.HS) je Kombination die Summe Faktor × Last und gibt sie einem IDEA-Bauteil."),
    ("Charakteristische Knotenlasten", "Lasten aus dem PDF ohne Teilsicherheits- und Kombinationsbeiwerte. Fx, Fz: global; M: um y."),
    ("Gegenkraft", "Äußere Kräfte (z. B. Kran) wirken auf das Bauteil, IDEA erwartet die Gegenkraft des Anschlusses: Vorzeichen aller Werte wird umgekehrt. Normalerweise angehakt lassen."),
    ("Vorzeichen umkehren", "Kehrt das Vorzeichen aller Schnittgrößen dieser Zuordnung um. Nötig, wenn das Bauteil in IDEA auf der anderen Seite der Schnittstelle liegt als im Stab der Baustatik (z. B. Unterseite eines durchlaufenden Profils). Mit bekannter Last prüfen."),
    ("Anteil", "Anteil der Knotenlast für dieses Bauteil, z. B. 0,5 bei zwei gleich belasteten Kranbahnen. 1 = 100 %. Die Anteile aller Bauteile sollten zusammen 1 ergeben."),
    ("Abweichend je Einwirkung", "Eigener Anteil für einzelne Lastarten, z. B. Qk.HS=0,3; Qk.K=0,6 (0 = weglassen). Überschreibt den allgemeinen Anteil. Leer lassen, wenn alle gleich geteilt werden."),
    ("je Einwirkung", "Eigener Anteil für einzelne Lastarten, z. B. Qk.HS=0,3; Qk.K=0,6 (0 = weglassen). Überschreibt den allgemeinen Anteil. Leer lassen, wenn alle gleich geteilt werden."),
    ("Weiter", "Zu den gewählten Stäben bzw. Stabenden weitergehen."),
    # --- Bestätigungsdialog
    ("Baustatik-Modell → IDEA global", "Wie liegt das Baustatik-Modell im globalen IDEA-Modell? Standard: Baustatik x = IDEA +x (nach rechts), z = +z (nach oben)."),
    ("Baustatik x =", "Richtung der Baustatik-x-Achse (nach rechts) im globalen IDEA-Modell."),
    ("Baustatik z =", "Richtung der Baustatik-z-Achse (nach oben) im globalen IDEA-Modell."),
    ("Übernehmen", "Zuordnung mit diesen Achsen, Position und Faktoren anlegen."),
    ("Abbrechen", "Dialog schließen ohne Änderung."),
    ("OK", "Übernehmen."),
    # --- IFC-Ansicht
    ("Ansicht:", "Freie 3D-Ansicht (Ziehen = drehen) oder feste Ansichten Vorne, Seite, Oben."),
    ("Alles anzeigen", "Zoom so setzen, dass alles sichtbar ist."),
    ("Namen", "Bauteilnamen im Bild ein-/ausblenden."),
    ("Achsenkreuze", "Lokale IDEA-Achsen (x rot, y grün, z blau) am Ursprung jedes Bauteils ein-/ausblenden."),
    ("Anschlussteile", "Bleche, Winkel und andere Teile in Klammern ein-/ausblenden. Zum Anklicken der Stäbe meist besser ausblenden."),
    ("x umkehren", "Dreht die x-Achse (Stabachse) um. Die z-Achse folgt nach der Rechte-Hand-Regel."),
    ("y umkehren", "Dreht die y-Achse um. Die z-Achse folgt nach der Rechte-Hand-Regel."),
    ("Profil 90", "Dreht Querschnitt-Achsen y/z um 90° um die Stabachse (wenn das Profil in IDEA anders liegt)."),
    ("Zurücksetzen", "Verwirft Änderungen und nimmt wieder den automatischen Vorschlag."),
    ("✓ Bestätigen", "Markiert die Achsen als mit IDEA verglichen und richtig (grüner Punkt am Ursprung). Wird mit der Zuordnung gespeichert."),
    # --- Modellansicht
    ("Stabachsen", "Zeigt an jedem Stab das lokale Achsenkreuz der Baustatik: x rot in Stabrichtung, z blau = x um 90° im Uhrzeigersinn gedreht (bei Stab nach rechts nach unten), y grün = zum Betrachter. Dieselben Farben wie in der IFC-Ansicht."),
    ("Knotennummern", "Knotennummern ein-/ausblenden."),
    ("Stabnummern", "Stabnummern ein-/ausblenden."),
    ("Knoten Nr.", "Knoten per Nummer wählen, wenn er schwer anzuklicken ist."),
    ("Wählen", "Knoten mit dieser Nummer auswählen."),
    # --- IFC-Tabelle
    ("IFC-Datei wählen", "IFC-Export aus IDEA StatiCa Connection auswählen (Bauteilnamen = Namen in IDEA)."),
    ("Neu berechnen", "Vorschläge mit den gewählten Drehungen neu berechnen."),
    ("Auswahl übernehmen", "Vorgeschlagene Achsen der markierten Zeilen in die Zuordnung übernehmen."),
    ("Alle Vorschläge", "Vorgeschlagene Achsen aller Zeilen in die Zuordnung übernehmen."),
    ("Schließen", "Fenster schließen."),
]


EXACT = {"Neu", "Vorschlag", "Alle", "Keine", "OK", "Standard", "Weiter", "Namen", "Wählen", "Schließen", "Abbrechen"}


def tip_for(text: str) -> Optional[str]:
    t = (text or "").strip()
    if not t:
        return None
    for key, tip in TIPS:
        if t == key or (key not in EXACT and t.startswith(key)):
            return tip
    return None


class Tooltip:
    def __init__(self, widget, text: str, delay: int = DELAY_MS, wrap: int = 380):
        self.widget, self.text, self.delay, self.wrap = widget, text, delay, wrap
        self._after = None
        self._win = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._leave, add="+")
        widget.bind("<ButtonPress>", self._leave, add="+")
        widget.bind("<Destroy>", self._leave, add="+")

    def _enter(self, _e=None):
        self._cancel()
        self._after = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except Exception:       # noqa: BLE001
                pass
            self._after = None

    def _show(self):
        self._after = None
        if self._win is not None:
            return
        try:
            x = self.widget.winfo_pointerx() + 14
            y = self.widget.winfo_pointery() + 18
            win = tk.Toplevel(self.widget)
            win.wm_overrideredirect(True)
            win.wm_geometry(f"+{x}+{y}")
            lab = tk.Label(win, text=self.text, justify="left", background="#ffffe1", foreground="#000000",
                           relief="solid", borderwidth=1, wraplength=self.wrap, padx=6, pady=3,
                           font=("Segoe UI", 9))
            lab.pack()
            self._win = win
        except tk.TclError:
            self._win = None

    def _leave(self, _e=None):
        self._cancel()
        if self._win is not None:
            try:
                self._win.destroy()
            except Exception:       # noqa: BLE001
                pass
            self._win = None


def tip(widget, text: str) -> None:
    """Hinweis an ein Element haengen (einmalig)."""
    if text and not getattr(widget, "_has_tip", False):
        widget._has_tip = True
        Tooltip(widget, text)



def decorate(widget) -> None:
    """Alle Elemente unterhalb von widget anhand ihrer Beschriftung mit Hinweisen versehen."""
    last_tip: Optional[str] = None
    for ch in widget.winfo_children():
        try:
            txt = ch.cget("text") if "text" in ch.keys() else ""
        except tk.TclError:
            txt = ""
        own = tip_for(str(txt)) if txt else None
        if own:
            tip(ch, own)
            if isinstance(ch, ttk.Label):
                last_tip = own
            else:
                last_tip = None
        elif isinstance(ch, _INPUT) and last_tip:
            tip(ch, last_tip)
        elif isinstance(ch, ttk.Checkbutton) or isinstance(ch, ttk.Radiobutton):
            pass
        if isinstance(ch, (ttk.Frame, tk.Frame, ttk.LabelFrame, ttk.Panedwindow, ttk.Notebook)) or ch.winfo_children():
            decorate(ch)
            if isinstance(ch, (ttk.Frame, tk.Frame)):
                last_tip = last_tip      # Beschriftung vor einem Rahmen gilt weiter
    return None


def install(root) -> None:
    """Beim ersten Anzeigen jedes Fensters Hinweise anbringen."""
    def on_map(event):
        w = event.widget
        try:
            if w is not w.winfo_toplevel() or getattr(w, "_tips_done", False):
                return
            w._tips_done = True
            w.after(30, lambda: decorate(w))
        except tk.TclError:
            pass
    root.bind_all("<Map>", on_map, add="+")
