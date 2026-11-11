# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Guaranteed Mathieu characteristic values against scipy.special.mathieu_a / mathieu_b (PREREG D1.5 of 0.3.0).

Two steps, so that the comparison can run in a venv that has only scipy (e.g. a scipy nightly):

    python bench/mathieu_vs_scipy.py intervals OUT.json        # needs qraft_ra: r = 0…12, q = −400…400 step 0.5
    python bench/mathieu_vs_scipy.py intervals OUT.json 0.05   # the fine grid of qiskit-metal #1252: step 0.05, 400 025 values
    python bench/mathieu_vs_scipy.py compare OUT.json          # needs scipy only: counts the values of this scipy
                                                               # outside the interval widened by 1e-9·max(1, |a|)

"agree" = scipy inside the widened interval; "wrong" otherwise. For every wrong value the order r' whose interval
centre is within 1e-6 of the scipy value is reported (the known defect: the value of another order), or "none".
"""
import json
import statistics
import sys
import time

R_MAX, Q_MAX, STEP = 12, 400.0, 0.5
TOL_REL = 1e-9


def intervals(out, step=STEP):
    from qraft_ra import mathieu as M
    rows, times = [], []
    nq = int(round(2 * Q_MAX / step)) + 1
    for i in range(nq):
        q = -Q_MAX + i * step
        for r in range(R_MAX + 1):
            for kind in ("a", "b"):
                if kind == "b" and r == 0:
                    continue
                t = time.perf_counter()
                v = M.mathieu_value(kind, r, q)
                times.append(time.perf_counter() - t)
                rows.append([kind, r, q, str(v.low), str(v.high), v.state, v.K])
    doc = {"rows": rows, "values": len(rows), "median_ms": 1e3 * statistics.median(times),
           "mean_ms": 1e3 * statistics.mean(times), "max_ms": 1e3 * max(times),
           "not_guaranteed": sum(1 for x in rows if x[5] != "GUARANTEED"), "grid": [R_MAX, Q_MAX, step]}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    print(json.dumps({k: v for k, v in doc.items() if k != "rows"}))


def compare(path):
    from fractions import Fraction
    import scipy
    from scipy.special import mathieu_a, mathieu_b
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    centres = {}
    for kind, r, q, lo, hi, state, K in doc["rows"]:
        centres.setdefault((kind, q), {})[r] = (Fraction(lo) + Fraction(hi)) / 2
    wrong, agree, times = [], 0, []
    for kind, r, q, lo, hi, state, K in doc["rows"]:
        t = time.perf_counter()
        s = float(mathieu_a(r, q) if kind == "a" else mathieu_b(r, q))
        times.append(time.perf_counter() - t)
        lo, hi = Fraction(lo), Fraction(hi)
        tol = Fraction(TOL_REL) * max(1, abs(lo))
        if lo - tol <= Fraction(s) <= hi + tol:
            agree += 1
        else:
            other = [rp for rp, c in centres[(kind, q)].items() if abs(float(c) - s) <= 1e-6]
            wrong.append([kind, r, q, s, str(lo), str(hi), other[0] if other else None])
    with_other = sum(1 for w in wrong if w[6] is not None)
    res = {"scipy": scipy.__version__, "python": sys.version.split()[0], "values": len(doc["rows"]), "agree": agree,
           "wrong": len(wrong), "wrong_matching_another_order": with_other,
           "scipy_median_us": 1e6 * statistics.median(times), "wrong_list": wrong[:2000]}
    print(json.dumps({k: v for k, v in res.items() if k != "wrong_list"}))
    with open(path.replace(".json", f"_scipy_{scipy.__version__}.json"), "w", encoding="utf-8") as f:
        json.dump(res, f)


if __name__ == "__main__":
    if sys.argv[1:2] == ["intervals"] and len(sys.argv) in (3, 4):
        intervals(sys.argv[2], float(sys.argv[3]) if len(sys.argv) == 4 else STEP)
    elif sys.argv[1:2] == ["compare"] and len(sys.argv) == 3:
        compare(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(2)
