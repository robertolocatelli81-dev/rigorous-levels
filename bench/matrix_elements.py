# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Guaranteed matrix elements against scqubits (README "Measurements"): 200 transmons of the device regime (same
generator and seed as bench/readme_numbers.py), ⟨0|n|1⟩, ⟨1|n|2⟩, ⟨0|n|2⟩, ⟨0|cos φ|1⟩, ⟨1|cos φ|2⟩.

    python bench/matrix_elements.py OUT.json        # needs qraft_ra[scqubits]

For each element: the guaranteed enclosure and its width; whether |scqubits (ncut 40)| falls inside it (sign
convention of the eigenvectors is arbitrary on both sides: the absolute value is compared); the sin-θ bounds."""
import json
import statistics
import sys
import time

import numpy as np
import scqubits as sq

from qraft_ra import Rotor
from qraft_ra.matrix_elements import OutOfDomain, guaranteed_matrix_element

sq.settings.PROGRESSBAR_DISABLED = True
ELEMENTS = ((0, 1, "n"), (1, 2, "n"), (0, 2, "n"), (0, 1, "cos"), (1, 2, "cos"))


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
    rows, inside, outside, no_bound, widths, times = [], 0, 0, 0, [], []
    for idx, (ec, ej, ng) in enumerate(device_regime()):
        r = Rotor.transmon(ec, ej, n_g=ng)
        t = sq.Transmon(EJ=ej, EC=ec, ng=ng, ncut=40)
        tables = {"n": t.matrixelement_table("n_operator", evals_count=4),
                  "cos": t.matrixelement_table("cos_phi_operator", evals_count=4)}
        for i, j, op in ELEMENTS:
            t0 = time.perf_counter()
            try:
                e = guaranteed_matrix_element(r, i, j, op, deadline=600)
            except OutOfDomain as err:
                no_bound += 1
                rows.append({"i": idx, "E_C": ec, "E_J": ej, "n_g": ng, "element": [i, j, op], "no_bound": str(err)[:120]})
                continue
            times.append(time.perf_counter() - t0)
            ref = abs(complex(tables[op][i, j]))
            ok = e.contains(ref) or e.contains(-ref)
            inside += ok
            outside += not ok
            widths.append(e.max_width)
            rows.append({"i": idx, "E_C": ec, "E_J": ej, "n_g": ng, "element": [i, j, op], "value": e.value,
                         "width": e.max_width, "scqubits_abs": ref, "inside": ok, "sin_bounds": list(e.sin_bounds)})
        if idx % 40 == 0:
            print(idx, "inside", inside, "outside", outside, "no_bound", no_bound, flush=True)
    doc = {"cases": 200, "elements_per_case": len(ELEMENTS), "inside": inside, "outside": outside, "no_bound": no_bound,
           "width_median": statistics.median(widths), "width_max": max(widths), "seconds_median": statistics.median(times),
           "scqubits": sq.__version__, "rows": rows}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    print(json.dumps({k: v for k, v in doc.items() if k != "rows"}))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1])
