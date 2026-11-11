# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Mathieu characteristic values with a guaranteed order (where scipy ≤ 1.18.1 returns another order) and the
fluxonium of Zhang et al. 2021 (PRX 11, 011010) at half flux."""
from qraft_ra import Fluxonium, guaranteed_fluxonium_levels, mathieu_a, mathieu_b

v = mathieu_a(11, 299.0)
print("a_11(299):", v.state, v.strings, "K =", v.K)         # scipy 1.17.1 and 1.18.1 give 232.195… here
w = mathieu_b(3, 91.0)
print("b_3(91):", w.state, w.strings)                 # scipy 1.17.1 and 1.18.1 give -163.17… here

iv = guaranteed_fluxonium_levels(Fluxonium(E_C=0.479, E_J=3.395, E_L=0.132, flux=0.5), 3, 1e-9)
print("fluxonium:", iv.state, "N =", iv.N, "f01 (MHz):", [f"{float(x) * 1e3:.7f}" for x in iv.transition(0, 1)])
