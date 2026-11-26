"""Schnelle Tests ohne PDF (synthetische Daten)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pdf2idea.export import build_rows, resolve_station, station_options  # noqa: E402
from pdf2idea.mapping import Assignment, ManualLoad, Profile, parse_case_spec  # noqa: E402
from pdf2idea.model import ForceRow, LoadCase, MemberInfo, ParseResult  # noqa: E402


def fr(x, n, my, vz):
    return ForceRow(x, {"N": n, "My": my, "Vz": vz})


@pytest.fixture
def res():
    k1 = LoadCase("Komb. 1", {4: [fr(0, -35, 0.0, -1), fr(1.78, -35, 1.0, -1), fr(1.78, -35, 1.0, 2),
                                  fr(6.28, -20, 3.0, 2), fr(9.28, -8, 0.0, 2)]})
    k2 = LoadCase("Komb. 2", {4: [fr(0, -40, 0.0, -2), fr(4.0, -40, 8.0, 0), fr(9.28, -10, 0.0, 3)]})
    return ParseResult("t", [k1, k2], {4: MemberInfo(4, 21, 22, 9.28, "I 300")})


def test_station_options(res):
    o = dict(station_options(res, 4))
    assert o["Anfang"].startswith("0,00 – Knoten 21")
    assert o["Ende"].startswith("9,28 – Knoten 22")
    assert "x=1.78L" in o and "x=1.78R" in o            # Sprung -> links/rechts
    assert o["x=6.28"].endswith("[1/2 Komb.]")          # nur in Komb. 1 vorhanden


def test_resolve(res):
    rows = res.load_cases[0].members[4]
    assert resolve_station(rows, "x=1.78L")[0]["Vz"] == -1
    assert resolve_station(rows, "x=1.78R")[0]["Vz"] == 2
    v, note = resolve_station(res.load_cases[1].members[4], "x=6.28")   # zwischen 4.0 und 9.28
    assert note == "interpoliert"
    t = (6.28 - 4.0) / (9.28 - 4.0)
    assert v["My"] == pytest.approx(8.0 * (1 - t))
    v, note = resolve_station(rows, "x=12")
    assert "ausserhalb" in note and v["N"] == -8


def test_case_spec():
    assert parse_case_spec("alle") is None
    assert parse_case_spec("1-3, 7") == {1, 2, 3, 7}
    with pytest.raises(ValueError):
        parse_case_spec("abc")


def test_manual_member(res):
    res.load_cases += [LoadCase(f"Komb. {n}", {4: [fr(0, 0, 0, 0), fr(9.28, 0, 0, 0)]}) for n in (21, 36)]
    a = Assignment("Kranbahn 1", "Ende", manual=[ManualLoad("1-20", {"N": 0, "Vz": 200}),
                                                 ManualLoad("21-35", {"N": 10, "Vz": 250})])
    rows, _ = build_rows(res, Profile(assignments=[a]))
    by = {r.name: r.values for r in rows}
    assert by["Komb. 1"] == (0, 0, 200, 0, 0, 0)
    assert by["Komb. 21"] == (10, 0, 250, 0, 0, 0)
    assert by["Komb. 36"] == (0,) * 6                      # nicht gewaehlt -> 0


def test_idea_position_separate(res):
    a = Assignment("Stuetze mittig", "Ende", stab=4, station="x=1.78R")
    rows, warns = build_rows(res, Profile(assignments=[a], selected_cases=["Komb. 1"]))
    assert rows[0].position == "Ende" and rows[0].values[2] == 2   # IDEA-Position != PDF-Stelle


def test_legacy_profile():
    p = Profile.from_json('{"assignments":[{"idea_name":"A","stab":4,"position":"Anfang"}]}')
    assert p.assignments[0].station == "Anfang" and p.assignments[0].position == "Anfang"


def test_roundtrip():
    p = Profile(assignments=[Assignment("K", "Anfang", manual=[ManualLoad("1-2", {"N": 1.5})]),
                             Assignment("S", "Ende", stab=2, station="x=3.00L")])
    q = Profile.from_json(p.to_json())
    assert q.assignments[0].manual[0].values == {"N": 1.5} and q.assignments[1].station == "x=3.00L"


# ---------------------------------------------------------------- Achsenzuordnung
from pdf2idea.axes import (apply_component_map, component_map_from_axes, determinant,  # noqa: E402
                           parse_axes)

SCHEMA = {"x": "-y", "y": "+x", "z": "+z"}       # Baustatik x = -y, y = x, z = z


def test_axes_rotation():
    assert determinant(SCHEMA) == 1
    cm = component_map_from_axes(SCHEMA)
    assert cm == {"N": "+Vy", "Vy": "-N", "Vz": "+Vz", "Mx": "+My", "My": "-Mx", "Mz": "+Mz"}
    out = apply_component_map({"N": -35.07, "Vz": -0.07, "My": 0.05}, cm)
    assert out == (0.0, 35.07, -0.07, 0.05, 0.0, 0.0)


def test_axes_mirror_moments_pseudovector():
    ax = {"x": "-x", "y": "+y", "z": "+z"}      # Spiegelung an der y-z-Ebene
    assert determinant(ax) == -1
    cm = component_map_from_axes(ax)
    assert cm["N"] == "-N" and cm["Mx"] == "+Mx" and cm["My"] == "-My" and cm["Mz"] == "-Mz"


def test_axes_invalid_and_identity():
    with pytest.raises(ValueError):
        parse_axes({"x": "+x", "y": "+x", "z": "+z"})
    assert component_map_from_axes({"x": "+x", "y": "+y", "z": "+z"}) == {c: f"+{c}" for c in
                                                                         ("N", "Vy", "Vz", "Mx", "My", "Mz")}


def test_build_rows_with_axes(res):
    p = Profile(assignments=[Assignment("S", "Ende", stab=4, station="Anfang")], selected_cases=["Komb. 1"],
                axes=SCHEMA, component_map=component_map_from_axes(SCHEMA))
    rows, _ = build_rows(res, p)
    assert rows[0].values == (0.0, 35.0, -1.0, 0.0, 0.0, 0.0)      # N=-35, Vz=-1, My=0
    # Manuelle Staebe bleiben unveraendert
    a = Assignment("K", "Ende", manual=[ManualLoad("alle", {"N": 5, "Vz": 7})])
    rows, _ = build_rows(res, Profile(assignments=[a], selected_cases=["Komb. 1"], axes=SCHEMA,
                                      component_map=component_map_from_axes(SCHEMA)))
    assert rows[0].values == (5, 0, 7, 0, 0, 0)


def test_profile_roundtrip_axes():
    p = Profile(axes=SCHEMA, component_map=component_map_from_axes(SCHEMA))
    q = Profile.from_json(p.to_json())
    assert q.axes == SCHEMA and q.component_map["Vy"] == "-N"
    assert Profile.from_json('{"axes": {"x":"-y","y":"+x","z":"+z"}}').component_map["Vy"] == "-N"
    assert Profile.from_json("{}").component_map["N"] == "+N"      # alte Dateien: Identitaet


def test_knotenlast_je_kombination():
    from pdf2idea.export import build_rows
    from pdf2idea.mapping import Assignment, Profile
    from pdf2idea.model import LoadCase, MemberInfo, NodeLoad, ParseResult
    res = ParseResult("t", [LoadCase("Komb. 1"), LoadCase("Komb. 2")], {1: MemberInfo(1, 1, 2, 4.0)},
                      {1: (0.0, 0.0), 2: (0.0, 4.0)},
                      [NodeLoad("Gk", 2, 0.0, 10.0, -1.0), NodeLoad("Qk.K", 2, 2.0, 100.0, 0.0),
                       NodeLoad("Qk.K", 1, 0.0, 5.0, 0.0)],
                      {1: [(1.35, "Gk")], 2: [(1.0, "Gk"), (1.35, "Qk.K")]})
    a = Assignment("Kran", "Ende", node=2)
    rows, _ = build_rows(res, Profile(assignments=[a]))
    assert [round(v, 3) for v in rows[0].values] == [0.0, 0.0, 13.5, 0.0, -1.35, 0.0]
    assert [round(v, 3) for v in rows[1].values] == [2.7, 0.0, 145.0, 0.0, -1.0, 0.0]
    a.node_sign = -1.0
    rows, _ = build_rows(res, Profile(assignments=[a]))
    assert rows[1].values[2] == -145.0
    q = Profile.from_json(Profile(assignments=[a]).to_json())
    assert q.assignments[0].node == 2 and not q.assignments[0].is_manual


def test_knotenlast_anteil():
    from pdf2idea.export import build_rows
    from pdf2idea.mapping import Assignment, Profile
    from pdf2idea.model import LoadCase, NodeLoad, ParseResult
    res = ParseResult("t", [LoadCase("Komb. 1")], {}, {2: (0.0, 4.0)},
                      [NodeLoad("Gk", 2, 0.0, 10.0, 0.0), NodeLoad("Qk.K", 2, 0.0, 100.0, 0.0),
                       NodeLoad("Qk.HS", 2, 20.0, 0.0, 0.0)],
                      {1: [(1.0, "Gk"), (1.0, "Qk.K"), (1.0, "Qk.HS")]})
    a = Assignment("Kran links", "Ende", node=2, node_factor=0.4, node_einw={"Qk.HS": 0.0})
    rows, _ = build_rows(res, Profile(assignments=[a]))
    assert [round(v, 3) for v in rows[0].values] == [0.0, 0.0, 44.0, 0.0, 0.0, 0.0]
    assert "× 0.4" in a.describe()
    q = Profile.from_json(Profile(assignments=[a]).to_json())
    assert q.assignments[0].node_factor == 0.4 and q.assignments[0].node_einw == {"Qk.HS": 0.0}


def test_stab_vorzeichen_umkehren():
    from pdf2idea.export import build_rows
    from pdf2idea.mapping import Assignment, Profile
    from pdf2idea.model import ForceRow, LoadCase, MemberInfo, ParseResult
    lc = LoadCase("Komb. 1", {1: [ForceRow(0.0, {"N": 5.0, "Vz": 2.0, "My": 3.0}), ForceRow(4.0, {"N": 6.0, "Vz": 1.0, "My": -1.0})]})
    res = ParseResult("t", [lc], {1: MemberInfo(1, 1, 2, 4.0)}, {1: (0.0, 0.0), 2: (0.0, 4.0)})
    a = Assignment("A", "Ende", stab=1, station="Ende", sign=-1.0)
    rows, _ = build_rows(res, Profile(assignments=[a]))
    assert [round(v, 3) for v in rows[0].values] == [-6.0, 0.0, -1.0, 0.0, 1.0, 0.0]
    assert "Vorz." in a.describe()
    q = Profile.from_json(Profile(assignments=[a]).to_json())
    assert q.assignments[0].sign == -1.0


def test_sort_like_idea():
    import pytest
    pytest.importorskip("tkinter")
    import types
    from pdf2idea.gui import App
    from pdf2idea.mapping import Assignment
    app = types.SimpleNamespace()
    app.ifc_members = [types.SimpleNamespace(name="BL"), types.SimpleNamespace(name="M3")]
    app.assignments = [Assignment("BL", "Ende", stab=3, station="Anfang"), Assignment("M3", "Ende", stab=5, station="Anfang"),
                       Assignment("BL", "Anfang", stab=2, station="Ende")]
    App.sort_like_idea(app)
    assert [(a.idea_name, a.position) for a in app.assignments] == [("BL", "Anfang"), ("BL", "Ende"), ("M3", "Ende")]


def test_same_idea_row_is_summed():
    """Mehrere Zuordnungen (Stab 17 + 22, Zusatzlast) auf dieselbe IDEA-Zeile -> eine Zeile mit der Summe."""
    from pdf2idea.export import build_rows
    from pdf2idea.mapping import Assignment, ManualLoad, Profile
    from pdf2idea.modules import get_module
    import os
    pdf = os.path.join(os.path.dirname(__file__), "..", "Beispiele", "Aktive_Position.pdf")
    if not os.path.exists(pdf):
        return
    res = get_module("mbaec_s601").parse(pdf)
    case = res.load_cases[0].name
    one = lambda *asg: build_rows(res, Profile(module_id="mbaec_s601", assignments=list(asg), selected_cases=[case]))[0]
    a2 = Assignment("BL", "Ende", stab=2, station="Ende")
    a3 = Assignment("BL", "Ende", stab=3, station="Ende")
    zus = Assignment("BL", "Ende", manual=[ManualLoad("alle", {"N": 80.0})])
    r2, r3 = one(a2)[0], one(a3)[0]
    rs = one(a2, a3, zus)
    assert len(rs) == 1
    exp = [x + y for x, y in zip(r2.values, r3.values)]
    exp[0] += 80.0
    assert all(abs(x - y) < 1e-9 for x, y in zip(rs[0].values, exp))
    assert rs[0].name == r2.name


def test_row_parts_sum_to_values():
    """Herkunftsliste (parts) einer Zeile ergibt in der Summe die Werte; Knotenlast je Einwirkung aufgeteilt."""
    import os
    from pdf2idea.export import build_rows
    from pdf2idea.mapping import Assignment, Profile
    from pdf2idea.modules import get_module
    pdf = os.path.join(os.path.dirname(__file__), "..", "Beispiele", "Aktive_Position.pdf")
    if not os.path.exists(pdf):
        return
    res = get_module("mbaec_s601").parse(pdf)
    case = res.load_cases[0].name
    node = res.load_nodes()[0] if res.load_nodes() else None
    asg = [Assignment("BL", "Ende", stab=2, station="Ende"), Assignment("BL", "Ende", stab=3, station="Ende")]
    if node is not None:
        asg.append(Assignment("BL", "Ende", node=node))
    rows, _ = build_rows(res, Profile(module_id="mbaec_s601", assignments=asg, selected_cases=[case]))
    r = rows[0]
    assert len(r.parts) >= 2
    for i in range(6):
        assert abs(sum(p[2][i] for p in r.parts) - r.values[i]) < 1e-9


def test_missing_stations():
    import os
    from pdf2idea.export import build_rows, missing_stations, missing_text
    from pdf2idea.mapping import Assignment, Profile
    from pdf2idea.modules import get_module
    pdf = os.path.join(os.path.dirname(__file__), "..", "Beispiele", "Aktive_Position.pdf")
    if not os.path.exists(pdf):
        return
    res = get_module("mbaec_s601").parse(pdf)
    stab = res.load_cases[0].members and next(iter(res.load_cases[0].members))
    prof = Profile(module_id="mbaec_s601", assignments=[Assignment("X", "Ende", stab=stab, station="x=0.123L")])
    miss = missing_stations(res, prof)
    assert miss and miss[0][0] == stab and abs(miss[0][1] - 0.12) < 1e-9
    assert "Stab" in missing_text(miss)
    _rows, warns = build_rows(res, prof)
    assert warns[0].startswith("ZUSATZAUSGABE")
    ok = Profile(module_id="mbaec_s601", assignments=[Assignment("X", "Ende", stab=stab, station="Ende")])
    assert missing_stations(res, ok) == []


def test_left_side_of_jump_station():
    """Sprungstelle mit nur einem Wert: linke Seite 'einseitig' gemeldet; Zusatzzeile knapp links (x-0,01) wird als linker Wert genommen."""
    from pdf2idea.export import resolve_station
    from pdf2idea.model import ForceRow
    def row(x, n, v):
        return ForceRow(x=x, values={"N": n, "Vz": v, "My": 0.0})
    base = [row(0.0, -80.0, 1.0), row(4.8, -80.0, 1.0), row(7.72, -60.0, 3.0), row(18.0, -60.0, 3.0)]
    vals, note = resolve_station(base, "x=7.72L")
    assert note == "einseitig" and vals["N"] == -60.0
    vals, note = resolve_station(base, "x=7.72R")
    assert note == "" and vals["N"] == -60.0
    with_left = sorted(base + [row(7.71, -80.0, 1.0)], key=lambda r: r.x)
    vals, note = resolve_station(with_left, "x=7.72L")
    assert note == "" and vals["N"] == -80.0
    vals, note = resolve_station(with_left, "x=7.72R")
    assert vals["N"] == -60.0
