# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Tests of rigorous_levels.rotor_spectrum: closed input grammar and the convergence state.

The grammar of the rotor, tested directly: a malformed Rotor, k or tol must end in InputRejected, never in a
number or in another exception.
"""
import math
import random
import unittest
from unittest import mock

import numpy as np

from rigorous_levels import rotor_spectrum as RS
from rigorous_levels.rotor_spectrum import NOT_CONVERGED, OK, InputRejected, Rotor, spectrum

CATTIVI_NUMERO = [math.nan, math.inf, -math.inf, True, False, None, "1.0", [1.0], {}, 1 + 0j, np.nan, np.float64(np.inf)]
CATTIVE_ARMONICHE = [0, -1, 1.0, 1.5, True, "1", None, np.float64(2.0)]
CATTIVE_DISTINTE = [0, -1, 1.5, "1", None]   # never == a good harmonic: a dict would merge 1.0, True with 1


class TestIngressoChiuso(unittest.TestCase):
    def test_controllo_positivo(self):
        r = Rotor(0.2, {1: -10.0, 2: np.float64(0.5)}, {3: 0.1}, np.int64(0))
        self.assertEqual(r.cosines, ((1, -10.0), (2, 0.5)))
        self.assertEqual(spectrum(Rotor.transmon(0.2, 10.0), 4).state, OK)

    def test_numeri_cattivi_in_ogni_posizione(self):
        for x in CATTIVI_NUMERO:
            for costruisci in (lambda x: Rotor(x, {1: -1.0}), lambda x: Rotor(1.0, {1: x}),
                               lambda x: Rotor(1.0, {}, {1: x}), lambda x: Rotor(1.0, {1: -1.0}, n_g=x),
                               lambda x: Rotor.transmon(1.0, x), lambda x: Rotor.kite(1.0, 1.0, phi_ext=x)):
                with self.assertRaises(InputRejected, msg=repr(x)):
                    costruisci(x)

    def test_armoniche_cattive(self):
        for m in CATTIVE_ARMONICHE:
            for campo in ("cosines", "sines"):
                with self.assertRaises(InputRejected, msg=(campo, repr(m))):
                    Rotor(1.0, **{campo: {m: 1.0}})

    def test_contenitori_cattivi(self):
        for v in (5, "x", [1, 2], [(1,)], [(1, 2, 3)], object()):
            with self.assertRaises(InputRejected, msg=repr(v)):
                Rotor(1.0, v)

    def test_e_c_non_positiva(self):
        for ec in (0.0, -0.0, -1.0, -1e-300):
            with self.assertRaises(InputRejected):
                Rotor(ec, {1: -1.0})

    def test_k_e_tol_chiusi(self):
        r = Rotor.transmon(0.2, 10.0)
        for k in (0, -1, 1.0, True, "6", None):
            with self.assertRaises(InputRejected, msg=repr(k)):
                spectrum(r, k)
        for t in (0.0, -1e-9, math.nan, math.inf, True, "1e-9", None):
            with self.assertRaises(InputRejected, msg=repr(t)):
                spectrum(r, 4, t)

    def test_generativo(self):
        """400 random inputs mixing good and bad values: a bad value anywhere = InputRejected, all good = a Rotor."""
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
                with self.assertRaises(InputRejected, msg=(ec, cos, sen, ng)):
                    Rotor(ec, cos, sen, ng)
            else:
                self.assertIsInstance(Rotor(ec, cos, sen, ng), Rotor)
        self.assertGreater(min(conti.values()), 50, conti)      # both branches really exercised


class TestStato(unittest.TestCase):
    def test_base_troppo_piccola_non_convergente(self):
        s = spectrum(Rotor.transmon(1.0, 1e6), 6, 1e-12, nmax_limit=20)
        self.assertEqual(s.state, NOT_CONVERGED)
        self.assertEqual(s.error, math.inf)

    def test_la_base_cresce_finche_converge(self):
        """From a basis far too small (nmax = 3), the basis must keep doubling: the error returned is within tol and the
        levels agree with the default start. Without the second method, nothing else would catch a stop too early."""
        r = Rotor.transmon(1.0, 50.0, 0.3)
        giusto = spectrum(r, 6, 1e-9, two_methods=False)
        with mock.patch.object(RS, "_initial_nmax", return_value=3):
            s = spectrum(r, 6, 1e-9, two_methods=False)
        self.assertEqual(s.state, OK)
        self.assertGreater(s.nmax, 6)
        self.assertLessEqual(s.error, max(1e-9, s.floor))
        self.assertLess(max(abs(a - b) for a, b in zip(s.energies, giusto.energies)), 1e-8)

    def test_secondo_metodo_concorda(self):
        s = spectrum(Rotor(0.25, {1: -20.0, 2: 1.5}, {1: 0.3}, 0.41), 6, 1e-10)
        self.assertEqual(s.state, OK)
        self.assertLess(s.error, 1e-9)


if __name__ == "__main__":
    unittest.main()
