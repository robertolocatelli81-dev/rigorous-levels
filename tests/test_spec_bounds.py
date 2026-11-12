# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Specification tests of the constants of the proven bounds (review of 0.3.0): mutants that loosen a bound without
changing any number at the default widths (the slack hides them) must fail here. Each test recomputes the bound from
quantities built independently of the function under test, or forces the regime where the term decides."""
import importlib.util
import math
import unittest
from fractions import Fraction

FLINT = importlib.util.find_spec("flint") is not None
if FLINT:
    import numpy as np  # noqa: E402
    from rigorous_levels import fluxonium as FX  # noqa: E402
    from rigorous_levels import mathieu as MA  # noqa: E402
    from rigorous_levels import matrix_elements as ME  # noqa: E402
    from rigorous_levels.guaranteed_intervals import _flint  # noqa: E402
    from rigorous_levels.rotor_spectrum import Rotor  # noqa: E402


@unittest.skipUnless(FLINT, "python-flint absent")
class TestMathieuOuterBound(unittest.TestCase):
    def test_outer_bound_uses_q_squared_over_eta(self):
        """a_0(20) with the cut K = 1: t = d_2 − 2|q| = 16 − 40 does not lie above the enclosure, so the cut must grow;
        dropping q²/η from t (t = 16 − 20) accepts K = 1 (found by search: 78 such (sector, n, K, q) on a small grid)."""
        fl = _flint()
        fl.ctx.prec = 128
        self.assertIsNone(MA._attempt(fl, "a", 0, 0, 0, Fraction(20), 1, 1e-12))
        small = MA.mathieu_a(0, 20.0, K_initial=1)
        big = MA.mathieu_a(0, 20.0, K_initial=60)
        self.assertTrue(small.low <= big.high and big.low <= small.high, (small.strings, big.strings))
        self.assertGreater(small.K, 1)

    def test_second_outer_term_is_redundant_for_eta_equal_to_q(self):
        """Declared equivalence: with η = |q|, d_{K+2} − 2|q| > d_{K+1} − 2|q|, so t = d_{K+1} − 2|q| exactly."""
        for K in range(1, 300):
            for nu in (0, 1):
                for q in (Fraction(1, 3), Fraction(7), Fraction(10 ** 6), Fraction(-12345, 7)):
                    a = abs(q)
                    d1, d2 = Fraction((2 * (K + 1) + nu) ** 2), Fraction((2 * (K + 2) + nu) ** 2)
                    self.assertEqual(min(d1 - a - q * q / a, d2 - 2 * a), d1 - 2 * a)


@unittest.skipUnless(FLINT, "python-flint absent")
class TestFluxoniumColumnTail(unittest.TestCase):
    def test_column_tail_enters_c_max(self):
        """max_o c_o over o ≥ N needs the tail beyond N + N2: an inflated tail bound must show in c_max."""
        f = FX.Fluxonium(0.5, 3.0, 0.5, 0.25)
        fl = _flint()
        fl.ctx.prec = 128
        original = FX._laguerre_bound_tail

        def big_tail(fl_, y, N, N2):
            rows, col, ok = original(fl_, y, N, N2)
            return rows, col + 10 ** 6, ok
        FX._laguerre_bound_tail = big_tail
        try:
            b = FX._bounds(fl, f, 20, 40)
        finally:
            FX._laguerre_bound_tail = original
        self.assertGreaterEqual(float(b[4].lower()), 3.0 * 10 ** 6)


@unittest.skipUnless(FLINT, "python-flint absent")
class TestMatrixElementBound(unittest.TestCase):
    """ψ_0 replaced by cos θ ψ_0 + sin θ ψ_1 (θ = 0.3): s is O(0.3), so s(1 + s²) differs from s by ~9 % and the
    terms of the bound are visible; the expected half-width is recomputed from the vectors, not from the module."""

    def setUp(self):
        self.r = Rotor.transmon(0.3, 15.0, n_g=0.25)
        self.orig = ME._vectors
        orig = self.orig

        def mixed(r, N, k):
            v = orig(r, N, k)
            c, s = Fraction(math.cos(0.3)), Fraction(math.sin(0.3))
            keys = set(v[0]) | set(v[1])
            v[0] = {n: c * v[0].get(n, 0) + s * v[1].get(n, 0) for n in keys}
            self.vec = v
            return v
        ME._vectors = mixed

    def tearDown(self):
        ME._vectors = self.orig

    def test_bounded_operator_uses_both_errors_with_the_cubic_term(self):
        e = ME.guaranteed_matrix_element(self.r, 0, 0, "cos", 1)
        s = e.sin_bounds[0]
        self.assertGreater(s, 0.1)
        half = float(e.high - e.low) / 2
        self.assertAlmostEqual(half, 2 * s * (1 + s * s), delta=1e-9 * half)

    def test_charge_operator_bound_with_n_g(self):
        e = ME.guaranteed_matrix_element(self.r, 0, 0, "n")
        s = e.sin_bounds[0]
        err = s * (1 + s * s)
        iv = e.intervals
        nv = math.sqrt((float(iv.high[0]) + 15.0) / (4 * 0.3)) + 0.25
        psi = self.vec[0]
        npsi = math.sqrt(float(sum((x * n) ** 2 for n, x in psi.items()) / sum(x * x for x in psi.values())))
        half = float(e.high - e.low) / 2
        self.assertAlmostEqual(half, err * nv + npsi * err, delta=1e-6 * half)

    def test_gap_is_the_nearest_neighbour(self):
        ME._vectors = self.orig
        e = ME.guaranteed_matrix_element(Rotor.transmon(1.0, 0.5, n_g=0.45), 1, 1, "cos", 1)   # level 1 nearer to 0
        iv = e.intervals
        lam = (iv.low[1] + iv.high[1]) / 2
        self.assertLess(lam - iv.high[0], iv.low[2] - lam)
        self.assertAlmostEqual(e.gaps[0], float(min(lam - iv.high[0], iv.low[2] - lam)), delta=1e-12)
