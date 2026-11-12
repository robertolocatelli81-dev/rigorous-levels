# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""The origin case: H = h2·n² + c2·cos 4φ, solved in the author's earlier work by eigh on a FIXED charge basis
|n| ≤ Nb with Nb = 40. Here: guaranteed intervals of the first levels; eigh at Nb = 2 falls OUTSIDE (positive
control) and at Nb = 60 inside (within the float noise eps·‖H‖); over the batch Nb = 2…60 the first cut that is
inside is found, every smaller cut is outside for at least one level and every larger cut inside. Measured
(2026-11-11): the fixed Nb = 40 is inside for h2, c2 = (1, 2), (0.5, 20), (2, −15) and OFF by 1.4e-11 for
(0.25, 60), where the first cut inside is 41…60: a fixed basis cannot know."""
import importlib.util
import unittest

import numpy as np

FLINT = importlib.util.find_spec("flint") is not None
if FLINT:
    from rigorous_levels import Rotor, guaranteed_levels  # noqa: E402

CASES = ((1.0, 2.0), (0.5, 20.0), (2.0, -15.0), (0.25, 60.0))     # (h2, c2): E_C = h2/4, cosines {4: c2}


def eigh_levels(h2, c2, Nb, k):
    n = np.arange(-Nb, Nb + 1)
    H = np.diag(h2 * n.astype(float) ** 2)
    for i in range(len(n) - 4):
        H[i, i + 4] = H[i + 4, i] = c2 / 2.0
    return np.linalg.eigvalsh(H)[:k]


def inside(iv, levels, tol):
    return all(float(iv.low[j]) - tol <= levels[j] <= float(iv.high[j]) + tol for j in range(len(levels)))


@unittest.skipUnless(FLINT, "python-flint absent")
class TestCos4PhiOrigin(unittest.TestCase):
    def test_fixed_basis_60_inside_and_2_outside(self):
        off_at_40 = []
        for h2, c2 in CASES:
            r = Rotor(h2 / 4.0, {4: c2})
            iv = guaranteed_levels(r, 6, 1e-11, deadline=120)
            self.assertEqual(iv.state, "GUARANTEED", (h2, c2))
            tol = 64 * 2.0 ** -52 * (h2 * 60 ** 2 + abs(c2))             # float noise of eigh at Nb = 60
            self.assertTrue(inside(iv, eigh_levels(h2, c2, 60, 6), tol), (h2, c2, iv.strings))
            self.assertFalse(inside(iv, eigh_levels(h2, c2, 2, 6), tol), (h2, c2))
            if not inside(iv, eigh_levels(h2, c2, 40, 6), tol):
                off_at_40.append((h2, c2))
        self.assertEqual(off_at_40, [(0.25, 60.0)])                      # the fixed Nb = 40 of the old work is not enough here

    def test_batch_of_cuts(self):
        """For every case: the smallest Nb whose eigh levels are inside; all smaller Nb outside in some level; all
        larger Nb inside (the basis is nested, Rayleigh–Ritz: the eigh levels decrease monotonically with Nb)."""
        for h2, c2 in CASES:
            r = Rotor(h2 / 4.0, {4: c2})
            iv = guaranteed_levels(r, 6, 1e-11, deadline=120)
            tol = 64 * 2.0 ** -52 * (h2 * 60 ** 2 + abs(c2))
            verdicts = [(Nb, inside(iv, eigh_levels(h2, c2, Nb, 6), tol)) for Nb in range(3, 61)]
            first = next(Nb for Nb, ok in verdicts if ok)
            self.assertTrue(all(ok for Nb, ok in verdicts if Nb >= first), (h2, c2, verdicts))
            self.assertTrue(all(not ok for Nb, ok in verdicts if Nb < first), (h2, c2, verdicts))
            self.assertGreater(first, 3, (h2, c2))


if __name__ == "__main__":
    unittest.main()
