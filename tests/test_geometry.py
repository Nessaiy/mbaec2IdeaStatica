"""Tests der Geometrie-Helfer (ohne PDF, ohne tkinter)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pdf2idea.export import build_rows  # noqa: E402
from pdf2idea.geometry import (distance_point_segment, local_axes, member_geometry, node_members,  # noqa: E402
                               point_on_member, station_distance, station_key_from_distance)
from pdf2idea.mapping import Assignment, Profile  # noqa: E402
from pdf2idea.model import ForceRow, LoadCase, MemberInfo, ParseResult  # noqa: E402


@pytest.fixture
def res():
    nodes = {1: (0.0, 0.0), 2: (0.0, 4.0), 3: (6.0, 4.0)}
    members = {1: MemberInfo(1, 1, 2, 4.0, "Stuetze"), 2: MemberInfo(2, 2, 3, 6.0, "Riegel")}
    fr = lambda x, n, vz: ForceRow(x, {"N": n, "Vz": vz, "My": 0.0})
    lc = LoadCase("Komb. 1", {1: [fr(0, -10, 1), fr(4, -10, 1)], 2: [fr(0, 1, -10), fr(6, 1, 10)]})
    return ParseResult("t", [lc], members, nodes)


def test_member_geometry(res):
    g = member_geometry(res)
    assert g[1][2] == 4.0 and g[1][3] == (0.0, 1.0)
    assert g[2][3] == (1.0, 0.0)


def test_local_axes_convention():
    # Stab nach oben: z lokal zeigt nach +x; Stab nach rechts: z lokal zeigt nach unten (-z)
    assert local_axes((0.0, 1.0)) == ((0.0, 1.0), (1.0, 0.0))
    assert local_axes((1.0, 0.0)) == ((1.0, 0.0), (0.0, -1.0))


def test_node_members(res):
    assert node_members(res, 2) == [(1, "Ende"), (2, "Anfang")]
    assert node_members(res, 1) == [(1, "Anfang")]


def test_station_keys():
    assert station_key_from_distance(0.0, 4.0) == "Anfang"
    assert station_key_from_distance(3.999, 4.0) == "Ende"
    assert station_key_from_distance(1.2345, 4.0) == "x=1.23"
    assert station_distance("x=1.23L", 4.0) == pytest.approx(1.23)
    assert station_distance("Ende", 4.0) == 4.0


def test_point_and_segment(res):
    assert point_on_member(res, 2, 1.5) == (1.5, 4.0)
    d, t = distance_point_segment(3.0, 5.0, 0.0, 4.0, 6.0, 4.0)
    assert d == pytest.approx(1.0) and t == pytest.approx(0.5)


def test_per_assignment_axes(res):
    # Eigene Achsen nur fuer diesen Stab: lokales z der Baustatik = -z lokal in IDEA (Vz, My, N unveraendert bzw. gedreht)
    own = {"x": "+x", "y": "-y", "z": "-z"}                 # Drehung um x um 180 Grad
    from pdf2idea.axes import component_map_from_axes
    a1 = Assignment("Stuetze", "Ende", stab=1, station="Ende", axes=own, component_map=component_map_from_axes(own))
    a2 = Assignment("Riegel", "Anfang", stab=2, station="Anfang")       # Standard (Identitaet)
    rows, _ = build_rows(res, Profile(assignments=[a1, a2]))
    assert rows[0].values == (-10, 0, -1, 0, 0, 0)        # Vz -> -Vz
    assert rows[1].values == (1, 0, -10, 0, 0, 0)         # unveraendert


def test_members_through_node():
    from pdf2idea.geometry import members_through_node
    r = ParseResult("x", [], {1: MemberInfo(1, 1, 3, 4.0), 2: MemberInfo(2, 4, 5, 2.0)},
                    {1: (0.0, 0.0), 2: (0.0, 3.0), 3: (0.0, 4.0), 4: (-1.0, 3.0), 5: (1.0, 3.0)})
    assert [(n, round(s, 6)) for n, s in members_through_node(r, 2)] == [(1, 3.0), (2, 1.0)]
    assert members_through_node(r, 3) == []
