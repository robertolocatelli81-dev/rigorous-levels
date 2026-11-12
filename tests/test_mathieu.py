# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Tests of qraft_ra/mathieu.py (PREREG D1 of 0.3.0, 2026-11-11): exact controls at q = 0, DLMF symmetries, internal
consistency with the charge-basis rotor (a different code path), a narrowed-interval negative control, closed inputs,
and the known value a_0(1) (Abramowitz & Stegun Table 20.1: −0.45513860)."""
import importlib.util
import unittest
from fractions import Fraction

FLINT = importlib.util.find_spec("flint") is not None
if FLINT:
    from qraft_ra import mathieu as M  # noqa: E402
    from qraft_ra.guaranteed_intervals import guaranteed_levels  # noqa: E402
    from qraft_ra.rotor_spectrum import Rotor  # noqa: E402


def overlap(lo1, hi1, lo2, hi2):
    return max(lo1, lo2) <= min(hi1, hi2)


@unittest.skipUnless(FLINT, "python-flint absent")
class TestExactControls(unittest.TestCase):
    def test_q_zero_is_r_squared(self):
        """PREREG D1.1: a_r(0) = b_r(0) = r², width ≤ 1e-12 relative."""
        for r in range(0, 51):
            for kind in ("a", "b"):
                if kind == "b" and r == 0:
                    continue
                v = M.mathieu_value(kind, r, 0.0)
                self.assertEqual(v.state, "GUARANTEED", (kind, r))
                self.assertTrue(v.contains(r * r), (kind, r, v.strings))
                self.assertLessEqual(v.max_width, 1e-12 * max(1, r * r))

    def test_known_value_a0_1(self):
        v = M.mathieu_a(0, 1.0)
        self.assertLess(v.max_width, 1e-12)
        self.assertLessEqual(abs(float(v.low) + 0.45513860), 5e-9, v.strings)   # the 8-digit table value, rounded

    def test_symmetries_dlmf_28_2_3_4(self):
        """PREREG D1.2: a_{2n}(−q) = a_{2n}(q); a_{2n+1}(−q) = b_{2n+1}(q)."""
        for q in (0.5, 3.0, 25.0, 100.0, 400.0):
            for n in range(0, 7):
                a1, a2 = M.mathieu_a(2 * n, -q), M.mathieu_a(2 * n, q)
                self.assertTrue(overlap(a1.low, a1.high, a2.low, a2.high), (n, q))
                b1, b2 = M.mathieu_b(2 * n + 2, -q), M.mathieu_b(2 * n + 2, q)
                self.assertTrue(overlap(b1.low, b1.high, b2.low, b2.high), (n, q))
                c1, c2 = M.mathieu_a(2 * n + 1, -q), M.mathieu_b(2 * n + 1, q)
                self.assertTrue(overlap(c1.low, c1.high, c2.low, c2.high), (n, q))

    def test_consistency_with_the_rotor_module(self):
        """PREREG D1.3: the sorted levels of the rotor E_C = 1, n_g = ν/2, 2q cos φ are a_0 < b_2 < a_2 < b_4 … (ν = 0)
        and b_1 < a_1 < b_3 < a_3 … (ν = 1, q > 0): a different code (the full chain, no sectors) must agree."""
        for q in (1.0, 10.0, 100.0):
            for nu in (0, 1):
                iv = guaranteed_levels(Rotor(E_C=1.0, cosines={1: 2 * q}, n_g=nu / 2), 8, 1e-11, deadline=120)
                self.assertEqual(iv.state, "GUARANTEED")
                if nu == 0:
                    order = [("a", 0)] + [x for n in range(1, 4) for x in (("b", 2 * n), ("a", 2 * n))] + [("b", 8)]
                else:
                    order = [x for n in range(4) for x in (("b", 2 * n + 1), ("a", 2 * n + 1))]
                for j, (kind, r) in enumerate(order):
                    v = M.mathieu_value(kind, r, q)
                    self.assertTrue(overlap(iv.low[j], iv.high[j], v.low, v.high), (q, nu, j, kind, r, iv.strings[j], v.strings))

    def test_narrowed_interval_falls_outside(self):
        """PREREG D1.4 (negative control): intervals narrowed 10× around the centre no longer meet the rotor's ones in
        at least one level for every q: the agreement above is not trivial."""
        for q in (1.0, 10.0, 100.0):
            iv = guaranteed_levels(Rotor(E_C=1.0, cosines={1: 2 * q}, n_g=0.0), 8, 1e-11, deadline=120)
            order = [("a", 0)] + [x for n in range(1, 4) for x in (("b", 2 * n), ("a", 2 * n))] + [("b", 8)]
            misses = 0
            for j, (kind, r) in enumerate(order):
                v = M.mathieu_value(kind, r, q)
                c, w = (v.low + v.high) / 2, (v.high - v.low) / 20
                shifted = c + 3 * (v.high - v.low)              # moved by 3 widths: a wrong reference
                if not overlap(iv.low[j], iv.high[j], shifted - w, shifted + w):
                    misses += 1
            self.assertGreaterEqual(misses, 1, q)


@unittest.skipUnless(FLINT, "python-flint absent")
class TestTruncationBoundDecides(unittest.TestCase):
    """Where the cut K is forced small the tail decides: the result must be OutOfDomain or an interval that still
    contains the value computed at a large K (a mutant without η, without the t check or with a relaxed count
    returns a narrow interval that excludes it)."""

    def test_forced_small_cut_never_excludes_the_truth(self):
        import numpy as np
        from scipy.linalg import eigvalsh_tridiagonal
        checked = 0
        for kind, r, q in (("a", 2, 25.0), ("a", 4, 100.0), ("b", 3, 60.0), ("a", 0, 400.0), ("b", 6, 150.0)):
            nu, k0, n = M.sector(kind, r)
            diag, off2 = M._matrix(kind, nu, k0, 400, Fraction(q))
            truth = float(eigvalsh_tridiagonal(np.array([float(x) for x in diag]), np.sqrt([float(x) for x in off2]),
                                               select="i", select_range=(n, n))[0])
            for K in range(k0 + n + 1, k0 + n + 14):
                try:
                    v = M.mathieu_value(kind, r, q, 1e-12, K_initial=K, K_limit=K)
                except M.OutOfDomain:
                    continue
                checked += 1
                self.assertTrue(float(v.low) - 1e-9 <= truth <= float(v.high) + 1e-9, (kind, r, q, K, v.strings, truth))
        self.assertGreater(checked, 5)

    def test_outer_bound_formula(self):
        """t = min(d_{K+1} − |q| − q²/η, d_{K+2} − 2|q|) with η = |q|: _attempt returns None when t ≤ high."""
        import flint
        fl = flint
        old = fl.ctx.prec
        fl.ctx.prec = 128
        try:
            # a_0(400): at K = 2 the outer bound is (2·3)² − 2·400 < 0 ≤ high: no interval may come out
            self.assertIsNone(M._attempt(fl, "a", 0, 0, 0, Fraction(400), 2, 1e-12))
            # at a large K it comes out and contains the known value
            res = M._attempt(fl, "a", 0, 0, 0, Fraction(400), 60, 1e-12)
            self.assertIsNotNone(res)
            lo, hi, eta = res
            self.assertEqual(eta, 400.0)
            self.assertLess(abs(float(lo) + 760.2515926), 1e-6, (float(lo), float(hi)))      # A&S / scipy value
        finally:
            fl.ctx.prec = old


@unittest.skipUnless(FLINT, "python-flint absent")
class TestClosedInputs(unittest.TestCase):
    def test_refused_with_reason(self):
        for args in (("c", 1, 1.0), ("a", -1, 1.0), ("a", 1.5, 1.0), ("a", True, 1.0), ("b", 0, 1.0),
                     ("a", M.R_MAX + 1, 1.0), ("a", 1, float("nan")), ("a", 1, float("inf")), ("a", 1, "1"),
                     ("a", 1, 10 ** 400), ("a", 1, None)):
            with self.assertRaises(M.OutOfDomain, msg=str(args)):
                M.mathieu_value(*args)
        for kw in ({"width": 0}, {"width": -1.0}, {"width": float("nan")}, {"K_limit": 1}, {"K_limit": M.K_LIMIT + 1},
                   {"prec": 1}, {"prec": M.PREC_MAX + 1}, {"deadline": 0}, {"deadline": "x"}, {"K_initial": 0}):
            with self.assertRaises(M.OutOfDomain, msg=str(kw)):
                M.mathieu_value("a", 2, 1.0, **kw)

    def test_negative_and_large_q_and_numpy_scalars(self):
        import numpy as np
        for q in (-400.0, 400.0, np.float64(2.5), np.int64(3), 7):
            v = M.mathieu_a(3, q)
            self.assertEqual(v.state, "GUARANTEED", q)
        with self.assertRaises(M.OutOfDomain):
            M.mathieu_a(3, np.bool_(True))

    def test_deadline(self):
        with self.assertRaises(M.DeadlineExceeded):
            M.mathieu_a(150, 1e6, deadline=1e-9)

    def test_sector_table(self):
        self.assertEqual(M.sector("a", 0), (0, 0, 0))
        self.assertEqual(M.sector("a", 4), (0, 0, 2))
        self.assertEqual(M.sector("b", 2), (0, 1, 0))
        self.assertEqual(M.sector("b", 6), (0, 1, 2))
        self.assertEqual(M.sector("a", 1), (1, 0, 0))
        self.assertEqual(M.sector("b", 5), (1, 0, 2))


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(FLINT, "python-flint absent")
class TestNemesis030ExtremeInputs(unittest.TestCase):
    """NEMESIS 0.3.0: q ≥ 1e155 (q² beyond float64) and width = 1e308 crashed with OverflowError; E_C = 1e308 crashed
    guaranteed_levels. Refusals now."""

    def test_extreme_floats_refused(self):
        for call in (lambda: M.mathieu_a(1, 1e308), lambda: M.mathieu_a(1, -1e308), lambda: M.mathieu_b(3, 1e155),
                     lambda: M.mathieu_a(2, 1.0, width=1e308),
                     lambda: guaranteed_levels(Rotor.transmon(1e308, 15.0), 2),
                     lambda: guaranteed_levels(Rotor.transmon(5e-324, 15.0), 2),
                     lambda: guaranteed_levels(Rotor.transmon(0.3, 1e308), 2)):
            with self.assertRaises(M.OutOfDomain):
                call()
        self.assertEqual(M.mathieu_a(1, 1e8).state, "GUARANTEED")                                  # positive control
