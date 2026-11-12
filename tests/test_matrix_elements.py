# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Tests of rigorous_levels/matrix_elements.py: exact symmetry values inside the enclosures, scqubits' matrix elements
inside, a wrong vector gives no bound (negative control), the bound tightens with the residual, closed inputs."""
import importlib.util
import unittest
from fractions import Fraction

FLINT = importlib.util.find_spec("flint") is not None
SCQUBITS = importlib.util.find_spec("scqubits") is not None
if FLINT:
    from rigorous_levels import Rotor  # noqa: E402
    from rigorous_levels import matrix_elements as ME  # noqa: E402


@unittest.skipUnless(FLINT, "python-flint absent")
class TestGuarantee(unittest.TestCase):
    def test_exact_values_from_symmetry(self):
        """At n_g = ½ the spectrum is symmetric under n → 1 − n, so ⟨j|n|j⟩ = ½ exactly; at n_g = 0 under n → −n,
        so ⟨j|n|j⟩ = 0 and ⟨0|n|2⟩ = 0 (same parity), ⟨0|cos φ|1⟩ = 0 (opposite parity)."""
        r = Rotor.transmon(1.0, 5.0, n_g=0.5)
        for j in range(3):
            e = ME.guaranteed_matrix_element(r, j, j, "n")
            self.assertTrue(e.contains(Fraction(1, 2)), (j, e.low, e.high))
            self.assertLess(e.max_width, 1e-12)
        r0 = Rotor.transmon(0.2, 40.0, n_g=0.0)
        for i, j, op in ((0, 0, "n"), (1, 1, "n"), (0, 2, "n"), (0, 1, "cos"), (1, 1, "sin")):
            e = ME.guaranteed_matrix_element(r0, i, j, op)
            self.assertTrue(e.contains(0), (i, j, op, e.low, e.high))
            self.assertLess(e.max_width, 1e-12)

    def test_hermitian_symmetry_and_width(self):
        r = Rotor.transmon(0.3, 15.0, n_g=0.25)
        a = ME.guaranteed_matrix_element(r, 0, 1, "n")
        b = ME.guaranteed_matrix_element(r, 1, 0, "n")
        self.assertTrue(max(a.low, b.low) <= min(a.high, b.high))       # ⟨0|n|1⟩ = ⟨1|n|0⟩ for real vectors
        self.assertLess(a.max_width, 1e-12)
        self.assertGreater(abs(a.value), 1.0)                            # ≈ 1.0878 (device regime)
        c = ME.guaranteed_matrix_element(r, 0, 1, "sin")
        d = ME.guaranteed_matrix_element(r, 1, 0, "sin")
        self.assertTrue(max(c.low, -d.high) <= min(c.high, -d.low))     # Im⟨0|sin|1⟩ = −Im⟨1|sin|0⟩

    @unittest.skipUnless(SCQUBITS, "scqubits absent")
    def test_scqubits_inside(self):
        import scqubits as sq
        sq.settings.PROGRESSBAR_DISABLED = True
        for ec, ej, ng in ((0.3, 15.0, 0.25), (0.2, 40.0, 0.0), (1.0, 5.0, 0.5), (0.5, 100.0, 0.1)):
            r = Rotor.transmon(ec, ej, n_g=ng)
            t = sq.Transmon(EJ=ej, EC=ec, ng=ng, ncut=40)
            tn = t.matrixelement_table("n_operator", evals_count=4)
            tc = t.matrixelement_table("cos_phi_operator", evals_count=4)
            for i, j in ((0, 1), (1, 2), (0, 2), (2, 3), (1, 1)):
                e = ME.guaranteed_matrix_element(r, i, j, "n")
                ref = abs(complex(tn[i, j]))
                self.assertTrue(e.contains(ref) or e.contains(-ref), (ec, ej, ng, i, j, e.low, e.high, ref))
                self.assertLess(e.max_width, 1e-11)
                e = ME.guaranteed_matrix_element(r, i, j, "cos")
                ref = abs(complex(tc[i, j]))
                self.assertTrue(e.contains(ref) or e.contains(-ref), (ec, ej, ng, i, j, "cos", e.low, e.high, ref))

    def test_wrong_vector_gives_no_bound_or_a_wide_valid_one(self):
        """Negative control: with the eigenvectors of a very different rotor (E_J 2 instead of 15) the residual
        exceeds the gap and no bound comes out (OutOfDomain); with a mildly different one (E_J 12) the bound exists,
        is wide (≥ 0.05) and still contains the clean value: never a narrow wrong enclosure."""
        r = Rotor.transmon(0.3, 15.0, n_g=0.25)
        clean = ME.guaranteed_matrix_element(r, 0, 1, "n")
        original = ME._vectors
        ME._vectors = lambda rot, N, k: original(Rotor.transmon(0.3, 2.0, n_g=0.25), N, k)
        try:
            with self.assertRaises(ME.OutOfDomain):
                ME.guaranteed_matrix_element(r, 0, 1, "n")
        finally:
            ME._vectors = original
        ME._vectors = lambda rot, N, k: original(Rotor.transmon(0.3, 12.0, n_g=0.25), N, k)
        try:
            e = ME.guaranteed_matrix_element(r, 0, 1, "n")
        finally:
            ME._vectors = original
        self.assertGreater(e.max_width, 0.05)
        self.assertTrue(e.low <= clean.low and clean.high <= e.high, (e.low, e.high, clean.value))

    def test_perturbed_vector_widens_the_bound_but_keeps_the_truth(self):
        """A vector mixed with 1e-4 of the next eigenvector: residual ≈ 1e-4·gap, width ≈ 1e-4, truth still inside."""
        r = Rotor.transmon(0.3, 15.0, n_g=0.25)
        clean = ME.guaranteed_matrix_element(r, 0, 1, "n")
        original = ME._vectors

        def mixed(rot, N, k):
            vs = original(rot, N, k)
            v0, v1 = vs[0], vs[1]
            vs[0] = {n: v0.get(n, Fraction(0)) + Fraction(1, 10 ** 4) * v1.get(n, Fraction(0)) for n in set(v0) | set(v1)}
            return vs
        ME._vectors = mixed
        try:
            e = ME.guaranteed_matrix_element(r, 0, 1, "n")
        finally:
            ME._vectors = original
        self.assertGreater(e.max_width, 1e-5)
        self.assertLess(e.max_width, 1e-2)
        self.assertTrue(e.low <= clean.low and clean.high <= e.high)

    def test_closed_inputs(self):
        r = Rotor.transmon(0.3, 15.0, n_g=0.25)
        for args, kw in ((("x", 0, 1), {}), ((r, -1, 1), {}), ((r, 0, 1.5), {}), ((r, True, 1), {}), ((r, 0, ME.K_MAX), {}),
                         ((r, 0, 1, "x"), {}), ((r, 0, 1, "cos", 0), {}), ((r, 0, 1, "cos", 1.5), {}), ((r, 0, 1, "n", 1, 2), {}),
                         ((r, 0, 1, "n", 1, ME.K_MAX + 1), {}), ((Rotor(0.3, {1: -15.0}, {1: 1.0}), 0, 1), {})):
            with self.assertRaises(ME.OutOfDomain, msg=str(args)):
                ME.guaranteed_matrix_element(*args, **kw)

    def test_deadline(self):
        from rigorous_levels import DeadlineExceeded
        with self.assertRaises(DeadlineExceeded):
            ME.guaranteed_matrix_element(Rotor.transmon(0.01, 50000.0), 0, 1, "n", deadline=1e-6)


if __name__ == "__main__":
    unittest.main()
