# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Tests of qraft_ra.rotore_spettro: closed input grammar and the convergence state.

Before the extraction the grammar of the rotor was exercised through the certificate tests; this file tests it
directly. Every malformed input must end in IngressoRifiutato, never in a number or in another exception.
"""
import math
import random
import unittest

import numpy as np

from qraft_ra.rotore_spettro import NON_CONVERGENTE, OK, IngressoRifiutato, Rotore, spettro

CATTIVI_NUMERO = [math.nan, math.inf, -math.inf, True, False, None, "1.0", [1.0], {}, 1 + 0j, np.nan, np.float64(np.inf)]
CATTIVE_ARMONICHE = [0, -1, 1.0, 1.5, True, "1", None, np.float64(2.0)]
CATTIVE_DISTINTE = [0, -1, 1.5, "1", None]   # never == a good harmonic: a dict would merge 1.0, True with 1


class TestIngressoChiuso(unittest.TestCase):
    def test_controllo_positivo(self):
        r = Rotore(0.2, {1: -10.0, 2: np.float64(0.5)}, {3: 0.1}, np.int64(0))
        self.assertEqual(r.coseni, ((1, -10.0), (2, 0.5)))
        self.assertEqual(spettro(Rotore.transmon(0.2, 10.0), 4).stato, OK)

    def test_numeri_cattivi_in_ogni_posizione(self):
        for x in CATTIVI_NUMERO:
            for costruisci in (lambda x: Rotore(x, {1: -1.0}), lambda x: Rotore(1.0, {1: x}),
                               lambda x: Rotore(1.0, {}, {1: x}), lambda x: Rotore(1.0, {1: -1.0}, n_g=x),
                               lambda x: Rotore.transmon(1.0, x), lambda x: Rotore.kite(1.0, 1.0, phi_ext=x)):
                with self.assertRaises(IngressoRifiutato, msg=repr(x)):
                    costruisci(x)

    def test_armoniche_cattive(self):
        for m in CATTIVE_ARMONICHE:
            for campo in ("coseni", "seni"):
                with self.assertRaises(IngressoRifiutato, msg=(campo, repr(m))):
                    Rotore(1.0, **{campo: {m: 1.0}})

    def test_contenitori_cattivi(self):
        for v in (5, "x", [1, 2], [(1,)], [(1, 2, 3)], object()):
            with self.assertRaises(IngressoRifiutato, msg=repr(v)):
                Rotore(1.0, v)

    def test_e_c_non_positiva(self):
        for ec in (0.0, -0.0, -1.0, -1e-300):
            with self.assertRaises(IngressoRifiutato):
                Rotore(ec, {1: -1.0})

    def test_k_e_tol_chiusi(self):
        r = Rotore.transmon(0.2, 10.0)
        for k in (0, -1, 1.0, True, "6", None):
            with self.assertRaises(IngressoRifiutato, msg=repr(k)):
                spettro(r, k)
        for t in (0.0, -1e-9, math.nan, math.inf, True, "1e-9", None):
            with self.assertRaises(IngressoRifiutato, msg=repr(t)):
                spettro(r, 4, t)

    def test_generativo(self):
        """400 random inputs mixing good and bad values: a bad value anywhere = IngressoRifiutato, all good = a Rotore."""
        rnd = random.Random(20261110)
        buoni_n, buone_m = [0.5, -2.0, 3, np.float64(1.5)], [1, 2, 24, np.int64(3)]
        conti = {True: 0, False: 0}
        for _ in range(400):
            cattivo = False

            def numero():
                nonlocal cattivo
                if rnd.random() < 0.15:
                    cattivo = True
                    return rnd.choice(CATTIVI_NUMERO)
                return rnd.choice(buoni_n)

            def armoniche(n):      # distinct keys, so that no value is overwritten in the dict
                nonlocal cattivo
                chiavi = rnd.sample(buone_m + CATTIVE_DISTINTE, n) if rnd.random() < 0.3 else rnd.sample(buone_m, n)
                cattivo = cattivo or any(m in CATTIVE_DISTINTE for m in chiavi)
                return {m: numero() for m in chiavi}
            ec = numero()
            cos = armoniche(rnd.randint(0, 3))
            sen = armoniche(rnd.randint(0, 2))
            ng = numero()
            if not cattivo and not (isinstance(ec, (int, float, np.floating)) and float(ec) > 0):
                cattivo = True
            conti[cattivo] += 1
            if cattivo:
                with self.assertRaises(IngressoRifiutato, msg=(ec, cos, sen, ng)):
                    Rotore(ec, cos, sen, ng)
            else:
                self.assertIsInstance(Rotore(ec, cos, sen, ng), Rotore)
        self.assertGreater(min(conti.values()), 50, conti)      # both branches really exercised


class TestStato(unittest.TestCase):
    def test_base_troppo_piccola_non_convergente(self):
        s = spettro(Rotore.transmon(1.0, 1e6), 6, 1e-12, nmax_limite=20)
        self.assertEqual(s.stato, NON_CONVERGENTE)
        self.assertEqual(s.errore, math.inf)

    def test_secondo_metodo_concorda(self):
        s = spettro(Rotore(0.25, {1: -20.0, 2: 1.5}, {1: 0.3}, 0.41), 6, 1e-10)
        self.assertEqual(s.stato, OK)
        self.assertLess(s.errore, 1e-9)


if __name__ == "__main__":
    unittest.main()
