# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Recompute the numbers of the README "Measurements" section. Needs the extras: pip install ".[scqubits,test]".

    python bench/readme_numbers.py            # 40 interval cases
    python bench/readme_numbers.py --full     # all 400 interval cases (about 20 minutes on the author's machine,
                                              # mostly the 50-digit references)
Timings depend on the number of BLAS threads: set OMP_NUM_THREADS=1 to compare with the README.

Cases, generated with fixed seeds (the same generators as the author's benchmarks of 2026-11-08):
  device regime: 200 transmons, E_C ~ U(0.05, 1) GHz, E_J/E_C = 10^U(0, 3), n_g ~ U(0, 1)   (seed 20261108)
  wide range:    200 transmons, E_C = 1, E_J/E_C = 10^U(−1, 6), n_g ~ U(0, 1)                (seed 7)
Interval cases: the wide-range set as −E_J cos φ (bank A) and as −E_J cos 2φ (bank B), 6 levels each.
Reference for the intervals: mpmath at 50 digits on a larger truncated basis (implicit QL, tridiagonal parity sectors).
"""
import json
import math
import statistics
import sys
import time
from fractions import Fraction

import mpmath
import numpy as np
import scqubits as sq
from mpmath.matrices.eigen_symmetric import tridiag_eigen

from qraft_ra import guaranteed_intervals as IG
from qraft_ra import scqubits_adapter as SA
from qraft_ra.rotor_spectrum import OK, Rotor, spectrum

sq.settings.PROGRESSBAR_DISABLED = True
K = 6


def ms(f):
    t = time.perf_counter()
    r = f()
    return r, (time.perf_counter() - t) * 1e3


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
    return [(float(10 ** rng.uniform(-1, 6)), float(rng.uniform(0, 1))) for _ in range(200)]


def wrong(x, E):
    """The definition of "wrong" of the benchmark: error > 1e-6 of max(1, largest transition)."""
    return float(np.max(np.abs(np.asarray(x) - E))) / max(1.0, float(np.max(np.abs(np.diff(E))))) > 1e-6


def reference(ej, ng, m):
    mpmath.mp.dps = 50
    nc = math.ceil(abs(ng)) + 40 + math.ceil(8 * abs(ej) ** 0.25)
    tutti = []
    for r0 in range(m):
        ns = [n for n in range(-nc, nc + 1) if (n + nc) % m == r0]
        d = [4 * (mpmath.mpf(n) - mpmath.mpf(ng)) ** 2 for n in ns]
        e = [-mpmath.mpf(ej) / 2] * (len(d) - 1) + [mpmath.mpf(0)]
        tridiag_eigen(mpmath.mp, d, e)
        tutti += list(d)
    tutti.sort()
    out = []
    for x in tutti[:K]:
        s, man, e, _ = x._mpf_
        v = Fraction(man * 2 ** e) if e >= 0 else Fraction(man, 2 ** -e)
        out.append(-v if s else v)
    return out


def main(full):
    res = {"versions": {"python": sys.version.split()[0], "numpy": np.__version__, "scqubits": sq.__version__,
                        "mpmath": mpmath.__version__}}
    # 1. device regime: our solver against scqubits (adapter, auto), and timings
    t = {"scqubits_ncut30": [], "adapter_auto": [], "adapter_doubling": [], "ours": []}
    diff_tr = 0.0
    for ec, ej, ng in device_regime():
        r = Rotor.transmon(ec, ej, ng)
        _, t0 = ms(lambda: sq.Transmon(EJ=ej, EC=ec, ng=ng, ncut=30, truncated_dim=K).eigenvals(evals_count=K))
        a, t1 = ms(lambda: SA.scqubits_spectrum(r, K, check="auto", tol=1e-10))
        _, t2 = ms(lambda: SA.scqubits_spectrum(r, K, 30, check="doubling"))
        b, t3 = ms(lambda: spectrum(r, K, 1e-11))
        for k, v in zip(t, (t0, t1, t2, t3)):
            t[k].append(v)
        assert a.state in (OK, SA.OK_FLOAT_FLOOR) and b.state == OK    # OK_FLOAT_FLOOR: state added in 0.3.0
        ea, eb = np.array(a.energies), np.array(b.energies)
        diff_tr = max(diff_tr, float(np.max(np.abs((ea - ea[0]) - (eb - eb[0])))))
    res["device_regime"] = {"cases": 200, "max_diff_transitions_GHz": diff_tr,
                            "mean_ms": {k: round(statistics.fmean(v), 3) for k, v in t.items()}}
    # 2. wide range: scqubits at ncut = 30, alone and with the adapter
    rows = []
    for ej, ng in wide_range():
        r = Rotor.transmon(1.0, ej, ng)
        ref = np.asarray(sq.Transmon(EJ=ej, EC=1.0, ng=ng, ncut=300, truncated_dim=K).eigenvals(evals_count=K))
        bare = np.asarray(sq.Transmon(EJ=ej, EC=1.0, ng=ng, ncut=30, truncated_dim=K).eigenvals(evals_count=K))
        dbl = SA.scqubits_spectrum(r, K, 30, check="doubling")
        aut = SA.scqubits_spectrum(r, K, 30, check="auto")
        rows.append({"ej": ej, "wrong": wrong(bare, ref), "flag": dbl.state not in (OK, SA.OK_FLOAT_FLOOR), "auto_wrong": wrong(aut.energies, ref)})
    w = [x for x in rows if x["wrong"]]
    res["wide_range_ncut30"] = {"cases": 200, "wrong_silently": len(w),
                                "smallest_EJ_EC_wrong": min((x["ej"] for x in w), default=None),
                                "flagged_of_wrong": sum(x["flag"] for x in w),
                                "false_alarms_of_right": sum(x["flag"] for x in rows if not x["wrong"]),
                                "right": 200 - len(w), "auto_wrong": sum(x["auto_wrong"] for x in rows)}
    # 3. guaranteed intervals against mpmath at 50 digits
    casi = [("A", 1, ej, ng) for ej, ng in wide_range()] + [("B", 2, ej, ng) for ej, ng in wide_range()]
    if not full:
        casi = casi[:20] + casi[200:220]
    inside = levels = 0
    width = 0.0
    secs = []
    states = {}
    for _, m, ej, ng in casi:
        t0 = time.perf_counter()
        iv = IG.guaranteed_levels(Rotor(1.0, {m: -ej}, n_g=ng), K)
        secs.append(time.perf_counter() - t0)
        states[iv.state] = states.get(iv.state, 0) + 1
        ref = reference(ej, ng, m)
        inside += sum(iv.low[j] <= ref[j] <= iv.high[j] for j in range(K))
        levels += K
        width = max(width, iv.max_width)
    res["intervals"] = {"cases": len(casi), "levels": levels, "reference_inside": inside, "max_width_GHz": width,
                        "states": states, "seconds_mean": round(statistics.fmean(secs), 3),
                        "seconds_median": round(statistics.median(secs), 3), "seconds_max": round(max(secs), 3)}
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--full"]):
        raise SystemExit("usage: readme_numbers.py [--full]")
    main(sys.argv[1:] == ["--full"])
