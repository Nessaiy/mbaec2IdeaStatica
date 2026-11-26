from pdf2idea.tooltip import TIPS, tip_for


def test_tip_lookup():
    assert tip_for("Alle") != tip_for("Alle Vorschläge übernehmen")
    assert "Qk.HS" in tip_for("Abweichend je Einwirkung (z. B. Qk.HS=0,3; Qk.K=0,6):")
    assert tip_for("je Einwirkung:") is not None
    assert tip_for("Anteil an der Knotenlast (z. B. 0,5 bei zwei Kranbahnen):") == tip_for("Anteil:")
    assert tip_for("Standard") != tip_for("Standard-Achsenzuordnung Baustatik → IDEA (lokal)")
    assert tip_for("irgendwas") is None
    assert len({k for k, _ in TIPS}) == len(TIPS)
