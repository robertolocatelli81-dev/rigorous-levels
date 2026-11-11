"""Test di qraft_ra/molecola_iperfine_garantita.py (10/11/2026). PREREG e misure: gtm/qraft_iperfine_20261110/.
Ogni chiamata porta scadenza: un mutante che fa girare il ciclo a vuoto deve FALLIRE, non bloccare il banco."""
import importlib.util
import sys
import unittest
from fractions import Fraction
from pathlib import Path

import numpy as np


FLINT = importlib.util.find_spec("flint") is not None
DIATOMIC = importlib.util.find_spec("diatomic") is not None
if FLINT:
    from qraft_ra import molecola_iperfine_garantita as MI  # noqa: E402
    from qraft_ra import rotore_sferico_garantito as RS  # noqa: E402

# Gregory et al. 2016 (PRA 94, 041403(R)), costanti loro, in Hz
GREG = dict(B=490173.994e3, D=213.0, c1=29.4, c2=196.8, c3=192.4, c4=19.019e3, eQq1=-809.29e3, eQq2=59.98e3)
G_R, G_RB, G_CS = 0.0062, 1.8295, 0.7331


def rbcs(B_G, dE=0.0, **sost):
    kw = dict(GREG, z_N=MI.zeeman_hz(G_R, B_G), z1=MI.zeeman_hz(G_RB, B_G), z2=MI.zeeman_hz(G_CS, B_G), dE=dE)
    kw.update(sost)
    return MI.MolecolaSigma(3, 7, **kw)


def numpy_settore(m, dMF, L, k):
    stati, el = MI._matrice_simbolica(m, dMF, L)
    n = len(stati)
    M = np.zeros((n, n))
    for (i, j), t in el.items():
        M[i, j] = M[j, i] = MI._float_di(t)
    return np.linalg.eigvalsh(M)[:k]


def dentro(iv, valori, tol=0.0):
    return all(lo - Fraction(tol) <= Fraction(float(v)) <= hi + Fraction(tol)
               for lo, hi, v in zip(iv.bassi, iv.alti, valori))


@unittest.skipUnless(FLINT, "python-flint assente")
class TestRiduzioni(unittest.TestCase):
    def test_riduzione_alla_sfera(self):
        """P2: senza spin e senza iperfine gli intervalli sono quelli del rotore sferico (stesse stringhe)."""
        for B, dE, M in ((1.0, 5.0, 0), (490.173994, 100.0, 1), (1.0, 0.3, -2)):
            a = MI.livelli_molecola_garantiti(MI.MolecolaSigma(0, 0, B=B, dE=dE), 2 * M, 4, scadenza=60)
            b = RS.livelli_sfera_garantiti(RS.RotoreSferico(B=B, dE=dE, M=M), 4, scadenza=60)
            self.assertEqual(a.stato, "GARANTITO")
            for (lo, hi), (lo2, hi2) in zip(zip(a.bassi, a.alti), zip(b.bassi, b.alti)):
                self.assertLess(abs(float(lo - lo2)), 1e-12 * max(abs(float(lo)), B))
                self.assertLess(abs(float(hi - hi2)), 1e-12 * max(abs(float(hi)), B))

    def test_riduzione_con_distorsione(self):
        a = MI.livelli_molecola_garantiti(MI.MolecolaSigma(0, 0, B=1.0, dE=2.0, D=1e-4), 0, 5, scadenza=60)
        b = RS.livelli_sfera_garantiti(RS.RotoreSferico(B=1.0, dE=2.0, Dc=1e-4), 5, scadenza=60)
        veri = numpy_settore(MI.MolecolaSigma(0, 0, B=1.0, dE=2.0, D=1e-4), 0, 60, 5)
        self.assertEqual((a.stato, b.stato), ("GARANTITO", "GARANTITO"))
        self.assertTrue(dentro(a, veri, tol=1e-12) and dentro(b, veri, tol=1e-12))
        for (lo, hi), (lo2, hi2) in zip(zip(a.bassi, a.alti), zip(b.bassi, b.alti)):
            self.assertTrue(max(lo, lo2) <= min(hi, hi2))         # i due intervalli validi si intersecano

    def test_campo_zero_spin_liberi(self):
        """Solo rotazione + Zeeman nucleare: livelli esatti B N(N+1) − z₁M₁ − z₂M₂ − z_N M_N."""
        m = MI.MolecolaSigma(1, 3, B=1.0, z_N=0.01, z1=0.1, z2=0.2)
        stati = MI._stati(m, 2, 3)
        esatti = sorted(N * (N + 1) - 0.01 * MN - 0.1 * dM1 / 2 - 0.2 * dM2 / 2 for N, MN, dM1, dM2 in stati)[:6]
        iv = MI.livelli_molecola_garantiti(m, 2, 6, scadenza=60)
        self.assertTrue(dentro(iv, esatti), (iv.stringhe, esatti))
        self.assertEqual(iv.stato, "GARANTITO")


@unittest.skipUnless(FLINT, "python-flint assente")
class TestGregory2016(unittest.TestCase):
    """Riga M_F = +5 → +6 a 181,541 G (stato stirato: 1 stato in N = 1): f_the = 980 384,98 kHz."""

    def test_stirato_entro_100Hz(self):
        iv0 = MI.livelli_molecola_garantiti(rbcs(181.541), 10, 1, L_iniziale=3, L_limite=3, scadenza=120, larghezza=1e-11)
        iv6 = MI.livelli_molecola_garantiti(rbcs(181.541), 12, 1, L_iniziale=3, L_limite=3, scadenza=120, larghezza=1e-11)
        lo, hi = MI.transizione(iv0, 0, iv6, 0)
        self.assertLess(float(hi - lo), 0.01)
        centro = float(lo + hi) / 2
        self.assertLess(abs(centro - 980384.98e3), 100.0, centro)

    def test_segno_tensoriale_controllo_positivo(self):
        """Col segno del CODICE diatomic-py 2.1.0 (+√6 c₃, cioè c₃ → −c₃ qui) la stessa riga sbaglia di ~800 Hz."""
        m = rbcs(181.541, c3=-GREG["c3"])
        e0 = numpy_settore(m, 10, 3, 1)[0]
        e6 = numpy_settore(m, 12, 3, 1)[0]
        self.assertGreater(abs((e6 - e0) - 980384.98e3), 800.0)


@unittest.skipUnless(FLINT, "python-flint assente")
class TestDimostrazione(unittest.TestCase):
    def test_conta_sotto_banda(self):
        import flint
        fl = flint
        diag = [fl.arb(v) for v in (-3, -1, 0, 2, 5)]
        for x, atteso in ((-4, 0), (-2, 1), (0.5, 3), (3, 4), (10, 5)):
            self.assertEqual(MI._conta_sotto_banda(fl, diag, {}, 0, fl.arb(x)), atteso, x)
        d2, f2 = [fl.arb(0), fl.arb(0)], {(1, 0): fl.arb(4)}          # [[0,4],[4,0]]: ±4
        self.assertEqual(MI._conta_sotto_banda(fl, d2, f2, 1, fl.arb(-5)), 0)
        self.assertEqual(MI._conta_sotto_banda(fl, d2, f2, 1, fl.arb(0.5)), 1)
        self.assertEqual(MI._conta_sotto_banda(fl, d2, f2, 1, fl.arb(5)), 2)
        self.assertIsNone(MI._conta_sotto_banda(fl, d2, f2, 1, fl.arb(0)))
        # fuori banda ignorato per costruzione: w = 0 non deve vedere l'accoppiamento
        self.assertEqual(MI._conta_sotto_banda(fl, d2, f2, 0, fl.arb(0.5)), 2)

    def test_stima_float_spostata(self):
        """La stima numpy non entra nella dimostrazione: spostata di ±1 kHz e ±0,3 B gli intervalli contengono ancora."""
        originale = MI._approssimati
        m = MI.MolecolaSigma(1, 3, B=1e6, z_N=100.0, z1=1e3, z2=2e3, c4=500.0)
        veri = numpy_settore(m, 2, 8, 6)
        try:
            for spost in (1e3, -1e3, 3e5, -3e5):
                MI._approssimati = lambda stati, el, k, s=spost: originale(stati, el, k) + s
                iv = MI.livelli_molecola_garantiti(m, 2, 6, scadenza=60)
                self.assertTrue(dentro(iv, veri, tol=1e-6), (spost, iv.stringhe, veri))
        finally:
            MI._approssimati = originale

    def test_taglio_forzato_piccolo(self):
        """Campo elettrico forte (dE = 50 B): a L forzato piccolo il codice RIFIUTA o contiene il vero (L = 20)."""
        m = MI.MolecolaSigma(1, 1, B=1.0, dE=50.0, c4=0.01, z1=0.02, z2=0.03)
        veri = numpy_settore(m, 0, 20, 4)
        rifiuti, accettati = 0, 0
        for L in range(2, 13, 2):
            try:
                iv = MI.livelli_molecola_garantiti(m, 0, 4, L_iniziale=L, L_limite=L, scadenza=60)
            except MI.FuoriDominio:
                rifiuti += 1
                continue
            accettati += 1
            self.assertTrue(dentro(iv, veri, tol=1e-9), (L, iv.stringhe, veri))
            if L <= 4:
                self.assertGreater(abs(numpy_settore(m, 0, L, 4)[3] - veri[3]), 1e-6)
        self.assertGreater(rifiuti, 0)
        self.assertGreater(accettati, 0)

    def test_riferimento_sbagliato_escluso(self):
        """Controllo positivo: gli intervalli (larghi ~7 mHz) ESCLUDONO (a) il modello col segno di c₃ del codice
        diatomic-py (≈ 800 Hz più in là) e (b) il valore vero spostato di ±1 Hz. Il controllo «ristretto 10×» non è
        applicabile qui: la larghezza da η supera l'errore di troncamento (come il C1 della sfera, dichiarato)."""
        m = rbcs(181.541)
        iv = MI.livelli_molecola_garantiti(m, 12, 1, L_iniziale=3, L_limite=3, scadenza=120, larghezza=1e-11)
        vero = numpy_settore(m, 12, 7, 1)[0]
        sbagliato = numpy_settore(rbcs(181.541, c3=-GREG["c3"]), 12, 7, 1)[0]
        self.assertTrue(dentro(iv, [vero], tol=1e-6))
        self.assertLess(float(iv.alti[0] - iv.bassi[0]), 0.1)
        for v in (sbagliato, vero + 1.0, vero - 1.0):
            self.assertFalse(iv.bassi[0] <= Fraction(float(v)) <= iv.alti[0], v)


    def test_limite_esterno_formula(self):
        """Specifica del blocco esterno: g coincide con la formula in Fraction (K dalle norme Arb) e t = g − ‖V‖²/η con
        η = ‖V‖, cioè t = g − ‖V‖. Dall'11/11 la formula è −(K_T+K_Q) − dE (compressione di operatori limitati), non più
        −3(K_T+K_Q) − 2dE: qui si fissa ANCHE il coefficiente, ricalcolando g a mano per un caso."""
        import flint
        fl = flint
        vecchia = fl.ctx.prec
        fl.ctx.prec = 128
        try:
            m = MI.MolecolaSigma(2, 1, B=1.0, D=1e-3, c1=0.2, c2=0.3, c3=0.4, c4=0.5, eQq1=0.7, z_N=0.11, z1=0.13, z2=0.17, dE=2.0)
            KT, KQ = MI._norma_spin(fl, m)
            normaV = fl.arb(3)
            for dMF, L in ((1, 4), (7, 2), (-3, 6)):
                g, eta, t = MI._limite_esterno(fl, m, dMF, L, normaV)
                K_frac = Fraction(float((KT + KQ).mid()))
                atteso = MI._g_esterno(m, dMF, L + 1, K_frac)
                self.assertLess(abs(float(g.mid()) - float(atteso)), 1e-9, (dMF, L))
                self.assertEqual(eta, 3.0)
                self.assertLess(abs(float((g - t).mid()) - 3.0), 1e-12)
                # il termine Zeeman rotazionale usa min(N, |M_F| + I₁ + I₂): a L = 4, dMF = 1 → min(5, 2) = 2
                self.assertLess(abs(float(atteso - MI._g_esterno(m, 1, 5, K_frac))), 1e-12) if dMF == 1 else None
            # coefficienti fissati a mano: I₁ = 1, I₂ = ½, L = 4 → N = 5, x = 30
            m1 = MI.MolecolaSigma(2, 1, B=1.0, D=1e-3, c1=0.2, c2=0.3, c4=0.5, dE=2.0, z_N=0.11, z1=0.13, z2=0.17)
            KT, KQ = MI._norma_spin(fl, m1)
            self.assertEqual(float((KT + KQ).mid()), 0.0)                     # senza c3 ed eQq: K = 0
            g, eta, t = MI._limite_esterno(fl, m1, 1, 4, fl.arb(1))
            a_mano = 30 - 1e-3 * 900 - (0.11 * 2 + 0.13 * 1 + 0.17 * 0.5) - (0.2 * 1 + 0.3 * 0.5) * 6 - 0.5 * 2 * 1.5 - 2.0
            self.assertLess(abs(float(g.mid()) - a_mano), 1e-12)
            m2 = MI.MolecolaSigma(2, 1, B=1.0, c3=0.4, eQq1=0.7)
            KT, KQ = MI._norma_spin(fl, m2)
            g2, _, _ = MI._limite_esterno(fl, m2, 1, 4, fl.arb(1))
            self.assertLess(abs(float(g2.mid()) - (30 - float((KT + KQ).mid()))), 1e-12)   # coefficiente 1 su K
        finally:
            fl.ctx.prec = vecchia

    def test_g_non_crescente_rifiuta(self):
        """Mutante vivo 10/11: controllo «g crescente» tolto. Con c₁ = 100 B il limite di Gershgorin non domina
        prima di N ≈ 50: il codice deve RIFIUTARE entro L_limite = 16 (il mutante accetta)."""
        self.assertFalse(MI._g_crescente(MI.MolecolaSigma(2, 0, B=1.0, c1=100.0), 0, 5))
        self.assertTrue(MI._g_crescente(MI.MolecolaSigma(2, 0, B=1.0, c1=1.0), 0, 5))
        with self.assertRaises(MI.FuoriDominio):
            MI.livelli_molecola_garantiti(MI.MolecolaSigma(2, 0, B=1.0, c1=100.0), 0, 3, scadenza=60)
        iv = MI.livelli_molecola_garantiti(MI.MolecolaSigma(2, 0, B=1.0, c1=1.0), 0, 3, scadenza=60)
        self.assertEqual(iv.stato, "GARANTITO")
        # z_N conta solo finché N+1 ≤ |M_F| + I₁ + I₂: con z_N = 100 e M_F = 0, I = 1 → M_max = 1 → già a N = 1 non pesa
        self.assertTrue(MI._g_crescente(MI.MolecolaSigma(2, 0, B=1.0, z_N=100.0), 0, 1))
        self.assertFalse(MI._g_crescente(MI.MolecolaSigma(2, 0, B=1.0, z_N=100.0), 20, 1))


    def test_norma_rettangolare(self):
        """Mutante vivo 10/11: ‖V‖₂ ≤ ‖V‖_∞ è FALSO per V rettangolare (V = [1;1]: ‖V‖₂ = √2, ‖V‖_∞ = 1).
        Il limite √(‖V‖₁‖V‖_∞) deve essere ≥ ‖V‖₂."""
        import flint
        fl = flint
        righe = {0: fl.arb(1), 1: fl.arb(1)}          # due righe, somma assoluta 1 ciascuna
        colonne = {0: fl.arb(2)}                        # una colonna, somma 2
        lim = MI._norma_1_inf(fl, righe, colonne)
        self.assertGreaterEqual(float(lim.mid()), 2 ** 0.5 - 1e-12, lim)
        # V = [[1, 1]] (una riga, due colonne): ‖V‖₂ = √2, ‖V‖₁ = 1
        lim2 = MI._norma_1_inf(fl, {0: fl.arb(2)}, {0: fl.arb(1), 1: fl.arb(1)})
        self.assertGreaterEqual(float(lim2.mid()), 2 ** 0.5 - 1e-12, lim2)

    def test_N_fis_al_bordo_e_parita(self):
        """Mutanti vivi 10/11: N(N+1) < B/(2D) in senso stretto (B/(2D) = 42 → N_fis = 5); 2M_F di parità sbagliata
        è FuoriDominio con il motivo «parità», non un settore vuoto."""
        self.assertEqual(MI.MolecolaSigma(0, 0, B=84.0, D=1.0).N_fis, 5)
        self.assertEqual(MI.MolecolaSigma(0, 0, B=84.0 + 1e-9, D=1.0).N_fis, 6)
        with self.assertRaisesRegex(MI.FuoriDominio, "parità"):
            MI.livelli_molecola_garantiti(MI.MolecolaSigma(1, 0, B=1.0), 0, 1, scadenza=10)
        with self.assertRaisesRegex(MI.FuoriDominio, "parità"):
            MI.livelli_molecola_garantiti(MI.MolecolaSigma(1, 1, B=1.0), 1, 1, scadenza=10)

    def test_g_crescente_con_distorsione(self):
        """Mutante vivo 10/11 (controllo «g crescente» tolto): con D = 0,005 B e c₁ = 4 B gli incrementi h(N) sono
        negativi a N = 8 < N_fis = 9, quindi la prova NON è ammessa per L ≤ 7 anche se g(L+1) > alto_j; il codice
        vero dimostra solo a L ≥ 8 e il risultato deve stare sotto il vero calcolato sul modello intero (N ≤ 9)."""
        m = MI.MolecolaSigma(2, 0, B=1.0, D=0.005, c1=4.0)
        self.assertEqual(m.N_fis, 9)
        self.assertFalse(MI._g_crescente(m, 0, 5))
        self.assertTrue(MI._g_crescente(m, 0, 9))
        for L in range(2, 8):
            with self.assertRaises(MI.FuoriDominio, msg=L):
                MI.livelli_molecola_garantiti(m, 0, 3, L_iniziale=L, L_limite=L, scadenza=30)
        iv = MI.livelli_molecola_garantiti(m, 0, 3, scadenza=60)
        self.assertGreaterEqual(iv.N, 8)
        self.assertTrue(dentro(iv, numpy_settore(m, 0, 9, 3), tol=1e-12))


    def test_mai_stati_oltre_N_fis(self):
        """Mutante vivo 10/11: con D > 0 la matrice costruita per V non deve contenere stati con N > N_fis
        (fuori modello: conservativo nei numeri, ma non è la H dichiarata)."""
        originale = MI._matrice_simbolica
        visti = []

        def spia(m, dMF, Lmax, *resto):
            visti.append(Lmax)
            return originale(m, dMF, Lmax, *resto)
        MI._matrice_simbolica = spia
        try:
            m = MI.MolecolaSigma(0, 0, B=1.0, dE=0.5, D=0.01)        # N_fis = 6
            MI.livelli_molecola_garantiti(m, 0, 3, L_iniziale=5, L_limite=5, scadenza=30)
            MI.livelli_molecola_garantiti(m, 0, 3, L_iniziale=4, L_limite=4, scadenza=30)
        finally:
            MI._matrice_simbolica = originale
        self.assertTrue(visti and max(visti) <= 6, visti)


    def test_ciclo_largo_tiene_il_piu_stretto(self):
        """NEMESIS M20 (vivo): ciclo che si ferma al secondo LARGO. Caso misurato (B = 490,17, dE = 100, M = 1,
        larghezza 1e-16): L = 6 LARGO 2,6e-7, L = 8 LARGO 2,4e-12 (dimezza), L = 10 2,4e-12 (non dimezza) → si
        restituisce il più stretto, L = 8, non il primo."""
        iv = MI.livelli_molecola_garantiti(MI.MolecolaSigma(0, 0, B=490.173994, dE=100.0), 2, 4, scadenza=120, larghezza=1e-16)
        self.assertEqual(iv.N, 8)
        self.assertLess(iv.larghezza_max, 1e-10)
        self.assertEqual(iv.stato, "LARGO")

    def test_segno_eta_e_blocco_esterno(self):
        """Il limite inferiore sta sotto il vero anche dove la coda pesa: basso ≤ vero(L+6) in ogni livello."""
        m = MI.MolecolaSigma(1, 1, B=1.0, dE=20.0, c3=0.05, eQq1=0.0, c1=0.01)
        for L in (4, 6, 8):
            try:
                iv = MI.livelli_molecola_garantiti(m, 2, 5, L_iniziale=L, L_limite=L, scadenza=60)
            except MI.FuoriDominio:
                continue
            veri = numpy_settore(m, 2, L + 6, 5)
            for lo, hi, v in zip(iv.bassi, iv.alti, veri):
                self.assertLessEqual(lo, Fraction(float(v)) + Fraction(1e-10))
                self.assertGreaterEqual(hi, Fraction(float(v)) - Fraction(1e-10))



def _spin(dI):
    """Matrici cartesiane (Ix, Iy, Iz) per 2I = dI, base M = I … −I (numpy, indipendenti dal modulo)."""
    I = dI / 2
    Ms = [I - n for n in range(dI + 1)]
    Ip = np.zeros((dI + 1, dI + 1))
    for a in range(1, dI + 1):
        Ip[a - 1, a] = np.sqrt(I * (I + 1) - Ms[a] * (Ms[a] + 1))
    Ix, Iy, Iz = (Ip + Ip.T) / 2, (Ip - Ip.T) / 2j, np.diag(Ms)
    return Ix, Iy, Iz, Ip


@unittest.skipUnless(FLINT, "python-flint assente")
class TestSpecificaNEMESIS(unittest.TestCase):
    """NEMESIS 10/11: mutanti vivi sul commit 21f9f09c (K_T senza √6, K_Q /16, ‖V‖/2, V senza N = L+2,
    pivot incerto trattato come zero, g crescente non controllato al primo passo)."""

    def test_norme_spin_maggiorano_la_norma_vera(self):
        import flint
        vecchia = flint.ctx.prec
        flint.ctx.prec = 128
        try:
            for d1, d2, c3, e1, e2 in ((3, 7, 192.4, -809.29e3, 59.98e3), (2, 2, -0.7, 0.3, -1.1), (1, 5, 2.0, 0.0, 4.0)):
                m = MI.MolecolaSigma(d1, d2, B=1.0, c3=c3, eQq1=e1, eQq2=e2)
                KT, KQ = MI._norma_spin(flint, m)
                x1, y1, z1, p1 = _spin(d1)
                x2, y2, z2, p2 = _spin(d2)
                A = [np.kron(o, np.eye(d2 + 1)) for o in (x1, y1, z1)]
                Bm = [np.kron(np.eye(d1 + 1), o) for o in (x2, y2, z2)]
                Ap, Bp = A[0] + 1j * A[1], Bm[0] + 1j * Bm[1]
                Am, Bmm = Ap.conj().T, Bp.conj().T
                T = [0.5 * Ap @ Bp, -0.5 * (Ap @ Bm[2] + A[2] @ Bp), (3 * A[2] @ Bm[2] - sum(a @ b for a, b in zip(A, Bm))) / np.sqrt(6),
                     0.5 * (Am @ Bm[2] + A[2] @ Bmm), 0.5 * Am @ Bmm]
                kt = np.sqrt(6) * abs(c3) * sum(np.linalg.norm(t, 2) for t in T)
                self.assertGreaterEqual(float(KT.upper()), kt * (1 - 1e-12), (d1, d2))
                kq = 0.0
                for dI, e in ((d1, e1), (d2, e2)):
                    if e == 0.0:
                        continue
                    x, y, z, p = _spin(dI)
                    I = dI / 2
                    norm = (3 * I * I - I * (I + 1)) / np.sqrt(6)          # T²₀|I,I⟩ = 1 (normalizzazione diatomic-py)
                    pm = p.conj().T
                    TQ = [0.5 * p @ p, -0.5 * (p @ z + z @ p), (3 * z @ z - I * (I + 1) * np.eye(dI + 1)) / np.sqrt(6),
                          0.5 * (pm @ z + z @ pm), 0.5 * pm @ pm]
                    kq += abs(e) / 4 * sum(np.linalg.norm(t / norm, 2) for t in TQ)
                self.assertGreaterEqual(float(KQ.upper()), kq * (1 - 1e-12), (d1, d2))
        finally:
            flint.ctx.prec = vecchia

    def test_eta_maggiora_la_norma_di_V(self):
        """η restituito (= limite su ‖V‖₂) ≥ ‖V‖₂ in numpy e uguale a √(‖V‖₁‖V‖_∞), V = righe N ≤ L × colonne N ∈ {L+1, L+2}."""
        for m, dMF, L in ((MI.MolecolaSigma(2, 3, B=1.0, c3=0.05, eQq1=0.2), 1, 3),
                          (MI.MolecolaSigma(1, 1, B=1.0, dE=0.4, c3=0.03), 0, 4),
                          (MI.MolecolaSigma(2, 2, B=1.0, dE=0.3, eQq1=0.1, eQq2=-0.2, c3=0.02), 2, 3)):
            iv = MI.livelli_molecola_garantiti(m, dMF, 2, L_iniziale=L, L_limite=L, scadenza=60)
            stati, el = MI._matrice_simbolica(m, dMF, L + 2)
            n_in = sum(1 for s in stati if s[0] <= L)
            V = np.zeros((n_in, len(stati) - n_in))
            for (i, j), t in el.items():
                if i < n_in <= j:
                    V[i, j - n_in] = MI._float_di(t)
            self.assertGreater(np.linalg.norm(V, 2), 0.0)
            self.assertGreaterEqual(iv.alpha, np.linalg.norm(V, 2) * (1 - 1e-12), (dMF, L))
            # specifica: η = √(‖V‖₁‖V‖_∞) sulla V COMPLETA (colonne N = L+1 e L+2)
            stima = np.sqrt(np.abs(V).sum(axis=0).max() * np.abs(V).sum(axis=1).max())
            self.assertLess(abs(iv.alpha - stima), 1e-9 * stima, (dMF, L, iv.alpha, stima))

    def test_pivot_incerto_non_e_zero(self):
        """Un elemento fuori diagonale che è una palla contenente 0 NON va scartato: il conteggio resta incerto."""
        import flint
        d = [flint.arb(1), flint.arb(1)]
        f = {(1, 0): flint.arb(0, 0.5)}                       # [0 ± 0,5]
        self.assertIsNone(MI._conta_sotto_banda(flint, d, f, 1, flint.arb(0.9)))

    def test_g_crescente_primo_passo(self):
        """Con D > 0 l'incremento g(L+2) − g(L+1) va controllato anche al primo passo: z_N grande e M_max = L+2."""
        m = MI.MolecolaSigma(2, 0, B=1.0, D=1e-4, z_N=100.0)
        self.assertFalse(MI._g_crescente(m, 6, 3))              # h(3) < 0: g(5) < g(4)
        self.assertTrue(MI._g_crescente(m, 6, 4))

    def test_parita_rifiutata_col_suo_motivo(self):
        """Mutante vivo: controllo di parità tolto → FuoriDominio con il motivo sbagliato («non ha k stati»)."""
        with self.assertRaisesRegex(MI.FuoriDominio, "parità"):
            MI.livelli_molecola_garantiti(MI.MolecolaSigma(1, 0, B=1.0), 0, 1, scadenza=5)

    def test_precisione_ripristinata_dopo_eccezione(self):
        import flint
        p = flint.ctx.prec
        with self.assertRaises(MI.TempoScaduto):
            MI.livelli_molecola_garantiti(rbcs(181.5, dE=1e9), 8, 8, scadenza=1e-6)
        self.assertEqual(flint.ctx.prec, p)
        with self.assertRaises(MI.FuoriDominio):
            MI.livelli_molecola_garantiti(MI.MolecolaSigma(2, 0, B=1.0, c1=100.0), 0, 3, scadenza=60)
        self.assertEqual(flint.ctx.prec, p)

@unittest.skipUnless(FLINT and DIATOMIC, "python-flint o diatomic-py assenti")
class TestCostruzioneContraDiatomicPy(unittest.TestCase):
    def test_elementi_identici(self):
        """P1 su L = 2 (veloce): con c₃ → −c₃ (segno del codice diatomic-py opposto al suo articolo) ogni elemento di
        ogni settore coincide entro 1e-12 relativo; col segno uguale il peggiore è un elemento c₃ (≈ 924 Hz)."""
        import flint
        import scipy.constants as sc
        from diatomic import operators as op
        from diatomic.systems import SingletSigmaMolecule
        h = sc.h
        mol = SingletSigmaMolecule.from_preset("Rb87Cs133")
        mol.Nmax = 2
        B_G, E = 181.5, 10.0
        H = ((op.hyperfine_ham(mol) + op.zeeman_ham(mol) * (B_G * 1e-4) + op.dc_ham(mol) * (E * 100)) / h).real
        basi = list(op.uncoupled_basis_iter(2, mol.Ii[0], mol.Ii[1]))
        idx = {(N, int(MN), int(round(2 * float(M1))), int(round(2 * float(M2)))): i
               for i, (N, MN, M1, M2) in enumerate(basi)}
        vecchia = flint.ctx.prec
        flint.ctx.prec = 128
        try:
            for segno, atteso in ((-1, "uguale"), (+1, "diverso")):
                m = MI.MolecolaSigma(3, 7, B=mol.Brot / h, D=mol.Drot / h, c1=mol.Ci[0] / h, c2=mol.Ci[1] / h,
                                     c3=segno * mol.C3 / h, c4=mol.C4 / h, eQq1=mol.Qi[0] / h, eQq2=mol.Qi[1] / h,
                                     z_N=mol.MuN * B_G * 1e-4 / h, z1=mol.Mui[0] * B_G * 1e-4 / h,
                                     z2=mol.Mui[1] * B_G * 1e-4 / h, dE=mol.d0 * E * 100 / h)
                peggio = 0.0
                for dMF in range(-14, 15, 2):
                    stati, el = MI._matrice_simbolica(m, dMF, 2)
                    ii = [idx[s] for s in stati]
                    sub = H[np.ix_(ii, ii)]
                    for (i, j), t in el.items():
                        peggio = max(peggio, abs(float(MI._arb_di(flint, t).mid()) - sub[i, j]))
                if atteso == "uguale":
                    self.assertLess(peggio, 1e-12 * np.abs(H).max(), peggio)
                else:
                    self.assertGreater(peggio, 900.0, peggio)
        finally:
            flint.ctx.prec = vecchia


@unittest.skipUnless(FLINT, "python-flint assente")
class TestIngressiChiusi(unittest.TestCase):
    def test_parametri(self):
        for kw in ({"due_I1": -1, "due_I2": 0, "B": 1.0}, {"due_I1": 1.5, "due_I2": 0, "B": 1.0},
                   {"due_I1": 0, "due_I2": 0, "B": 0.0}, {"due_I1": 0, "due_I2": 0, "B": float("nan")},
                   {"due_I1": 0, "due_I2": 0, "B": 1.0, "D": -1.0}, {"due_I1": 0, "due_I2": 0, "B": 1.0, "dE": -1.0},
                   {"due_I1": 1, "due_I2": 0, "B": 1.0, "eQq1": 1.0}, {"due_I1": 0, "due_I2": 0, "B": True},
                   {"due_I1": 0, "due_I2": 0, "B": 1.0, "c3": "1"}, {"due_I1": 0, "due_I2": 0, "B": 1.0, "z1": float("inf")}):
            with self.assertRaises(MI.FuoriDominio, msg=str(kw)):
                MI.MolecolaSigma(**kw)

    def test_chiamata(self):
        m = MI.MolecolaSigma(1, 1, B=1.0)
        for args, kw in (((m, 1, 2), {}), ((m, 0, 0), {}), ((m, 0, 101), {}), ((m, 0, 2), {"larghezza": 0.0}),
                         ((m, 0, 2), {"L_limite": -1}), ((m, 0, 2), {"scadenza": 0.0}), ((object(), 0, 2), {}),
                         ((m, 0, 2), {"L_iniziale": 3, "L_limite": 2}), ((m, 0, 50), {"L_limite": 1})):
            with self.assertRaises(MI.FuoriDominio, msg=str((args, kw))):
                MI.livelli_molecola_garantiti(*args, **kw)
        with self.assertRaises(MI.FuoriDominio):
            MI.livelli_molecola_garantiti(MI.MolecolaSigma(0, 0, B=1.0, D=0.01), 0, 3, L_iniziale=20)

    def test_funzioni_di_servizio_chiuse(self):
        """NEMESIS R5: zeeman_hz, dimensione_settore e transizione erano aperte (bool, IndexError, AttributeError)."""
        for args in ((True, 1.0), (1.0, float("nan")), ("1", 1.0)):
            with self.assertRaises(MI.FuoriDominio, msg=str(args)):
                MI.zeeman_hz(*args)
        with self.assertRaises(MI.FuoriDominio):
            MI.dimensione_settore(object(), 0, 1)
        m = MI.MolecolaSigma(1, 1, B=1.0)
        self.assertEqual(MI.dimensione_settore(m, 0, 1), 6)            # N=0: (½,−½),(−½,½); N=1: M_N=0: 2, M_N=±1: 1+1
        iv = MI.livelli_molecola_garantiti(m, 0, 2, scadenza=20)
        with self.assertRaises(MI.FuoriDominio):
            MI.transizione(iv, 0, iv, 2)
        with self.assertRaises(MI.FuoriDominio):
            MI.transizione(iv, -1, iv, 0)
        with self.assertRaises(MI.FuoriDominio):
            MI.transizione(object(), 0, iv, 0)
        lo, hi = MI.transizione(iv, 0, iv, 1)
        self.assertLessEqual(lo, hi)

    def test_scadenza(self):
        with self.assertRaises(MI.TempoScaduto):
            MI.livelli_molecola_garantiti(rbcs(181.5, dE=1e9), 8, 8, scadenza=1e-6)

    def test_precisione_ripristinata(self):
        import flint
        p = flint.ctx.prec
        MI.livelli_molecola_garantiti(MI.MolecolaSigma(1, 1, B=1.0, c4=0.1), 0, 2, scadenza=60)
        self.assertEqual(flint.ctx.prec, p)


if __name__ == "__main__":
    unittest.main()
