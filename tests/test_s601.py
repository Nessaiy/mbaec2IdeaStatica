"""Tests mit dem Beispiel-PDF (Beispiele/C1-D1). Ohne PDF werden sie uebersprungen.
Ausfuehren:  python -m pytest tests   (Beispiel-PDF ggf. per Umgebungsvariable PDF2IDEA_SAMPLE angeben)"""
import glob
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pdf2idea.export import build_rows, pick_row  # noqa: E402
from pdf2idea.mapping import Assignment, Profile  # noqa: E402
from pdf2idea.modules import get_module  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
_found = glob.glob(os.path.join(HERE, "..", "Beispiele", "C1-D1", "*.pdf"))
SAMPLE = os.environ.get("PDF2IDEA_SAMPLE") or (_found[0] if _found else "")
pytestmark = pytest.mark.skipif(not SAMPLE or not os.path.exists(SAMPLE), reason="Beispiel-PDF fehlt")


@pytest.fixture(scope="module")
def result():
    return get_module("mbaec_s601").parse(SAMPLE)


def test_counts(result):
    assert len(result.load_cases) == 25
    assert len(result.member_numbers()) == 77
    assert result.case_names()[0] == "Komb. 1" and result.case_names()[-1] == "Komb. 56"
    assert all(len(c.members) == 77 for c in result.load_cases)


def test_member_info(result):
    m = result.members[4]
    assert (m.node_start, m.node_end, m.length) == (21, 22, 9.28)
    assert 52 in result.members and 53 in result.members


def test_start_end_values(result):
    c = result.load_cases[0]  # Komb. 1
    s4 = c.members[4]
    a, e = pick_row(s4, "Anfang"), pick_row(s4, "Ende")
    assert (a.x, a.values) == (0.0, {"N": -35.07, "My": 0.05, "Vz": -0.07})
    assert (e.x, e.values) == (9.28, {"N": -8.03, "My": 0.04, "Vz": 0.04})
    # Sprung am Stabende: letzte Zeile bei x = l
    e2 = pick_row(c.members[2], "Ende")
    assert e2.values == {"N": -47.58, "My": 6.45, "Vz": 11.99}


def test_build_rows(result):
    p = Profile(assignments=[Assignment("Stuetze mittig (nur Dach)", "Ende", stab=4, station="Anfang"),
                             Assignment("Stuetze aussen", "Ende", stab=4, station="Ende")],
                selected_cases=["Komb. 1", "Komb. 2"], signs={"N": 1, "Vy": 1, "Vz": -1, "Mx": 1, "My": 1, "Mz": 1})
    rows, warns = build_rows(result, p)
    assert not warns and len(rows) == 4
    assert rows[0].name == "Komb. 1" and rows[1].name == "" and rows[2].name == "Komb. 2"
    assert rows[0].values == (-35.07, 0.0, 0.07, 0.0, 0.05, 0.0)  # Vz mit Faktor -1


def test_geometry_from_pdf(result):
    from pdf2idea.geometry import member_geometry
    assert len(result.nodes) == 64 and result.nodes[22] == (0.62, 18.0)
    g = member_geometry(result)
    assert len(g) == 77
    assert all(abs(v[2] - result.members[n].length) < 0.02 for n, v in g.items())   # Laenge aus Knoten = Laenge im PDF
