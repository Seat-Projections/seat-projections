#!/usr/bin/env python3
"""
Live-blog CLI for election night.

Data files (source of truth, both inside site/ so a GitHub web edit publishes):
  site/data/live_forecast_vic2026.json  frozen copy of the final forecast (written once by init)
  site/data/live_vic2026.json           {"title", "coverage_start", "entries": [...]}

Commands:
  init [--force]                          freeze the current forecast + create/keep the live file
  post "text" [--district Kew] [--call LP] [--push]
  call <District> <PARTY> [--note "text"] [--push]
  list
  edit <id> "new text" [--push]
  delete <id> [--push]

Party codes: LP, NP, ALP, GRN, ON, IND*, OTH (aliases LIB, NAT, LAB, ONP, IND).
Every write regenerates site/live/index.html via build_site.write_live (fast, not a full build).
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import build_site  # noqa: E402

ROOT = SCRIPTS.parent
SITE = ROOT / "site"
DATA = SITE / "data"
MODEL_JSON = DATA / "model2_vic2026.json"
LIVE = DATA / "live_vic2026.json"
FORECAST = DATA / "live_forecast_vic2026.json"
LIVE_DIR = SITE / "live"

PARTY_CODES = ["LP", "NP", "ALP", "GRN", "ON", "IND*", "OTH"]
ALIASES = {"LIB": "LP", "NAT": "NP", "LAB": "ALP", "ONP": "ON", "IND": "IND*"}
LIVE_TITLE = "Live: 2026 Victorian election results"
COVERAGE_START = "2026-11-28T18:00:00+11:00"


def norm_party(s):
    """Canonical party code or None."""
    if not s:
        return None
    u = s.strip().upper()
    u = ALIASES.get(u, u)
    return u if u in PARTY_CODES else None


def load(path):
    return json.loads(path.read_text())


def save(path, doc):
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")


def find_district(query, districts):
    """Exact case-insensitive match on district name or slug -> canonical name, else error."""
    q = query.strip().lower()
    for name, d in districts.items():
        if q in (name.lower(), d["slug"]):
            return name
    close = difflib.get_close_matches(query, list(districts), n=3, cutoff=0.5)
    hint = f" Did you mean: {', '.join(close)}?" if close else ""
    raise SystemExit(f"Unknown district {query!r}.{hint}")


def effective_calls(entries):
    """Latest entry with district+call per district wins -> {district: entry}."""
    calls = {}
    for e in entries:
        if e.get("district") and e.get("call"):
            calls[e["district"]] = e
        for c in e.get("calls", []):
            calls[c["district"]] = {**e, "district": c["district"], "call": c["call"]}
    return calls


def scoreboard(live, forecast):
    """Rows for the scoreboard plus the favourite-correct tally."""
    calls = effective_calls(live.get("entries", []))
    by_party = Counter(e["call"] for e in calls.values())
    coal = by_party.get("LP", 0) + by_party.get("NP", 0)
    rows = [
        ("Coalition", coal, forecast["blocs"].get("COAL", {}).get("seats_mean"),
         f"Lib {by_party.get('LP', 0)} &middot; Nat {by_party.get('NP', 0)}"),
        ("Labor", by_party.get("ALP", 0), forecast["blocs"].get("ALP", {}).get("seats_mean"), None),
        ("One Nation", by_party.get("ON", 0), forecast["blocs"].get("ON", {}).get("seats_mean"), None),
        ("Greens", by_party.get("GRN", 0), forecast["blocs"].get("GRN", {}).get("seats_mean"), None),
        ("Independents", by_party.get("IND*", 0), forecast["blocs"].get("IND*", {}).get("seats_mean"), None),
    ]
    if by_party.get("OTH"):
        rows.append(("Others", by_party["OTH"], None, None))
    correct = sum(1 for d, e in calls.items()
                  if forecast["districts"].get(d, {}).get("fav_party") == e["call"])
    return {"rows": rows, "called": len(calls), "correct": correct}


def fmt_live_time(iso):
    """'2026-11-28T21:42:00+11:00' -> '9:42pm'."""
    t = datetime.fromisoformat(iso)
    return t.strftime("%-I:%M%p").lower()


def fmt_frozen(iso):
    return datetime.fromisoformat(iso).strftime("%-d %B %Y")


def now_aedt():
    return datetime.now(ZoneInfo("Australia/Melbourne")).replace(microsecond=0).isoformat()


def regen():
    ok = build_site.write_live(LIVE, FORECAST, LIVE_DIR)
    if not ok:
        raise SystemExit("write_live skipped: live data files missing (run init first)")
    build_site.write_sitemap(build_site.load_posts())


def git_push(message):
    """Stage only live files (and sitemap if it changed), commit TZ=UTC, push via gh credentials."""
    rel = lambda p: str(p.relative_to(ROOT))
    paths = [rel(LIVE), rel(LIVE_DIR / "index.html")]
    if (SITE / "sitemap.xml").exists():
        paths.append(rel(SITE / "sitemap.xml"))
    env = {**os.environ, "TZ": "UTC"}
    subprocess.run(["git", "add", *paths], cwd=ROOT, check=True, env=env)
    subprocess.run(["git", "commit", "-m", message], cwd=ROOT, check=True, env=env)
    subprocess.run(["git", "-c", "http.postBuffer=524288000", "-c", "credential.helper=",
                    "-c", "credential.helper=!gh auth git-credential",
                    "push", "origin", "main"], cwd=ROOT, check=True, env=env)


def maybe_push(args, text):
    if getattr(args, "push", False):
        git_push(f"live: {text[:50]}")


def cmd_init(args):
    if FORECAST.exists() and not args.force:
        raise SystemExit(f"{FORECAST} exists; use --force to re-freeze")
    doc = load(MODEL_JSON)
    meta, seats = doc["meta"], {s["party"]: s["seats_mean"] for s in doc["seats"]}
    frozen = {
        "frozen_at": meta["timestamp"],
        "run_id": meta["run_id"],
        "git_commit": meta["git_commit"],
        "blocs": {b["party"]: {"seats_mean": b["seats_mean"], "p_majority": b["p_majority"]}
                  for b in doc["blocs"]},
        "seats": seats,
        "districts": {},
    }
    for name, d in doc["districts"].items():
        fav = max(d["candidates"], key=lambda c: c["p_win"])
        frozen["districts"][name] = {
            "slug": build_site.slug(name), "fav_party": fav["party"],
            "fav_name": build_site.disp_names(fav["id"]), "p_win": fav["p_win"],
        }
    save(FORECAST, frozen)
    if not LIVE.exists():
        save(LIVE, {"title": LIVE_TITLE, "coverage_start": COVERAGE_START, "entries": []})
    regen()
    print(f"Froze {meta['run_id']} ({meta['timestamp'][:10]}); live file: "
          f"{len(load(LIVE)['entries'])} entries")


def next_id(entries):
    return max((int(e["id"]) for e in entries), default=0) + 1


def add_entry(live, text, district=None, call=None, time=None):
    e = {"id": str(next_id(live["entries"])),
         "time": time or now_aedt(),
         "text": text}
    if district:
        e["district"] = district
    if call:
        e["call"] = call
    live["entries"].append(e)
    return e


def cmd_post(args):
    live, forecast = load(LIVE), load(FORECAST)
    call = norm_party(args.call) if args.call else None
    if args.call and not call:
        raise SystemExit(f"Unknown party {args.call!r}; codes: {', '.join(PARTY_CODES)}")
    district = find_district(args.district, forecast["districts"]) if args.district else None
    if call and not district:
        raise SystemExit("A call requires --district")
    add_entry(live, args.text, district, call)
    save(LIVE, live)
    regen()
    maybe_push(args, args.text)
    print("posted")


def cmd_call(args):
    live, forecast = load(LIVE), load(FORECAST)
    district = find_district(args.district, forecast["districts"])
    call = norm_party(args.party)
    if not call:
        raise SystemExit(f"Unknown party {args.party!r}; codes: {', '.join(PARTY_CODES)}")
    text = f"{district} called for {build_site.pname(call)}."
    if args.note:
        text += f" {args.note}"
    add_entry(live, text, district, call)
    save(LIVE, live)
    regen()
    maybe_push(args, text)
    print(text)


def cmd_list(_args):
    for e in load(LIVE)["entries"]:
        print(f"{e['id']:>3} {e['time'][:16]} {(e.get('district') or '-'):20} "
              f"{(e.get('call') or '-'):4} {e['text'][:60]}")


def cmd_edit(args):
    live = load(LIVE)
    e = next((x for x in live["entries"] if x["id"] == args.id), None)
    if not e:
        raise SystemExit(f"No entry {args.id}")
    e["text"] = args.text
    save(LIVE, live)
    regen()
    maybe_push(args, args.text)
    print("edited")


def cmd_delete(args):
    live = load(LIVE)
    n = len(live["entries"])
    live["entries"] = [e for e in live["entries"] if e["id"] != args.id]
    if len(live["entries"]) == n:
        raise SystemExit(f"No entry {args.id}")
    save(LIVE, live)
    regen()
    maybe_push(args, f"delete {args.id}")
    print("deleted")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init"); s.add_argument("--force", action="store_true"); s.set_defaults(f=cmd_init)
    s = sub.add_parser("post"); s.add_argument("text")
    s.add_argument("--district"); s.add_argument("--call"); s.add_argument("--push", action="store_true")
    s.set_defaults(f=cmd_post)
    s = sub.add_parser("call"); s.add_argument("district"); s.add_argument("party")
    s.add_argument("--note"); s.add_argument("--push", action="store_true"); s.set_defaults(f=cmd_call)
    s = sub.add_parser("list"); s.set_defaults(f=cmd_list)
    s = sub.add_parser("edit"); s.add_argument("id"); s.add_argument("text")
    s.add_argument("--push", action="store_true"); s.set_defaults(f=cmd_edit)
    s = sub.add_parser("delete"); s.add_argument("id"); s.add_argument("--push", action="store_true")
    s.set_defaults(f=cmd_delete)
    args = p.parse_args()
    args.f(args)


if __name__ == "__main__":
    main()
