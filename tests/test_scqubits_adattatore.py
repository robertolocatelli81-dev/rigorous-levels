# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Test di qraft_ra/scqubits_adattatore.py, regola "soglia-scq/1.0" (11/11/2026). Specifica e PREREG in
note dell'autore (non pubblicate). Ogni test deve poter fallire: controlli positivi sulla formula e sui rami."""
import importlib.util
import shutil
import unittest

import numpy as np


from qraft_ra import scqubits_adattatore as A  # noqa: E402
from qraft_ra.rotore_spettro import Rotore  # noqa: E402

SCQ = importlib.util.find_spec("scqubits") is not None
BWRAP = shutil.which("bwrap") is not None
FLINT = importlib.util.find_spec("flint") is not None


class mock_nostro:
    """Sostituisce il nostro solutore con un risultato fisso (stato OK)."""
    def __init__(self, mod, energie):
        self.mod, self.energie = mod, energie

    def __enter__(self):
        from types import SimpleNamespace
        self.orig = self.mod._spettro_nostro
        self.mod._spettro_nostro = lambda r, k, tol: SimpleNamespace(stato=A.OK, energie=self.energie, nmax=1)

    def __exit__(self, *a):
        self.mod._spettro_nostro = self.orig


def transmon(ec=0.3, ej=15.0, ng=0.25, f=1.0):
    return Rotore(E_C=ec * f, coseni=((1, -ej * f),), n_g=ng)


class TestRegola(unittest.TestCase):
    def test_norma_H_gershgorin(self):
        """‖H(n)‖₂ ≤ 4E_C(n+|n_g|)² + E_J: confronto con la norma spettrale vera della tridiagonale (deve maggiorare)
        e crescita con |n_g| (n_g = 0,5 ≥ n_g = 0)."""
        for ec, ej, ng, n in ((0.3, 15.0, 0.0, 10), (0.3, 15.0, 0.5, 10), (1.0, 1e6, 0.25, 128), (0.2, 2.3, -0.5, 5)):
            m = np.arange(-n, n + 1)
            H = np.diag(4 * ec * (m - ng) ** 2) - 0.5 * ej * (np.eye(2 * n + 1, k=1) + np.eye(2 * n + 1, k=-1))
            vera = np.linalg.norm(H, 2)
            self.assertGreaterEqual(A.norma_H(ec, ej, ng, n), vera * (1 - 1e-12), (ec, ej, ng, n))
            self.assertLessEqual(A.norma_H(ec, ej, ng, n), 2 * vera + ej)        # non assurdamente larga
        self.assertGreaterEqual(A.norma_H(0.3, 15.0, 0.5, 10), A.norma_H(0.3, 15.0, 0.0, 10))
        self.assertEqual(A.norma_H(0.3, 15.0, -0.5, 10), A.norma_H(0.3, 15.0, 0.5, 10))

    def test_formula_soglia(self):
        """Specifica §2 ricalcolata a mano: assoluta quando la relativa è più grande, relativa quando è più piccola,
        utente quando tol è data, pavimento quando tutto sta sotto il rumore float."""
        E2 = np.array([0.0, 5.0, 10.0, 20.0])              # scala 20 GHz → relativa 2e-5 > assoluta 1e-6
        s, o, pav = A.soglia_regola(E2, 0.3, 15.0, 0.25, 15, None, "GHz")
        self.assertEqual((s, o), (1e-6, "assoluta"))
        atteso = 32 * 2 ** -52 * (A.norma_H(0.3, 15.0, 0.25, 15) + A.norma_H(0.3, 15.0, 0.25, 30))
        self.assertLess(abs(pav - atteso), 1e-12 * atteso)        # relativo: con assertAlmostEqual a 7 cifre 1e-11 ≈ 0 passava sempre (mutante 32 → 1 vivo)
        self.assertGreater(pav, 2 ** -52 * (A.norma_H(0.3, 15.0, 0.25, 15) + A.norma_H(0.3, 15.0, 0.25, 30)) * 31)
        E2 = np.array([0.0, 0.1, 0.2, 0.3])                # scala 0,3 → relativa 3e-7 < assoluta
        s, o, _ = A.soglia_regola(E2, 0.3, 15.0, 0.25, 15, None, "GHz")
        self.assertEqual(o, "relativa")
        self.assertAlmostEqual(s, 3e-7)
        s, o, _ = A.soglia_regola(E2, 0.3, 15.0, 0.25, 15, 2e-3, "GHz")
        self.assertEqual((s, o), (2e-3, "utente"))
        # pavimento: tol dell'utente sotto il rumore
        s, o, pav = A.soglia_regola(E2, 0.3, 15.0, 0.25, 15, 1e-20, "GHz")
        self.assertEqual((s, o), (pav, "pavimento"))
        # k = 1: niente relativa
        s, o, _ = A.soglia_regola(np.array([3.0]), 0.3, 15.0, 0.25, 15, None, "GHz")
        self.assertEqual((s, o), (1e-6, "assoluta"))
        # unità: l'assoluta è convertita (1e-6 GHz = 1e-3 MHz = 1e3 Hz)
        self.assertEqual(A.soglia_regola(np.array([0.0, 5e3, 20e3]), 300.0, 15e3, 0.25, 15, None, "MHz")[:2], (1e-3, "assoluta"))
        self.assertEqual(A.soglia_regola(np.array([0.0, 5e9, 20e9]), 3e8, 15e9, 0.25, 15, None, "Hz")[:2], (1e3, "assoluta"))

    def test_verdetto_rami(self):
        E = np.array([0.0, 5.0, 10.0])
        E2 = E + np.array([0.0, 0.0, 5e-7])                 # err 5e-7 ≤ 1e-6 → OK assoluta
        err, s, o, pav, st = A._verdetto(E, E2, 0.3, 15.0, 0.25, 15, None, "GHz", "")
        self.assertEqual((o, st), ("assoluta", A.OK))
        self.assertAlmostEqual(err, 5e-7)
        E2 = E + np.array([0.0, 0.0, 2e-6])                 # err 2e-6 > 1e-6 → NON_CONVERGENTE
        self.assertEqual(A._verdetto(E, E2, 0.3, 15.0, 0.25, 15, None, "GHz", "")[4], A.NON_CONVERGENTE)
        E2 = E + np.array([0.0, 0.0, 1.5e-6])               # appena sopra la soglia: NON_CONVERGENTE (mutante err > 2s vivo)
        self.assertEqual(A._verdetto(E, E2, 0.3, 15.0, 0.25, 15, None, "GHz", "")[4], A.NON_CONVERGENTE)
        E2 = E + np.array([0.0, 0.0, 1e-6])                 # esattamente sulla soglia: OK (≤)
        self.assertEqual(A._verdetto(E, E2, 0.3, 15.0, 0.25, 15, None, "GHz", "")[4], A.OK)
        E2 = E + 1e-15                                       # sotto il pavimento con tol minuscola → OK_LIMITE_FLOAT
        err, s, o, pav, st = A._verdetto(E, E2, 0.3, 15.0, 0.25, 15, 1e-20, "GHz", "")
        self.assertEqual((o, st), ("pavimento", A.OK_LIMITE_FLOAT))
        self.assertLessEqual(err, s)
        # pavimento ma errore sopra: NON_CONVERGENTE, non OK_LIMITE_FLOAT
        E2 = E + 1e-9
        self.assertEqual(A._verdetto(E, E2, 0.3, 15.0, 0.25, 15, 1e-20, "GHz", "")[4], A.NON_CONVERGENTE)


@unittest.skipUnless(SCQ, "scqubits assente")
class TestConScqubits(unittest.TestCase):
    def test_covarianza_unita(self):
        """M1 su 3 casi: stesso stato e origine in GHz/MHz/Hz; err e soglia scalano col fattore."""
        for ec, ej, ng, ncut in ((0.3, 15.0, 0.25, 15), (0.2, 2.3, 0.0, 5), (0.25, 125.0, 0.5, 15)):
            base = A.spettro_scqubits(transmon(ec, ej, ng), 6, ncut, unita="GHz")
            for u, f in (("MHz", 1e3), ("Hz", 1e9)):
                s = A.spettro_scqubits(transmon(ec, ej, ng, f), 6, ncut, unita=u)
                self.assertEqual((s.stato, s.soglia_origine), (base.stato, base.soglia_origine), (ec, ej, ng, ncut, u))
                self.assertLess(abs(s.soglia / f - base.soglia), 1e-9 * base.soglia)
                self.assertLess(abs(s.pavimento / f - base.pavimento), 1e-9 * base.pavimento)
                self.assertEqual(s.unita, u)
            self.assertEqual(base.regola, "soglia-scq/1.0")

    def test_non_convergente_e_auto(self):
        s = A.spettro_scqubits(transmon(0.3, 150.0, 0.5), 6, 5)       # E_J/E_C = 500, ncut 5: sbagliato
        self.assertEqual(s.stato, A.NON_CONVERGENTE)
        a = A.spettro_scqubits(transmon(0.3, 150.0, 0.5), 6, 5, controllo="auto")
        self.assertEqual(a.stato, A.OK)
        self.assertGreaterEqual(a.ncut, 20)
        self.assertIn(a.soglia_origine, ("assoluta", "relativa"))
        lim = A.spettro_scqubits(transmon(), 6, 15, tol=1e-20, controllo="auto")
        self.assertEqual((lim.stato, lim.soglia_origine), (A.OK_LIMITE_FLOAT, "pavimento"))
        n = A.spettro_scqubits(transmon(), 6, 15, controllo="nessuno")
        self.assertEqual((n.stato, n.soglia_origine, n.pavimento), (A.NON_CONTROLLATO, None, None))

    def test_riferimento_a_due_ncut(self):
        """Specifica: il riferimento del raddoppio è 2·ncut (non ncut+1: mutante vivo); «auto» raddoppia."""
        orig = A._autovalori
        chiamate = []

        def spia(sq, ec, ej, ng, ncut, k):
            chiamate.append(ncut)
            return orig(sq, ec, ej, ng, ncut, k)
        A._autovalori = spia
        try:
            A.spettro_scqubits(transmon(), 6, 15)
            self.assertEqual(chiamate, [15, 30])
            chiamate.clear()
            A.spettro_scqubits(transmon(0.3, 150.0, 0.5), 6, 5, controllo="auto")
            self.assertEqual(chiamate[:3], [5, 10, 20])
        finally:
            A._autovalori = orig

    def test_sandbox_uscita_non_ok(self):
        """Se la porta risponde ERRORE/NON_VALIDA l'adattatore non dà numeri (mutante vivo: controllo tolto)."""
        from qraft_ra import multiporta as MP
        orig = MP.esegui_porta
        MP.esegui_porta = lambda r: MP.Uscita(r.porta, "", (), r.unita, "ERRORE", "finto", 0.0, "")
        try:
            with self.assertRaises(A.ScqubitsAssente):
                A.spettro_scqubits(transmon(), 6, 15, motore="sandbox")
        finally:
            MP.esegui_porta = orig

    def test_sandbox_unita_diversa_rifiutata(self):
        """NEMESIS 11/11: una porta che risponde in MHz a una richiesta in GHz non dà numeri (prima: energie ×1e3, OK)."""
        from qraft_ra import multiporta as MP
        orig = MP.esegui_porta
        MP.esegui_porta = lambda r: MP.Uscita(r.porta, "x", tuple(1e3 * i for i in range(r.livelli)), "MHz", "OK", "", 0.0, "")
        try:
            with self.assertRaises(A.ScqubitsAssente):
                A.spettro_scqubits(transmon(), 6, 15, motore="sandbox")
            MP.esegui_porta = lambda r: MP.Uscita(r.porta, "x", tuple(float(i) for i in range(r.livelli)), "GHz", "OK", "", 0.0, "")
            self.assertEqual(len(A.spettro_scqubits(transmon(), 6, 15, motore="sandbox").energie), 6)   # controllo positivo
        finally:
            MP.esegui_porta = orig

    def test_confini_k_relativa_limite_e_confronta(self):
        """NEMESIS 11/11, mutanti vivi A1-A4: k = 2·ncut+1 è ammesso; con k = 2 decide la relativa; a ncut = NCUT_LIMITE/2
        il raddoppio a NCUT_LIMITE si fa; confronta accetta OK_LIMITE_FLOAT."""
        s = A.spettro_scqubits(transmon(), 7, 3)                                   # k = dimensione: ammesso
        self.assertEqual(len(s.energie), 7)
        E2 = np.array([0.0, 0.3])                                                   # k = 2, scala 0,3 → relativa 3e-7
        self.assertEqual(A.soglia_regola(E2, 0.3, 15.0, 0.25, 15, None, "GHz")[1], "relativa")
        orig = A._autovalori
        chiamate = []

        def spia(sq, ec, ej, ng, ncut, k):
            chiamate.append(ncut)
            return orig(sq, ec, ej, ng, ncut, k)
        A._autovalori = spia
        try:
            A.spettro_scqubits(transmon(), 6, A.NCUT_LIMITE // 2, controllo="auto", tol=1e-30)
            self.assertIn(A.NCUT_LIMITE, chiamate)
        finally:
            A._autovalori = orig
        finto = A.SpettroScq((0.0, 1.0), 0.0, 1e-8, 30, A.OK_LIMITE_FLOAT, "x", "pavimento", 1e-8)
        orig_s = A.spettro_scqubits
        A.spettro_scqubits = lambda *a, **k: finto
        try:
            with mock_nostro(A, (0.0, 1.0)):
                self.assertEqual(A.confronta(transmon(), 2)["stato"], A.OK)
        finally:
            A.spettro_scqubits = orig_s

    def test_ingressi_chiusi(self):
        r = transmon()
        for kw in (dict(unita="eV"), dict(unita=1), dict(motore="rete"), dict(controllo="x"), dict(tol=0.0),
                   dict(tol=float("nan")), dict(k=0), dict(k=True), dict(ncut=0), dict(secondi=0), dict(k=50, ncut=10)):
            with self.assertRaises(A.IngressoRifiutato, msg=str(kw)):
                A.spettro_scqubits(r, **{**dict(k=6, ncut=15), **kw})
        with self.assertRaises(A.IngressoRifiutato):
            A.spettro_scqubits(Rotore(E_C=0.3, coseni=((2, -1.0),)), 6, 15)
        with self.assertRaises(A.IngressoRifiutato):
            A.spettro_scqubits(Rotore(E_C=0.3, coseni=((1, 15.0),)), 6, 15)          # E_J < 0

    def test_confronta_propaga_origine(self):
        if not FLINT:
            self.skipTest("flint assente")
        c = A.confronta(transmon(), 4)
        self.assertEqual(c["stato"], A.OK)
        self.assertIn(c["soglia_origine"], A.ORIGINI)
        self.assertLess(c["scarto_assoluto"], 1e-9)

    @unittest.skipUnless(BWRAP, "bwrap assente")
    def test_sandbox_uguale_processo(self):
        """S: stessi bit e stesso verdetto fra motore sandbox e processo; senza bwrap nessun numero."""
        for ec, ej, ng in ((0.3, 15.0, 0.25), (0.25, 125.0, 0.5)):
            p = A.spettro_scqubits(transmon(ec, ej, ng), 6, 15)
            s = A.spettro_scqubits(transmon(ec, ej, ng), 6, 15, motore="sandbox")
            self.assertEqual(s.energie, p.energie)
            self.assertEqual((s.stato, s.soglia_origine, s.errore, s.soglia), (p.stato, p.soglia_origine, p.errore, p.soglia))
            self.assertIn("sandbox", s.motore)
        from qraft_ra import multiporta as MP
        orig = MP.shutil.which
        MP.shutil.which = lambda nome: None
        try:
            with self.assertRaises((A.ScqubitsAssente, MP.SandboxAssente)):
                A.spettro_scqubits(transmon(), 6, 15, motore="sandbox")
        finally:
            MP.shutil.which = orig


if __name__ == "__main__":
    unittest.main()
