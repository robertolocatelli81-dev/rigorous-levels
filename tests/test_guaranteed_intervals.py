# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Tests of qraft_ra.guaranteed_intervals.

They need python-flint; without it only the absence tests run. Independent reference: mpmath at 50 digits, implicit
QL (tridiag_eigen) on the matrix truncated to a larger basis. Identifiers and messages are in Italian, as in the code.
"""
import importlib.util
import math
import sys
import unittest
from decimal import Decimal
from fractions import Fraction
from unittest import mock

import numpy as np

from qraft_ra import guaranteed_intervals as IG
from qraft_ra.rotor_spectrum import Rotor, spectrum

FLINT = importlib.util.find_spec("flint") is not None
MPMATH = importlib.util.find_spec("mpmath") is not None


def riferimento(ej, ng, m, k=6, ncut=None):
    """mpmath 50 cifre, settori tridiagonali per parità (m = 1 o 2), base più larga della nostra."""
    import mpmath
    from mpmath.matrices.eigen_symmetric import tridiag_eigen
    mpmath.mp.dps = 50
    nc = ncut or math.ceil(abs(ng)) + 40 + math.ceil(8 * abs(ej) ** 0.25)
    tutti = []
    for r0 in range(m):
        ns = [n for n in range(-nc, nc + 1) if (n + nc) % m == r0]
        d = [4 * (mpmath.mpf(n) - mpmath.mpf(ng)) ** 2 for n in ns]
        e = [-mpmath.mpf(ej) / 2] * (len(d) - 1) + [mpmath.mpf(0)]
        tridiag_eigen(mpmath.mp, d, e)
        tutti += list(d)
    tutti.sort()
    out = []
    for x in tutti[:k]:
        s, man, e, _ = x._mpf_
        v = Fraction(man * 2 ** e) if e >= 0 else Fraction(man, 2 ** -e)
        out.append(-v if s else v)
    return out


@unittest.skipUnless(FLINT and MPMATH, "servono python-flint e mpmath")
class TestIntervalli(unittest.TestCase):
    def test_contiene_il_riferimento_transmon_e_cos2(self):
        for ej, ng, m in ((10.0, 0.3, 1), (300.0, 0.71, 1), (0.2, 0.5, 1), (50.0, 0.0, 2), (800.0, 0.37, 2),
                          (5.0, -1.4, 1), (20.0, 2.6, 2)):
            iv = IG.guaranteed_levels(Rotor(1.0, {m: -ej}, n_g=ng), 6)
            ref = riferimento(ej, ng, m)
            for j in range(6):
                self.assertTrue(iv.low[j] <= ref[j] <= iv.high[j], (ej, ng, m, j))
            self.assertEqual(iv.state, IG.GUARANTEED)
            self.assertLessEqual(iv.max_width, 1e-12)

    def test_ej_zero_valori_esatti(self):
        for ng in (-1.3, -0.5, 0.0, 0.25, 0.5, 0.999, 3.7):
            iv = IG.guaranteed_levels(Rotor(1.0, {}, n_g=ng), 6)
            ex = sorted(4 * (n - Fraction(ng)) ** 2 for n in range(-30, 31))[:6]
            for j in range(6):
                self.assertTrue(iv.low[j] <= ex[j] <= iv.high[j], (ng, j))

    def test_mathieu_scipy_compatibile(self):
        from scipy.special import mathieu_a, mathieu_b
        for ej in (1.0, 30.0, 400.0):
            iv = IG.guaranteed_levels(Rotor(1.0, {2: -ej}), 6)
            q = ej / 8.0
            ch = sorted([mathieu_a(n, q) for n in range(8)] + [mathieu_b(n, q) for n in range(1, 8)])[:6]
            for j in range(6):
                v = Fraction(4.0 * ch[j])
                d = max(iv.low[j] - v, v - iv.high[j], 0)
                self.assertLess(float(d), 1e-8 * max(1.0, ej), (ej, j))

    def test_bound_sbagliato_si_vede(self):
        """Controllo positivo C2: il limite inferiore preso da H_N (senza H_N′ e senza L_out) a base piccola
        esclude il valore vero; il bound giusto alla stessa base lo contains."""
        import flint
        ej, ng = 400.0, 0.3
        r = Rotor(1.0, {1: -ej}, n_g=ng)
        ref = riferimento(ej, ng, 1)
        Nc = 1 + math.ceil(2 * ej ** 0.25)
        diag, bande = IG._matrix(r, Nc, None)
        lo, hi, _ = IG._enclose(flint, diag, bande, 6, Fraction(1, 10 ** 13), 128, None)
        fuori = sum(not (lo[j] <= ref[j] <= hi[j]) for j in range(6))
        self.assertGreater(fuori, 0)
        try:
            iv = IG.guaranteed_levels(r, 6, N_initial=Nc, N_limit=Nc)
        except IG.OutOfDomain:
            return
        for j in range(6):
            self.assertTrue(iv.low[j] <= ref[j] <= iv.high[j], j)

    def test_alpha_senza_penalita_si_vede(self):
        """Mutante del teorema: H_N′ = H_N (α ignorato). A base piccola il limite inferiore sale sopra il vero."""
        ej, ng = 400.0, 0.3
        r = Rotor(1.0, {1: -ej}, n_g=ng)
        ref = riferimento(ej, ng, 1)
        Nc = 1 + math.ceil(2 * ej ** 0.25)
        vero = IG._matrix
        with mock.patch.object(IG, "_matrix", lambda r, N, a: vero(r, N, None)):
            try:
                iv = IG.guaranteed_levels(r, 6, N_initial=Nc, N_limit=Nc)
            except IG.OutOfDomain:
                self.fail("la condizione su L_out dovrebbe passare anche col mutante")
        self.assertTrue(any(not (iv.low[j] <= ref[j] <= iv.high[j]) for j in range(6)))

    def test_l_out_e_controllato(self):
        """Base troppo piccola per la condizione su L_out: nessun intervallo, non un intervallo falso."""
        with self.assertRaises(IG.OutOfDomain):
            IG.guaranteed_levels(Rotor(1.0, {1: -1e4}, n_g=0.2), 6, N_initial=4, N_limit=4)

    def test_rayleigh_ritz_alto_sopra_il_vero_e_basso_sotto(self):
        r = Rotor(0.25, {1: -20.0, 2: 1.5, 3: -0.4}, n_g=0.41)
        iv = IG.guaranteed_levels(r, 8)
        s = spectrum(r, 8, 1e-11)
        for j in range(8):
            self.assertLess(abs(float(iv.low[j]) - s.energies[j]), 1e-9)
        tr = iv.transition(0, 1)
        self.assertLess(tr[0], tr[1])
        self.assertTrue(tr[0] <= Fraction(s.energies[1] - s.energies[0]) + Fraction(1e-9))

    def test_conteggio_contro_numpy_generativo(self):
        import flint
        rng = np.random.default_rng(11)
        for _ in range(60):
            n = int(rng.integers(3, 40))
            w = int(rng.integers(1, 9))
            diag = [Fraction(float(x)) for x in rng.normal(0, 10, n)]
            bande = {m: Fraction(float(rng.normal(0, 3))) for m in range(1, w + 1) if rng.random() < 0.7}
            A = np.diag([float(d) for d in diag])
            for m, b in bande.items():
                if m < n:
                    A += np.diag([float(b)] * (n - m), m) + np.diag([float(b)] * (n - m), -m)
            ev = np.linalg.eigvalsh(A)
            for x in rng.normal(0, 15, 5):
                if np.min(np.abs(ev - x)) < 1e-6:
                    continue
                c, _ = IG._count_arb(flint, diag, bande, {}, Fraction(float(x)), 128, None)
                self.assertEqual(c, int(np.sum(ev < x)))

    def test_pivot_nullo_non_indovina(self):
        """x esattamente su un autovalore di una diagonale: pivot zero esatto = None, mai un conteggio."""
        import flint
        diag = [Fraction(1), Fraction(2), Fraction(3)]
        flint.ctx.prec = 128
        try:
            c = IG._count_below(flint.arb, [flint.arb(1), flint.arb(2), flint.arb(3)], {}, flint.arb(2))
        finally:
            flint.ctx.prec = 53
        self.assertIsNone(c)
        c, p = IG._count_arb(flint, diag, {}, {}, Fraction(2), 128, None)
        self.assertEqual(c, -1)

    def test_precisione_bassa_sale(self):
        r = Rotor(1.0, {1: -1e5}, n_g=0.37)
        a = IG.guaranteed_levels(r, 3, prec=53)
        b = IG.guaranteed_levels(r, 3)
        self.assertGreater(a.prec, 53)
        for j in range(3):
            self.assertTrue(max(a.low[j], b.low[j]) <= min(a.high[j], b.high[j]), j)

    def test_dominio_chiuso(self):
        casi = [(Rotor(1.0, {1: -5.0}), 21), (Rotor(1.0, {1: -5.0}), 0), (Rotor(1.0, {1: -5.0}), True),
                (Rotor(1.0, {25: -5.0}), 6), (Rotor(1.0, {1: -5.0}, {1: 0.1}), 6), (Rotor(1.0, {1: -5.0}), 2.0)]
        for r, k in casi:
            with self.assertRaises(IG.OutOfDomain, msg=(r, k)):
                IG.guaranteed_levels(r, k)
        for larg in (0, -1e-12, math.nan, math.inf, "1e-12", True):
            with self.assertRaises(IG.OutOfDomain, msg=larg):
                IG.guaranteed_levels(Rotor(1.0, {1: -5.0}), 3, larg)
        for kw in ({"N_initial": -1}, {"N_initial": True}, {"N_limit": 0}, {"N_limit": 2.0}, {"prec": 1},
                   {"prec": 2048}, {"prec": None}, {"deadline": -1.0}, {"deadline": math.nan}, {"deadline": True}):
            with self.assertRaises(IG.OutOfDomain, msg=kw):
                IG.guaranteed_levels(Rotor(1.0, {1: -5.0}), 3, **kw)
        IG.guaranteed_levels(Rotor(1.0, {24: -5.0}, {1: -0.0}), 20)   # at the limits k = 20, m = 24, null sine: accepted

    def test_scadenza(self):
        with self.assertRaises(IG.DeadlineExceeded):
            IG.guaranteed_levels(Rotor(1.0, {1: -1e5}), 6, deadline=1e-9)

    def test_stringhe_verso_l_esterno(self):
        iv = IG.guaranteed_levels(Rotor(1.0, {1: -10.0}, n_g=0.3), 4)
        for (a, b), lo, hi in zip(iv.strings, iv.low, iv.high):
            self.assertEqual(Fraction(Decimal(a)), lo)
            self.assertEqual(Fraction(Decimal(b)), hi)
        self.assertEqual(IG._decimal(Fraction(1, 3), False), "3.33333333333333333333333e-1")
        self.assertEqual(IG._decimal(Fraction(1, 3), True), "3.33333333333333333333334e-1")
        self.assertEqual(IG._decimal(Fraction(-1, 3), False), "-3.33333333333333333333334e-1")
        self.assertEqual(IG._decimal(Fraction(0), True), "0")


@unittest.skipUnless(FLINT and MPMATH, "servono python-flint e mpmath")
class TestTeoremaPezzoPerPezzo(unittest.TestCase):
    """Each step of the argument of docs/PROOF.md against a hand computation (added for mutants that survived)."""

    def test_l_out_a_mano(self):
        r = Rotor(1.0, {1: -10.0, 2: 3.0}, n_g=0.3)
        d_out = 4 * (6 - Fraction(0.3)) ** 2
        self.assertEqual(IG._l_out(r, 5, Fraction(1, 2)), d_out - Fraction(13, 2) * 3)
        self.assertEqual(IG._l_out(r, 5, Fraction(4)), d_out - Fraction(13, 2) * 2)
        self.assertEqual(IG._l_out(r, 5, Fraction(1)), d_out - 13)
        self.assertEqual(IG._l_out(Rotor(0.5, {}, n_g=-2.0), 3, Fraction(1)), 2 * (4 - 2) ** 2)
        with self.assertRaises(IG.OutOfDomain):
            IG._l_out(Rotor(1.0, {1: -1.0}, n_g=5.3), 5, Fraction(1))

    def test_matrice_a_mano(self):
        diag, bande = IG._matrix(Rotor(1.0, {2: -4.0}), 3, Fraction(1, 4))
        self.assertEqual(bande, {2: Fraction(-2)})
        atteso = [36 - Fraction(1, 2), 16 - Fraction(1, 2), 4, 0, 4, 16 - Fraction(1, 2), 36 - Fraction(1, 2)]
        self.assertEqual(diag, atteso)
        diag, _ = IG._matrix(Rotor(1.0, {1: -4.0, 3: 6.0}), 2, Fraction(2))
        #   n:  -2  -1   0   1   2 ; m=1 esce da ±2 (|b|=2), m=3 esce da tutti tranne none (|b|=3): n=0 ha ±3 fuori
        atteso = [16 - 2 * 2 - 2 * 3, 4 - 2 * 3, 0 - 2 * 3 * 2, 4 - 2 * 3, 16 - 2 * 2 - 2 * 3]
        self.assertEqual(diag, atteso)

    def test_alpha_cattivo_fermato_dal_controllo(self):
        """α scelto male (1e-6): L_out precipita; il check L_out > λ_{k−1}(H_N′) deve rifiutare, non dare numeri."""
        r = Rotor(1.0, {1: -50.0}, n_g=0.2)
        with mock.patch.object(IG, "_choose_alpha", return_value=Fraction(1, 10 ** 6)):
            with self.assertRaises(IG.OutOfDomain):
                IG.guaranteed_levels(r, 4, N_initial=20, N_limit=20)
        IG.guaranteed_levels(r, 4, N_initial=20, N_limit=20)    # con α giusto la stessa base basta

    def test_stime_float_sbagliate_si_correggono(self):
        r = Rotor(1.0, {1: -10.0}, n_g=0.3)
        ref = riferimento(10.0, 0.3, 1)
        vero = IG._float_estimates
        for spost in (-3.0, 3.0, -0.7, 0.7):
            with mock.patch.object(IG, "_float_estimates", lambda d, b, k, s=spost: vero(d, b, k) + s):
                iv = IG.guaranteed_levels(r, 6)
            for j in range(6):
                self.assertTrue(iv.low[j] <= ref[j] <= iv.high[j], (spost, j))

    def test_conteggi_incerti_mai_usati_come_estremi(self):
        import flint
        r = Rotor(1.0, {1: -30.0}, n_g=0.41)
        diag, bande = IG._matrix(r, 30, None)
        vero = IG._count_arb
        visti, n = {}, [0]

        def finto(fl, d, b, cache, x, prec, deadline):
            n[0] += 1
            c = (-1, prec) if n[0] % 4 == 1 else vero(fl, d, b, cache, x, prec, deadline)
            visti[x] = c[0]
            return c
        with mock.patch.object(IG, "_count_arb", finto):
            lo, hi, _ = IG._enclose(flint, diag, bande, 5, Fraction(1, 10 ** 12), 128, None)
        for j in range(5):
            self.assertIn(visti[lo[j]], range(0, j + 1), j)
            self.assertGreaterEqual(visti[hi[j]], j + 1, j)

    def test_estremo_iniziale_incerto_non_accettato(self):
        """Stime spostate in su (estremo basso iniziale sopra λ_j) e conteggio incerto proprio lì: l'estremo
        va scartato, non preso per buono."""
        r = Rotor(1.0, {1: -10.0}, n_g=0.3)
        ref = riferimento(10.0, 0.3, 1)
        vero_c, vero_s, n = IG._count_arb, IG._float_estimates, [0]

        def finto(fl, d, b, cache, x, prec, deadline):
            n[0] += 1
            return (-1, prec) if n[0] % 4 == 1 else vero_c(fl, d, b, cache, x, prec, deadline)
        with mock.patch.object(IG, "_count_arb", finto), \
                mock.patch.object(IG, "_float_estimates", lambda d, b, k: vero_s(d, b, k) + 3.0):
            iv = IG.guaranteed_levels(r, 6)
        for j in range(6):
            self.assertTrue(iv.low[j] <= ref[j] <= iv.high[j], j)

    def test_precisione_massima_si_usa(self):
        import flint
        c, p = IG._count_arb(flint, [Fraction(1), Fraction(3)], {1: Fraction(1, 2)}, {}, Fraction(2), IG.PREC_MAX,
                             None)
        self.assertEqual((c, p), (1, IG.PREC_MAX))

    def test_base_che_cresce_e_stato_largo(self):
        r = Rotor(1.0, {1: -10.0}, n_g=0.3)
        iv = IG.guaranteed_levels(r, 2, 1e-20, N_initial=8)
        self.assertEqual(iv.state, IG.GUARANTEED)
        self.assertLessEqual(iv.max_width, 1e-20)
        self.assertGreater(iv.N, 8)
        iv = IG.guaranteed_levels(r, 2, 1e-20, N_initial=8, N_limit=8)
        self.assertEqual(iv.state, IG.WIDE)
        self.assertGreater(iv.max_width, 1e-20)
        ref = riferimento(10.0, 0.3, 1, k=2)
        for j in range(2):
            self.assertTrue(iv.low[j] <= ref[j] <= iv.high[j], j)

    def test_n_sotto_n_g(self):
        r = Rotor(1.0, {1: -2.0}, n_g=5.3)
        with self.assertRaises(IG.OutOfDomain):
            IG.guaranteed_levels(r, 1, N_initial=1, N_limit=1)
        iv = IG.guaranteed_levels(r, 3, N_initial=1, N_limit=64)
        self.assertGreaterEqual(iv.N, 6)
        ref = riferimento(2.0, 5.3, 1, k=3)
        for j in range(3):
            self.assertTrue(iv.low[j] <= ref[j] <= iv.high[j], j)


class TestAssenzaFlint(unittest.TestCase):
    def test_flint_assente(self):
        with mock.patch.dict(sys.modules, {"flint": None}):
            with self.assertRaises(IG.ArbMissing):
                IG.guaranteed_levels(Rotor(1.0, {1: -5.0}), 3)


@unittest.skipUnless(FLINT, "serve python-flint")
class TestRevisione0811(unittest.TestCase):
    """Findings of the 2026-11-08 review: inputs that are not a Rotor, reason of the failure."""

    def test_solo_rotore_vero(self):
        import types
        finti = [types.SimpleNamespace(E_C=1.0, cosines=((0, 5.0), (1, -1.0)), sines=(), n_g=0.0),    # m = 0
                 types.SimpleNamespace(E_C=1.0, cosines=((1, -1.0), (1, -1.0)), sines=(), n_g=0.0),   # m ripetuta
                 types.SimpleNamespace(E_C=-1.0, cosines=((1, -1.0),), sines=(), n_g=0.0),            # E_C < 0
                 types.SimpleNamespace(E_C=1.0, cosines=((1, -1.0),), sines=(), n_g=0.0)]   # campi validi, non Rotor
        alterati = []
        for campo, valore in (("cosines", ((1, -1.0), (1, -1.0))), ("cosines", ((0, 5.0), (1, -1.0))),
                              ("E_C", -1.0), ("E_C", 0.0)):
            a = Rotor(1.0, {1: -1.0})
            object.__setattr__(a, campo, valore)
            alterati.append(a)
        for r in finti + alterati:
            with self.assertRaises(IG.OutOfDomain, msg=r):
                IG.guaranteed_levels(r, 3)
        IG.guaranteed_levels(Rotor(1.0, {1: -1.0, 2: 0.5}), 3)        # check: un Rotor vero passa

    def test_motivo_conteggi_incerti(self):
        def finto(fl, diag, bande, k, t, p, d):
            return [Fraction(-10 ** 9)] * k, [Fraction(10 ** 9)] * k, 2 * IG.PREC_MAX
        with mock.patch.object(IG, "_enclose", finto):
            with self.assertRaises(IG.OutOfDomain) as e:
                IG.guaranteed_levels(Rotor(1.0, {1: -5.0}), 3, N_initial=4, N_limit=8)
        self.assertIn("uncertain", str(e.exception))
        chiamate = []

        def prima_incerto(fl, diag, bande, k, t, p, d):        # incerto solo al primo N, poi certo ma largo
            chiamate.append(1)
            return [Fraction(-10 ** 9)] * k, [Fraction(10 ** 9)] * k, (2 * IG.PREC_MAX if len(chiamate) <= 2 else 128)
        with mock.patch.object(IG, "_enclose", prima_incerto):
            with self.assertRaises(IG.OutOfDomain) as e:
                IG.guaranteed_levels(Rotor(1.0, {1: -5.0}), 3, 1.0, N_initial=4, N_limit=8)
        self.assertEqual(len(chiamate), 4)                          # due basi: N = 4 poi N = 8
        self.assertIn("uncertain", str(e.exception))
        def al_massimo(fl, diag, bande, k, t, p, d):                # PREC_MAX usata ma conteggi certi
            return [Fraction(-10 ** 9)] * k, [Fraction(10 ** 9)] * k, IG.PREC_MAX
        with mock.patch.object(IG, "_enclose", al_massimo):
            with self.assertRaises(IG.OutOfDomain) as e:
                IG.guaranteed_levels(Rotor(1.0, {1: -5.0}), 3, N_initial=4, N_limit=8)
        self.assertNotIn("uncertain", str(e.exception))
        with self.assertRaises(IG.OutOfDomain) as e:                     # check: senza incertezza, L_out
            IG.guaranteed_levels(Rotor(1.0, {1: -30.0}, n_g=0.5), 6, N_initial=3, N_limit=3)
        self.assertIn("L_out", str(e.exception))
        self.assertLessEqual(IG.guaranteed_levels(Rotor(1.0, {}, n_g=0.5), 6).prec, IG.PREC_MAX)


@unittest.skipUnless(FLINT and MPMATH, "servono python-flint e mpmath")
class TestFiltroBase(unittest.TestCase):
    """Fixes of 2026-11-08: first-order filter of the basis, large E_C within the time cap."""

    def test_scarto_primo_ordine_contro_la_differenza_vera(self):
        r = Rotor(1.0, {1: -3.0, 2: 0.7}, n_g=0.3)
        diag, bande = IG._matrix(r, 2, None)                  # base piccola: peso vero ai bordi, differenza
        giu, _ = IG._matrix(r, 2, Fraction(1, 10 ** 4))       # ben sopra il rumore; α piccolo: primo ordine ≈ esatto
        H = np.diag([float(d) for d in diag])
        for m, b in bande.items():
            H += np.diag([float(b)] * (len(diag) - m), m) + np.diag([float(b)] * (len(diag) - m), -m)
        vero = np.linalg.eigvalsh(H)[:4] - np.linalg.eigvalsh(H - np.diag([float(a - b) for a, b in zip(diag, giu)]))[:4]
        stima = IG._first_order_shift(diag, giu, bande, 4)
        self.assertGreater(stima, 0)
        self.assertAlmostEqual(stima / float(np.max(vero)), 1.0, places=4)
        senza_bande = IG._first_order_shift([Fraction(i) for i in range(5)], [Fraction(i) - i * Fraction(1, 100)
                                                                               for i in range(5)], {}, 3)
        self.assertAlmostEqual(senza_bande, 0.02, places=12)     # diagonale: max dei primi 3 scarti (0, 0,01, 0,02)

    def test_e_c_grande_entro_il_tetto(self):
        # E_C = 1e6, E_J = 3e7, n_g = 0.2, k = 20: with the old filter (difference of float eigenvalues) N reached
        # 2080 in 31-50 s. Now N = 65 in about 1 s, and mpmath is inside.
        r = Rotor(1e6, {1: -3e7}, n_g=0.2)
        iv = IG.guaranteed_levels(r, 20, deadline=10)
        self.assertEqual((iv.state, iv.N), (IG.GUARANTEED, 65))
        ref = riferimento(30.0, 0.2, 1, k=20)
        self.assertTrue(all(iv.low[j] <= ref[j] * 10 ** 6 <= iv.high[j] for j in range(20)))
        self.assertFalse(all(iv.low[j] <= ref[j] * 10 ** 6 + Fraction(2, 10 ** 13) <= iv.high[j]
                             for j in range(20)))                # check: il riferimento spostato esce

    def test_tetto_rispettato_anche_se_la_base_cresce(self):
        import time
        r = Rotor(1e6, {1: -3e7}, n_g=0.2)
        with mock.patch.object(IG, "_first_order_shift", lambda *a: math.inf):     # base che raddoppia sempre
            t = time.monotonic()
            with self.assertRaises(IG.DeadlineExceeded):
                IG.guaranteed_levels(r, 20, deadline=2)
            self.assertLess(time.monotonic() - t, 4.0)


@unittest.skipUnless(FLINT, "serve python-flint")
class TestArmonicaBooleana(unittest.TestCase):
    def test_armonica_booleana_rifiutata(self):
        # a mutant without `isinstance(m, bool)` survived: an altered Rotor with m = True was accepted
        r = Rotor(1.0, {1: -1.0}, {}, 0.2)
        object.__setattr__(r, "cosines", ((True, -1.0),))
        with self.assertRaises(IG.OutOfDomain):
            IG.guaranteed_levels(r, 2)


if __name__ == "__main__":
    unittest.main()
