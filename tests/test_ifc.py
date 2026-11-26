"""Tests des IFC-Lesers und der Achsenermittlung (Beispiel-IFC aus IdeaConnection, Beispiele/C1-D1)."""
import glob
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from pdf2idea.ifc import read_members  # noqa: E402
from pdf2idea.ifcaxes import (GLOBAL_DEFAULT, IFC_TO_IDEA_DEFAULT, idea_frame, match_member,  # noqa: E402
                              suggest_axes, ifc_det)
from pdf2idea.model import MemberInfo, ParseResult  # noqa: E402

_found = glob.glob(os.path.join(HERE, "..", "Beispiele", "C1-D1", "*.ifc"))
SAMPLE = os.environ.get("PDF2IDEA_SAMPLE_IFC") or (_found[0] if _found else "")
needs_ifc = pytest.mark.skipif(not SAMPLE or not os.path.exists(SAMPLE), reason="Beispiel-IFC fehlt")


@pytest.fixture(scope="module")
def members():
    return read_members(SAMPLE)


def near(a, b, tol=0.03):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


@needs_ifc
def test_members_found(members):
    assert len(members) == 24
    assert match_member("Stütze mittig (nur Dach)", members).profile == "I300"
    assert match_member("stütze MITTIG (nur dach)", members) is not None


@needs_ifc
def test_ifc_transform_is_rotation():
    assert ifc_det(IFC_TO_IDEA_DEFAULT) == 1


# In IDEA abgelesene lokale Achsen (global x rechts, y Kranbahn, z oben)
@needs_ifc
@pytest.mark.parametrize("name,ex,ey,ez", [
    ("Stütze mittig (nur Dach)", (0, 0, 1), (1, 0, 0), (0, 1, 0)),
    ("Stütze innen (unter Kranbahn)", (0, 0, -1), (1, 0, 0), (0, -1, 0)),
    ("Stütze außen", (0, 0, 1), (1, 0, 0), (0, 1, 0)),
])
def test_columns_match_idea(members, name, ex, ey, ez):
    fr = idea_frame(match_member(name, members), IFC_TO_IDEA_DEFAULT)
    assert near(fr.ex, ex) and near(fr.ey, ey) and near(fr.ez, ez), fr.describe()


@needs_ifc
def test_diagonals_match_idea(members):
    o = idea_frame(match_member("Auskreuzung oben", members), IFC_TO_IDEA_DEFAULT)
    u = idea_frame(match_member("Auskreuzung unten", members), IFC_TO_IDEA_DEFAULT)
    assert o.ex[0] > 0.3 and o.ex[2] > 0.3 and near(o.ey, (0, 1, 0)) and o.ez[2] > 0.3     # x rechts, y hoch
    assert u.ex[0] < -0.3 and u.ex[2] < -0.3 and near(u.ey, (0, -1, 0)) and u.ez[2] > 0.3  # x links, y runter


@needs_ifc
def test_continuous_member_flagged(members):
    fr = idea_frame(match_member("Stütze außen", members), IFC_TO_IDEA_DEFAULT)
    assert any("durch" in n for n in fr.notes)


@needs_ifc
def test_suggest_axes_vertical_up(members):
    # Baustatik: Stab 1 senkrecht nach oben; Rechts der Baustatik = IDEA +x  ->  Fall A
    res = ParseResult("t", [], {1: MemberInfo(1, 1, 2, 4.0)}, {1: (0.0, 0.0), 2: (0.0, 4.0)})
    fr = idea_frame(match_member("Stütze mittig (nur Dach)", members), IFC_TO_IDEA_DEFAULT)
    s = suggest_axes(res, 1, fr, GLOBAL_DEFAULT)
    assert s.axes == {"x": "+x", "y": "-z", "z": "+y"}
    assert s.component_map == {"N": "+N", "Vy": "+Vz", "Vz": "-Vy", "Mx": "+Mx", "My": "+Mz", "Mz": "-My"}
    # Baustatik-Rechts = IDEA -x  ->  Fall B
    s2 = suggest_axes(res, 1, fr, {"x": "-x", "z": "+z"})
    assert s2.axes == {"x": "+x", "y": "+z", "z": "-y"}


@needs_ifc
def test_suggest_axes_inner_column_down(members):
    res = ParseResult("t", [], {1: MemberInfo(1, 1, 2, 4.0)}, {1: (0.0, 0.0), 2: (0.0, 4.0)})
    fr = idea_frame(match_member("Stütze innen (unter Kranbahn)", members), IFC_TO_IDEA_DEFAULT)
    s = suggest_axes(res, 1, fr, GLOBAL_DEFAULT)
    assert s.axes == {"x": "-x", "y": "+z", "z": "+y"}


@needs_ifc
def test_view_helpers(members):
    from pdf2idea.ifcaxes import idea_position, is_connector, member_segment
    main = [m for m in members if not is_connector(m)]
    assert len(main) == 6                                  # 3 Stuetzen, Kranbahntraeger, 2 Auskreuzungen
    mitt = match_member("Stütze mittig (nur Dach)", members)
    p0, p1, o = member_segment(mitt, IFC_TO_IDEA_DEFAULT)
    assert near(o, (0.38, 0.0, -0.6125), 0.001) and near(p0, o, 0.001) and near(p1, (0.38, 0.0, 1.27), 0.001)
    assert idea_position(mitt, "Anfang") == "Anfang"
    aussen = match_member("Stütze außen", members)
    assert idea_position(aussen, "x=8.72R") == "Anfang" and idea_position(aussen, "x=7.72L") == "Ende"


def test_frame_ops_and_faces():
    import glob
    from pdf2idea.ifc import read_members
    from pdf2idea.ifcaxes import IFC_TO_IDEA_DEFAULT, flip_x, flip_y, idea_frame, rotate90, IdeaFrame, _cross
    ms = read_members(glob.glob(os.path.join(os.path.dirname(__file__), "..", "Beispiele", "C1-D1", "*.ifc"))[0])
    assert sum(len(m.faces) for m in ms) > 300
    fr = idea_frame(next(m for m in ms if m.name.startswith("Stütze mittig")), IFC_TO_IDEA_DEFAULT)
    for g in (flip_x(fr), flip_y(fr), rotate90(fr)):
        c = _cross(g.ex, g.ey)
        assert all(abs(a - b) < 1e-9 for a, b in zip(c, g.ez))            # Rechtssystem bleibt erhalten
    r = IdeaFrame.from_dict("a", fr.to_dict())
    assert all(abs(a - b) < 1e-5 for a, b in zip(r.ex, fr.ex))
