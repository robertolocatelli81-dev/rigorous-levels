# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""RbCs, the 16 hyperfine transitions N = 0 → 1 of Gregory et al., PRA 94, 041403(R) (2016), Table I, with THEIR
constants, as guaranteed intervals (README "Measurements"). Claim: the centre of every interval is within 100 Hz of
their model value f_the; the intervals are ≤ 10 Hz wide.

    python bench/gregory2016.py OUT.json        # ~1 min (L = 4 forced: enough for N = 0, 1 at the 1e-11 width)

Table I as read on 2026-11-10 (ar5iv): (final M_F, B in gauss, f_the kHz, f_exp kHz, sigma kHz). The sign of the
tensor spin-spin term is the paper's (durham-qlm/diatomic-py #15)."""
import json
import sys
import time

from qraft_ra import SigmaMolecule, guaranteed_molecule_levels, zeeman_hz
from qraft_ra.hyperfine_molecule import transition

TAB = [(5, 181.507, 980231.07, 980233.0, 2.0), (5, 204.436, 980235.14, 980237.0, 1.0),
       (4, 181.484, 980277.96, 980278.9, 0.2), (4, 204.397, 980292.08, 980291.0, 0.2),
       (4, 181.487, 980320.47, 980320.4, 0.2), (4, 204.397, 980331.83, 980331.8, 0.3),
       (6, 181.541, 980384.98, 980384.97, 0.06), (6, 204.38, 980384.87, 980384.90, 0.05),
       (5, 181.507, 980443.97, 980444.8, 0.7), (5, 204.436, 980458.35, 980457.2, 0.8),
       (5, 181.507, 980546.75, 980546.9, 0.7), (5, 204.436, 980572.86, 980573.5, 0.6),
       (4, 181.487, 980661.35, 980661.15, 0.06), (4, 204.397, 980694.22, 980694.35, 0.05),
       (4, 181.487, 980758.64, 980758.6, 0.1), (4, 204.397, 980810.62, 980810.8, 0.3)]
B_HZ, D_HZ = 490173.994e3, 213.0
EQQ_RB, EQQ_CS, C_RB, C_CS, C3, C4 = -809.29e3, 59.98e3, 29.4, 196.8, 192.4, 19.019e3
G_R, G_RB, G_CS = 0.0062, 1.8295, 0.7331
K = {4: 8, 5: 4, 6: 1}             # levels per sector: N = 0 (2, 1, 0 states) + N = 1 (6, 3, 1)
FIRST_N1 = {4: 2, 5: 1, 6: 0}
L = 4


def molecule(B_G):
    return SigmaMolecule(3, 7, B=B_HZ, D=D_HZ, c1=C_RB, c2=C_CS, c3=C3, c4=C4, eQq1=EQQ_RB, eQq2=EQQ_CS,
                         z_N=zeeman_hz(G_R, B_G), z1=zeeman_hz(G_RB, B_G), z2=zeeman_hz(G_CS, B_G))


def main(out):
    t0 = time.time()
    cache = {}

    def levels(B_G, MF):
        if (B_G, MF) not in cache:
            cache[(B_G, MF)] = guaranteed_molecule_levels(molecule(B_G), 2 * MF, K[MF], 1e-11, L_initial=L, L_limit=L, deadline=900)
        return cache[(B_G, MF)]
    rows = []
    for MF, B_G, f_the, f_exp, sig in TAB:
        iv0 = levels(B_G, 5)                        # ground state N = 0, M_F = +5
        iv = levels(B_G, MF)
        cands = []
        for j in range(FIRST_N1[MF], K[MF]):
            lo, hi = transition(iv0, 0, iv, j)
            cands.append((j, float(lo), float(hi)))
        j, lo, hi = min(cands, key=lambda c: abs((c[1] + c[2]) / 2 - f_the * 1e3))
        centre = (lo + hi) / 2
        rows.append({"MF": MF, "B_G": B_G, "f_the_kHz": f_the, "f_exp_kHz": f_exp, "sigma_kHz": sig, "level": j,
                     "centre_kHz": centre / 1e3, "width_Hz": hi - lo, "centre_minus_the_Hz": centre - f_the * 1e3,
                     "exp_minus_centre_over_sigma": (f_exp * 1e3 - centre) / (sig * 1e3), "state": iv.state})
    within_100 = sum(abs(r["centre_minus_the_Hz"]) <= 100 for r in rows)
    narrow = sum(r["width_Hz"] <= 10 for r in rows)
    doc = {"lines": 16, "centre_within_100_Hz_of_f_the": within_100, "width_le_10_Hz": narrow,
           "max_abs_centre_minus_the_Hz": max(abs(r["centre_minus_the_Hz"]) for r in rows),
           "max_width_Hz": max(r["width_Hz"] for r in rows), "seconds": round(time.time() - t0, 1), "rows": rows}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    print(json.dumps({k: v for k, v in doc.items() if k != "rows"}))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1])
