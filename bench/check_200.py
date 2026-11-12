# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""`rigorous_levels.check(scqubits_obj)` at ncut = 30 on the two 200-transmon sets of bench/readme_numbers.py (README
"Measurements"): the device regime (E_C ~ U(0.05, 1), E_J/E_C = 10^U(0, 3), seed 20261108) and the wide range
(E_C = 1, E_J/E_C = 10^U(−1, 6), seed 7, where scqubits at ncut 30 is wrong in 65 cases): the guaranteed verdict
against the adapter's doubling rule and against the truth.

    python bench/check_200.py OUT.json        # needs rigorous_levels[scqubits]

For every case: (a) `check(Transmon(ncut=30), tolerance=1e-6)` → OUTSIDE/INSIDE (1e-6 GHz = the absolute part of the
rule "scq-threshold/1.0", so that the two verdicts are comparable); (b) the adapter's doubling verdict at ncut 30
(NOT_CONVERGED / OK); (c) the TRUE distance of the ncut-30 levels from the guaranteed intervals, which decides who is
right. Counts: flagged by both, by the check only (true error > 1e-6 the rule missed), by the adapter only (false
alarm of the rule), by neither; plus the same with the default tolerance (the float floor 32·eps·‖H‖)."""
import json
import statistics
import sys
import time

import numpy as np
import scqubits as sq

from rigorous_levels import check, scqubits_spectrum, Rotor

sq.settings.PROGRESSBAR_DISABLED = True


def device_regime():
    rng = np.random.default_rng(20261108)
    out = []
    for _ in range(200):
        ec = float(rng.uniform(0.05, 1.0))
        rap = float(10 ** rng.uniform(0, 3))
        ng = float(rng.uniform(0, 1))
        out.append((ec, ec * rap, ng))
    return out


def wide_range():
    rng = np.random.default_rng(7)
    for _ in range(200):
        rng.uniform(-1, 6)
        rng.integers(1, 5)
    return [(1.0, float(10 ** rng.uniform(-1, 6)), float(rng.uniform(0, 1))) for _ in range(200)]


def main(out):
    docs = {}
    for label, cases in (("device_regime", device_regime()), ("wide_range", wide_range())):
        docs[label] = one_set(label, cases)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"scqubits": sq.__version__, "sets": docs}, f, indent=1)
    for label, d in docs.items():
        print(label, json.dumps({k: v for k, v in d.items() if k != "rows"}))


def one_set(label, cases):
    rows, both, check_only, adapter_only, neither, floor_outside, times = [], 0, 0, 0, 0, 0, []
    for i, (ec, ej, ng) in enumerate(cases):
        q = sq.Transmon(EJ=ej, EC=ec, ng=ng, ncut=30)
        t = time.perf_counter()
        c = check(q, 6, 1e-10, tolerance=1e-6, deadline=600)
        times.append(time.perf_counter() - t)
        c_floor = check(q, 6, 1e-10, deadline=600)
        a = scqubits_spectrum(Rotor.transmon(ec, ej, n_g=ng), 6, 30, check="doubling")
        dist = max((float(d.split()[0]) if s != "INSIDE" else 0.0) for s, d in c_floor.verdict.per_level)
        flagged_check = c.verdict.overall == "OUTSIDE"
        flagged_adapter = a.state == "NOT_CONVERGED"
        both += flagged_check and flagged_adapter
        check_only += flagged_check and not flagged_adapter
        adapter_only += flagged_adapter and not flagged_check
        neither += not flagged_check and not flagged_adapter
        floor_outside += c_floor.verdict.overall == "OUTSIDE"
        rows.append({"i": i, "E_C": ec, "E_J": ej, "n_g": ng, "EJ_over_EC": ej / ec, "check_1e-6": c.verdict.overall,
                     "check_floor": c_floor.verdict.overall, "adapter": a.state, "true_distance_GHz": dist,
                     "adapter_error_estimate": a.error, "adapter_threshold": a.threshold})
        if i % 40 == 0:
            print(label, i, "both", both, "check_only", check_only, "adapter_only", adapter_only, "neither", neither, flush=True)
    return {"cases": 200, "ncut": 30, "flagged_by_both": both, "flagged_by_check_only": check_only,
           "flagged_by_adapter_only": adapter_only, "flagged_by_neither": neither,
           "outside_with_float_floor_tolerance": floor_outside,
           "max_true_distance_among_unflagged_GHz": max((r["true_distance_GHz"] for r in rows if r["check_1e-6"] != "OUTSIDE"), default=0.0),
           "seconds_median": statistics.median(times), "rows": rows}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1])
