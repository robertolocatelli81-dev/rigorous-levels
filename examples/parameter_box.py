# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Parameters known with an uncertainty: E_C and E_J as intervals, levels guaranteed over the whole box
(two guaranteed computations, Weyl's inequality and monotonicity in E_C; docs/PROOF.md)."""
from rigorous_levels import Rotor, RotorBall, guaranteed_levels, guaranteed_levels_over_box

box = RotorBall.transmon((0.297, 0.303), (14.85, 15.15), n_g=0.25)      # E_C ± 1 %, E_J ± 1 % (GHz)
iv = guaranteed_levels_over_box(box, 4, 1e-10)
print(iv.state, "rho =", iv.alpha, "GHz; f01 over the box:", [f"{float(x):.6f}" for x in iv.transition(0, 1)])

point = guaranteed_levels(Rotor.transmon(0.3, 15.0, n_g=0.25), 4, 1e-10)   # the midpoint, as a check
print("midpoint f01:", [f"{float(x):.9f}" for x in point.transition(0, 1)],
      "inside the box interval:", all(iv.low[j] <= point.low[j] and point.high[j] <= iv.high[j] for j in range(4)))
