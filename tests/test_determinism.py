# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Determinism of the guaranteed intervals (0.3.0, 2026-11-12): the ends must depend only on the inputs, the package
and python-flint, never on the CPU or the BLAS/LAPACK kernel.

Before this change the float estimates came from numpy/scipy (eigvalsh, eig_banded, eigvalsh_tridiagonal) and the
fluxonium intervals were centred on them: `reproduce --hash` changed with OPENBLAS_CORETYPE (Haswell, Prescott,
Nehalem) and between CI machines. These tests
  - fix the exact strings of one enclosure per guaranteed module (they failed on the previous code under
    OPENBLAS_CORETYPE=Prescott: the fluxonium entry);
  - make every numpy/scipy eigen-solver raise and check that no guaranteed entry point calls one;
  - check the deterministic estimators against numpy on seeded inputs (accuracy, not identity)."""
import hashlib
import importlib.util
import random
import unittest
from unittest import mock

FLINT = importlib.util.find_spec("flint") is not None

# sha256 (first 16 hex) of the exact strings of each entry of reproduce.determinism_parts(), python-flint 0.9.0,
# measured 2026-11-12 on Python 3.11–3.14 with OPENBLAS_CORETYPE Haswell, Prescott, Nehalem and the default.
EXPECTED = {
    "transmon": "6537d65da09e",
    "sphere": "39dbed32be42",
    "mathieu": "ae89a27d5520",
    "fluxonium": "8a0a87d46568",
    "box": "3f1124812a13",
    "matrix element n": "486a8c3d8764",
    "rotor cos 2phi": "2af5fc5bf2e1",
    "matrix element cos": "5fb719004574",
    "hyperfine": "7e6bdc60f0e8",
}
FLINT_VERSION = "0.9.0"


def _flint_version():
    import flint
    return getattr(flint, "__version__", "?")


@unittest.skipUnless(FLINT, "python-flint absent")
class TestFixedStrings(unittest.TestCase):
    def test_parts_equal_the_measured_strings(self):
        """Each guaranteed module gives the exact strings measured on every kernel (python-flint 0.9.0 only: another
        version of Arb may round a radius differently, which is allowed by the goal and skipped here with the reason)."""
        if _flint_version() != FLINT_VERSION:
            self.skipTest(f"python-flint {_flint_version()}: the fixed strings are for {FLINT_VERSION}")
        from qraft_ra.reproduce import determinism_parts
        got = {name: hashlib.sha256("\n".join(ss).encode()).hexdigest()[:12] for name, ss in determinism_parts()}
        self.assertEqual(got, EXPECTED)

    def test_fluxonium_ends_exact(self):
        """The fluxonium entry spelled out: the first level of the hash case, ends as exact decimal strings."""
        if _flint_version() != FLINT_VERSION:
            self.skipTest(f"python-flint {_flint_version()}: the fixed strings are for {FLINT_VERSION}")
        from qraft_ra import Fluxonium, guaranteed_fluxonium_levels
        iv = guaranteed_fluxonium_levels(Fluxonium(E_C=0.567, E_J=2.052, E_L=0.835, flux=0.5), 3, 1e-9)
        self.assertEqual((str(iv.low[0]), str(iv.high[0])), FLUXONIUM_0)


FLUXONIUM_0 = ("33641487192716065069672811/19342813113834066795298816",
               "33641487202387471626589845/19342813113834066795298816")


# computed in a fresh interpreter per BLAS kernel; written with the public API only, so that the same script also runs
# on the code before this change (where it printed different strings under Prescott and Nehalem)
SCRIPT = r"""
from qraft_ra import (Fluxonium, Rotor, SigmaMolecule, SphericalRotor, guaranteed_fluxonium_levels, guaranteed_levels,
                      guaranteed_matrix_element, guaranteed_molecule_levels, guaranteed_sphere_levels, mathieu_a)
out = []
out += [str(x) for x in guaranteed_fluxonium_levels(Fluxonium(E_C=0.567, E_J=2.052, E_L=0.835, flux=0.5), 3, 1e-9).low]
out += [str(x) for x in guaranteed_fluxonium_levels(Fluxonium(E_C=1.1, E_J=4.3, E_L=0.4, flux=0.31), 2, 1e-9).high]
out += [s for p in guaranteed_sphere_levels(SphericalRotor(B=3.7, dE=11.0, M=1), 3).strings for s in p]
out += [s for p in guaranteed_molecule_levels(SigmaMolecule(2, 1, B=1.3, c1=0.02, dE=0.8), 1, 3, 1e-11).strings for s in p]
out += [s for p in guaranteed_levels(Rotor(0.21, {1: -9.0, 2: 1.3, 3: -0.4}, n_g=0.17), 4, 1e-10).strings for s in p]
e = guaranteed_matrix_element(Rotor(0.3, {1: -11.0, 2: 0.5}, n_g=0.1), 0, 1, "cos", 1)
out += [str(e.low), str(e.high), str(mathieu_a(7, 313.5).low)]
print("\n".join(out))
"""


def _openblas_dynamic():
    """True if numpy runs on OpenBLAS with run-time kernel choice on x86-64 (there OPENBLAS_CORETYPE selects the
    kernel); elsewhere the variable does nothing and the cross-kernel test has nothing to compare."""
    import platform
    if platform.machine().lower() not in ("x86_64", "amd64"):
        return False
    try:
        import numpy as np
        cfg = np.show_config(mode="dicts")
        blas = cfg["Build Dependencies"]["blas"]
        return "openblas" in str(blas.get("name", "")).lower() and "DYNAMIC_ARCH" in str(blas.get("openblas configuration", ""))
    except Exception:
        return False


@unittest.skipUnless(FLINT, "python-flint absent")
class TestAcrossBlasKernels(unittest.TestCase):
    def test_same_strings_with_every_kernel(self):
        """The same guaranteed intervals with OPENBLAS_CORETYPE unset, Prescott (SSE3) and Nehalem (SSE4.2), each in a
        fresh interpreter. On the code before this change Prescott and Nehalem changed the fluxonium strings."""
        if not _openblas_dynamic():
            self.skipTest("numpy is not on a run-time-dispatched OpenBLAS on x86-64: OPENBLAS_CORETYPE has no effect here")
        import os
        import subprocess
        import sys
        outs = {}
        for core in (None, "Prescott", "Nehalem"):
            env = dict(os.environ)
            env.pop("OPENBLAS_CORETYPE", None)
            if core:
                env["OPENBLAS_CORETYPE"] = core
            r = subprocess.run([sys.executable, "-c", SCRIPT], env=env, capture_output=True, text=True, timeout=600)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            outs[core or "default"] = r.stdout
        self.assertGreater(len(outs["default"].splitlines()), 20)
        self.assertEqual(outs["Prescott"], outs["default"])
        self.assertEqual(outs["Nehalem"], outs["default"])


def _forbidden(*a, **k):
    raise AssertionError("a BLAS/LAPACK eigen-solver was called in a guaranteed path")


@unittest.skipUnless(FLINT, "python-flint absent")
class TestNoLapackInGuaranteedPaths(unittest.TestCase):
    def test_no_numpy_scipy_eigensolver(self):
        """numpy.linalg.eigvalsh/eigh/eig and scipy.linalg eigen-solvers raise: every guaranteed entry point still
        returns (negative control: the same patch makes a direct numpy call fail)."""
        import numpy as np
        import scipy.linalg as sl
        patches = [mock.patch.object(np.linalg, n, _forbidden) for n in ("eigvalsh", "eigh", "eig", "eigvals")]
        patches += [mock.patch.object(sl, n, _forbidden) for n in ("eigh", "eigvalsh", "eig_banded",
                                                                  "eigvalsh_tridiagonal", "eigh_tridiagonal", "eig")]
        for p in patches:
            p.start()
        try:
            with self.assertRaises(AssertionError):                       # negative control: the patch is live
                np.linalg.eigvalsh(np.eye(2))
            from qraft_ra.reproduce import determinism_parts
            names = [name for name, _ in determinism_parts()]
            self.assertEqual(names, list(EXPECTED))
        finally:
            for p in patches:
                p.stop()


class TestFloatDecisions(unittest.TestCase):
    """The float decisions outside the estimators: overflow is refused, φ_zpf and the fluxonium cuts are spelled out."""

    def test_overflowing_estimate_is_refused(self):
        from qraft_ra import _deterministic as D
        big = 1.7e308
        with self.assertRaises(OverflowError):                     # λ = 2·1.7e308 is beyond float64
            D.band_lowest([big, big], {1: [big]}, 2)
        with self.assertRaises(OverflowError):
            D.dense_lowest([[big, big], [big, big]], 2)
        got = D.band_lowest([1.0, 3.0], {1: [0.0]}, 2)                                   # positive control: finite
        self.assertLess(max(abs(got[0] - 1.0), abs(got[1] - 3.0)), 1e-15)

    def test_phi_zpf_and_cuts(self):
        from qraft_ra import fluxonium as F
        f = F.Fluxonium(E_C=1.0, E_J=1.0, E_L=0.01, flux=0.25)
        self.assertLess(abs(f.phi_zpf ** 4 - 200.0), 1e-12)
        seen = []

        class Stop(Exception):
            pass

        def spy(fl, f_, k, width, N, N2, dl):
            seen.append((N, N2))
            raise Stop

        if not FLINT:
            self.skipTest("python-flint absent")
        with mock.patch.object(F, "_attempt", spy):
            with self.assertRaises(Stop):
                F.guaranteed_fluxonium_levels(f, 2, 1e-6, N_initial=100)
            with self.assertRaises(Stop):
                F.guaranteed_fluxonium_levels(f, 2, 1e-6)
        phi2 = 200.0 ** 0.5
        self.assertEqual(seen[0], (100, int(2.5 * (phi2 * 100) ** 0.5) + 8))            # 102
        self.assertEqual(seen[1][0], int(6 * phi2) + 16)                                  # 100


class TestEstimators(unittest.TestCase):
    """The deterministic estimators agree with LAPACK to a few eps·‖A‖ (they choose points only; this guards the
    efficiency, not the proof), and give the same floats when called twice."""

    def test_against_numpy(self):
        import numpy as np
        from qraft_ra import _deterministic as D
        rng = random.Random(20261112)
        for _ in range(40):
            n = rng.randint(3, 60)
            A = [[0.0] * n for _ in range(n)]
            for i in range(n):
                A[i][i] = rng.uniform(-5, 5) + i
                for j in range(i):
                    A[i][j] = A[j][i] = rng.gauss(0, 1)
            k = min(5, n)
            ref = np.linalg.eigvalsh(np.array(A))[:k]
            got = D.dense_lowest(A, k)
            scale = float(np.abs(np.array(A)).sum(axis=1).max())
            self.assertLess(max(abs(a - b) for a, b in zip(got, ref)), 64 * 2.2e-16 * n * scale)
            self.assertEqual(got, D.dense_lowest(A, k))
            d = [A[i][i] for i in range(n)]
            e = [rng.gauss(0, 2) for _ in range(n - 1)]
            T = np.diag(d) + np.diag(e, 1) + np.diag(e, -1)
            ref = np.linalg.eigvalsh(T)[:k]
            got = D.tridiagonal_lowest(d, [x * x for x in e], k)
            scale = float(np.abs(T).sum(axis=1).max())
            self.assertLess(max(abs(a - b) for a, b in zip(got, ref)), 64 * 2.2e-16 * n * scale)
            w = rng.randint(2, 4)
            bands = {m: [rng.gauss(0, 1) for _ in range(n - m)] for m in range(1, min(w, n - 1) + 1)}
            Bm = np.diag(d)
            for m, b in bands.items():
                Bm = Bm + np.diag(b, m) + np.diag(b, -m)
            ref = np.linalg.eigvalsh(Bm)[:k]
            got = D.band_lowest(d, bands, k)
            scale = float(np.abs(Bm).sum(axis=1).max())
            self.assertLess(max(abs(a - b) for a, b in zip(got, ref)), 1e3 * 2.2e-16 * n * scale)
            v = D.band_eigenvector(d, bands, got[0])
            big = max(range(n), key=lambda i: (abs(v[i]), -i))
            self.assertGreater(v[big], 0.0)                                  # sign convention: largest entry > 0
            r = Bm @ np.array(v) - got[0] * np.array(v)
            self.assertLess(float(np.linalg.norm(r)), 1e3 * 2.2e-16 * n * scale)

    def test_zero_pivot_counts_as_negative(self):
        """LAPACK dlaebz convention, fixed here so that it cannot change silently: a pivot of exactly 0 (|q| ≤ pivmin)
        is replaced by −pivmin, so the eigenvalue 0 of diag(0, 5) counts as below x = 0; and the band count agrees."""
        from qraft_ra import _deterministic as D
        self.assertEqual(D.sturm_count([0.0, 5.0], [0.0], 0.0, D._pivmin([0.0])), 1)
        self.assertEqual(D.sturm_count([5.0, 0.0], [0.0], 0.0, D._pivmin([0.0])), 1)
        self.assertEqual(D.band_count([0.0, 5.0, 7.0], {2: [0.0]}, 2, 0.0, D.SAFMIN), 1)

    def test_first_index(self):
        from qraft_ra import _deterministic as D
        d = [float(i * i) for i in range(30)]
        e2 = [4.0] * 29
        self.assertEqual(D.tridiagonal_lowest(d, e2, 6, first=5), D.tridiagonal_lowest(d, e2, 6)[5:])


if __name__ == "__main__":
    unittest.main()
