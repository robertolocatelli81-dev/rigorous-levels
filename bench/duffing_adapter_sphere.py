# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Three rows of the README "Measurements" re-measured from this tree (each one was measured in the author's
repository on 2026-11-10/11 and is re-run here):

  duffing   200 transmons of the device regime: |δ_3| of the Duffing model against the transmon, guaranteed
            (claim: |δ_3| ≥ 1 MHz in 200 of 200, median 34 MHz);
  adapter   the rule "scq-threshold/1.0" on the same 200 transmons × ncut 3…30 (doubling check): results marked OK
            whose true error (against the guaranteed intervals) exceeds their own threshold (claim: 0), and the
            same verdicts in GHz / MHz / Hz (claim: 0 differ);
  sphere    the spherical rotor: for 60 random (B, dE, M) the guaranteed intervals against numpy at a cut 40 larger
            than the one used (claim: inside in every case).

    python bench/duffing_adapter_sphere.py OUT.json        # needs qraft_ra[scqubits] for the adapter row; ~3 min
"""
import json
import statistics
import sys
import time

import numpy as np

from qraft_ra import Rotor, SphericalRotor, duffing_error, guaranteed_levels, guaranteed_sphere_levels
from qraft_ra.spherical_rotor import _c2


def device_regime():
    rng = np.random.default_rng(20261108)
    out = []
    for _ in range(200):
        ec = float(rng.uniform(0.05, 1.0))
        rap = float(10 ** rng.uniform(0, 3))
        ng = float(rng.uniform(0, 1))
        out.append((ec, ec * rap, ng))
    return out


def duffing(cases):
    d3 = []
    for ec, ej, ng in cases:
        e = duffing_error(ec, ej, ng, 4, "spectrum", width=1e-10, deadline=600)
        lo, hi = e.delta_float()[3]
        d3.append(float(min(abs(lo), abs(hi))) if lo * hi > 0 else 0.0)
    return {"cases": len(cases), "abs_delta3_ge_1MHz": sum(x >= 1e-3 for x in d3), "median_MHz": statistics.median(d3) * 1e3,
            "p90_MHz": float(np.percentile(d3, 90)) * 1e3}


def adapter(cases):
    try:
        from qraft_ra import scqubits_spectrum
        import scqubits  # noqa: F401
    except ImportError:
        return {"skipped": "scqubits absent"}
    bad_ok = runs = differ = 0
    for ec, ej, ng in cases:
        r = Rotor.transmon(ec, ej, n_g=ng)
        iv = guaranteed_levels(r, 6, 1e-10, deadline=600)
        for ncut in range(3, 31):
            runs += 1
            a = scqubits_spectrum(r, 6, ncut, check="doubling")
            true_err = float(max(max(float(iv.low[j]) - a.energies[j], a.energies[j] - float(iv.high[j]), 0.0) for j in range(6)))
            if a.state in ("OK", "OK_FLOAT_FLOOR") and true_err > a.threshold:
                bad_ok += 1
            if ncut in (3, 10, 30):                 # the same H written in MHz / Hz (the unit declares the unit of the Rotor)
                for unit, f in (("MHz", 1e3), ("Hz", 1e9)):
                    b = scqubits_spectrum(Rotor.transmon(ec * f, ej * f, n_g=ng), 6, ncut, check="doubling", unit=unit)
                    differ += int((b.state, b.threshold_origin) != (a.state, a.threshold_origin))
    return {"runs": runs, "OK_results_outside_their_threshold": bad_ok, "verdicts_differing_by_unit": differ}


def sphere():
    rng = np.random.default_rng(20261110)
    inside = total = 0
    for _ in range(60):
        B = float(10 ** rng.uniform(0, 4))
        dE = float(B * 10 ** rng.uniform(-3, 1.5))
        M = int(rng.integers(0, 4))
        iv = guaranteed_sphere_levels(SphericalRotor(B=B, dE=dE, M=M), 4, 1e-11, deadline=600)
        L = iv.N + 40
        Ns = np.arange(M, L + 1)
        c = np.sqrt([float(_c2(int(N), M)) for N in Ns[:-1]])
        T = np.diag(B * Ns * (Ns + 1.0)) - dE * (np.diag(c, 1) + np.diag(c, -1))
        ref = np.linalg.eigvalsh(T)[:4]
        for j in range(4):
            total += 1
            inside += int(float(iv.low[j]) - 1e-9 * max(1.0, abs(ref[j])) <= ref[j] <= float(iv.high[j]) + 1e-9 * max(1.0, abs(ref[j])))
    return {"cases": 60, "levels": total, "numpy_reference_inside": inside}


def main(out):
    t0 = time.time()
    cases = device_regime()
    doc = {"duffing": duffing(cases), "adapter": adapter(cases), "sphere": sphere(), "seconds": round(time.time() - t0, 1)}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    print(json.dumps(doc))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1])
