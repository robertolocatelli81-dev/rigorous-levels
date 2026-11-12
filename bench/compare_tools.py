# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Time per point: this package (guaranteed) against the float tools on the same inputs (README table
"Against the existing tools, measured"). Every cell of the "speed" column comes from here; the other columns come
from bench/readme_numbers.py (transmon), bench/mathieu_vs_scipy.py, bench/fluxonium_devices.py,
bench/parameter_balls.py and the tests named in the README.

    python bench/compare_tools.py OUT.json        # scqubits optional (its rows are skipped without it)

Timings are medians of REPEAT runs of one representative input per row, single BLAS thread; they depend on the
machine (stated in the output) and are meant for the ratio, not the absolute value."""
import json
import platform
import statistics
import sys
import time

import numpy as np

from rigorous_levels import (Fluxonium, Rotor, RotorBall, SigmaMolecule, SphericalRotor, guaranteed_fluxonium_levels,
                      guaranteed_levels, guaranteed_levels_over_box, guaranteed_molecule_levels,
                      guaranteed_sphere_levels, mathieu_a, spectrum)

REPEAT = 5


def med(fn, repeat=REPEAT):
    ts = []
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t)
    return statistics.median(ts)


def main(out):
    rows = []
    try:
        import scqubits as sq
        sq.settings.PROGRESSBAR_DISABLED = True
    except ImportError:
        sq = None
    from scipy.special import mathieu_a as sp_a

    # transmon: ours (guaranteed, 6 levels) vs our float solver vs scqubits ncut 30
    r = Rotor.transmon(0.3, 15.0, n_g=0.25)
    row = {"quantity": "transmon, 6 levels (E_C 0.3, E_J 15, n_g 0.25)",
           "guaranteed_s": med(lambda: guaranteed_levels(r, 6)), "float_spectrum_s": med(lambda: spectrum(r, 6))}
    if sq:
        row["scqubits_ncut30_s"] = med(lambda: sq.Transmon(EJ=15.0, EC=0.3, ng=0.25, ncut=30).eigenvals(evals_count=6))
    rows.append(row)
    # parameter box
    box = RotorBall.transmon((0.297, 0.303), (14.85, 15.15), n_g=0.25)
    rows.append({"quantity": "transmon with E_C, E_J ± 1 %, 6 levels", "guaranteed_box_s": med(lambda: guaranteed_levels_over_box(box, 6))})
    # Mathieu
    rows.append({"quantity": "Mathieu a_5(100)", "guaranteed_s": med(lambda: mathieu_a(5, 100.0), 50),
                 "scipy_mathieu_a_s": med(lambda: sp_a(5, 100.0), 200)})
    # fluxonium
    f = Fluxonium(E_C=0.567, E_J=2.052, E_L=0.835, flux=0.5)
    row = {"quantity": "fluxonium (Moskalenko 2022 A), 4 levels, 1e-9 GHz", "guaranteed_s": med(lambda: guaranteed_fluxonium_levels(f, 4, 1e-9), 3)}
    if sq:
        row["scqubits_cutoff110_s"] = med(lambda: sq.Fluxonium(EJ=2.052, EC=0.567, EL=0.835, flux=0.5, cutoff=110).eigenvals(evals_count=4))
    rows.append(row)
    # spherical rotor
    s = SphericalRotor(B=490.173994, dE=1.225 * 0.503412 * 1.2, M=0)
    rows.append({"quantity": "spherical rotor RbCs at 1.2 V/cm, 2 levels", "guaranteed_s": med(lambda: guaranteed_sphere_levels(s, 2)),
                 "numpy_eigvalsh_L60_s": med(lambda: np.linalg.eigvalsh(np.diag(490.173994 * np.arange(61) * np.arange(1, 62).astype(float))))})
    # molecule
    m = SigmaMolecule(3, 7, B=490173.994e3, D=213.0, c1=29.4, c2=196.8, c3=192.4, c4=19.019e3, eQq1=-809.29e3, eQq2=59.98e3)
    rows.append({"quantity": "RbCs molecule, sector 2M_F = 12, 1 level, L = 3", "guaranteed_s": med(lambda: guaranteed_molecule_levels(m, 12, 1, 1e-11, L_initial=3, L_limit=3), 3)})
    doc = {"machine": platform.platform(), "python": sys.version.split()[0], "numpy": np.__version__,
           "scqubits": getattr(sq, "__version__", None), "repeat": REPEAT, "rows": rows}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
    for row in rows:
        print(json.dumps(row))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1])
