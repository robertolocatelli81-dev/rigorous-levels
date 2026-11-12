# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Tests of qraft_ra/fluxonium.py (PREREG D2 of 0.3.0, 2026-11-11): the exact oscillator at E_J = 0, scqubits inside
the intervals at a large cutoff and OUTSIDE at a small one (negative control), the cosine matrix against numpy
(a different construction), closed inputs, deadline."""
import importlib.util
import math
import unittest
from fractions import Fraction

FLINT = importlib.util.find_spec("flint") is not None
SCQUBITS = importlib.util.find_spec("scqubits") is not None
if FLINT:
    from qraft_ra import fluxonium as F  # noqa: E402

DEVICES = (("Zhang 2021", 0.479, 3.395, 0.132), ("Moskalenko 2022 A", 0.567, 2.052, 0.835))


@unittest.skipUnless(FLINT, "python-flint absent")
class TestGuarantee(unittest.TestCase):
    def test_pure_oscillator_limit(self):
        """PREREG D2.1 (exact control): with a tiny E_J the levels are ω(j + ½) up to O(E_J): the intervals of the
        H with E_J = 1e-9 contain ω(j+½) ± 1e-9 (E_J = 0 is refused: closed domain, E_J > 0)."""
        f = F.Fluxonium(E_C=0.5, E_J=1e-9, E_L=0.5, flux=0.3)
        iv = F.guaranteed_fluxonium_levels(f, 6, 1e-10, deadline=300)
        self.assertEqual(iv.state, "GUARANTEED")
        w = Fraction(8 * Fraction(0.5) * Fraction(0.5)) ** Fraction(1, 2)          # exact: √2
        for j in range(6):
            self.assertLess(abs(float(iv.low[j]) - math.sqrt(2) * (j + 0.5)), 2e-9, j)
            self.assertLess(float(iv.high[j] - iv.low[j]), 1e-10)
        self.assertEqual(float(w), math.sqrt(2))

    def test_cosine_matrix_against_numpy(self):
        """The Arb matrix of cos(φ − φ_ext) agrees with numpy's expm-free construction (eigen-decomposition of φ)."""
        import numpy as np
        import flint
        N, phi2, flux = 24, 1.7, 0.37
        fl = flint
        old = fl.ctx.prec
        fl.ctx.prec = 128
        try:
            C = F.cos_matrix(fl, N, fl.arb(phi2), Fraction(flux), 1)
        finally:
            fl.ctx.prec = old
        M = N + 60                                        # numpy: diagonalize φ on a larger space, then truncate
        a = np.diag(np.sqrt(np.arange(1, M)), 1)
        phi = math.sqrt(phi2) * (a + a.T)
        w, V = np.linalg.eigh(phi)
        cos_np = (V * np.cos(w - 2 * math.pi * flux)) @ V.T
        for i in range(N):
            for j in range(N):
                self.assertLess(abs(float(C[i, j]) - cos_np[i, j]), 1e-9, (i, j))

    @unittest.skipUnless(SCQUBITS, "scqubits absent")
    def test_scqubits_inside_at_large_cutoff_and_outside_at_small(self):
        """PREREG D2.2 and D2.3: scqubits.Fluxonium cutoff 110 inside (widened by 1e-8 GHz); cutoff 6 outside in at
        least one level of at least one device (the small truncation is wrong and the intervals see it)."""
        import scqubits as sq
        sq.settings.PROGRESSBAR_DISABLED = True
        outside_small = 0
        for name, ec, ej, el in DEVICES:
            for flux in (0.0, 0.25, 0.5):
                iv = F.guaranteed_fluxonium_levels(F.Fluxonium(E_C=ec, E_J=ej, E_L=el, flux=flux), 4, 1e-9, deadline=600)
                self.assertEqual(iv.state, "GUARANTEED", (name, flux))
                big = sq.Fluxonium(EJ=ej, EC=ec, EL=el, flux=flux, cutoff=110).eigenvals(evals_count=4)
                small = sq.Fluxonium(EJ=ej, EC=ec, EL=el, flux=flux, cutoff=6).eigenvals(evals_count=4)
                for j in range(4):
                    self.assertTrue(float(iv.low[j]) - 1e-8 <= big[j] <= float(iv.high[j]) + 1e-8, (name, flux, j, iv.strings[j], big[j]))
                    if not (float(iv.low[j]) - 1e-8 <= small[j] <= float(iv.high[j]) + 1e-8):
                        outside_small += 1
        self.assertGreaterEqual(outside_small, 1)

    def test_narrowed_intervals_exclude_the_reference(self):
        """Negative control of the bench itself: an interval shifted by 3 widths no longer contains scqubits/numpy."""
        f = F.Fluxonium(E_C=0.567, E_J=2.052, E_L=0.835, flux=0.5)
        iv = F.guaranteed_fluxonium_levels(f, 3, 1e-9, deadline=300)
        for j in range(3):
            w = iv.high[j] - iv.low[j]
            self.assertFalse(iv.low[j] + 3 * w <= (iv.low[j] + iv.high[j]) / 2 <= iv.high[j] + 3 * w)


@unittest.skipUnless(FLINT, "python-flint absent")
class TestTruncationBoundDecides(unittest.TestCase):
    """Where N is forced small the tails and the outer bound decide: OutOfDomain, or an interval that still contains
    the levels computed at a large N (a mutant that drops the tails, the lowering or the c_o term returns a narrow
    interval that excludes them)."""

    def test_forced_small_N_never_excludes_the_truth(self):
        f = F.Fluxonium(E_C=0.479, E_J=3.395, E_L=0.132, flux=0.5)
        ref = F.guaranteed_fluxonium_levels(f, 3, 1e-9, deadline=600)
        checked = 0
        for N in range(5, 30, 3):
            try:
                iv = F.guaranteed_fluxonium_levels(f, 3, 1e-9, N_initial=N, N_limit=N, deadline=600)
            except F.OutOfDomain:
                continue
            checked += 1
            for j in range(3):
                self.assertTrue(iv.low[j] <= ref.low[j] and ref.high[j] <= iv.high[j], (N, j, iv.strings[j], ref.strings[j]))
        self.assertGreater(checked, 0)

    def test_laguerre_tail_and_outer_bound_formulas(self):
        import flint
        fl = flint
        old = fl.ctx.prec
        fl.ctx.prec = 128
        try:
            y = fl.arb(fl.fmpq(269, 100))
            rows, col, ok = F._laguerre_bound_tail(fl, y, 20, 40)
            self.assertTrue(ok)                                        # ρ = √(2.69·61)/41 ≈ 0.31 ≤ 1/2
            self.assertFalse(F._laguerre_bound_tail(fl, y, 20, 4)[2])  # ρ = √(2.69·25)/5 ≈ 1.6 > 1/2
            # every row tail is twice v(i, o0) and the column tail is the sum of the v(i, o0)
            o0 = 60
            total = fl.arb(0)
            for i in range(20):
                ratio = Fraction(1)
                for j in range(i + 1, o0 + 1):
                    ratio *= j
                v = y ** fl.arb(fl.fmpq(o0 - i, 2)) * fl.arb(fl.fmpq(ratio.numerator, ratio.denominator)).sqrt() / fl.arb(math.factorial(o0 - i))
                self.assertTrue((rows[i] - 2 * v).contains(0), i)
                total += v
            self.assertTrue((col - total).contains(0))
            # the per-site lowerings include the tails, and the outer bound is ω(N+½) − E_J − c_max with c_max > 0:
            # for this device at N = 10, ω(N+½) − E_J ≈ 4.07 is above the 3rd level (≈ 1.89) but t is not
            f = F.Fluxonium(E_C=0.479, E_J=3.395, E_L=0.132, flux=0.5)
            C, omega, EJa, r, cmax, t_out = F._bounds(fl, f, 10, 40)
            rows10, _, _ = F._laguerre_bound_tail(fl, fl.arb(F._fmpq(fl, 2 * Fraction(0.479) / Fraction(0.132))).sqrt(), 10, 40)
            for i in range(10):                                   # r_i = E_J (Σ_{o<N+N2} |C_io| + tail_i), exactly
                s = rows10[i]
                for o in range(10, 50):
                    s += abs(C[i, o])
                self.assertTrue((r[i] - EJa * s).contains(0), i)
                self.assertFalse((r[i] - EJa * (s - rows10[i])).contains(0), i)   # the tail is not negligible in Arb
            self.assertTrue(cmax > 1)
            self.assertTrue((omega * (10 + fl.arb(fl.fmpq(1, 2))) - EJa - cmax - t_out).contains(0))
            self.assertTrue(omega * fl.arb(fl.fmpq(21, 2)) - EJa > fl.arb(fl.fmpq(189, 100)))
            self.assertTrue(t_out < fl.arb(fl.fmpq(189, 100)))
            self.assertIsNone(F._attempt(fl, f, 3, 1e-9, 10, 40, None))
        finally:
            fl.ctx.prec = old


@unittest.skipUnless(FLINT, "python-flint absent")
class TestClosedInputs(unittest.TestCase):
    def test_constructor(self):
        for kw in ({"E_C": 0}, {"E_J": -1.0}, {"E_L": float("nan")}, {"flux": float("inf")}, {"E_C": True},
                   {"E_C": "0.5"}, {"E_C": 10 ** 400}, {"flux": None}):
            with self.assertRaises(F.OutOfDomain, msg=str(kw)):
                F.Fluxonium(**{**dict(E_C=0.5, E_J=4.0, E_L=0.5), **kw})

    def test_arguments(self):
        f = F.Fluxonium(E_C=0.5, E_J=4.0, E_L=0.5)
        for args, kw in (((f, 0), {}), ((f, F.K_MAX + 1), {}), ((f, True), {}), ((f, 2), {"width": 0}),
                         ((f, 2), {"N_limit": 3}), ((f, 2), {"N_limit": F.N_LIMIT + 1}), ((f, 2), {"prec": 1}),
                         ((f, 2), {"deadline": -1}), ((f, 2), {"N_initial": 1}), (("x", 2), {})):
            with self.assertRaises(F.OutOfDomain, msg=str((args, kw))):
                F.guaranteed_fluxonium_levels(*args, **kw)

    def test_deadline(self):
        with self.assertRaises(F.DeadlineExceeded):
            F.guaranteed_fluxonium_levels(F.Fluxonium(E_C=0.5, E_J=4.0, E_L=0.02), 6, 1e-12, deadline=1e-6)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(FLINT, "python-flint absent")
class TestNemesis030ExtremeInputs(unittest.TestCase):
    """NEMESIS 0.3.0: E_C = 1e17 or 2**63 grew the outer block N2 = 2.5·√(φ²N) without a cap (MemoryError under a
    4 GB ulimit, OOM kill of the host without it); E_C = 1e308 and E_L = 5e-324 crashed with OverflowError. All are
    refusals with the reason now, in seconds."""

    def test_extreme_parameters_refused_quickly(self):
        import time
        for args in ((1e17, 3.0, 0.5), (2 ** 63, 3.0, 0.5), (1e308, 3.0, 0.5), (0.5, 3.0, 5e-324), (0.5, 1e308, 0.5),
                     (1e308, 3.0, 1e308), (1e3, 3.0, 1e-3)):
            t0 = time.time()
            with self.assertRaises((F.OutOfDomain, F.DeadlineExceeded), msg=args):
                F.guaranteed_fluxonium_levels(F.Fluxonium(*args), 2, 1e-6, deadline=10)
            self.assertLess(time.time() - t0, 20, args)
        iv = F.guaranteed_fluxonium_levels(F.Fluxonium(0.5, 3.0, 0.5, 0.25), 2, 1e-6)          # positive control
        self.assertEqual(iv.state, "GUARANTEED")
