# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Test di qraft_ra/scqubits_adapter.py, rule "scq-threshold/1.0" (11/11/2026). Specifica e PREREG in
note dell'autore (non pubblicate). Ogni test deve poter fallire: controlli positivi sulla formula e sui rami."""
import importlib.util
import shutil
import subprocess
import unittest

import numpy as np


from qraft_ra import scqubits_adapter as A  # noqa: E402
from qraft_ra.rotor_spectrum import Rotor  # noqa: E402

SCQ = importlib.util.find_spec("scqubits") is not None
FLINT = importlib.util.find_spec("flint") is not None


def _bwrap_funziona():
    """bwrap presente E capace di creare i namespace (stessa sonda di test_multiporta: su runner con userns non
    privilegiati negati bwrap esiste ma fallisce, e i test della sandbox vanno SALTATI con questo reason)."""
    if shutil.which("bwrap") is None:
        return False
    try:
        return subprocess.run(["bwrap", "--unshare-all", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
                               "true"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


BWRAP = _bwrap_funziona()


class mock_nostro:
    """Sostituisce il nostro solutore con un risultato fisso (state OK)."""
    def __init__(self, mod, energies):
        self.mod, self.energies = mod, energies

    def __enter__(self):
        from types import SimpleNamespace
        self.orig = self.mod._our_spectrum
        self.mod._our_spectrum = lambda r, k, tol: SimpleNamespace(state=A.OK, energies=self.energies, nmax=1)

    def __exit__(self, *a):
        self.mod._our_spectrum = self.orig


def transmon(ec=0.3, ej=15.0, ng=0.25, f=1.0):
    return Rotor(E_C=ec * f, cosines=((1, -ej * f),), n_g=ng)


class TestRegola(unittest.TestCase):
    def test_norma_H_gershgorin(self):
        """‖H(n)‖₂ ≤ 4E_C(n+|n_g|)² + E_J: confronto con la norma spettrale vera della tridiagonale (deve maggiorare)
        e crescita con |n_g| (n_g = 0,5 ≥ n_g = 0)."""
        for ec, ej, ng, n in ((0.3, 15.0, 0.0, 10), (0.3, 15.0, 0.5, 10), (1.0, 1e6, 0.25, 128), (0.2, 2.3, -0.5, 5)):
            m = np.arange(-n, n + 1)
            H = np.diag(4 * ec * (m - ng) ** 2) - 0.5 * ej * (np.eye(2 * n + 1, k=1) + np.eye(2 * n + 1, k=-1))
            vera = np.linalg.norm(H, 2)
            self.assertGreaterEqual(A.norm_H(ec, ej, ng, n), vera * (1 - 1e-12), (ec, ej, ng, n))
            self.assertLessEqual(A.norm_H(ec, ej, ng, n), 2 * vera + ej)        # non assurdamente larga
        self.assertGreaterEqual(A.norm_H(0.3, 15.0, 0.5, 10), A.norm_H(0.3, 15.0, 0.0, 10))
        self.assertEqual(A.norm_H(0.3, 15.0, -0.5, 10), A.norm_H(0.3, 15.0, 0.5, 10))

    def test_formula_soglia(self):
        """Specifica §2 ricalcolata a mano: absolute quando la relative è più grande, relative quando è più piccola,
        user quando tol è data, floor quando tutto sta sotto il rumore float."""
        E2 = np.array([0.0, 5.0, 10.0, 20.0])              # scala 20 GHz → relative 2e-5 > absolute 1e-6
        s, o, pav = A.threshold_rule(E2, 0.3, 15.0, 0.25, 15, None, "GHz")
        self.assertEqual((s, o), (1e-6, "absolute"))
        atteso = 32 * 2 ** -52 * (A.norm_H(0.3, 15.0, 0.25, 15) + A.norm_H(0.3, 15.0, 0.25, 30))
        self.assertLess(abs(pav - atteso), 1e-12 * atteso)        # relativo: con assertAlmostEqual a 7 cifre 1e-11 ≈ 0 passava sempre (mutante 32 → 1 vivo)
        self.assertGreater(pav, 2 ** -52 * (A.norm_H(0.3, 15.0, 0.25, 15) + A.norm_H(0.3, 15.0, 0.25, 30)) * 31)
        E2 = np.array([0.0, 0.1, 0.2, 0.3])                # scala 0,3 → relative 3e-7 < absolute
        s, o, _ = A.threshold_rule(E2, 0.3, 15.0, 0.25, 15, None, "GHz")
        self.assertEqual(o, "relative")
        self.assertAlmostEqual(s, 3e-7)
        s, o, _ = A.threshold_rule(E2, 0.3, 15.0, 0.25, 15, 2e-3, "GHz")
        self.assertEqual((s, o), (2e-3, "user"))
        # floor: tol dell'user sotto il rumore
        s, o, pav = A.threshold_rule(E2, 0.3, 15.0, 0.25, 15, 1e-20, "GHz")
        self.assertEqual((s, o), (pav, "floor"))
        # k = 1: niente relative
        s, o, _ = A.threshold_rule(np.array([3.0]), 0.3, 15.0, 0.25, 15, None, "GHz")
        self.assertEqual((s, o), (1e-6, "absolute"))
        # unità: l'absolute è convertita (1e-6 GHz = 1e-3 MHz = 1e3 Hz)
        self.assertEqual(A.threshold_rule(np.array([0.0, 5e3, 20e3]), 300.0, 15e3, 0.25, 15, None, "MHz")[:2], (1e-3, "absolute"))
        self.assertEqual(A.threshold_rule(np.array([0.0, 5e9, 20e9]), 3e8, 15e9, 0.25, 15, None, "Hz")[:2], (1e3, "absolute"))

    def test_verdetto_rami(self):
        E = np.array([0.0, 5.0, 10.0])
        E2 = E + np.array([0.0, 0.0, 5e-7])                 # err 5e-7 ≤ 1e-6 → OK absolute
        err, s, o, pav, st = A._verdict(E, E2, 0.3, 15.0, 0.25, 15, None, "GHz")
        self.assertEqual((o, st), ("absolute", A.OK))
        self.assertAlmostEqual(err, 5e-7)
        E2 = E + np.array([0.0, 0.0, 2e-6])                 # err 2e-6 > 1e-6 → NOT_CONVERGED
        self.assertEqual(A._verdict(E, E2, 0.3, 15.0, 0.25, 15, None, "GHz")[4], A.NOT_CONVERGED)
        E2 = E + np.array([0.0, 0.0, 1.5e-6])               # appena sopra la threshold: NOT_CONVERGED (mutante err > 2s vivo)
        self.assertEqual(A._verdict(E, E2, 0.3, 15.0, 0.25, 15, None, "GHz")[4], A.NOT_CONVERGED)
        E2 = E + np.array([0.0, 0.0, 1e-6])                 # esattamente sulla threshold: OK (≤)
        self.assertEqual(A._verdict(E, E2, 0.3, 15.0, 0.25, 15, None, "GHz")[4], A.OK)
        E2 = E + 1e-15                                       # sotto il floor con tol minuscola → OK_FLOAT_FLOOR
        err, s, o, pav, st = A._verdict(E, E2, 0.3, 15.0, 0.25, 15, 1e-20, "GHz")
        self.assertEqual((o, st), ("floor", A.OK_FLOAT_FLOOR))
        self.assertLessEqual(err, s)
        # floor ma error sopra: NOT_CONVERGED, non OK_FLOAT_FLOOR
        E2 = E + 1e-9
        self.assertEqual(A._verdict(E, E2, 0.3, 15.0, 0.25, 15, 1e-20, "GHz")[4], A.NOT_CONVERGED)


@unittest.skipUnless(SCQ, "scqubits assente")
class TestConScqubits(unittest.TestCase):
    def test_covarianza_unita(self):
        """M1 su 3 casi: stesso state e origine in GHz/MHz/Hz; err e threshold scalano col fattore."""
        for ec, ej, ng, ncut in ((0.3, 15.0, 0.25, 15), (0.2, 2.3, 0.0, 5), (0.25, 125.0, 0.5, 15)):
            base = A.scqubits_spectrum(transmon(ec, ej, ng), 6, ncut, unit="GHz")
            for u, f in (("MHz", 1e3), ("Hz", 1e9)):
                s = A.scqubits_spectrum(transmon(ec, ej, ng, f), 6, ncut, unit=u)
                self.assertEqual((s.state, s.threshold_origin), (base.state, base.threshold_origin), (ec, ej, ng, ncut, u))
                self.assertLess(abs(s.threshold / f - base.threshold), 1e-9 * base.threshold)
                self.assertLess(abs(s.floor / f - base.floor), 1e-9 * base.floor)
                self.assertEqual(s.unit, u)
            self.assertEqual(base.rule, "scq-threshold/1.0")

    def test_non_convergente_e_auto(self):
        s = A.scqubits_spectrum(transmon(0.3, 150.0, 0.5), 6, 5)       # E_J/E_C = 500, ncut 5: sbagliato
        self.assertEqual(s.state, A.NOT_CONVERGED)
        a = A.scqubits_spectrum(transmon(0.3, 150.0, 0.5), 6, 5, check="auto")
        self.assertEqual(a.state, A.OK)
        self.assertGreaterEqual(a.ncut, 20)
        self.assertIn(a.threshold_origin, ("absolute", "relative"))
        lim = A.scqubits_spectrum(transmon(), 6, 15, tol=1e-20, check="auto")
        self.assertEqual((lim.state, lim.threshold_origin), (A.OK_FLOAT_FLOOR, "floor"))
        n = A.scqubits_spectrum(transmon(), 6, 15, check="none")
        self.assertEqual((n.state, n.threshold_origin, n.floor), (A.UNCHECKED, None, None))

    def test_riferimento_a_due_ncut(self):
        """Specifica: il riferimento del doubling è 2·ncut (non ncut+1: mutante vivo); «auto» raddoppia."""
        orig = A._eigenvalues
        chiamate = []

        def spia(sq, ec, ej, ng, ncut, k):
            chiamate.append(ncut)
            return orig(sq, ec, ej, ng, ncut, k)
        A._eigenvalues = spia
        try:
            A.scqubits_spectrum(transmon(), 6, 15)
            self.assertEqual(chiamate, [15, 30])
            chiamate.clear()
            A.scqubits_spectrum(transmon(0.3, 150.0, 0.5), 6, 5, check="auto")
            self.assertEqual(chiamate[:3], [5, 10, 20])
        finally:
            A._eigenvalues = orig

    def test_sandbox_uscita_non_ok(self):
        """Se la port risponde ERROR/INVALID l'adattatore non dà numeri (mutante vivo: check tolto)."""
        from qraft_ra import multiport as MP
        orig = MP.run_port
        MP.run_port = lambda r: MP.Output(r.port, "", (), r.unit, "ERROR", "finto", 0.0, "")
        try:
            with self.assertRaises(A.ScqubitsMissing):
                A.scqubits_spectrum(transmon(), 6, 15, engine="sandbox")
        finally:
            MP.run_port = orig

    def test_sandbox_unita_diversa_rifiutata(self):
        """NEMESIS 11/11: una port che risponde in MHz a una request in GHz non dà numeri (prima: energies ×1e3, OK)."""
        from qraft_ra import multiport as MP
        orig = MP.run_port
        MP.run_port = lambda r: MP.Output(r.port, "x", tuple(1e3 * i for i in range(r.levels)), "MHz", "OK", "", 0.0, "")
        try:
            with self.assertRaises(A.ScqubitsMissing):
                A.scqubits_spectrum(transmon(), 6, 15, engine="sandbox")
            MP.run_port = lambda r: MP.Output(r.port, "x", tuple(float(i) for i in range(r.levels)), "GHz", "OK", "", 0.0, "")
            self.assertEqual(len(A.scqubits_spectrum(transmon(), 6, 15, engine="sandbox").energies), 6)   # check positivo
        finally:
            MP.run_port = orig

    def test_confini_k_relativa_limite_e_confronta(self):
        """NEMESIS 11/11, mutanti vivi A1-A4: k = 2·ncut+1 è ammesso; con k = 2 decide la relative; a ncut = NCUT_LIMIT/2
        il doubling a NCUT_LIMIT si fa; compare accetta OK_FLOAT_FLOOR."""
        s = A.scqubits_spectrum(transmon(), 7, 3)                                   # k = dimensione: ammesso
        self.assertEqual(len(s.energies), 7)
        E2 = np.array([0.0, 0.3])                                                   # k = 2, scala 0,3 → relative 3e-7
        self.assertEqual(A.threshold_rule(E2, 0.3, 15.0, 0.25, 15, None, "GHz")[1], "relative")
        orig = A._eigenvalues
        chiamate = []

        def spia(sq, ec, ej, ng, ncut, k):
            chiamate.append(ncut)
            return orig(sq, ec, ej, ng, ncut, k)
        A._eigenvalues = spia
        try:
            A.scqubits_spectrum(transmon(), 6, A.NCUT_LIMIT // 2, check="auto", tol=1e-30)
            self.assertIn(A.NCUT_LIMIT, chiamate)
        finally:
            A._eigenvalues = orig
        finto = A.ScqubitsSpectrum((0.0, 1.0), 0.0, 1e-8, 30, A.OK_FLOAT_FLOOR, "x", "floor", 1e-8)
        orig_s = A.scqubits_spectrum
        A.scqubits_spectrum = lambda *a, **k: finto
        try:
            with mock_nostro(A, (0.0, 1.0)):
                self.assertEqual(A.compare(transmon(), 2)["state"], A.OK)
        finally:
            A.scqubits_spectrum = orig_s

    def test_ingressi_chiusi(self):
        r = transmon()
        for kw in (dict(unit="eV"), dict(unit=1), dict(engine="rete"), dict(check="x"), dict(tol=0.0),
                   dict(tol=float("nan")), dict(k=0), dict(k=True), dict(ncut=0), dict(seconds=0), dict(k=50, ncut=10)):
            with self.assertRaises(A.InputRejected, msg=str(kw)):
                A.scqubits_spectrum(r, **{**dict(k=6, ncut=15), **kw})
        with self.assertRaises(A.InputRejected):
            A.scqubits_spectrum(Rotor(E_C=0.3, cosines=((2, -1.0),)), 6, 15)
        with self.assertRaises(A.InputRejected):
            A.scqubits_spectrum(Rotor(E_C=0.3, cosines=((1, 15.0),)), 6, 15)          # E_J < 0

    def test_confronta_propaga_origine(self):
        if not FLINT:
            self.skipTest("flint assente")
        c = A.compare(transmon(), 4)
        self.assertEqual(c["state"], A.OK)
        self.assertIn(c["threshold_origin"], A.ORIGINS)
        self.assertLess(c["absolute_shift"], 1e-9)

    @unittest.skipUnless(BWRAP, "bwrap assente")
    def test_sandbox_uguale_processo(self):
        """S: stessi bit e stesso verdetto fra engine sandbox e process; senza bwrap nessun numero."""
        for ec, ej, ng in ((0.3, 15.0, 0.25), (0.25, 125.0, 0.5)):
            p = A.scqubits_spectrum(transmon(ec, ej, ng), 6, 15)
            s = A.scqubits_spectrum(transmon(ec, ej, ng), 6, 15, engine="sandbox")
            self.assertEqual(s.energies, p.energies)
            self.assertEqual((s.state, s.threshold_origin, s.error, s.threshold), (p.state, p.threshold_origin, p.error, p.threshold))
            self.assertIn("sandbox", s.engine)
        from qraft_ra import isolation
        orig, probes = isolation.shutil.which, dict(isolation._PROBES)
        isolation.shutil.which = lambda name: None          # every engine's executable missing: no number
        isolation._PROBES.clear()
        try:
            with self.assertRaises((A.ScqubitsMissing, isolation.SandboxMissing)):
                A.scqubits_spectrum(transmon(), 6, 15, engine="sandbox")
        finally:
            isolation.shutil.which = orig
            isolation._PROBES.update(probes)


if __name__ == "__main__":
    unittest.main()
