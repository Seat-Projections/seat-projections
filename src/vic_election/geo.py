"""
Electoral boundaries and point-in-polygon assignment of polling places to districts. Pure Python: no GIS
dependencies.

Sources: Victorian Legislative Assembly districts (EBC 2021 redivision, KMZ), AEC federal divisions
(MapInfo MID/MIF or ESRI shapefile) and Geoscape state electoral districts for NSW, QLD, WA and SA (shapefile).
Coordinates are WGS84 (longitude, latitude). A polygon is a list of rings (outer ring first, then holes);
a district geometry is a list of polygons.
"""
from __future__ import annotations

import csv
import io
import json
import math
import struct
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .config import STATE_BOUNDARIES_DIR, VIC_DISTRICTS_GEOJSON
from .http_cache import CachedSession

EBC_DISTRICTS_KMZ_URL = (
    "https://www.ebc.vic.gov.au/files/2021-boundaries/resources/New%20districts%20and%20regions.kmz"
)
_KML = "{http://www.opengis.net/kml/2.2}"

Ring = list[tuple[float, float]]
Polygon = list[Ring]

# Kilometres per degree of longitude (at the equator; scaled by cos(latitude)) and of latitude, for
# the small-distance approximation used by District.distance
KM_PER_DEGREE_LON = 111.32
KM_PER_DEGREE_LAT = 110.57
# A booth outside every district polygon is still assigned if it lies within this distance of one
# (coastal booths, booths just over a state border)
NEAREST_DISTRICT_MAX_KM = 5.0
# Ring simplification tolerances in degrees (~20 m and ~10 m): point-in-polygon tests only need street-level accuracy
FEDERAL_DIVISION_TOLERANCE_DEG = 0.0002
STATE_DISTRICT_TOLERANCE_DEG = 0.0001


@dataclass
class District:
    name: str
    region: str
    polygons: list[Polygon]
    bbox: tuple[float, float, float, float]  # min_lon, min_lat, max_lon, max_lat

    def contains(self, lon: float, lat: float) -> bool:
        x0, y0, x1, y1 = self.bbox
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            return False
        # Inside the outer ring and not inside any hole
        return any(_in_ring(lon, lat, p[0]) and not any(_in_ring(lon, lat, h) for h in p[1:]) for p in self.polygons)

    def distance(self, lon: float, lat: float) -> float:
        """Approximate distance in km from a point to the district boundary."""
        kx = KM_PER_DEGREE_LON * math.cos(math.radians(lat))
        ky = KM_PER_DEGREE_LAT
        return min(
            _seg_dist((lon - a[0]) * kx, (lat - a[1]) * ky, (b[0] - a[0]) * kx, (b[1] - a[1]) * ky)
            for p in self.polygons
            for ring in p
            for a, b in zip(ring, ring[1:])
        )


def _in_ring(x: float, y: float, ring: Ring) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _seg_dist(px: float, py: float, dx: float, dy: float) -> float:
    """Distance from point (px, py) to the segment from (0, 0) to (dx, dy)."""
    t = max(0.0, min(1.0, (px * dx + py * dy) / (dx * dx + dy * dy))) if (dx or dy) else 0.0
    return math.hypot(px - t * dx, py - t * dy)


def _parse_ring(el: ET.Element) -> Ring:
    text = el.findtext(f".//{_KML}coordinates") or ""
    return [(float(c.split(",")[0]), float(c.split(",")[1])) for c in text.split()]


def _bbox(polygons: list[Polygon]) -> tuple[float, float, float, float]:
    pts = [pt for p in polygons for pt in p[0]]
    return min(x for x, _ in pts), min(y for _, y in pts), max(x for x, _ in pts), max(y for _, y in pts)


def parse_districts_kml(kml: bytes, names: dict[str, str] | None = None) -> list[District]:
    """`names` maps upper-case district names to the VEC's preferred spelling (e.g. 'BOX HILL' -> 'Box Hill')."""
    names = names or {}
    districts = []
    for pm in ET.fromstring(kml).iter(f"{_KML}Placemark"):
        data = {d.get("name"): d.text or "" for d in pm.iter(f"{_KML}SimpleData")}
        raw = data.get("DISTRICT") or pm.findtext(f"{_KML}name") or ""
        polygons = [
            [_parse_ring(b) for b in poly.findall(f"{_KML}outerBoundaryIs")]
            + [_parse_ring(b) for b in poly.findall(f"{_KML}innerBoundaryIs")]
            for poly in pm.iter(f"{_KML}Polygon")
        ]
        districts.append(District(names.get(raw.upper(), raw.title()), data.get("REGION", "").title(), polygons, _bbox(polygons)))
    return sorted(districts, key=lambda d: d.name)


def parse_mif_regions(mif: str, mid: str) -> list[District]:
    """
    AEC division boundaries in MapInfo MID/MIF (longitude/latitude). Each `Region n` object holds n rings,
    stored here as separate polygons (enclaves are not treated as holes). Names come from the MID file's
    second column, in the same order as the MIF objects.
    """
    names = [row[1] for row in csv.reader(mid.splitlines()) if len(row) > 1]
    lines = iter(mif.splitlines())
    for line in lines:
        if line.strip().lower() == "data":
            break
    regions = []
    for line in lines:
        tok = line.split()
        if tok and tok[0].lower() == "region":
            polys = []
            for _ in range(int(tok[1])):
                n = int(next(lines).split()[0])
                polys.append([[tuple(map(float, next(lines).split()[:2])) for _ in range(n)]])
            regions.append(polys)
    return [District(name, "", polys, _bbox(polys)) for name, polys in zip(names, regions)]


def assign_point(districts: list[District], lon: float, lat: float, max_km: float = NEAREST_DISTRICT_MAX_KM) -> tuple[str | None, str]:
    """
    Return (district, method): 'inside' if the point is in a polygon; 'nearest' if it lies within `max_km`
    of a district (e.g. a coastal booth or one just over the state border); otherwise (None, 'outside').
    """
    for d in districts:
        if d.contains(lon, lat):
            return d.name, "inside"
    dist, nearest = min((d.distance(lon, lat), d.name) for d in districts)
    return (nearest, "nearest") if dist <= max_km else (None, "outside")


def state_outline(districts: list[District]) -> list[Ring]:
    """
    Outer boundary of the union of all districts (mainland plus islands), as closed rings.
    Edges shared by two districts cancel out; the remaining edges are walked into rings.
    """
    count: Counter = Counter()
    directed = []
    for d in districts:
        for poly in d.polygons:
            for ring in poly:
                for a, b in zip(ring, ring[1:]):
                    if a != b:
                        count[frozenset((a, b))] += 1
                        directed.append((a, b))
    boundary = [e for e in directed if count[frozenset(e)] == 1]
    nxt: dict[tuple[float, float], list[tuple[float, float]]] = defaultdict(list)
    for a, b in boundary:
        nxt[a].append(b)
    used: set = set()
    rings = []
    for edge in boundary:
        if edge in used:
            continue
        ring = [edge[0]]
        while edge and edge not in used:
            used.add(edge)
            ring.append(edge[1])
            edge = next(((edge[1], n) for n in nxt[edge[1]] if (edge[1], n) not in used), None)
        rings.append(ring)
    return sorted(rings, key=len, reverse=True)


def to_geojson(districts: list[District], tolerance: float = 0.0, decimals: int = 6) -> dict:
    """GeoJSON FeatureCollection; `tolerance` (degrees) > 0 simplifies rings for display."""

    def ring(r: Ring) -> list[list[float]]:
        pts = simplify_ring(r, tolerance) if tolerance else r
        return [[round(x, decimals), round(y, decimals)] for x, y in pts]

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"district": d.name, "region": d.region},
                "geometry": {"type": "MultiPolygon", "coordinates": [[ring(r) for r in p] for p in d.polygons]},
            }
            for d in districts
        ],
    }


def districts_from_geojson(gj: dict) -> list[District]:
    out = []
    for f in gj["features"]:
        polys = [[[(x, y) for x, y in r] for r in p] for p in f["geometry"]["coordinates"]]
        out.append(District(f["properties"]["district"], f["properties"]["region"], polys, _bbox(polys)))
    return out


def simplify_ring(ring: Ring, tol: float) -> Ring:
    """Ramer-Douglas-Peucker on a closed ring; keeps at least 4 points."""
    if len(ring) < 8:
        return ring
    keep = [False] * len(ring)
    keep[0] = keep[-1] = True
    stack = [(0, len(ring) - 1)]
    while stack:
        i, j = stack.pop()
        (ax, ay), (bx, by) = ring[i], ring[j]
        best, idx = 0.0, -1
        for k in range(i + 1, j):
            d = _seg_dist(ring[k][0] - ax, ring[k][1] - ay, bx - ax, by - ay)
            if d > best:
                best, idx = d, k
        if best > tol:
            keep[idx] = True
            stack += [(i, idx), (idx, j)]
    out = [p for p, k in zip(ring, keep) if k]
    return out if len(out) >= 4 else ring


def read_dbf(data: bytes) -> list[dict[str, str]]:
    """Records of a dBASE (.dbf) table, all values as stripped strings."""
    n, header_len, rec_len = struct.unpack("<IHH", data[4:12])
    fields, pos = [], 32
    while data[pos] != 0x0D:
        fields.append((data[pos:pos + 11].split(b"\0")[0].decode("latin-1"), data[pos + 16]))
        pos += 32
    rows = []
    for i in range(n):
        rec = data[header_len + i * rec_len: header_len + (i + 1) * rec_len]
        if rec[:1] == b"*":  # deleted
            continue
        off, row = 1, {}
        for name, width in fields:
            row[name] = rec[off:off + width].decode("latin-1").strip()
            off += width
        rows.append(row)
    return rows


def read_shp_polygons(data: bytes) -> list[list[Ring]]:
    """Polygon records of an ESRI .shp file (lon/lat), each a list of rings; null shapes give []."""
    out, pos = [], 100
    while pos + 8 <= len(data):
        content_len = struct.unpack(">i", data[pos + 4:pos + 8])[0] * 2
        rec = data[pos + 8: pos + 8 + content_len]
        pos += 8 + content_len
        if struct.unpack("<i", rec[:4])[0] == 0:
            out.append([])
            continue
        n_parts, n_points = struct.unpack("<ii", rec[36:44])
        parts = list(struct.unpack(f"<{n_parts}i", rec[44:44 + 4 * n_parts])) + [n_points]
        pts = struct.unpack(f"<{2 * n_points}d", rec[44 + 4 * n_parts: 44 + 4 * n_parts + 16 * n_points])
        out.append([[(pts[2 * k], pts[2 * k + 1]) for k in range(parts[j], parts[j + 1])] for j in range(n_parts)])
    return out


# Geoscape Administrative Boundaries: state electoral districts (data.gov.au, CC BY 4.0)
GEOSCAPE_STATE_SED = {
    "SA": "https://data.gov.au/data/dataset/e9fb5d4f-8117-4aa9-8481-6e06ee9f1fae/resource/3565f80d-49db-4908-bfbe-8e607dab7e59/download/sa_sed_gda94.zip",
    "NSW": "https://data.gov.au/data/dataset/8047ddd1-7193-4667-aef9-b75bc3076075/resource/05fdd482-bc77-44a8-80ed-6d856917cba8/download/nsw_sed_gda94.zip",
    "QLD": "https://data.gov.au/data/dataset/f0779c64-56cb-46c3-b46a-3bcbb907400d/resource/1ad8fe87-48a8-462c-87f2-71a777e49e5e/download/qld_sed_gda94.zip",
    "WA": "https://data.gov.au/data/dataset/c72845f8-45ff-4dd1-a955-87a32ee9d073/resource/3ba077e6-2d19-4bd5-ae8f-d3459558e682/download/wa_sed_gda94.zip",
}


# AEC national federal division boundaries (MID/MIF), by the federal election they applied to
AEC_NATIONAL_DIVISIONS = {
    2022: "https://www.aec.gov.au/Electorates/gis/files/2021-Cwlth_electoral_boundaries_mid-mif.zip",
    2025: "https://www.aec.gov.au/Electorates/files/2025/AUS-March-2025-midmif.zip",
}


# No national file covers the 2019 election: per-state boundaries in force at it (redistributions of 2016-2018)
AEC_2019_DIVISIONS = {
    "QLD": "https://www.aec.gov.au/Electorates/gis/files/qld-march-2018-esri.zip",
    "WA": "https://www.aec.gov.au/Electorates/gis/files/wa-midmif-19012016.zip",
    "SA": "https://www.aec.gov.au/Electorates/gis/files/sa-july-2018-mid-mif.zip",
}


def _divisions_from_zip(content: bytes) -> list[District]:
    """AEC division boundaries from a zip holding either MID/MIF or an ESRI shapefile (names in `Elect_div`)."""
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        files = [n for n in zf.namelist() if "sa1" not in n.lower()]  # some zips also carry SA1 statistical areas
        member = {Path(n).suffix.lower(): n for n in files if Path(n).suffix}
        if ".mif" in member:
            return parse_mif_regions(*(zf.read(member[s]).decode("latin-1") for s in (".mif", ".mid")))
        shapes, rows = read_shp_polygons(zf.read(member[".shp"])), read_dbf(zf.read(member[".dbf"]))
    return [District(r["Elect_div"], "", [[ring] for ring in s], _bbox([[ring] for ring in s])) for r, s in zip(rows, shapes) if s]


def fetch_national_divisions(
    out_dir: Path, year: int, tolerance: float = FEDERAL_DIVISION_TOLERANCE_DEG, refresh: bool = False, states: tuple[str, ...] = ()
) -> list[District]:
    """
    Federal divisions used at the `year` federal election (names are unique nationally), simplified.
    2022 and 2025 come from one national file; 2019 from per-state files for `states`.
    """
    urls = [AEC_NATIONAL_DIVISIONS[year]] if year in AEC_NATIONAL_DIVISIONS else [AEC_2019_DIVISIONS[s] for s in states]
    http = CachedSession(refresh)
    return [_simplified(d, tolerance) for url in urls for d in _divisions_from_zip(http.bytes(out_dir / url.rsplit("/", 1)[-1], url))]


def _simplified(d: District, tolerance: float) -> District:
    polys = [[simplify_ring(r, tolerance) for r in p] for p in d.polygons]
    return District(d.name, d.region, polys, d.bbox)


def _signed_area(ring: Ring) -> float:
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1])) / 2


def shapefile_polygons(rings: list[Ring]) -> list[Polygon]:
    """
    Group a shapefile record's rings into polygons: ESRI outer rings run clockwise (negative signed
    area), holes anticlockwise. Each hole joins the outer ring containing it, so a district with an
    enclave (e.g. Bundaberg inside Burnett) does not also claim the enclave's booths.
    """
    outers = [[r] for r in rings if _signed_area(r) < 0] or [[r] for r in rings]
    for hole in (r for r in rings if _signed_area(r) >= 0 and len(outers) and [r] not in outers):
        host = next((p for p in outers if _in_ring(hole[0][0], hole[0][1], p[0])), None)
        if host is not None:
            host.append(hole)
    return outers


def fetch_state_districts(out_dir: Path, state: str, on_date: str, tolerance: float = STATE_DISTRICT_TOLERANCE_DEG, refresh: bool = False) -> list[District]:
    """
    Geoscape state electoral districts in force on `on_date` (YYYY-MM-DD). Geoscape keeps retired
    versions with creation/retirement dates, so past boundaries can be selected. Holes (enclaves of
    other districts) are subtracted; region suffixes in names ('Churchlands, Nm') are dropped.
    """
    url = GEOSCAPE_STATE_SED[state]
    content = CachedSession(refresh).bytes(out_dir / url.rsplit("/", 1)[-1], url)
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = {Path(n).name.upper(): n for n in zf.namelist()}
        polys = read_shp_polygons(zf.read(names[f"{state}_STATE_ELECTORAL_POLYGON_SHP.SHP"]))
        poly_attrs = read_dbf(zf.read(names[f"{state}_STATE_ELECTORAL_POLYGON_SHP.DBF"]))
        districts = read_dbf(zf.read(names[f"{state}_STATE_ELECTORAL_SHP.DBF"]))

    day = on_date.replace("-", "")
    # EFF_START: first election the boundary applies to; EFF_END: the replacing election (or the day before it).
    # SECL_CODE 2 = lower house districts (3 = Legislative Council).
    name_by_pid = {
        r["SE_PID"]: r["NAME"].split(",")[0].strip() for r in districts
        if r.get("SECL_CODE", "2") == "2" and r["EFF_START"] <= day and (not r["EFF_END"] or r["EFF_END"] > day)
    }
    rings: dict[str, list[Polygon]] = defaultdict(list)
    for attrs, shape in zip(poly_attrs, polys):
        if attrs["SE_PID"] in name_by_pid and not attrs["DT_RETIRE"] and shape:
            rings[name_by_pid[attrs["SE_PID"]]].extend(shapefile_polygons(shape))
    return sorted((_simplified(District(n.title(), state, p, _bbox(p)), tolerance) for n, p in rings.items()), key=lambda d: d.name)


# 2012-13 redivision (used at the 2014 and 2018 elections): Vicmap Admin "State Assembly Polygon 2013" (VEC, CC BY 4.0)
VIC_DISTRICTS_2013_WFS_URL = (
    "https://opendata.maps.vic.gov.au/geoserver/wfs?service=WFS&version=2.0.0&request=GetFeature"
    "&typeNames=open-data-platform:state_assembly_2013&outputFormat=application/json&srsName=EPSG:4326"
)


def fetch_vic_districts_2013(out_dir: Path, tolerance: float = 0.0001, refresh: bool = False) -> list[District]:
    """The 88 Legislative Assembly districts of the 2013 redivision (cached GeoJSON from the Vicmap WFS)."""
    gj = json.loads(CachedSession(refresh).bytes(out_dir / "state_assembly_2013_wfs.json", VIC_DISTRICTS_2013_WFS_URL))
    out = []
    for f in gj["features"]:
        p = f["properties"]
        polys = [[[(x, y) for x, y in r] for r in poly] for poly in f["geometry"]["coordinates"]]
        name = p["district_label"].removesuffix(" District")
        region = p["region_label"].removesuffix(" Region")
        out.append(_simplified(District(name, region, polys, _bbox(polys)), tolerance))
    return sorted(out, key=lambda d: d.name)


def fetch_vic_districts(out_dir: Path, names: dict[str, str] | None = None, refresh: bool = False) -> list[District]:
    """Download the EBC 2021-redivision KMZ (cached) and write full-resolution `districts.geojson`."""
    kmz = CachedSession(refresh).bytes(out_dir / "districts_and_regions_2021.kmz", EBC_DISTRICTS_KMZ_URL)
    with zipfile.ZipFile(io.BytesIO(kmz)) as zf:
        kml = zf.read(next(n for n in zf.namelist() if n.endswith(".kml")))
    districts = parse_districts_kml(kml, names)
    (out_dir / "districts.geojson").write_text(json.dumps(to_geojson(districts)), encoding="utf-8")
    return districts


def load_state_districts(state: str, on_date: str | None = None) -> list[District]:
    """
    Lower-house districts of `state` in force on `on_date` (YYYY-MM-DD): Victoria from the committed EBC
    GeoJSON (2021 redivision, used in 2022 and 2026, names matching the VEC; `on_date` not needed), other
    states from Geoscape (downloaded and cached on first use).
    """
    if state == "VIC":
        return districts_from_geojson(json.loads(VIC_DISTRICTS_GEOJSON.read_text(encoding="utf-8")))
    if on_date is None:
        raise ValueError(f"{state} boundaries change between elections: pass the state election date")
    return fetch_state_districts(STATE_BOUNDARIES_DIR, state, on_date)
