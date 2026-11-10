# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Tests of qraft_ra.scqubits_adattatore.

The tests that call scqubits run only where it is installed; the absence tests simulate a missing scqubits with
sys.modules["scqubits"] = None and run everywhere. Identifiers and messages are in Italian, as in the code.
"""
import importlib.util
import math
import sys
import unittest
from unittest import mock

from qraft_ra import scqubits_adattatore as SA
from qraft_ra.rotore_spettro import NON_CONVERGENTE, OK, IngressoRifiutato, Rotore, spettro

SCQ = importlib.util.find_spec("scqubits") is not None


class TestAssenza(unittest.TestCase):
    def test_assente_lo_dice(self):
        with mock.patch.dict(sys.modules, {"scqubits": None}):
            d = SA.disponibile()
            self.assertFalse(d["presente"])
            self.assertIn("scqubits non installato", d["motivo"])
            with self.assertRaises(SA.ScqubitsAssente):
                SA.spettro_scqubits(Rotore.transmon(0.2, 10.0), 6)


class TestDominio(unittest.TestCase):
    def test_rifiuti(self):
        casi = [Rotore.kite(0.05, 7.0), Rotore(1.0, {1: -5.0}, {1: 0.1}), Rotore(1.0, {1: 5.0}),
                Rotore(1.0, {1: -5.0, 2: 1.0}), Rotore(1.0, {2: -5.0}), Rotore(1.0, {}), "transmon", None,
                Rotore(1.0, {1: 0.0}), Rotore(1.0, {1: -0.0})]          # E_J = 0 outside the domain
        for r in casi:
            with self.assertRaises(IngressoRifiutato, msg=repr(r)):
                SA.spettro_scqubits(r, 6)
        r = Rotore.transmon(1.0, 5.0)
        for kw in ({"k": 0}, {"k": True}, {"k": 2.0}, {"ncut": 0}, {"ncut": True}, {"ncut": 1, "k": 6},
                   {"controllo": "boh"}, {"tol": 0.0}, {"tol": -1.0}, {"tol": float("nan")},
                   {"tol": float("inf")}, {"tol": "1e-9"}):
            with self.assertRaises(IngressoRifiutato, msg=repr(kw)):
                SA.spettro_scqubits(r, **kw)


@unittest.skipUnless(SCQ, "scqubits non installato in questo Python")
class TestScqubits(unittest.TestCase):
    def test_soglia_e_quella_del_banco(self):
        # la soglia dell'avviso è la stessa della definizione di «sbagliato» (1e-6 · max(1, massima
        # transizione a 2·ncut)); qui ncut=30 non basta, quindi le transizioni a ncut e a 2·ncut differiscono
        import numpy as np
        import scqubits as sq
        self.assertEqual(SA.SOGLIA_RELATIVA, 1e-6)
        s = SA.spettro_scqubits(Rotore.transmon(1.0, 1e5, 0.3), 6, 30)
        E2 = np.asarray(sq.Transmon(EJ=1e5, EC=1.0, ng=0.3, ncut=60, truncated_dim=6).eigenvals(evals_count=6))
        E1 = np.array(s.energie)
        self.assertNotEqual(max(np.diff(E1)), max(np.diff(E2)))
        self.assertEqual(s.soglia, 1e-6 * max(1.0, float(np.max(np.diff(E2)))))

    def test_errore_uguale_alla_soglia_e_ok(self):
        # «NON_CONVERGENTE se SUPERA la soglia»: errore == soglia è OK
        r = Rotore.transmon(1.0, 20000.0, 0.3)
        e = SA.spettro_scqubits(r, 6, 30).errore
        self.assertEqual(SA.spettro_scqubits(r, 6, 30, tol=e).stato, OK)
        self.assertEqual(SA.spettro_scqubits(r, 6, 30, tol=e * (1 - 1e-12)).stato, NON_CONVERGENTE)

    def test_confini_di_ncut(self):
        # k = 2·ncut+1 ammesso (base piena), k = 2·ncut+2 rifiutato; auto a ncut=960 calcola a 1920
        r = Rotore.transmon(1.0, 10.0, 0.3)
        self.assertEqual(len(SA.spettro_scqubits(r, 7, 3).energie), 7)
        with self.assertRaises(IngressoRifiutato):
            SA.spettro_scqubits(r, 8, 3)
        s = SA.spettro_scqubits(r, 6, SA.NCUT_LIMITE // 2, controllo="auto")
        self.assertEqual((s.stato, s.ncut), (OK, SA.NCUT_LIMITE))

    def test_raddoppio_avvisa_dove_ncut30_non_basta(self):
        s = SA.spettro_scqubits(Rotore.transmon(1.0, 20000.0, 0.3), 6, 30)
        self.assertEqual(s.stato, NON_CONVERGENTE)
        self.assertGreater(s.errore, s.soglia)
        vero = spettro(Rotore.transmon(1.0, 20000.0, 0.3), 6, 1e-6).energie
        self.assertGreater(max(abs(a - b) for a, b in zip(s.energie, vero)), s.errore * 0.999)

    def test_raddoppio_tace_dove_ncut30_basta(self):
        s = SA.spettro_scqubits(Rotore.transmon(0.2, 50.0, 0.1), 6, 30)
        self.assertEqual(s.stato, OK)
        self.assertLessEqual(s.errore, s.soglia)
        self.assertEqual(s.ncut, 30)

    def test_nessuno_non_controllato(self):
        s = SA.spettro_scqubits(Rotore.transmon(1.0, 20000.0), 6, 30, controllo="nessuno")
        self.assertEqual(s.stato, SA.NON_CONTROLLATO)
        self.assertIsNone(s.errore)

    def test_auto_converge_e_coincide(self):
        r = Rotore.transmon(1.0, 20000.0, 0.3)
        s = SA.spettro_scqubits(r, 6, 30, controllo="auto", tol=1e-9)
        self.assertEqual(s.stato, OK)
        self.assertGreater(s.ncut, 30)
        vero = spettro(r, 6, 1e-9).energie
        self.assertLess(max(abs(a - b) for a, b in zip(s.energie, vero)), 1e-8)

    def test_auto_limite_non_convergente(self):
        with mock.patch.object(SA, "NCUT_LIMITE", 40):
            s = SA.spettro_scqubits(Rotore.transmon(1.0, 20000.0), 6, 30, controllo="auto")
        self.assertEqual(s.stato, NON_CONVERGENTE)
        self.assertTrue(math.isinf(s.errore))

    def test_auto_piu_raddoppi(self):
        r = Rotore.transmon(1.0, 1e6, 0.2)
        s = SA.spettro_scqubits(r, 6, 8, controllo="auto")
        self.assertEqual(s.stato, OK)
        self.assertGreaterEqual(s.ncut, 64)          # da 8 servono almeno tre raddoppi
        vero = SA.spettro_scqubits(r, 6, 300, controllo="nessuno").energie
        self.assertLess(max(abs(a - b) for a, b in zip(s.energie, vero)) / 2000.0, 1e-6)

    def test_tol_esplicita_sostituisce_la_soglia(self):
        r = Rotore.transmon(0.2, 50.0, 0.1)
        self.assertEqual(SA.spettro_scqubits(r, 6, 30).stato, OK)
        s = SA.spettro_scqubits(r, 6, 30, tol=1e-30)
        self.assertEqual(s.soglia, 1e-30)
        self.assertEqual(s.stato, NON_CONVERGENTE)

    def test_confronta_vede_uno_scarto(self):
        from qraft_ra.rotore_spettro import Spettro
        r = Rotore.transmon(0.099, 32.19, 0.25)
        b = spettro(r, 6, 1e-11)
        storto = Spettro(tuple(e + 1e-6 * j for j, e in enumerate(b.energie)), b.errore, b.pavimento, b.nmax, OK)
        with mock.patch.object(SA, "_spettro_nostro", return_value=storto):
            c = SA.confronta(r)
        self.assertAlmostEqual(c["scarto_transizioni"], 5e-6, delta=1e-9)

    def test_monotonia_rayleigh_ritz(self):
        for ej in (1.0, 100.0, 1e4, 1e5):
            a = SA.spettro_scqubits(Rotore.transmon(1.0, ej, 0.37), 6, 20, controllo="nessuno").energie
            b = SA.spettro_scqubits(Rotore.transmon(1.0, ej, 0.37), 6, 40, controllo="nessuno").energie
            for x, y in zip(a, b):
                self.assertGreaterEqual(x, y - 1e-9 * max(1.0, abs(y)))

    def test_confronta(self):
        c = SA.confronta(Rotore.transmon(0.099, 32.19, 0.25))
        self.assertEqual(c["stato"], OK)
        self.assertLess(c["scarto_transizioni"], 1e-9)
        c2 = SA.confronta(Rotore.transmon(0.099, 32.19, 0.25))
        self.assertEqual(c, c2)

    def test_confronta_vede_n_g_diverso(self):
        r = Rotore.transmon(0.3, 3.0, 0.25)
        a = SA.spettro_scqubits(r.con_n_g(0.26), 6, controllo="auto", tol=1e-10)
        b = spettro(r, 6, 1e-11)
        self.assertGreater(max(abs(x - y) for x, y in zip(a.energie, b.energie)), 1e-6)


def _percorsi(x, base=()):
    if isinstance(x, dict):
        yield base, x
        for k, v in x.items():
            yield from _percorsi(v, base + (k,))
    elif isinstance(x, list):
        yield base, x
        for i, v in enumerate(x):
            yield from _percorsi(v, base + (i,))
    else:
        yield base, x


def _metti(c, percorso, valore):
    d = c
    for p in percorso[:-1]:
        d = d[p]
    d[percorso[-1]] = valore


if __name__ == "__main__":
    unittest.main(verbosity=2)
