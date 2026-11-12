# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Parameters as intervals against sampled points (README "Measurements"): 200 transmons of the device regime
(same generator and seed as bench/readme_numbers.py), E_J given as ±1 % and E_C as ±1 %, 6 levels.

    python bench/parameter_balls.py OUT.json

For each case: the box interval (two guaranteed computations); S random inner points (E_C, E_J uniform in the box)
with their point intervals, which must lie INSIDE the box interval (count of violations: expected 0 by the proof);
one point OUTSIDE the box (E_J at +3 %) whose point interval must leave the box interval in at least one level
(negative control: counted, not required of every case); the ratio between the box width and the spread actually
observed among the inner points (how loose the Lipschitz bound is)."""
import json
import random
import statistics
import sys
import time

import numpy as np

from rigorous_levels import Rotor, RotorBall, guaranteed_levels, guaranteed_levels_over_box

K, S, REL = 6, 5, 0.01


def device_regime():
    rng = np.random.default_rng(20261108)
    out = []
    for _ in range(200):
        ec = float(rng.uniform(0.05, 1.0))
        rap = float(10 ** rng.uniform(0, 3))
        ng = float(rng.uniform(0, 1))
        out.append((ec, ec * rap, ng))
    return out


def main(out):
    rnd = random.Random(20261111)
    rows, inner_out, neg_out, ratios, times = [], 0, 0, [], []
    for i, (ec, ej, ng) in enumerate(device_regime()):
        box = RotorBall.transmon((ec * (1 - REL), ec * (1 + REL)), (ej * (1 - REL), ej * (1 + REL)), n_g=ng)
        t = time.perf_counter()
        iv = guaranteed_levels_over_box(box, K, 1e-10, deadline=600)
        times.append(time.perf_counter() - t)
        lows, highs = [[] for _ in range(K)], [[] for _ in range(K)]
        viol = 0
        for _ in range(S):
            p = guaranteed_levels(Rotor.transmon(rnd.uniform(ec * (1 - REL), ec * (1 + REL)),
                                                 rnd.uniform(ej * (1 - REL), ej * (1 + REL)), n_g=ng), K, 1e-10, deadline=600)
            for j in range(K):
                lows[j].append(float(p.low[j]))
                highs[j].append(float(p.high[j]))
                if not (iv.low[j] <= p.low[j] and p.high[j] <= iv.high[j]):
                    viol += 1
        inner_out += viol
        q = guaranteed_levels(Rotor.transmon(ec, ej * 1.03, n_g=ng), K, 1e-10, deadline=600)
        neg = any(q.high[j] < iv.low[j] or q.low[j] > iv.high[j] for j in range(K))
        neg_out += neg
        spread = max(max(highs[j]) - min(lows[j]) for j in range(K))
        ratio = iv.max_width / spread if spread > 0 else float("inf")
        ratios.append(ratio)
        rows.append({"i": i, "E_C": ec, "E_J": ej, "n_g": ng, "state": iv.state, "box_width": iv.max_width, "rho": iv.alpha,
                     "inner_violations": viol, "outside_point_detected": neg, "observed_spread": spread, "width_over_spread": ratio})
        if i % 20 == 0:
            print(i, iv.state, f"width {iv.max_width:.3e} spread {spread:.3e} ratio {ratio:.1f} neg {neg}", flush=True)
    doc = {"cases": len(rows), "inner_points_per_case": S, "inner_violations": inner_out,
           "outside_point_detected": neg_out, "all_guaranteed": all(r["state"] == "GUARANTEED" for r in rows),
           "width_over_spread_median": statistics.median(ratios), "width_over_spread_max": max(ratios),
           "seconds_per_box_median": statistics.median(times), "rows": rows}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    print(json.dumps({k: v for k, v in doc.items() if k != "rows"}))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1])
