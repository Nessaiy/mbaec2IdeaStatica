# Export_Zu_Ideastatica

PDF aus der Baustatik einlesen -> Excel ausgeben, das sich in IDEA StatiCa
(Dialog "Import von Lasten") einfügen lässt.

## Ablauf in der Oberfläche
1. **Baustatik-Modul** wählen (aktuell: mb AEC Baustatik S601.de, Stabwerk) und **PDF öffnen**.
2. **Bauteile wie in IDEA** anlegen (Reihenfolge = Reihenfolge im IDEA-Importdialog). Je Bauteil:
   - **Position im IDEA-Bauteil** (Anfang/Ende) und
   - **Stab aus PDF + Stelle x** per Dropdown, z. B. Stab 4: `0,00 – Knoten 21 (Anfang)`, `1,78`, `6,28`,
     `9,28 – Knoten 22 (Ende)`. Bei Sprüngen gibt es "links/rechts". x lässt sich auch frei eintippen.
     Fehlt die Stelle in einer Kombination, wird linear interpoliert (Zeile gelb, Hinweis in der Warnung).
   - oder Reiter **Manuell (nicht im PDF)**: Stab ohne PDF-Werte; Zeilen wie `1-20` -> N, Vy, Vz, Mx, My, Mz.
     Nicht genannte Kombinationen und leere Felder = 0 (Vorzeichenfaktoren gelten nur für PDF-Werte).
3. **Kombinationen** auswählen, ggf. Namensschema, **Achsenzuordnung** und Vorzeichenfaktoren anpassen.
4. **Excel speichern** (oder "In Zwischenablage").
Die Zuordnung lässt sich als JSON speichern/laden und für ähnliche Positionen wiederverwenden.

## Modellansicht (Knoten/Stab anklicken)
Button **Modellansicht…** zeichnet das Stabwerk aus der Knoten- und Stabdefinition des PDFs
(Mausrad = Zoom, Ziehen = Verschieben, "Knoten Nr." zum direkten Wählen).
- **Klick auf einen Knoten:** Liste der Stäbe an diesem Knoten mit der Seite (Stabanfang/Stabende). Auswahl
  (auch mehrere) -> je Stab wird das IDEA-Bauteil abgefragt.
- **Klick mitten auf einen Stab:** Abfrage der Strecke vom Anfangsknoten in Stabrichtung (mit dem Klickpunkt
  vorbelegt). Liegt dort ein Sprung, wird links/rechts gefragt.
- Pfeil am Stab = Stabrichtung (lokales x). Nach einem Klick auf einen Stab werden lokales x (rot) und z (grün) gezeigt.
- Orange Kreise mit Nummer = bereits zugewiesene Stellen (Nummer = Zeile in der Bauteilliste).
Lokale Achsen S601.de: x = von Knoten "von" nach "bis", z = x um 90° im Uhrzeigersinn gedreht
(Stab nach rechts -> z nach unten; Stab nach oben -> z nach rechts). Per Knotengleichgewicht am Beispiel geprüft.

## Achsenzuordnung Baustatik -> IDEA (lokal, je Bauteil)
IDEA erwartet die Lasten im **lokalen** System des IDEA-Bauteils. Deshalb gibt es die Achsenzuordnung
je Bauteil (im Zuweisungsdialog, Reiter "Stab aus PDF"). Die Standard-Zuordnung im Hauptfenster wird
für neue Bauteile vorgeschlagen.
Je Baustatik-Achse wird die IDEA-Achse gewählt, z. B. `x = -y`, `y = x`, `z = z`
(jede IDEA-Achse genau einmal). Kräfte folgen der Achse direkt. Momente werden mitgedreht;
bei Spiegelungen (Determinante -1) wird der Pseudovektor-Vorzeichenwechsel automatisch berücksichtigt.
Daraus entsteht die Tabelle "IDEA-Komponente <- Baustatik-Komponente", die sich einzeln überschreiben lässt.
Beispiel `x=-y, y=x, z=z`: N = +Vy, Vy = -N, Vz = +Vz, Mx = +My, My = -Mx, Mz = +Mz.
Die Zuordnung wirkt nur auf PDF-Werte (nicht auf manuell eingegebene Stäbe). Standard = keine Änderung.
Beispiel Stütze, deren lokales z in IDEA gegen die Baustatik zeigt: `y = -y, z = -z` -> Vz, My, Vy, Mz wechseln das Vorzeichen, N und Mx bleiben.

## Excel-Aufbau (Blatt "IDEA-Import")
`Name | Bauteil | Position | N [kN] | Vy [kN] | Vz [kN] | Mx [kNm] | My [kNm] | Mz [kNm]`
- Name (Lasteinwirkung) steht nur in der ersten Zeile je Kombination, wie im IDEA-Dialog.
- Blatt "Nur Werte": nur die 6 Zahlenspalten. Blatt "Info": Quelle und Zuordnung.
- Fehlende Komponenten (z. B. Vy, Mx, Mz bei ebenen Systemen) = 0.

## Regeln für Stellen
- Anfang = erste Zeile bei kleinstem x, Ende = letzte Zeile bei größtem x (also nach einem Sprung).
- Die Kombinationsnummern der manuellen Bereiche beziehen sich auf die Nummern im PDF ("Komb. 21" = 21).
  Es werden nur Kombinationen ausgegeben, die im PDF stehen (dort nur die maßgebenden).

## Kommandozeile
    python run.py --pdf X.pdf --list
    python run.py --pdf X.pdf --profile zuordnung.json --out ergebnis.xlsx

## EXE bauen (einmalig, ohne Admin)
`build_exe.bat` auf einem Windows-PC mit Python ausführen -> `dist\pdf2idea.exe`
(eine Datei, auf den Terminalserver kopieren).

## Neues Baustatik-Modul
Unterklasse von `ModuleParser` in `pdf2idea/modules/` anlegen (`parse()` liefert `ParseResult`)
und in `modules/__init__.py` eintragen. Zuordnung und Export bleiben unverändert.

## Achsen aus IFC (IDEA Connection) ermitteln

Button **"Achsen aus IFC…"**: Die IFC wird in IDEA Connection exportiert (Bauteile als Körper, Namen = IDEA-Bauteile).
Das Programm liest sie ohne Zusatzpakete ein (`pdf2idea/ifc.py`) und bestimmt je Bauteil die lokalen IDEA-Achsen
(`pdf2idea/ifcaxes.py`):

- **x** = Stabachse, vom Bauteil-Ursprung in Richtung des Körpers (läuft das Bauteil beidseitig durch, ist die Richtung
  nicht bestimmbar → Vorgabe nach +Z, Hinweis "Richtung prüfen").
- **y/z** in IDEA-Standardlage: senkrechter Stab y = +X(global), z = x × y; sonstiger Stab z = Anteil von +Z senkrecht zu x,
  y = z × x. Bei I-Profilen wird geprüft, ob die Profilhöhe in lokal z liegt (sonst Hinweis "Profil gedreht").
- Dieses Regelwerk stimmt mit den in IDEA abgelesenen Achsen von Stütze innen/mittig/außen und Auskreuzung oben/unten
  im Beispiel C1-D1 überein (siehe `tests/test_ifc.py`).

Einmalige Einstellungen im Dialog: (1) IFC → IDEA-Global (Vorgabe: IDEA x = +IFC y, y = −IFC x, z = +IFC z;
im Beispiel bestimmt aus der Lage der Stützen), (2) Baustatik → IDEA-Global (Vorgabe: Baustatik rechts = IDEA +x, oben = +z).
Daraus und aus der Lage des Stabes im PDF ergibt sich je Zuordnung die Achsenzuordnung; "Übernehmen" trägt sie ein.
Heißt ein IDEA-Bauteil anders als in der IFC, per Doppelklick das IFC-Bauteil wählen.

### Grafische Zuordnung (IFC + Baustatik-Modell)

Button **"Grafische Zuordnung (IFC)…"** öffnet zwei Fenster nebeneinander: die Modellansicht (Baustatik aus dem PDF) und die
IFC-Ansicht (Bauteile aus IDEA Connection, Ansicht vorne/seitlich/oben, Zoom und Verschieben wie in der Modellansicht).

1. IFC-Bauteil anklicken (in der Grafik oder in der Liste) – die lokalen IDEA-Achsen erscheinen (x rot, y grün, z blau).
2. In der Modellansicht Knoten oder Stab anklicken (Knoten: Stab wählen; Stab: Strecke vom Knoten) – oder umgekehrt.
3. Die Zuordnung entsteht mit Name = IFC-Bauteil, IDEA-Position und Achsen automatisch. Orange Markierungen mit "#n" zeigen
   die Zuordnungen in beiden Ansichten.

IDEA-Position (Vorgabe): Bauteil endet am Ursprung → "Anfang"; durchlaufendes Bauteil → "Anfang" bei Stelle rechts vom Sprung,
sonst "Ende". Beim ersten Import prüfen (Testwerte N=10, Vy=20, Vz=30). Anschlussteile (Name beginnt mit "(") sind ausgeblendet.

## Tests
    python -m pytest tests     (Beispiel-PDF in Beispiele/C1-D1 nötig)

## Offene Punkte
- Vorzeichenkonvention mb AEC <-> IDEA prüfen (Faktoren je Komponente einstellbar).
- Prüfen, ob IDEA Name/Bauteil/Position beim Einfügen mitliest oder nur die 6 Werte in Reihenfolge.


## 3D-IFC-Ansicht und Bestätigung (neu)

"Grafische Zuordnung (IFC)…" öffnet die IFC als **3D-Modell** (Ziehen = drehen, rechte Maustaste = verschieben, Rad = Zoom;
Voreinstellungen Vorne/Seite/Oben). An jedem Bauteil steht das lokale IDEA-Achsenkreuz (x rot, y grün, z blau).

1. IFC-Bauteil anklicken (im 3D-Bild oder in der Liste): die vorgeschlagenen lokalen Achsen werden angezeigt. Mit der
   Ansicht in IDEA vergleichen, bei Bedarf „x umkehren", „y umkehren (z folgt)" oder „Profil 90° drehen" und
   „✓ Bestätigen" (grüner Punkt am Ursprung). Angepasste/bestätigte Achsen werden in der Zuordnungsdatei (JSON) mitgespeichert.
2. Danach in der Modellansicht den Stab bzw. Knoten anklicken: Es öffnet sich ein Dialog mit der vorgeschlagenen
   Umrechnung Baustatik → IDEA (Baustatik x/z → IDEA global änderbar, Achsen und IDEA-Position änderbar). „Übernehmen" legt die Zuordnung an.


## Knotenlasten / Kranlasten je Kombination (neu)

Das Programm liest aus dem S601-PDF die charakteristischen Punktlasten je Einwirkung (z. B. Gk, Qk.K, Qk.HM, Qk.HS) und
die Kombinationsvorschriften (Faktor × Einwirkung). In der Modellansicht den Knoten anklicken (z. B. Knoten 17 am Kranbahnträger) →
„Knotenlast je Kombination (z. B. Kran) …". Je Kombination wird Σ Faktor × Last gebildet (Fx → N, Fz → Vz, M → My, danach
Achsenzuordnung wie bei Stäben). Mit geladener IFC: Knotenlast und IFC-Bauteil anklicken, im Dialog Achsen/Position/Vorzeichen prüfen.
Vorzeichen: „umkehren" gibt die Gegenkraft aus (je nachdem, wie IDEA die Last am Bauteilende erwartet).

**Aufteilung auf zwei Kranbahnen:** Im Knotenlast-Dialog steht „Anteil" (z. B. 0,5 je Kranbahn oder 0,6/0,4). Für einzelne
Einwirkungen kann ein abweichender Anteil eingetragen werden, z. B. `Qk.HS=0,3; Qk.K=0,6` (0 = Einwirkung weglassen). Die Knotenlast
zweimal anlegen (je Kranbahnträger ein Bauteil, Anteile zusammen = 1). Doppelklick auf die Zeile ändert die Angaben nachträglich.

## Hinweise per Mouseover
Alle Schaltflächen, Eingabefelder und Optionen zeigen nach kurzem Verweilen mit der Maus eine Erklärung. Die Texte stehen
gesammelt in `pdf2idea/tooltip.py` (Liste `TIPS`) und lassen sich dort anpassen oder ergänzen.

## Position, Vorzeichen und globale Ausrichtung (grafische Zuordnung)
Alles wird aus den (bestätigten) lokalen IDEA-Achsen des Bauteils abgeleitet:
- **Globale Ausrichtung:** Liegt der Stab waagerecht und das Bauteil in IDEA entlang einer anderen waagerechten Achse als „Baustatik x",
  wird Baustatik x automatisch darauf gesetzt (z. B. Rahmenebene y–z statt x–z). Die Richtung ± bitte prüfen. Wird sie geändert,
  müssen früher angelegte Zuordnungen neu angelegt werden (Warnhinweis).
- **IDEA-Position:** „Ende" = belasteter Bauteilrand bei größtem lokalen x, „Anfang" = bei kleinstem x. Maßgebend ist, in welche
  Richtung in IDEA der Stabkörper vom Schnitt aus liegt.
- **Vorzeichen:** Schnittgrößen gelten an der Schnittfläche. Liegt das Bauteil in IDEA auf der anderen Seite des Schnitts als der Stab,
  kehrt sich das Vorzeichen um; wird automatisch vorgeschlagen (Haken „Vorzeichen umkehren").
- **Knotenlasten:** Lasten Fz sind in der S601 positiv nach unten (wie das lokale z). Äußere Last am Bauteilende „Anfang": Gegenkraft
  (Vorschlag automatisch, folgt der gewählten Position).
Alle Vorschläge sind änderbar und sollten mit IDEA (Lastpfeile) verglichen werden.

## Bildliche Achsenzuordnung (neu, v0.4.0)
Nach dem Anklicken von IFC-Bauteil und Stab/Knoten öffnet sich „Koordinaten zuweisen“: links das IDEA-Bauteil in 3D
(andere Bauteile grau) mit seinen lokalen Achsen X Y Z, rechts das Achsenkreuz der Baustatik (x in Stabrichtung,
z 90° im Uhrzeigersinn, y zum Betrachter). Jede Achse hat zwei Spitzen (+ ausgezogen, − gestrichelt).
Erst eine Spitze links anklicken, dann die gleiche Richtung rechts: das Vorzeichen ergibt sich aus der angeklickten Seite.
Zwei Paare genügen, die dritte Achse wird (ohne Spiegelung) ergänzt. Position und Vorzeichen werden danach aus der
gewählten Zuordnung vorgeschlagen. Die technischen Einstellungen stehen unter „Technische Details anzeigen“.

## Hinweis v0.5.0: kein globales IDEA-System mehr
Die frühere Einstellung „globale Ausrichtung“ und der Dialog „Achsen aus IFC…“ sind entfernt. Alles bezieht sich auf die
lokalen Achsen: Du weist im Bild die lokalen Achsen von Bauteil (IDEA) und Stab (Baustatik) einander zu; Position (Anfang/Ende)
und Vorzeichen folgen daraus. Bauteile, die am Knoten enden, haben nur „Ende“; durchlaufende Bauteile „Anfang“ und „Ende“.
Der Titel zeigt Version und Build-Zeit.

## Grafische Lastvorschau (v0.6.0)
In „Vorschau“ gibt es oben den Knopf „Grafisch in IFC-Ansicht …“: 3D-Ansicht der IFC-Bauteile mit den Lasten der gewählten
Kombination (Kräfte grün, Momente rot, positiv = in Richtung der lokalen Bauteilachse, wie in IDEA). Mit ◀ ▶ durch die Kombinationen blättern.

## Mehrere Zuordnungen auf eine IDEA-Zeile (v0.7.0)
Werden mehreren Zuordnungen dieselbe IDEA-Zeile (Bauteil + Position) zugewiesen, schreibt das Programm **eine** Zeile mit der **Summe**
(z. B. Doppelstab = Stab 17 + Stab 22, jeweils mit eigener Achsenzuordnung). Das gilt auch für manuelle Lasten und Knotenlasten:
eine manuelle Zuordnung („Hinzufügen → Manuell“) auf dieselbe Zeile wirkt als **Zusatzlast** (Werte in den lokalen IDEA-Achsen).
In der Liste sind solche Zeilen mit „Σ“ markiert.

## Herkunft der Lasten in der grafischen Vorschau (v0.8.0)
Rechts neben der 3D-Ansicht steht je Zeile die Summe und ihre Summanden (Stab @ Stelle, Knotenlast je Einwirkung mit Faktor, manuelle Last).
„Herkunft im Bild“ schreibt die Summanden zusätzlich an die Pfeile (z. B. N -114.6 = -56.0 S1 rechts + -58.6 Kn.6).

## Externe Punktlast / Gleichgewicht (v0.10.0)
In der grafischen Vorschau: „Externe Punktlast“ zeichnet die fehlende Knotenlast (= negative Summe aller Zeilen in globalen IDEA-Koordinaten) als orange Pfeil am Ursprung;
„Gleichgewicht aller Kombinationen…“ listet sie für alle Kombinationen (rot = Komponente > 0,5 kN). Unbestätigte Bauteilachsen (Roll geraten) werden angezeigt.

## Gleichgewicht: Komponenten wählbar (v0.12.0)
In der grafischen Vorschau oben „Für das Gleichgewicht berücksichtigen“: Fx, Fy, Fz, Mx, My, Mz einzeln abwählbar (Standard: Mx und My aus).
Abgewählte Komponenten gehen weder in die Warnung, den orangen Pfeil noch in die Kombinationstabelle ein (dort grau/„ignoriert“).
