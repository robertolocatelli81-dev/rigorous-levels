# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Test di qraft_ra/duffing_vs_transmon.py (11/11/2026). Spec: note dell'autore (non pubblicate)."""
import importlib.util
import unittest
from fractions import Fraction

import numpy as np

FLINT = importlib.util.find_spec("flint") is not None
if FLINT:
    from qraft_ra import duffing_vs_transmon as DT


def transmon_numpy(ec, ej, ng, k, ncut=60):
    n = np.arange(-ncut, ncut + 1)
    H = np.diag(4 * ec * (n - ng) ** 2) - 0.5 * ej * (np.eye(2 * ncut + 1, k=1) + np.eye(2 * ncut + 1, k=-1))
    return np.linalg.eigvalsh(H)[:k]


@unittest.skipUnless(FLINT, "python-flint assente")
class TestDuffing(unittest.TestCase):
    def test_livelli_duffing_esatti(self):
        self.assertEqual(DT.livelli_duffing(Fraction(5), Fraction(-1, 3), 3), 15 - 1)
        self.assertEqual(DT.livelli_duffing(Fraction(5), Fraction(-1, 3), 0), 0)
        self.assertEqual(DT.livelli_duffing(Fraction(5), Fraction(-1, 3), 1), 5)

    def test_spettro_zero_sui_primi_tre_e_contiene_numpy(self):
        for ec, ej, ng in ((0.3, 15.0, 0.25), (0.25, 5.0, 0.5), (0.2, 100.0, 0.0)):
            e = DT.errore_duffing(ec, ej, ng, 6, "spettro", scadenza=60)
            for j in range(3):
                lo, hi = e.delta[j]
                self.assertLessEqual(lo, 0)
                self.assertGreaterEqual(hi, 0)
                self.assertLess(float(hi - lo), 1e-9)
            E = transmon_numpy(ec, ej, ng, 6)
            w = E[1] - E[0]
            a = (E[2] - E[1]) - w
            for j in range(3, 6):
                vero = (E[j] - E[0]) - (w * j + a * j * (j - 1) / 2)
                lo, hi = e.delta[j]
                self.assertLessEqual(float(lo) - 1e-9, vero, (ec, ej, ng, j))
                self.assertGreaterEqual(float(hi) + 1e-9, vero, (ec, ej, ng, j))
            self.assertLess(e.delta[3][0], 0)         # il transmon sta SOTTO il Duffing a j = 3 (anarmonicità cresce)

    def test_koch_contiene_numpy(self):
        for ec, ej, ng in ((0.3, 15.0, 0.25), (0.25, 50.0, 0.5)):
            e = DT.errore_duffing(ec, ej, ng, 5, "koch", scadenza=60)
            E = transmon_numpy(ec, ej, ng, 5)
            w = np.sqrt(8 * ej * ec) - ec
            for j in range(1, 5):
                vero = (E[j] - E[0]) - (w * j - ec * j * (j - 1) / 2)
                self.assertLessEqual(float(e.delta[j][0]) - 1e-9, vero, (ec, ej, j))
                self.assertGreaterEqual(float(e.delta[j][1]) + 1e-9, vero, (ec, ej, j))
            self.assertLess(float(e.omega[1] - e.omega[0]), 1e-30)       # radice racchiusa a 128 bit
            self.assertLessEqual(e.omega[0], Fraction(w) + Fraction(1e-9))

    def test_controllo_positivo_riferimento_spostato(self):
        """Gli intervalli δ_j (larghi ~1e-13) ESCLUDONO il valore numpy spostato di ±1e-9."""
        e = DT.errore_duffing(0.3, 15.0, 0.25, 6, "spettro", scadenza=60)
        E = transmon_numpy(0.3, 15.0, 0.25, 6)
        w = E[1] - E[0]
        a = (E[2] - E[1]) - w
        vero = (E[5] - E[0]) - (w * 5 + a * 10)
        lo, hi = e.delta[5]
        self.assertFalse(lo <= Fraction(vero + 1e-9) <= hi)
        self.assertFalse(lo <= Fraction(vero - 1e-9) <= hi)

    def test_radice_racchiusa(self):
        import flint
        for x in (Fraction(2), Fraction(36), Fraction(8 * 15, 10), Fraction(1, 3)):
            lo, hi = DT._sqrt_intervallo(flint, x)
            self.assertLessEqual(lo * lo, x)
            self.assertGreaterEqual(hi * hi, x)
            self.assertLess(float(hi - lo), 1e-30 * float(hi))

    def test_formule_degli_intervalli_su_intervalli_larghi(self):
        """Mutanti vivi (11/11): con gli intervalli Q6 larghi 1e-13 una direzione sbagliata non si vede. Qui
        livelli_garantiti è sostituita da intervalli LARGHI [E−w_j, E+w_j]: ω, α e δ_j devono contenere il valore
        in OGNI vertice della scatola (enumerazione esatta) e coincidere con la formula della specifica."""
        from itertools import product
        from qraft_ra.intervallo_garantito import Intervalli
        E = [Fraction(-12), Fraction(-6), Fraction(-1), Fraction(4), Fraction(9)]
        w = [Fraction(1, 10), Fraction(1, 5), Fraction(3, 10), Fraction(2, 5), Fraction(1, 2)]
        bassi = tuple(e - x for e, x in zip(E, w))
        alti = tuple(e + x for e, x in zip(E, w))
        finto = Intervalli(bassi, alti, tuple((str(b), str(a)) for b, a in zip(bassi, alti)), 1.0, "LARGO", 10, 128, 0.0, 0.0)
        originale = DT.livelli_garantiti
        DT.livelli_garantiti = lambda *a, **k: finto
        try:
            e = DT.errore_duffing(0.3, 15.0, 0.0, 5, "spettro")
        finally:
            DT.livelli_garantiti = originale
        self.assertEqual(e.omega, (bassi[1] - alti[0], alti[1] - bassi[0]))
        self.assertEqual(e.delta[0], (bassi[0] - alti[0], alti[0] - bassi[0]))      # E_0 − E_0 come intervallo: (b0−a0, a0−b0)
        self.assertEqual(e.delta[1], ((bassi[1] - alti[0]) - (alti[1] - bassi[0]), (alti[1] - bassi[0]) - (bassi[1] - alti[0])))
        self.assertEqual(e.alpha, ((bassi[2] - alti[1]) - (alti[1] - bassi[0]), (alti[2] - bassi[1]) - (bassi[1] - alti[0])))
        for j in range(5):
            lo, hi = e.delta[j]
            vertici = []
            for p in product(*[(bassi[i], alti[i]) for i in range(5)]):
                om = p[1] - p[0]
                al = (p[2] - p[1]) - om
                vertici.append((p[j] - p[0]) - (om * j + al * j * (j - 1) / 2))
            self.assertLessEqual(lo, min(vertici), j)
            self.assertGreaterEqual(hi, max(vertici), j)
            if j >= 3:          # per j < 3 l'intervallo è valido ma non stretto (dipendenza fra ω, α e E_j: δ_j ≡ 0 ai vertici)
                self.assertLess(hi - lo, 20 * (max(vertici) - min(vertici)), j)   # non assurdamente largo

    def test_allarga_radice(self):
        x = Fraction(2)
        lo, hi = DT._allarga(Fraction(15, 10), Fraction(14, 10), x)       # lo² > x e hi² < x: deve allargare entrambi
        self.assertLessEqual(lo * lo, x)
        self.assertGreaterEqual(hi * hi, x)
        lo2, hi2 = DT._allarga(Fraction(1), Fraction(2), x)               # già buono: invariato
        self.assertEqual((lo2, hi2), (Fraction(1), Fraction(2)))

    def test_ingressi_chiusi(self):
        for args, kw in (((0.0, 15.0), {}), ((0.3, -1.0), {}), ((0.3, 15.0, float("nan")), {}), ((0.3, 15.0, 0.0, 2), {}),
                         ((0.3, 15.0, 0.0, 21), {}), ((0.3, 15.0, 0.0, True), {}), ((0.3, 15.0), {"variante": "x"}),
                         ((True, 15.0), {}), ((10 ** 400, 15.0), {})):
            with self.assertRaises(DT.FuoriDominio, msg=str((args, kw))):
                DT.errore_duffing(*args, **kw)

    def test_allarga_ingressi_lontani_e_negativi(self):
        """NEMESIS 11/11: lo ≥ 10√x, lo < 0 e hi < 0 non devono bloccare né dare un intervallo falso."""
        for lo, hi, x in ((100, 100, 1), (10, 10, 1), (-5, 1, 1), (0, -5, 1), (3, -2, 9), (10 ** 6, 0, 2), (0, 0, 0)):
            lo, hi, x = Fraction(lo), Fraction(hi), Fraction(x)
            a, b = DT._allarga(lo, hi, x)
            self.assertLessEqual(a, b)
            self.assertGreaterEqual(b, 0)
            self.assertGreaterEqual(b * b, x)
            self.assertTrue(a <= 0 or a * a <= x)
        with self.assertRaises(ArithmeticError):
            DT._allarga(Fraction(1), Fraction(1), Fraction(-1))

    def test_koch_omega_racchiude_la_radice_esatta(self):
        """ω_koch + E_C deve racchiudere √(8 E_J E_C) in aritmetica esatta (mutanti vivi NEMESIS 11/11:
        intervallo degenere [r0, r0] o radice di 8E_JE_C(1+1e-20) passavano i test a ±1e-9)."""
        for ec, ej in ((0.3, 15.0), (0.25, 50.0), (0.17, 7.3)):
            e = DT.errore_duffing(ec, ej, 0.0, 3, "koch", scadenza=60)
            x = 8 * Fraction(ej) * Fraction(ec)
            lo, hi = e.omega[0] + Fraction(ec), e.omega[1] + Fraction(ec)
            self.assertLessEqual(lo * lo, x)
            self.assertGreaterEqual(hi * hi, x)
            self.assertLessEqual(lo, hi)


if __name__ == "__main__":
    unittest.main()
