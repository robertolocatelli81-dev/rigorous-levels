# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Test di qraft_ra/rotore_sferico_garantito.py (10/11/2026). Da note dell'autore (non pubblicate) (PREREG, ESITO).
Ogni chiamata porta scadenza=20 s: un mutante che fa girare il ciclo fino a L_LIMITE/PREC_MAX deve FALLIRE (TempoScaduto),
non bloccare il banco (banco mutanti 10/11: il mutante sul segno del pivot non dava esito)."""
import importlib.util
import math
import unittest
from fractions import Fraction

import numpy as np


FLINT = importlib.util.find_spec("flint") is not None
if FLINT:
    from qraft_ra import rotore_sferico_garantito as RS  # noqa: E402


def numpy_livelli(B, dE, M, k, L, Dc=0.0):
    Ns = np.arange(abs(M), L + 1)
    c = np.sqrt([((N + 1) ** 2 - M * M) / ((2 * N + 1) * (2 * N + 3)) for N in Ns[:-1]])
    x = Ns * (Ns + 1.0)
    T = np.diag(B * x - Dc * x * x) - dE * (np.diag(c, 1) + np.diag(c, -1))
    return np.linalg.eigvalsh(T)[:k]


def dentro(iv, valori, tol=0.0):
    return all(lo - Fraction(tol) <= Fraction(float(v)) <= hi + Fraction(tol)
               for lo, hi, v in zip(iv.bassi, iv.alti, valori))


@unittest.skipUnless(FLINT, "python-flint assente")
class TestValori(unittest.TestCase):
    def test_campo_zero_valori_esatti(self):
        for M in (0, 1, -2):
            iv = RS.livelli_sfera_garantiti(RS.RotoreSferico(B=1.0, dE=0.0, M=M), 6, scadenza=20)
            self.assertTrue(dentro(iv, [N * (N + 1) for N in range(abs(M), abs(M) + 6)]))
            self.assertEqual(iv.stato, "GARANTITO")

    def test_campo_debole_secondo_ordine(self):
        lam = 0.01
        for M in (0, 1):
            iv = RS.livelli_sfera_garantiti(RS.RotoreSferico(B=1.0, dE=lam, M=M), 6, scadenza=20)
            ref = []
            for N in range(M, M + 6):
                e2 = -lam * lam / 6 if N == 0 else \
                    lam * lam * (N * (N + 1) - 3 * M * M) / (2 * N * (N + 1) * (2 * N - 1) * (2 * N + 3))
                ref.append(N * (N + 1) + e2)
            self.assertTrue(dentro(iv, ref, tol=10 * lam ** 4))

    def test_riferimento_numpy_grande(self):
        for lam in (0.1, 1.0, 10.0, 100.0, 1000.0):
            for M in (0, 1):
                iv = RS.livelli_sfera_garantiti(RS.RotoreSferico(B=1.0, dE=lam, M=M), 6, scadenza=20)
                self.assertTrue(dentro(iv, numpy_livelli(1.0, lam, M, 6, 400), tol=1e-12), (lam, M))

    def test_unita_assolute_scalano(self):
        """Stessa fisica in MHz: B = 490,173994, dE = λB. Gli intervalli contengono B × (valori in unità di B)."""
        B = 490.173994
        iv = RS.livelli_sfera_garantiti(RS.RotoreSferico(B=B, dE=3.7742 * B, M=0), 4, scadenza=20)
        self.assertTrue(dentro(iv, numpy_livelli(B, 3.7742 * B, 0, 4, 300), tol=1e-9))

    def test_M_e_meno_M_uguali(self):
        a = RS.livelli_sfera_garantiti(RS.RotoreSferico(B=1.0, dE=5.0, M=2), 4, scadenza=20)
        b = RS.livelli_sfera_garantiti(RS.RotoreSferico(B=1.0, dE=5.0, M=-2), 4, scadenza=20)
        self.assertEqual((a.bassi, a.alti), (b.bassi, b.alti))

    def test_riferimento_sbagliato_escluso(self):
        """Controllo positivo: un numpy troncato troppo presto deve cadere FUORI dagli intervalli."""
        iv = RS.livelli_sfera_garantiti(RS.RotoreSferico(B=1.0, dE=100.0, M=0), 6, scadenza=20)
        sbagliato = numpy_livelli(1.0, 100.0, 0, 6, 10)
        fuori = sum(not (lo <= Fraction(float(v)) <= hi) for lo, hi, v in zip(iv.bassi, iv.alti, sbagliato))
        self.assertEqual(fuori, 6)


@unittest.skipUnless(FLINT, "python-flint assente")
class TestDistorsioneCentrifuga(unittest.TestCase):
    def test_N_fis(self):
        r = RS.RotoreSferico(B=1.0, dE=0.0, Dc=0.01)          # N(N+1) < 50 → N ≤ 6
        self.assertEqual(r.N_fis, 6)
        self.assertIsNone(RS.RotoreSferico(B=1.0).N_fis)

    def test_campo_zero_con_distorsione(self):
        Dc = 1e-4
        iv = RS.livelli_sfera_garantiti(RS.RotoreSferico(B=1.0, dE=0.0, Dc=Dc), 6, scadenza=20)
        esatti = [N * (N + 1) - Dc * (N * (N + 1)) ** 2 for N in range(6)]
        self.assertTrue(dentro(iv, esatti))

    def test_con_campo_e_distorsione(self):
        Dc = 1e-4
        for lam in (1.0, 10.0):
            iv = RS.livelli_sfera_garantiti(RS.RotoreSferico(B=1.0, dE=lam, Dc=Dc), 5, scadenza=20)
            r = RS.RotoreSferico(B=1.0, dE=lam, Dc=Dc)
            self.assertTrue(dentro(iv, numpy_livelli(1.0, lam, 0, 5, r.N_fis, Dc), tol=1e-12), lam)

    def test_modello_finito_tutto_incluso(self):
        """D_c grande: N_fis piccolo, la base è finita e i due limiti vengono dalla stessa matrice."""
        r = RS.RotoreSferico(B=1.0, dE=0.5, Dc=0.01)
        iv = RS.livelli_sfera_garantiti(r, 6, scadenza=20)
        self.assertEqual(iv.N, r.N_fis)
        self.assertTrue(dentro(iv, numpy_livelli(1.0, 0.5, 0, 6, r.N_fis, 0.01), tol=1e-12))

    def test_troppi_livelli_per_il_modello(self):
        with self.assertRaises(RS.FuoriDominio):
            RS.livelli_sfera_garantiti(RS.RotoreSferico(B=1.0, Dc=0.01), 8, scadenza=20)

    def test_N_fis_al_bordo(self):
        """Mutante vivo (banco 10/11): N(N+1) > q invece di ≥ nel ciclo. La definizione è N(N+1) < B/(2 D_c) in senso
        stretto: con B/(2D_c) = 42 = 6·7 esatto, N_fis = 5 (non 6)."""
        self.assertEqual(RS.RotoreSferico(B=84.0, dE=0.0, Dc=1.0).N_fis, 5)
        self.assertEqual(RS.RotoreSferico(B=84.0 + 1e-9, dE=0.0, Dc=1.0).N_fis, 6)

    def test_stato_largo(self):
        """Mutante vivo (banco 10/11): stato sempre GARANTITO. Con larghezza 1e-17 la stima float (errore ~1e-16) non
        permette intervalli così stretti: il risultato è valido ma LARGO, e lo deve dire."""
        iv = RS.livelli_sfera_garantiti(RS.RotoreSferico(B=1.0, dE=3.0), 3, larghezza=1e-17, scadenza=20)
        self.assertEqual(iv.stato, "LARGO")
        self.assertGreater(iv.larghezza_max, 1e-17 * max(max(abs(float(b)) for b in iv.bassi), 1.0))
        self.assertTrue(dentro(iv, numpy_livelli(1.0, 3.0, 0, 3, 200), tol=1e-12))


@unittest.skipUnless(FLINT, "python-flint assente")
class TestIngressiChiusi(unittest.TestCase):
    def test_parametri(self):
        for kw in ({"B": 0.0}, {"B": -1.0}, {"B": True}, {"B": float("nan")}, {"B": "1"}, {"B": 1.0, "dE": -1.0},
                   {"B": 1.0, "dE": float("inf")}, {"B": 1.0, "M": 1.5}, {"B": 1.0, "M": True},
                   {"B": 1.0, "Dc": -1e-6}):
            with self.assertRaises(RS.FuoriDominio, msg=str(kw)):
                RS.RotoreSferico(**kw)

    def test_chiamata(self):
        r = RS.RotoreSferico(B=1.0, dE=1.0)
        for args, kw in (((r, 0), {}), ((r, True), {}), ((r, 201), {}), ((r, 3), {"larghezza": 0.0}),
                         ((r, 3), {"L_limite": 2}), ((r, 3), {"scadenza": -1.0}), ((object(), 3), {})):
            with self.assertRaises(RS.FuoriDominio, msg=str((args, kw))):
                RS.livelli_sfera_garantiti(*args, **kw)

    def test_scadenza(self):
        with self.assertRaises(RS.TempoScaduto):
            RS.livelli_sfera_garantiti(RS.RotoreSferico(B=1.0, dE=1e6), 6, scadenza=1e-9)

    def test_precisione_ripristinata(self):
        import flint
        p = flint.ctx.prec
        RS.livelli_sfera_garantiti(RS.RotoreSferico(B=1.0, dE=1.0), 3, scadenza=20)
        self.assertEqual(flint.ctx.prec, p)


@unittest.skipUnless(FLINT, "python-flint assente")
class TestDimostrazione(unittest.TestCase):
    """Test che guardano la DIMOSTRAZIONE, non solo il contenimento a L convergente (banco mutanti 10/11/2026:
    5 mutanti vivi su 6 con i soli test sopra; ognuno di questi test ne uccide almeno uno, elencato nel docstring)."""

    def test_conta_sotto_diagonale(self):
        """Mutante: pivot contato col segno sbagliato (`if d > 0: n += 1`). Su una diagonale il conteggio è esatto."""
        import flint
        diag = [flint.arb(v) for v in (-3, -1, 0, 2, 5)]
        off2 = [flint.arb(0)] * 4
        for x, atteso in ((-4, 0), (-2, 1), (0.5, 3), (3, 4), (10, 5)):
            self.assertEqual(RS._conta_sotto(diag, off2, flint.arb(x)), atteso, x)
        # tridiagonale 2×2 [[0, b],[b, 0]]: autovalori ±b
        d2, o2 = [flint.arb(0), flint.arb(0)], [flint.arb(4)]
        self.assertEqual(RS._conta_sotto(d2, o2, flint.arb(-3)), 0)
        self.assertEqual(RS._conta_sotto(d2, o2, flint.arb(1)), 1)
        self.assertEqual(RS._conta_sotto(d2, o2, flint.arb(3)), 2)
        self.assertIsNone(RS._conta_sotto(d2, o2, flint.arb(0)))      # pivot nullo: incerto, mai un conteggio

    def test_stato_e_larghezza(self):
        """Mutante: +D_c nella diagonale Arb. Gli intervalli restano centrati sulla stima numpy e si allargano fino a
        contenere il valore vero: contenimento sì, ma stato LARGO. Qui si esige GARANTITO e larghezza ≤ obiettivo."""
        casi = [RS.RotoreSferico(B=1.0, dE=0.0, Dc=1e-4), RS.RotoreSferico(B=1.0, dE=3.0, Dc=1e-4),
                RS.RotoreSferico(B=1.0, dE=10.0, M=1), RS.RotoreSferico(B=490.173994, dE=50.0, Dc=2.13e-4)]
        for r in casi:
            iv = RS.livelli_sfera_garantiti(r, 6, larghezza=1e-12, scadenza=20)
            self.assertEqual(iv.stato, "GARANTITO", r)
            obiettivo = 1e-12 * max(max(abs(float(b)) for b in iv.bassi), r.B)
            self.assertLessEqual(iv.larghezza_max, obiettivo, r)
            for lo, hi in zip(iv.bassi, iv.alti):
                self.assertLess(hi - lo, Fraction(obiettivo), r)

    def test_segno_distorsione_centrifuga(self):
        """Controllo positivo: i valori con +D_c (segno sbagliato) devono cadere FUORI dagli intervalli."""
        Dc = 1e-4
        for dE in (0.0, 2.0):
            r = RS.RotoreSferico(B=1.0, dE=dE, Dc=Dc)
            iv = RS.livelli_sfera_garantiti(r, 6, scadenza=20)
            giusti = numpy_livelli(1.0, dE, 0, 6, r.N_fis, Dc)
            sbagliati = numpy_livelli(1.0, dE, 0, 6, r.N_fis, -Dc)
            self.assertTrue(dentro(iv, giusti, tol=1e-12), dE)
            fuori = sum(not (lo <= Fraction(float(v)) <= hi) for lo, hi, v in zip(iv.bassi, iv.alti, sbagliati))
            self.assertEqual(fuori, 5 if dE == 0.0 else 6, dE)   # con dE = 0 il livello N = 0 vale 0 per entrambi i segni

    def test_taglio_forzato_piccolo(self):
        """Mutanti: blocco esterno senza −dE e senza Young; η col segno sbagliato; controllo t > hi tolto.
        A L forzato piccolo (campo forte, dE = 100 B) la coda decide: il codice vero o RIFIUTA (FuoriDominio) o
        restituisce un intervallo che contiene il valore vero (numpy a L = 400). I mutanti accettano intervalli
        stretti attorno all'autovalore TRONCATO, che il valore vero non rispetta."""
        r = RS.RotoreSferico(B=1.0, dE=100.0, M=0)
        veri = numpy_livelli(1.0, 100.0, 0, 6, 400)
        rifiuti, accettati = 0, 0
        for L in range(8, 41, 2):
            try:
                iv = RS.livelli_sfera_garantiti(r, 6, L_iniziale=L, L_limite=L, scadenza=20)
            except RS.FuoriDominio:
                rifiuti += 1
                continue
            accettati += 1
            self.assertEqual(iv.N, L)
            self.assertTrue(dentro(iv, veri, tol=1e-9), (L, iv.stringhe, veri))
            # l'autovalore troncato a L (ciò che un solutore senza garanzia restituirebbe) è dentro solo se
            # la coda è già trascurabile: a L ≤ 12 il livello 5 troncato dista > 1e-6 dal vero
            if L <= 12:
                tronc = numpy_livelli(1.0, 100.0, 0, 6, L)
                self.assertGreater(abs(tronc[5] - veri[5]), 1e-6)
        self.assertGreater(rifiuti, 0, "a L = 8 il codice vero deve rifiutare (t ≤ hi per il livello 5)")
        self.assertGreater(accettati, 0)

    def test_taglio_forzato_con_distorsione(self):
        """Come sopra, con D_c: f(L+1) resta il minimo del blocco esterno solo se f cresce (L < N_fis)."""
        Dc = 1e-5
        r = RS.RotoreSferico(B=1.0, dE=100.0, M=1, Dc=Dc)
        veri = numpy_livelli(1.0, 100.0, 1, 5, r.N_fis, Dc)
        for L in (10, 14, 20, 30):
            try:
                iv = RS.livelli_sfera_garantiti(r, 5, L_iniziale=L, L_limite=L, scadenza=20)
            except RS.FuoriDominio:
                continue
            self.assertTrue(dentro(iv, veri, tol=1e-9), (L, iv.stringhe, veri))

    def test_taglio_al_limite_controesempi(self):
        """NEMESIS 10/11: mutanti vivi «t senza −D» e «modello finito già a L = N_fis − 1». Casi trovati da un fuzz
        contro numpy: al taglio forzato il codice rifiuta o contiene il vero; i due mutanti danno intervalli sbagliati."""
        casi = ((RS.RotoreSferico(B=1.0, dE=312.6214358127753, M=2), 3, 9),
                (RS.RotoreSferico(B=1.0, dE=21.70028901484712, M=5, Dc=0.006828698540348708), 2, 7))
        for r, k, L in casi:
            Lv = r.N_fis if r.N_fis is not None else L + 80
            veri = numpy_livelli(r.B, r.dE, r.M, k, Lv, r.Dc)
            try:
                iv = RS.livelli_sfera_garantiti(r, k, L_iniziale=L, L_limite=L, scadenza=20, larghezza=1e-10)
            except RS.FuoriDominio:
                continue
            self.assertTrue(dentro(iv, veri, tol=1e-9), (r, L, iv.stringhe, veri))

    def test_non_oltre_N_fis(self):
        """NEMESIS 10/11 (mutante vivo: L_limite non ristretto a N_fis). Con L_iniziale piccolo il ciclo su L non deve
        superare N_fis: oltre, la matrice contiene stati fuori modello e gli intervalli escono dal vero."""
        r = RS.RotoreSferico(B=1.0, dE=200.0, Dc=0.005)
        veri = numpy_livelli(1.0, 200.0, 0, 2, r.N_fis, 0.005)
        iv = RS.livelli_sfera_garantiti(r, 2, L_iniziale=2, scadenza=20)
        self.assertLessEqual(iv.N, r.N_fis)
        self.assertTrue(dentro(iv, veri, tol=1e-9), (iv.stringhe, veri))

    def test_specifica_blocco_esterno(self):
        """NEMESIS 10/11 (mutanti vivi su t e su η: −D tolto, f(L+2), c²(L−1), η/2 nella diagonale). Specifica
        ricalcolata in numpy: η = dE·√c²(L), t = f(L+1) − dE − dE²c²(L)/η. (1) se accetta, t > alto_j (altrimenti
        doveva rifiutare); (2) se accetta, basso_j ≤ λ_j(A − η e_L e_Lᵀ) + margine."""
        provati = rifiuti = 0
        for dE, M, k in ((5.0, 0, 1), (14.520956109204292, 3, 2), (312.6214358127753, 2, 3), (40.0, 1, 2)):
            for L in range(M + k, M + k + 14):
                Ns = np.arange(M, L + 1)
                x = Ns * (Ns + 1.0)
                c2 = [((N + 1) ** 2 - M * M) / ((2 * N + 1) * (2 * N + 3)) for N in range(M, L + 1)]
                T = np.diag(x) - dE * (np.diag(np.sqrt(c2[:-1]), 1) + np.diag(np.sqrt(c2[:-1]), -1))
                eta = dE * math.sqrt(c2[-1])
                t = (L + 1) * (L + 2) - dE - dE * dE * c2[-1] / eta
                lam = np.linalg.eigvalsh(T)[:k]
                TA = T.copy()
                TA[-1, -1] -= eta
                lamA = np.linalg.eigvalsh(TA)[:k]
                margine = 1e-6 * max(1.0, abs(lam[-1]))
                try:
                    iv = RS.livelli_sfera_garantiti(RS.RotoreSferico(B=1.0, dE=dE, M=M), k, L_iniziale=L, L_limite=L,
                                                    scadenza=20, larghezza=1e-10)
                except RS.FuoriDominio:
                    rifiuti += 1
                    continue
                provati += 1
                self.assertGreater(t, float(max(iv.alti)) - 1e-9 * max(1.0, abs(t)), (dE, M, k, L, t, iv.stringhe))
                for lo, la in zip(iv.bassi, lamA):
                    self.assertLessEqual(float(lo), la + margine, (dE, M, k, L, float(lo), la))
        self.assertGreater(provati, 10)
        self.assertGreater(rifiuti, 0)

    def test_stima_float_spostata(self):
        """Mutante: condizione dei conteggi indebolita (n_hi ≥ j, n_lo ≤ j+1). La stima numpy NON entra nella
        dimostrazione: anche spostata di ±1e-6 e di ±0,3 B gli intervalli devono contenere i valori esatti."""
        originale = RS._approssimati
        esatti = [N * (N + 1) for N in range(6)]
        try:
            for spost in (1e-6, -1e-6, 0.3, -0.3):
                RS._approssimati = lambda r, L, k, s=spost: originale(r, L, k) + s
                iv = RS.livelli_sfera_garantiti(RS.RotoreSferico(B=1.0, dE=0.0), 6, scadenza=20)
                self.assertTrue(dentro(iv, esatti), (spost, iv.stringhe))
                for lo, hi, e in zip(iv.bassi, iv.alti, esatti):
                    self.assertLess(lo, Fraction(e), spost)      # strettamente dentro: il bordo non coincide
                    self.assertGreater(hi, Fraction(e), spost)
        finally:
            RS._approssimati = originale

    def test_limite_inferiore_sotto_il_vero(self):
        """Ogni basso ≤ vero ≤ alto con il vero preso da un calcolo a L molto più grande di iv.N (tol = rumore float)."""
        for dE, M in ((30.0, 0), (300.0, 2)):
            r = RS.RotoreSferico(B=1.0, dE=dE, M=M)
            iv = RS.livelli_sfera_garantiti(r, 6, scadenza=20)
            veri = numpy_livelli(1.0, dE, M, 6, max(400, 4 * iv.N))
            for lo, hi, v in zip(iv.bassi, iv.alti, veri):
                self.assertLessEqual(lo, Fraction(float(v)) + Fraction(1e-10), (dE, M))
                self.assertGreaterEqual(hi, Fraction(float(v)) - Fraction(1e-10), (dE, M))


if __name__ == "__main__":
    unittest.main()
