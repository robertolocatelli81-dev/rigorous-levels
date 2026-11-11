# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Six real transmons of arXiv:2407.17407 (their E_J, E_C and measured transitions, read on 2026-11-10; for Q5 also
their fits with up to cos 8φ): guaranteed intervals of every measured level (README "Measurements": 26 of 26
GUARANTEED with up to cos 8φ, width ≤ 1.1e-13 GHz), and the smallest fixed charge cut ncut whose dense levels stay
within 1 kHz of the guaranteed intervals (the authors' solvers use a fixed cut).

    python bench/real_transmons.py OUT.json        # ~1 min
"""
import json
import sys
import time

import numpy as np

from qraft_ra import Rotor, guaranteed_levels

DEVICES = {
    "Q0": (16.685, 0.190, 4), "Q1": (21.194, 0.152, 5), "Q2": (21.960, 0.152, 5), "Q3": (25.636, 0.126, 7),
    "Q4": (28.702, 0.108, 10), "Q5": (32.191, 0.099, 11),
}
HARMONICS_Q5 = {
    2: (0.107, [30.7166, -0.2025]),
    4: (0.109, [30.3566, -0.3303, 0.0176, -0.0014]),
    8: (0.109, [30.4054, -0.3409, 0.0251, -0.0038, 0.0004, -0.0004, 0.0005, -0.0002]),
}
NCUTS = (3, 5, 8, 10, 12, 15, 20, 30)


def dense(ec, ejs, ncut, k):
    n = np.arange(-ncut, ncut + 1)
    H = np.diag(4 * ec * n.astype(float) ** 2)
    for m, ej in enumerate(ejs, start=1):
        if m < len(n):
            H -= ej / 2 * (np.eye(len(n), k=m) + np.eye(len(n), k=-m))
    return np.linalg.eigvalsh(H)[:k]


def main(out):
    rows, guaranteed, total = [], 0, 0
    t0 = time.time()
    cases = [(name, ec, [ej], k + 1) for name, (ej, ec, k) in DEVICES.items()]
    cases += [(f"Q5 cos{m}phi", ec, ejs, 12) for m, (ec, ejs) in HARMONICS_Q5.items()]
    for name, ec, ejs, k in cases:
        r = Rotor(ec, {m: -ej for m, ej in enumerate(ejs, start=1) if ej != 0.0})
        iv = guaranteed_levels(r, k, 1e-12, deadline=600)
        total += k
        guaranteed += k if iv.state == "GUARANTEED" else 0
        need = None
        for ncut in NCUTS:
            lev = dense(ec, ejs, ncut, k)
            if len(lev) < k:                       # fewer charge states than levels asked: not a candidate
                continue
            d = float(max(max(float(iv.low[j]) - lev[j], lev[j] - float(iv.high[j]), 0.0) for j in range(k)))
            if d <= 1e-6 and need is None:
                need = ncut
        rows.append({"device": name, "E_C": ec, "E_J": ejs, "levels": k, "state": iv.state, "max_width_GHz": iv.max_width,
                     "N": iv.N, "smallest_ncut_within_1kHz": need, "seconds": iv.seconds})
        print(json.dumps(rows[-1]), flush=True)
    doc = {"levels_total": total, "levels_guaranteed": guaranteed, "max_width_GHz": max(r["max_width_GHz"] for r in rows),
           "ncut_within_1kHz": {r["device"]: r["smallest_ncut_within_1kHz"] for r in rows}, "seconds": round(time.time() - t0, 1), "rows": rows}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    print(json.dumps({k: v for k, v in doc.items() if k != "rows"}))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1])
