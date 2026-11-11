# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Guaranteed matrix elements between eigenvectors of the transmon: the charge element ⟨0|n|1⟩ (coupling, Purcell)
and ⟨0|cos φ|1⟩, with the bound on the eigenvector error that makes them rigorous (docs/PROOF.md)."""
from qraft_ra import Rotor, guaranteed_matrix_element

r = Rotor.transmon(0.3, 15.0, n_g=0.25)
e = guaranteed_matrix_element(r, 0, 1, "n")           # the sign of an eigenvector is arbitrary: report |element|
lo, hi = sorted((abs(float(e.low)), abs(float(e.high))))
print("|<0|n|1>| in", f"[{lo:.12f}, {hi:.12f}]", "width", f"{e.max_width:.1e}", "sin-theta bounds", [f"{s:.1e}" for s in e.sin_bounds])
c = guaranteed_matrix_element(r, 0, 1, "cos")
lo, hi = sorted((abs(float(c.low)), abs(float(c.high))))
print("|<0|cos phi|1>| in", f"[{lo:.3e}, {hi:.3e}]")
h = guaranteed_matrix_element(Rotor.transmon(1.0, 5.0, n_g=0.5), 1, 1, "n")
print("<1|n|1> at n_g = 1/2 contains 1/2:", h.contains(0.5), "width", f"{h.max_width:.1e}")
