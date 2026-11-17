#!/usr/bin/env python3
"""
Model 3: model1's federal-booth replay plus (a) soft booth→district splitting by distance to
boundaries and (b) rescaling district primaries to state polling. See model3/README.md.

  run_model3.py "VIC2022 (2022)" --lam 1.18 --clip C1 --rescale R3 [--runs --seed]   # one variant
  run_model3.py --grid T1                                                          # primary-error grid
  run_model3.py --grid T3 [--reduced]                                              # simulated-seat grid
  run_model3.py --all --lam 1.18 --clip C1 --rescale R3                              # one variant, every run

Outputs: predictions/modelling/model3/output/<run_id> L<lam>-<clip>-<rescale>/ plus grid_T1.csv,
grid_T3.csv and summary_T3.csv.
"""
from __future__ import annotations

import argparse
import csv
import tempfile
import itertools
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

MODEL3_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MODEL3_DIR))          # model3
sys.path.insert(0, str(MODEL3_DIR.parent / "model1"))  # model1 + run_model1 (imported, not copied)

import model1  # noqa: E402
import model3  # noqa: E402
import run_model1  # noqa: E402
import vic_election.polls as vic_polls
from vic_election.benchmark import align_districts, bloc_seats, load_forecast, norm_district, party_group, score  # noqa: E402
from vic_election.booth_flows import OWN_DIVISION_TOLERANCE_KM, assign_booths, load_booth_flows, load_candidates, load_polling_places  # noqa: E402
from vic_election.config import DATA_DIR, FEDERAL_BOUNDARIES_DIR, MODELS_DIR, ROOT, RUNS, WINNERS_DIR, BenchmarkRun, majority_of, vec_distributions_path  # noqa: E402
from vic_election.geo import fetch_national_divisions, load_state_districts  # noqa: E402

MODEL = "model3"
OUTPUT_DIR = MODELS_DIR / MODEL / "output"
FIELDS = run_model1.FIELDS
POLL_CSV = DATA_DIR / "benchmarks" / "polls" / "final_polls.csv"
VIC2026_POLLS = DATA_DIR / "2026" / "polls_vic2026.csv"
SCORED_RUNS = [r for r in RUNS if RUNS[r].winners]
CLIPS = ("C0", "C1")
RESCALES = ("R0", "R2", "R3")


def variant_dir(run_id: str, lam: float, clip: str, rescale: str, out_root: Path = OUTPUT_DIR) -> Path:
    return out_root / f"{run_id} L{lam:g}-{clip}-{rescale}"


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))




def poll_target_for(bench: BenchmarkRun) -> tuple[dict[str, float], list[str]]:
    """(target shares, poll rows used). The VIC2026 forecast averages the live poll register."""
    if bench.winners is None:  # VIC2026 (2025)
        sys.path.insert(0, str(MODEL3_DIR.parent / "model2"))
        import model2  # noqa: E402
        avg = model2.poll_average(read_csv(VIC2026_POLLS), as_of=None)
        return {c: avg[c] / 100 for c in ("ALP", "LNP", "GRN", "ON", "OTH")}, avg["_polls"]
    election = f"{bench.state}{bench.state_election[:4]}"
    rows = vic_polls.load_final_polls(election)
    return model3.poll_target(rows), [f"{r['pollster']} {r['fieldwork_end']}" for r in rows]


def setup(run_id: str) -> dict:
    """Shared inputs for a run: geometry cache + model1's booths/weights, exactly as model1 sets up."""
    bench = RUNS[run_id]
    districts = load_state_districts(bench.state, bench.state_election)
    divisions = fetch_national_divisions(FEDERAL_BOUNDARIES_DIR, bench.federal_year, states=(bench.state,))
    candidates = load_candidates(bench.federal_dir / "house", bench.event)
    booths, declaration = load_booth_flows(bench.federal_dir / "house", bench.event, bench.state)
    places = load_polling_places(bench.federal_dir / "general", bench.event, bench.state)
    assignment = assign_booths(places, districts, divisions)
    weights = model1.preference_weights([*booths.values(), *declaration.values()], candidates)
    by_name = {d.name: d for d in districts}
    div_by_name = {d.name.lower(): d for d in divisions}
    near: dict[str, dict[str, float]] = {}   # counted booth -> {district: km}
    keep: dict[str, dict[str, bool]] = {}    # counted booth -> {district: C1-eligible} (lazy)
    for pid, b in booths.items():
        loc = assignment.get(pid)
        if loc is None or not loc.counted:
            continue
        p = places[pid]
        near[pid] = model3.nearby_districts(float(p["Longitude"]), float(p["Latitude"]), districts)
        if not near[pid]:
            raise SystemExit(f"{run_id}: counted booth {pid} ({b.name}) has no district within {model3.R_MAX} km")
    return {
        "bench": bench, "districts": districts, "divisions": divisions, "candidates": candidates,
        "booths": booths, "declaration": declaration, "places": places, "assignment": assignment,
        "weights": weights, "by_name": by_name, "div_by_name": div_by_name, "near": near, "keep": keep,
    }


def _clip_keep(ctx: dict, pid: str, name: str) -> bool:
    """C1: is district `name`'s nearest boundary point inside booth `pid`'s own federal division."""
    cache = ctx["keep"].setdefault(pid, {})
    if name not in cache:
        p = ctx["places"][pid]
        lon, lat = float(p["Longitude"]), float(p["Latitude"])
        div = ctx["div_by_name"].get((p["DivisionNm"] or "").lower())
        cache[name] = model3.clip_keep(lon, lat, ctx["by_name"][name], div)
    return cache[name]


def primaries_for(ctx: dict, lam: float, clip: str) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """Split-booth district primaries + booth weights, from the cached distances."""
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    booth_w: dict[str, dict[str, float]] = {}
    for pid, dists in ctx["near"].items():
        own = ctx["assignment"][pid].district
        if clip == "C1":
            dists = {n: d for n, d in dists.items() if n == own or _clip_keep(ctx, pid, n)}
        w = model3.split_weights(dists, lam, own)
        booth_w[pid] = w
        for (src, to), v in ctx["booths"][pid].votes.items():
            group = ctx["candidates"][to].group if src == model1.FIRST else ctx["candidates"][src].group
            for d, share in w.items():
                out[d][group] += share * v
    return {d: dict(prim) for d, prim in out.items()}, booth_w


def rescale(primaries: dict, rescale: str, target: dict[str, float]) -> dict:
    if rescale == "R0":
        return {d: dict(p) for d, p in primaries.items()}
    return model3.rescale_r2(primaries, target) if rescale == "R2" else model3.rescale_r3(primaries, target)


# ---------- T1: primary-error benchmark ----------


def _actual_shares(bench: BenchmarkRun, district_names: list[str], on_polled: bool) -> dict[str, dict[str, float]]:
    """Actual state-election first-preference shares by poll category, per district."""
    if bench.winners.startswith("vec:"):
        path = vec_distributions_path(int(bench.winners.split(":")[1]))
    else:
        path = DATA_DIR / bench.winners / "distributions" / f"dop_{bench.winners}.json"
    tables = json.loads(path.read_text(encoding="utf-8"))
    by_norm = {norm_district(k): v for k, v in tables.items()}
    out = {}
    for d in district_names:
        t = by_norm.get(norm_district(d))
        if t is None:
            continue
        party = {c["candidate_id"]: party_group(c["party"]) for c in t["candidates"]}
        cats: Counter = Counter()
        for cid, v in t["first_preferences"].items():
            cats[model3.cat_of(party[cid], on_polled)] += v
        z = sum(cats.values())
        out[d] = {c: cats[c] / z for c in model3.CATEGORIES}
    return out


def predicted_shares(primaries: dict[str, dict[str, float]], on_polled: bool) -> dict[str, dict[str, float]]:
    return {d: {c: sum(v for p, v in prim.items() if model3.cat_of(p, on_polled) == c) / sum(prim.values())
                for c in model3.CATEGORIES}
            for d, prim in primaries.items()}


def t1_mae(pred: dict[str, dict[str, float]], actual: dict[str, dict[str, float]],
           on_polled: bool) -> tuple[float, dict[str, float]]:
    """Mean over districts of the mean |predicted - actual| share (fraction) across categories."""
    cats = [c for c in model3.CATEGORIES if c != "ON" or on_polled]
    per_cat: dict[str, list[float]] = {c: [] for c in cats}
    for d, a in actual.items():
        for c in cats:
            per_cat[c].append(abs(pred[d][c] - a[c]))
    cat_mae = {c: 100 * sum(v) / len(v) for c, v in per_cat.items() if v}
    return sum(cat_mae.values()) / len(cat_mae), cat_mae


def grid_t1(out_path: Path = OUTPUT_DIR / "grid_T1.csv") -> list[dict]:
    rows = []
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["run_id", "lam", "clip", "rescale", "mae_pp"] + [f"mae_{c}" for c in model3.CATEGORIES])
        for run_id in SCORED_RUNS:
            ctx = setup(run_id)
            target, _ = poll_target_for(ctx["bench"])
            on_polled = target.get("ON", 0) > 0
            actual = _actual_shares(ctx["bench"], [d.name for d in ctx["districts"]], on_polled)
            for lam, clip in itertools.product(model3.DEFAULT_LAMBDAS, CLIPS):
                prim, _ = primaries_for(ctx, lam, clip)
                for r in RESCALES:
                    pred = predicted_shares(rescale(prim, r, target), on_polled)
                    mae, cat_mae = t1_mae(pred, actual, on_polled)
                    row = {"run_id": run_id, "lam": lam, "clip": clip, "rescale": r, "mae": mae, **cat_mae}
                    rows.append(row)
                    w.writerow([run_id, f"{lam:g}", clip, r, round(mae, 4)]
                               + [round(cat_mae.get(c, 0), 4) for c in model3.CATEGORIES])
            print(f"{run_id}: T1 done", flush=True)
    return rows


# ---------- full run (T3) ----------


def run(run_id: str, lam: float, clip: str, rescale_v: str, runs: int, seed: int) -> dict:
    return run_variant(setup(run_id), lam, clip, rescale_v, runs, seed)


def run_variant(ctx: dict, lam: float, clip: str, rescale_v: str, runs: int, seed: int,
                out_root: Path = OUTPUT_DIR) -> dict:
    bench = ctx["bench"]
    run_id = bench.run_id
    primaries, booth_w = primaries_for(ctx, lam, clip)
    missing = [d.name for d in ctx["districts"] if d.name not in primaries]
    if missing:
        raise SystemExit(f"{run_id}: no counted polling place in {missing}")
    federal = primaries
    target, poll_rows = poll_target_for(bench)
    names = notes = None
    if run_id in FIELDS:
        if not FIELDS[run_id].exists():
            raise SystemExit(f"Needs {FIELDS[run_id].relative_to(ROOT)}: run scripts/fetch_vic2026_candidates.py")
        field, names = run_model1.load_field(FIELDS[run_id])
        primaries, notes = model1.apply_state_field(primaries, field, ctx["weights"])
    primaries = rescale(primaries, rescale_v, target)
    majority = majority_of(len(ctx["districts"]))
    sim = model1.simulate(primaries, ctx["weights"], runs=runs, seed=seed, noise=model1.NOISE)

    out = variant_dir(run_id, lam, clip, rescale_v, out_root)
    out.mkdir(parents=True, exist_ok=True)
    run_model1.write_seat_probabilities(out / "seat_probabilities.csv", primaries, sim)
    run_model1.write_statewide_seats(out / "statewide_seats.csv", sim, majority)
    run_model1.write_statewide_seats(out / "statewide_blocs.csv", sim, majority, bloc_seats(sim["seats"]))
    run_model1.write_district_primaries(out / "district_primaries.csv", {d: Counter(p) for d, p in federal.items()})
    run_model1.write_district_primaries(out / "simulated_primaries.csv", {d: Counter(p) for d, p in primaries.items()})
    with (out / "booth_assignment.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["booth", "district", "weight"])
        for pid in sorted(booth_w):
            for d, share in sorted(booth_w[pid].items()):
                w.writerow([pid, d, round(share, 6)])
    (out / "district_counts.json").write_text(
        json.dumps(run_model1.district_counts(primaries, sim, ctx["weights"], names, notes), separators=(",", ":")),
        encoding="utf-8")

    meta = {
        "model": MODEL, "run_id": run_id, "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": run_model1.git_commit(), "runs": runs, "seed": seed, "noise_log_sd": model1.NOISE,
        "variant": {"lam": lam, "clip": clip, "rescale": rescale_v, "r_max_km": model3.R_MAX,
                    "clip_tolerance_km": model3.CLIP_TOLERANCE_KM},
        "inputs": {
            "state": bench.state, "state_election": bench.state_election, "districts": len(ctx["districts"]),
            "federal_election": bench.federal_year, "aec_event": bench.event, "aec_download": run_model1.input_manifest(bench),
            "booths": f"inside the district and within {OWN_DIVISION_TOLERANCE_KM} km of their own federal division",
            "poll_target": {c: round(100 * v, 3) for c, v in sorted(target.items())}, "poll_rows": poll_rows,
            "winners": bench.winners,
            "state_field": str(FIELDS[run_id].relative_to(ROOT)) if run_id in FIELDS else None,
        },
    }
    if bench.winners:
        forecast = load_forecast(out / "seat_probabilities.csv")
        actual = align_districts(run_model1.winners_for(bench.winners), list(forecast))
        meta["scores"] = score(forecast, actual)
        meta["actual_seats"] = {p: list(actual.values()).count(p) for p in sorted(set(actual.values()))}
        (out / "scores.json").write_text(json.dumps(meta["scores"], indent=2), encoding="utf-8")
    meta["predicted_seats_mean"] = {p: round(sum(s) / len(s), 2) for p, s in sim["seats"].items() if any(s)}
    (out / "run_metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def grid_t3(variants: list[tuple[float, str, str]], runs: int, seed: int) -> list[dict]:
    # trial outputs go to a throwaway directory; only the CSVs land in output/
    tmp = Path(tempfile.mkdtemp(prefix="model3_grid_"))
    out_path = OUTPUT_DIR / "grid_T3.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["run_id", "lam", "clip", "rescale", "raw_seats", "districts", "brier", "log_loss"])
        rows = []
        for run_id in SCORED_RUNS:
            ctx = setup(run_id)
            for lam, clip, r in variants:
                meta = run_variant(ctx, lam, clip, r, runs, seed, tmp)
                s = meta["scores"]
                row = {"run_id": run_id, "lam": lam, "clip": clip, "rescale": r,
                       "raw_seats": s["raw_seat_count"], "districts": s["districts"],
                       "brier": s["brier"], "log_loss": s["log_loss"]}
                rows.append(row)
                w.writerow([run_id, f"{lam:g}", clip, r, s["raw_seat_count"], s["districts"],
                            round(s["brier"], 4), round(s["log_loss"], 4)])
                print(f"{run_id} L{lam:g}-{clip}-{r}: {s['raw_seat_count']}/{s['districts']} acc, "
                      f"Brier {s['brier']}, log {s['log_loss']}", flush=True)
    return rows


def summarise(t3_rows: list[dict], t1_rows: list[dict]) -> list[dict]:
    """summary_T3.csv: per variant mean accuracy/Brier/log loss over the scored runs + mean T1 MAE."""
    t1: dict[tuple, list[float]] = defaultdict(list)
    for r in t1_rows:
        t1[(r["lam"], r["clip"], r["rescale"])].append(r["mae"])
    by_var: dict[tuple, list[dict]] = defaultdict(list)
    for r in t3_rows:
        by_var[(r["lam"], r["clip"], r["rescale"])].append(r)
    rows = []
    for (lam, clip, r), rs in by_var.items():
        rows.append({
            "lam": lam, "clip": clip, "rescale": r, "n_runs": len(rs),
            "mean_accuracy": sum(x["raw_seats"] / x["districts"] for x in rs) / len(rs),
            "mean_brier": sum(x["brier"] for x in rs) / len(rs),
            "mean_log_loss": sum(x["log_loss"] for x in rs) / len(rs),
            "mean_t1_mae": sum(t1[(lam, clip, r)]) / len(t1[(lam, clip, r)]) if t1.get((lam, clip, r)) else None,
        })
    rows.sort(key=lambda x: (x["mean_log_loss"], x["mean_brier"], x["mean_t1_mae"] or 9e9))
    with (OUTPUT_DIR / "summary_T3.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["lam", "clip", "rescale", "n_runs", "mean_accuracy", "mean_brier", "mean_log_loss", "mean_t1_mae"])
        for x in rows:
            w.writerow([f"{x['lam']:g}", x["clip"], x["rescale"], x["n_runs"], round(x["mean_accuracy"], 4),
                        round(x["mean_brier"], 4), round(x["mean_log_loss"], 4),
                        "" if x["mean_t1_mae"] is None else round(x["mean_t1_mae"], 4)])
    return rows


def select(rows: list[dict]) -> dict:
    """Lowest mean log loss; ties within 0.005 by mean Brier, then mean T1 MAE."""
    best = min(rows, key=lambda x: x["mean_log_loss"])
    tied = [x for x in rows if x["mean_log_loss"] <= best["mean_log_loss"] + 0.005]
    return min(tied, key=lambda x: (x["mean_brier"], x["mean_t1_mae"] or 9e9))


def main() -> None:
    p = argparse.ArgumentParser(description="Model 3: model1 + soft booth splitting + poll rescaling")
    p.add_argument("run_ids", nargs="*")
    p.add_argument("--all", action="store_true")
    p.add_argument("--grid", choices=["T1", "T3"])
    p.add_argument("--reduced", action="store_true", help="T3: reduced variant set instead of the full 42")
    p.add_argument("--lam", type=float, default=0)
    p.add_argument("--clip", choices=CLIPS, default="C0")
    p.add_argument("--rescale", choices=RESCALES, default="R2")
    p.add_argument("--runs", type=int, default=1000)
    p.add_argument("--seed", type=int, default=1)
    args = p.parse_args()

    if args.grid == "T1":
        grid_t1()
        return
    if args.grid == "T3":
        variants = [(lam, c, r) for lam, c, r in
                    itertools.product(model3.DEFAULT_LAMBDAS, CLIPS, RESCALES)]
        if args.reduced:
            variants = [(0, "C0", "R0")]
            variants += [(lam, c, r) for lam, c, r in
                         itertools.product((0.5, 1.18, 2.0), CLIPS, RESCALES)]
            t1 = read_csv(OUTPUT_DIR / "grid_T1.csv")
            for c, r in itertools.product(CLIPS, RESCALES):
                best = min((x for x in t1 if x["clip"] == c and x["rescale"] == r),
                           key=lambda x: float(x["mae_pp"]))
                lam = float(best["lam"])
                if (lam, c, r) not in variants:
                    variants.append((lam, c, r))
        t3 = grid_t3(variants, args.runs, args.seed)
        t1_rows = [{"lam": float(x["lam"]), "clip": x["clip"], "rescale": x["rescale"], "mae": float(x["mae_pp"])}
                   for x in read_csv(OUTPUT_DIR / "grid_T1.csv")] if (OUTPUT_DIR / "grid_T1.csv").exists() else []
        summarise(t3, t1_rows)
        return

    unknown = [r for r in args.run_ids if r not in RUNS]
    if unknown:
        raise SystemExit(f"Unknown run(s) {unknown}; choose from {list(RUNS)}")
    for run_id in (list(RUNS) if args.all else args.run_ids):
        meta = run(run_id, args.lam, args.clip, args.rescale, args.runs, args.seed)
        s = meta.get("scores")
        seats = ", ".join(f"{p} {v:.1f}" for p, v in sorted(meta["predicted_seats_mean"].items(), key=lambda kv: -kv[1]))
        print(f"{run_id}: {seats}" + (f" | {s['raw_seat_count']}/{s['districts']}, Brier {s['brier']}, log loss {s['log_loss']}" if s else ""))


if __name__ == "__main__":
    main()
