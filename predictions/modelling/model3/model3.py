"""
Model 3 = model1 + soft booth→district splitting by distance to boundaries + rescaling to state polls.

(a) Booth splitting: a counted booth at point x in district A spreads its votes over every state
district within R_MAX km, with weight exp(-d_j/lam) (d_j = distance to polygon j, 0 inside).
lam = 0 reproduces model1's hard assignment. Variant C1 drops a neighbouring district whose nearest
boundary point lies outside the booth's own federal division (voters across a division line vote
elsewhere).

(b) Rescale: district primaries (after splitting, and after model1.apply_state_field for the 2026
run) are scaled so the statewide category shares match the poll target. Categories: ALP, LNP
(Coalition groups LP/NP/LNP/CLP), GRN, ON only when the poll reports it, OTH = everything else.
R2 = multiplicative factor per category, raked to targets; R3 = constant added to each member
party's logit(share), solved to targets.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from vic_election import polls
from vic_election.booth_flows import FIRST
from vic_election.geo import KM_PER_DEGREE_LAT, KM_PER_DEGREE_LON, District

R_MAX = 10.0  # km: districts farther than this never share a booth's votes
CLIP_TOLERANCE_KM = 0.2  # C1: a neighbour's nearest boundary point may be this far outside the division
DEFAULT_LAMBDAS = (0, 0.25, 0.5, 1.0, 1.18, 2.0, 4.0)

# party group -> poll category; everything else is OTH
CATEGORY = {"ALP": "ALP", "LAB": "ALP",
            "LP": "LNP", "NP": "LNP", "LNP": "LNP", "CLP": "LNP", "LIB": "LNP", "NAT": "LNP",
            "GRN": "GRN",
            "ON": "ON", "ONP": "ON", "PHON": "ON"}
CATEGORIES = ("ALP", "LNP", "GRN", "ON", "OTH")


def cat_of(group: str, on_polled: bool = True) -> str:
    c = CATEGORY.get(group, "OTH")
    return c if c != "ON" or on_polled else "OTH"


# ---------- geometry ----------


def nearest_boundary_point(lon: float, lat: float, district: District) -> tuple[float, float, float]:
    """Nearest point on the district's rings to (lon, lat): (lon, lat, distance km)."""
    kx = KM_PER_DEGREE_LON * math.cos(math.radians(lat))
    ky = KM_PER_DEGREE_LAT
    best = (0.0, 0.0, math.inf)
    for poly in district.polygons:
        for ring in poly:
            for a, b in zip(ring, ring[1:]):
                dx, dy = (b[0] - a[0]) * kx, (b[1] - a[1]) * ky
                px, py = (lon - a[0]) * kx, (lat - a[1]) * ky
                t = max(0.0, min(1.0, (px * dx + py * dy) / (dx * dx + dy * dy))) if (dx or dy) else 0.0
                d = math.hypot(px - t * dx, py - t * dy)
                if d < best[2]:
                    best = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), d)
    return best


def nearby_districts(lon: float, lat: float, districts: list[District], r_max: float = R_MAX) -> dict[str, float]:
    """{district name: distance km} for every district within r_max (bbox prefilter)."""
    kx = KM_PER_DEGREE_LON * math.cos(math.radians(lat))
    dx_deg, dy_deg = r_max / kx, r_max / KM_PER_DEGREE_LAT
    out = {}
    for d in districts:
        x0, y0, x1, y1 = d.bbox
        if lon < x0 - dx_deg or lon > x1 + dx_deg or lat < y0 - dy_deg or lat > y1 + dy_deg:
            continue
        dist = 0.0 if d.contains(lon, lat) else d.distance(lon, lat)
        if dist <= r_max:
            out[d.name] = dist
    return out


def split_weights(distances: dict[str, float], lam: float, own: str) -> dict[str, float]:
    """exp(-d/lam) weights over the nearby districts; lam=0 -> one-hot on `own`."""
    if lam == 0:
        return {own: 1.0}
    w = {d: math.exp(-dist / lam) for d, dist in distances.items()}
    z = sum(w.values())
    return {d: v / z for d, v in w.items()}


def clip_keep(lon: float, lat: float, district: District, division: District | None,
              tol: float = CLIP_TOLERANCE_KM) -> bool:
    """C1: keep a neighbour district only if its nearest boundary point lies in the booth's division."""
    if division is None:
        return True
    nx, ny, _ = nearest_boundary_point(lon, lat, district)
    return division.contains(nx, ny) or division.distance(nx, ny) <= tol


def district_primaries_split(booths, candidates, places, assignment, districts, divisions,
                             lam: float, clip: str) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """
    district -> party group -> votes, with each counted booth's votes spread over nearby districts.
    Also returns booth -> {district: weight} for booth_assignment.csv. lam=0 == model1.district_primaries.
    """
    by_name = {d.name: d for d in districts}
    div_by_name = {d.name.lower(): d for d in divisions}
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    booth_w: dict[str, dict[str, float]] = {}
    for pid, b in booths.items():
        loc = assignment.get(pid)
        if loc is None or not loc.counted:
            continue
        p = places[pid]
        lon, lat = float(p["Longitude"]), float(p["Latitude"])
        near = nearby_districts(lon, lat, districts)
        if clip == "C1":
            div = div_by_name.get((p["DivisionNm"] or "").lower())
            near = {n: dist for n, dist in near.items()
                    if n == loc.district or clip_keep(lon, lat, by_name[n], div)}
        w = split_weights(near, lam, loc.district)
        booth_w[pid] = w
        for (src, to), v in b.votes.items():
            group = candidates[to].group if src == FIRST else candidates[src].group
            for d, share in w.items():
                out[d][group] += share * v
    return {d: dict(prim) for d, prim in out.items()}, booth_w


# ---------- poll targets ----------


def poll_target(rows: list[dict]) -> dict[str, float]:
    """Statewide target shares (summing to 1) from final-poll rows (ALP/LNP/GRN/ON/OTH convention).

    ON is averaged only over rows that report it and is dropped (into OTH) when no row does;
    OTH = 100 - the other categories. Rows use the final_polls.csv column names."""
    out = polls.final_poll_mean(rows, oth_floor=False)
    return {c: v / 100 for c, v in out.items()}


# ---------- rescaling ----------


def _statewide_shares(primaries: dict[str, dict[str, float]], on_polled: bool) -> dict[str, float]:
    catv: dict[str, float] = Counter()
    for prim in primaries.values():
        for p, v in prim.items():
            catv[cat_of(p, on_polled)] += v
    z = sum(catv.values())
    return {c: catv[c] / z for c in CATEGORIES}


def rescale_r2(primaries: dict[str, dict[str, float]], target: dict[str, float],
               tol: float = 1e-6, max_iter: int = 300) -> dict[str, dict[str, float]]:
    """One multiplicative factor per category, raked iteratively: scale member parties, renormalise
    every district to its original total, repeat until statewide shares hit `target`."""
    on_polled = target.get("ON", 0) > 0
    totals = {d: sum(prim.values()) for d, prim in primaries.items()}
    out = {d: dict(prim) for d, prim in primaries.items()}
    cats = [c for c in CATEGORIES if c != "ON" or on_polled]
    for _ in range(max_iter):
        cur = _statewide_shares(out, on_polled)
        if max(abs(cur[c] - target.get(c, 0.0)) for c in cats) < tol:
            break
        for c in cats:
            a, t = cur[c], target.get(c, 0.0)
            if a <= 0 or t <= 0:
                continue
            f = t / a
            for prim in out.values():
                for p in list(prim):
                    if cat_of(p, on_polled) == c:
                        prim[p] *= f
        for d, prim in out.items():
            z = sum(prim.values())
            if z:
                for p in prim:
                    prim[p] *= totals[d] / z
    return out


def rescale_r3(primaries: dict[str, dict[str, float]], target: dict[str, float],
               tol: float = 1e-6, max_passes: int = 60) -> dict[str, dict[str, float]]:
    """Per category, a constant c added to logit(district share) of every member party in every
    district (then districts are renormalised to their original totals). Constants are solved to
    hit the statewide targets by alternating bisection."""
    on_polled = target.get("ON", 0) > 0
    totals = {d: sum(prim.values()) for d, prim in primaries.items()}
    cats = [c for c in CATEGORIES if c != "ON" or on_polled]
    members = {d: {c: [p for p in prim if cat_of(p, on_polled) == c] for c in cats}
               for d, prim in primaries.items()}
    consts = {c: 0.0 for c in cats}

    def apply() -> dict[str, dict[str, float]]:
        out = {}
        for d, prim in primaries.items():
            t = totals[d]
            new = dict(prim)
            for c in cats:
                if consts[c] == 0:
                    continue
                ec = math.exp(consts[c])
                for p in members[d][c]:
                    s = prim[p] / t
                    new[p] = t * (s * ec) / (1 - s + s * ec)
            z = sum(new.values())
            out[d] = {p: v * t / z for p, v in new.items()} if z else new
        return out

    def share_for(c: str, value: float) -> float:
        consts[c] = value
        s = _statewide_shares(apply(), on_polled)[c]
        return s

    for _ in range(max_passes):
        cur = _statewide_shares(apply(), on_polled)
        if max(abs(cur[c] - target.get(c, 0.0)) for c in cats) < tol:
            break
        for c in cats:
            t = target.get(c, 0.0)
            if cur[c] <= 0 or t <= 0:
                consts[c] = 0.0
                continue
            lo, hi = -8.0, 8.0  # share is increasing in c
            for _ in range(50):
                mid = (lo + hi) / 2
                if share_for(c, mid) < t:
                    lo = mid
                else:
                    hi = mid
            consts[c] = (lo + hi) / 2
    return apply()
