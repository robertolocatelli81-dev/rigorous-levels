# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""An assertion helper for other people's regression tests: `assert_inside(levels, intervals, tolerance)` raises
AssertionError with the per-level verdict when a solver's levels leave the guaranteed intervals.

The case is the one of scqubits issue #334: for a matrix with an exact zero eigenvalue, scipy's sparse `eigsh`
(k = 4, which = "SA") omits the zero from scipy 1.15.0 on (measured: 1.14.1 right; 1.15.0, 1.15.3, 1.16.2, 1.17.1,
1.18.1 wrong), while the dense solver is right. The charge-basis rotor with no potential, 4E_C n² with n_g = 0, has
that exact zero; its guaranteed intervals contain 0, 1.2, 1.2, 4.8 GHz for E_C = 0.3."""
import numpy as np
import scipy
import scipy.sparse as sp
from scipy.sparse.linalg import eigsh

from rigorous_levels import Rotor, assert_inside, guaranteed_levels

r = Rotor(0.3, {})                                   # H = 4 E_C n², exact spectrum 0, 1.2, 1.2, 4.8, ...
iv = guaranteed_levels(r, 4, 1e-10)
H, _ = r.matrix(30)
dense = np.linalg.eigvalsh(H)[:4]
assert_inside(dense, iv, tolerance=1e-9)
print("dense eigvalsh:", np.round(dense, 6), "-> inside the guaranteed intervals")

sparse = np.sort(eigsh(sp.csc_matrix(H), k=4, which="SA")[0])
try:
    assert_inside(sparse, iv, tolerance=1e-9)
    print(f"sparse eigsh (scipy {scipy.__version__}):", np.round(sparse, 6), "-> inside")
except AssertionError as e:
    print(f"sparse eigsh (scipy {scipy.__version__}):", np.round(sparse, 6), "-> AssertionError:", str(e)[:60])
