"""Compare the November 2026 Kew cards with rankings of Model 2 transfer strengths."""
import json
import random
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "predictions/modelling/model2")]
import model2

# Each list omits the source candidate and everyone outside the five main contenders.
# None is an open card, not an instruction to distribute preferences uniformly.
CARDS = {
    "LP": ("ON", "IND*", "ALP", "GRN"),
    "ALP": ("IND*", "GRN", "LP", "ON"),
    "GRN": ("IND*", "ALP", "LP", "ON"),
    "ON": ("LP", "ALP", "IND*", "GRN"),
    "IND*": None,
}


def main():
    tables = json.loads((ROOT / "data/2022/distributions/full_2cp_2022.json").read_text())
    weights = model2.fit_flows(model2.flow_observations(tables))
    meta = json.loads((ROOT / "predictions/modelling/model2/output/VIC2026 snapshots/2026-11-16/run_metadata.json").read_text())
    rng = random.Random(meta["seed"])
    orders = {src: Counter() for src in CARDS}
    for _ in range(meta["runs"]):
        draw = {k: rng.triangular(lo, hi, mode) for k, (lo, mode, hi) in meta["on_priors"].items()}
        strength = model2.strength_fn(weights, draw, *(model2.LogNoise(rng, meta["noise"][key])
                                                       for key in ("flow_state", "flow_seat")))
        for src in CARDS:
            recipients = [dst for dst in CARDS if dst != src]
            order = sorted(recipients, key=lambda dst: strength(src, dst), reverse=True)
            orders[src][tuple(order)] += 1
    for src, card in CARDS.items():
        order, freq = orders[src].most_common(1)[0]
        pairs = sum(order.index(a) < order.index(b) for a, b in combinations(card, 2)) if card else None
        print(src, " > ".join(order), f"({freq}/{meta['runs']} draws); agreeing pairs:", pairs)


if __name__ == "__main__":
    main()
