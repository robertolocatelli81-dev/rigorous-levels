# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Tests of qraft_ra/parameter_balls.py (parameters as intervals) and of the entry from scqubits objects
(scqubits_adapter.guaranteed_from_scqubits): every point of the box falls inside the box interval (positive), a point
outside the box falls outside for a level that moves (negative control), exact parameters reduce to the point
intervals, closed inputs."""
import importlib.util
import unittest
from fractions import Fraction

FLINT = importlib.util.find_spec("flint") is not None
SCQUBITS = importlib.util.find_spec("scqubits") is not None
if FLINT:
    from qraft_ra import Rotor, RotorBall, guaranteed_levels, guaranteed_levels_over_box  # noqa: E402
    from qraft_ra.parameter_balls import OutOfDomain  # noqa: E402


@unittest.skipUnless(FLINT, "python-flint absent")
class TestBox(unittest.TestCase):
    def test_every_inner_point_is_inside(self):
        import random
        rnd = random.Random(20261111)
        for ec, ej, ng in ((0.3, 15.0, 0.25), (0.2, 40.0, 0.0), (1.0, 5.0, 0.5)):
            box = RotorBall.transmon((ec * 0.98, ec * 1.02), (ej * 0.99, ej * 1.01), n_g=ng)
            iv = guaranteed_levels_over_box(box, 4, 1e-10, deadline=120)
            self.assertEqual(iv.state, "GUARANTEED")
            self.assertAlmostEqual(iv.alpha, ej * 0.01, places=9)             # ρ = half-width of E_J
            for _ in range(6):
                p = guaranteed_levels(Rotor.transmon(rnd.uniform(ec * 0.98, ec * 1.02), rnd.uniform(ej * 0.99, ej * 1.01), n_g=ng),
                                      4, 1e-10, deadline=120)
                for j in range(4):
                    self.assertTrue(iv.low[j] <= p.low[j] and p.high[j] <= iv.high[j], (ec, ej, ng, j))
            # the corners of the box too (monotonicity in E_C is used at the ends)
            for c in (ec * 0.98, ec * 1.02):
                for e in (ej * 0.99, ej * 1.01):
                    p = guaranteed_levels(Rotor.transmon(c, e, n_g=ng), 4, 1e-10, deadline=120)
                    for j in range(4):
                        self.assertTrue(iv.low[j] <= p.low[j] and p.high[j] <= iv.high[j], (c, e, j))

    def test_point_outside_the_box_falls_outside(self):
        """Negative control: E_J 5 % above the box moves the ground level by ≈ 5 % of E_J, more than ρ (1 %)."""
        box = RotorBall.transmon(0.3, (15.0 * 0.99, 15.0 * 1.01), n_g=0.25)
        iv = guaranteed_levels_over_box(box, 2, 1e-10, deadline=120)
        p = guaranteed_levels(Rotor.transmon(0.3, 15.0 * 1.05, n_g=0.25), 2, 1e-10, deadline=120)
        self.assertTrue(p.high[0] < iv.low[0] or p.low[0] > iv.high[0], (iv.strings[0], p.strings[0]))

    def test_exact_parameters_reduce_to_the_point_intervals(self):
        iv = guaranteed_levels_over_box(RotorBall.transmon(0.3, 15.0, n_g=0.25), 3, 1e-10, deadline=120)
        p = guaranteed_levels(Rotor.transmon(0.3, 15.0, n_g=0.25), 3, 1e-10, deadline=120)
        self.assertEqual((iv.low, iv.high), (p.low, p.high))
        self.assertEqual(iv.alpha, 0.0)

    def test_several_harmonics(self):
        box = RotorBall(E_C=(0.3, 0.31), cosines={1: (-15.1, -14.9), 2: (0.9, 1.1)}, n_g=0.1)
        self.assertAlmostEqual(float(box.rho), 0.2, places=12)
        iv = guaranteed_levels_over_box(box, 3, 1e-10, deadline=120)
        p = guaranteed_levels(Rotor(0.305, {1: -15.05, 2: 0.95}, n_g=0.1), 3, 1e-10, deadline=120)
        for j in range(3):
            self.assertTrue(iv.low[j] <= p.low[j] and p.high[j] <= iv.high[j], j)

    def test_closed_inputs(self):
        for args in (((0.3, 0.2), {1: (-1.0, -1.0)}), ((0.0, 0.3), {1: (-1.0, -1.0)}), ((0.3,), {1: (-1.0, -1.0)}),
                     (0.3, {}), (0.3, {0: (-1.0, -1.0)}), (0.3, {1: (-1.0, "x")}), (0.3, {1: (1.0, -1.0)}),
                     (0.3, {1: (float("nan"), 1.0)}), (0.3, {1: (10 ** 400, 10 ** 400)}), (0.3, [(-1.0, -1.0)])):
            with self.assertRaises(OutOfDomain, msg=str(args)):
                RotorBall(*args)
        with self.assertRaises(OutOfDomain):
            RotorBall(0.3, {1: (-1.0, -1.0)}, n_g=(0.2, 0.1))
        with self.assertRaises(OutOfDomain):
            RotorBall.transmon(0.3, (-1.0, 1.0))
        with self.assertRaises(OutOfDomain):
            guaranteed_levels_over_box("x", 2)


@unittest.skipUnless(FLINT, "python-flint absent")
class TestChargeOffsetInterval(unittest.TestCase):
    """n_g as an interval: the band functions are monotone on [0, ½] (docs/PROOF.md), so the extremes are at the ends
    and at the band edges 0, ½ (mod 1) inside the interval. Checked against a fine sampling of n_g (positive) and
    against a sample outside the interval (negative control) in the charge-sensitive regime E_J/E_C = 5."""

    def test_candidates(self):
        self.assertEqual(RotorBall.transmon(0.3, 1.5, n_g=(0.1, 0.3)).n_g_candidates(), (0.1, 0.3))
        self.assertEqual(RotorBall.transmon(0.3, 1.5, n_g=(0.3, 0.6)).n_g_candidates(), (0.3, 0.5, 0.6))
        self.assertEqual(RotorBall.transmon(0.3, 1.5, n_g=(-0.2, 0.2)).n_g_candidates(), (-0.2, 0.0, 0.2))
        self.assertEqual(RotorBall.transmon(0.3, 1.5, n_g=(0.9, 1.6)).n_g_candidates(), (0.9, 1.0, 1.5, 1.6))
        self.assertEqual(RotorBall.transmon(0.3, 1.5, n_g=(0.0, 1.0)).n_g_candidates(), (0.0, 0.5))
        self.assertEqual(RotorBall.transmon(0.3, 1.5, n_g=0.25).n_g_candidates(), (0.25,))

    def test_fine_sampling_inside_and_a_point_outside(self):
        import numpy as np
        for a, b in ((0.05, 0.2), (0.3, 0.7), (-0.1, 0.1)):
            box = RotorBall.transmon(0.3, 1.5, n_g=(a, b))              # E_J/E_C = 5: levels move with n_g
            iv = guaranteed_levels_over_box(box, 4, 1e-10, deadline=300)
            self.assertEqual(iv.state, "GUARANTEED")
            for g in np.linspace(a, b, 9):
                p = guaranteed_levels(Rotor.transmon(0.3, 1.5, n_g=float(g)), 4, 1e-10, deadline=300)
                for j in range(4):
                    self.assertTrue(iv.low[j] <= p.low[j] and p.high[j] <= iv.high[j], (a, b, float(g), j))
            q = guaranteed_levels(Rotor.transmon(0.3, 1.5, n_g=b + 0.15 if b + 0.15 <= 0.5 else a - 0.15), 4, 1e-10, deadline=300)
            self.assertTrue(any(q.high[j] < iv.low[j] or q.low[j] > iv.high[j] for j in range(4)), (a, b))

    def test_combined_box(self):
        box = RotorBall.transmon((0.297, 0.303), (1.485, 1.515), n_g=(0.1, 0.4))
        iv = guaranteed_levels_over_box(box, 3, 1e-10, deadline=300)
        import random
        rnd = random.Random(7)
        for _ in range(8):
            p = guaranteed_levels(Rotor.transmon(rnd.uniform(0.297, 0.303), rnd.uniform(1.485, 1.515), n_g=rnd.uniform(0.1, 0.4)),
                                  3, 1e-10, deadline=300)
            for j in range(3):
                self.assertTrue(iv.low[j] <= p.low[j] and p.high[j] <= iv.high[j], j)


@unittest.skipUnless(FLINT and SCQUBITS, "python-flint or scqubits absent")
class TestFromScqubits(unittest.TestCase):
    def test_transmon_inside_and_outside(self):
        import scqubits as sq
        from qraft_ra import guaranteed_from_scqubits
        sq.settings.PROGRESSBAR_DISABLED = True
        c = guaranteed_from_scqubits(sq.Transmon(EJ=15.0, EC=0.3, ng=0.25, ncut=30), 4)
        self.assertEqual((c.kind, c.cutoff, c.verdict.overall), ("Transmon", 30, "INSIDE"))
        self.assertEqual(c.intervals.state, "GUARANTEED")
        c2 = guaranteed_from_scqubits(sq.Transmon(EJ=20000.0, EC=1.0, ng=0.0, ncut=30), 4)
        self.assertEqual(c2.verdict.overall, "OUTSIDE")                 # ncut 30 is too small at E_J/E_C = 2e4
        self.assertGreater(float(c2.verdict.per_level[-1][1].split()[0]), 1e-3)

    def test_fluxonium_and_refusals(self):
        import scqubits as sq
        from qraft_ra import guaranteed_from_scqubits
        from qraft_ra.rotor_spectrum import InputRejected
        sq.settings.PROGRESSBAR_DISABLED = True
        c = guaranteed_from_scqubits(sq.Fluxonium(EJ=2.052, EC=0.567, EL=0.835, flux=0.5, cutoff=110), 3, 1e-9)
        self.assertEqual((c.kind, c.cutoff), ("Fluxonium", 110))
        self.assertIn(c.verdict.overall, ("INSIDE", "INSIDE_TOLERANCE"))
        with self.assertRaises(InputRejected):
            guaranteed_from_scqubits(object(), 3)
        with self.assertRaises(InputRejected):
            guaranteed_from_scqubits(sq.Transmon(EJ=15.0, EC=0.3, ng=0.25, ncut=30), 0)


if __name__ == "__main__":
    unittest.main()
