"""Point-in-polygon booth assignment and the stored Victorian district boundaries."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vic_election.geo import District, assign_point, districts_from_geojson, simplify_ring, state_outline

BOUNDARIES = Path(__file__).resolve().parent.parent / "data" / "boundaries" / "vic_assembly_2022" / "districts.geojson"


def _square(name: str, x0: float, y0: float, size: float, hole: bool = False) -> District:
    outer = [(x0, y0), (x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size), (x0, y0)]
    rings = [outer]
    if hole:
        c = size / 4
        rings.append([(x0 + c, y0 + c), (x0 + 3 * c, y0 + c), (x0 + 3 * c, y0 + 3 * c), (x0 + c, y0 + 3 * c), (x0 + c, y0 + c)])
    return District(name, "Test", [rings], (x0, y0, x0 + size, y0 + size))


def test_inside_hole_nearest_and_outside() -> None:
    districts = [_square("A", 145.0, -38.0, 0.1, hole=True), _square("B", 145.1, -38.0, 0.1)]
    assert assign_point(districts, 145.01, -37.99) == ("A", "inside")
    assert assign_point(districts, 145.15, -37.95) == ("B", "inside")
    assert assign_point(districts, 145.05, -37.95)[1] != "inside"  # in A's hole
    assert assign_point(districts, 145.25, -37.95) == ("B", "nearest")  # ~4.4 km east of B
    assert assign_point(districts, 149.1, -35.3) == (None, "outside")  # Canberra


def test_simplify_keeps_closed_ring_with_min_points() -> None:
    ring = [(145 + i * 1e-6, -38.0) for i in range(50)] + [(145.0, -37.9), (145.0, -38.0)]
    out = simplify_ring(ring, 1e-4)
    assert out[0] == ring[0] and out[-1] == ring[-1] and len(out) >= 4


def test_shapefile_holes_exclude_enclaves() -> None:
    from vic_election.geo import shapefile_polygons
    outer = [(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)]  # clockwise: ESRI outer ring
    hole = [(4, 4), (6, 4), (6, 6), (4, 6), (4, 4)]  # anticlockwise: hole (an enclave of another district)
    polys = shapefile_polygons([outer, hole])
    assert len(polys) == 1 and len(polys[0]) == 2
    d = District("Surround", "", polys, (0, 0, 10, 10))
    assert d.contains(1, 1) and not d.contains(5, 5)


def test_state_outline_cancels_shared_edges() -> None:
    rings = state_outline([_square("A", 145.0, -38.0, 0.1), _square("B", 145.1, -38.0, 0.1)])
    assert len(rings) == 1 and rings[0][0] == rings[0][-1]
    assert {p for p in rings[0]} == {(145.0, -38.0), (145.1, -38.0), (145.2, -38.0), (145.2, -37.9), (145.1, -37.9), (145.0, -37.9)}


@pytest.mark.skipif(not BOUNDARIES.exists(), reason="boundaries not fetched; run scripts/build_visualiser.py")
def test_88_districts_match_vec_names_and_known_points() -> None:
    districts = districts_from_geojson(json.loads(BOUNDARIES.read_text()))
    vec = json.loads((BOUNDARIES.parents[2] / "2022" / "distributions" / "official_2022.json").read_text())
    assert sorted(d.name for d in districts) == sorted(vec)
    assert assign_point(districts, 144.9631, -37.8136)[0] == "Melbourne"  # Melbourne GPO
    assert assign_point(districts, 141.5640, -38.3436)[0] == "South-West Coast"  # Portland
    assert assign_point(districts, 142.1580, -34.1855)[0] == "Mildura"
