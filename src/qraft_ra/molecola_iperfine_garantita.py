# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra/molecola_iperfine_garantita.py — molecola ¹Σ (rotazione + iperfine + Zeeman + Stark) con livelli come
INTERVALLI GARANTITI [basso, alto] rispetto al troncamento N ≤ L.

    H = B N² − D (N²)² + c₁ N·I₁ + c₂ N·I₂ + c₄ I₁·I₂ − √6 c₃ T²(C)·T²(I₁,I₂) + ¼ Σ_i (eQq)_i T²(Q_i)·T²(∇E)
        − dE C¹₀(θ) − (z_N N_z + z₁ I₁z + z₂ I₂z)                                   (tutto in Hz)

Base disaccoppiata |N M_N⟩|I₁ M₁⟩|I₂ M₂⟩ con campi E e B lungo z: M_F = M_N + M₁ + M₂ è conservato e si lavora in un
settore M_F per volta. Forma di Aldegunde et al., PRA 78, 033434 (2008) eq. 3 (+c₃ I₁·T·I₂, T dipolare) e di
Blackmore et al. 2022 (articolo di diatomic-py, arXiv:2205.05686, eq. 5b: −c₃√6 T²(C)·T²(I_A,I_B)): le due coincidono
perché √6 T²(C)·T²(I₁,I₂) = 3(I₁·r̂)(I₂·r̂) − I₁·I₂ = −I₁·T·I₂.
SEGNO MISURATO (note dell'autore (non pubblicate), 10/11/2026): il CODICE diatomic-py 2.1.0 (`tensor_nuclear`)
usa +√6 c₃, cioè il segno opposto al suo articolo; con il segno dell'articolo le 16 transizioni di Gregory et al. 2016
(PRA 94, 041403(R)) sono riprodotte entro 94 Hz, con quello del codice no (fino a 1,96 kHz). Qui vale il segno
dell'articolo; il confronto con diatomic-py nei test passa c₃ → −c₃ (dichiarato).
Gli elementi di matrice sono ricostruiti in palle Arb da radici quadrate di razionali esatti (3j di sympy) e
confrontati con diatomic-py nei test (controllo della costruzione, non della dimostrazione).

Garanzia (Teschl, Teor. 4.12(i) e Cor. 4.11; argomento di qraft_ra/intervallo_garantito.py e della sfera):
  A = compressione di H su N ≤ L; V = accoppiamento di A con N ∈ {L+1, L+2} (escono da A solo lo Stark, ΔN = 1, e i
  termini di rango 2, ΔN = 2); C = blocco N ≥ L+1.
  - sopra: λ_j(H) ≤ λ_j(A);
  - sotto: H ≥ (A − η P_B) ⊕ (C − ‖V‖²/η) come forme (Young sul solo accoppiamento), P_B = proiettore sugli stati di A
    con riga non nulla in V, ‖V‖₂ ≤ √(‖V‖₁‖V‖_∞) in Arb; λ_min(C) ≥ g(L+1) con g (Gershgorin a blocchi)
      g(N) = B N(N+1) − D[N(N+1)]² − (|z_N| min(N, |M_F|+I₁+I₂) + |z₁| I₁ + |z₂| I₂) − (|c₁| I₁ + |c₂| I₂)(N+1)
             − |c₄|(I₁+1)(I₂+1)
             − (K_T + K_Q) − dE,
    crescente su [L+1, N_fis] (verificato con incrementi esatti); se t = g(L+1) − ‖V‖²/η > alto_j allora
    λ_j(H) ≥ λ_j(A − η P_B).
  - conteggi «autovalori < x» con LDLᵀ a banda in palle Arb; pivot incerto → precisione raddoppiata o punto spostato.
Con D > 0 il modello è DEFINITO su N ≤ N_fis = max{N : N(N+1) < B/(2D)} (dichiarato, come nella sfera).
Ipotesi dichiarate: le costanti float64 sono esatte; correttezza di Arb/FLINT e di sympy (3j).
PREREG e misure: note dell'autore (non pubblicate).

Cosa NON dice: che la H descriva la molecola (termini mancanti: polarizzabilità AC, campi non paralleli).
QRAFT-RA è un modello interno, non un validatore esterno.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, replace
from fractions import Fraction
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import numpy as np

from qraft_ra.intervallo_garantito import ArbAssente, FuoriDominio, Intervalli, TempoScaduto, _flint

__all__ = ["MolecolaSigma", "livelli_molecola_garantiti", "transizione", "dimensione_settore", "zeeman_hz",
           "FuoriDominio", "ArbAssente", "TempoScaduto"]

L_LIMITE = 16          # LDLᵀ a banda in Python puro: a L = 16 un settore di RbCs ha ~500 stati (secondi per conteggio)
PREC_MIN, PREC_MAX = 128, 1024
K_MAX = 100
DUE_I_MAX = 40         # 2I ≤ 40 (I ≤ 20): oltre ogni spin nucleare noto; senza tetto il settore cresce senza limite (NEMESIS 10/11)
L_LIMITE_MAX = 64      # tetto di L_limite: oltre, la costruzione O(n²) non rispetta nessuna scadenza ragionevole
MU_N_HZ_PER_T = 7.6225932188e6      # μ_N/h, CODATA 2018 (scipy.constants "nuclear magneton in MHz/T" × 1e6)


def zeeman_hz(g: float, B_gauss: float) -> float:
    """Coefficiente Zeeman in Hz: g · μ_N/h · B (B in gauss). Ingressi chiusi (FuoriDominio)."""
    return _reale(g, "g") * MU_N_HZ_PER_T * _reale(B_gauss, "B_gauss") * 1e-4


def _reale(x, nome: str, *, positivo=False, non_negativo=False) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float, np.floating)):
        raise FuoriDominio(f"{nome}: atteso un numero reale finito")
    try:
        x = float(x)
    except OverflowError:                                   # int oltre il float (es. 10**400): fuori dominio, non crash
        raise FuoriDominio(f"{nome}: atteso un numero reale finito (intero oltre il float64)") from None
    if not math.isfinite(x):
        raise FuoriDominio(f"{nome}: atteso un numero reale finito")
    if positivo and x <= 0:
        raise FuoriDominio(f"{nome}: deve essere > 0")
    if non_negativo and x < 0:
        raise FuoriDominio(f"{nome}: deve essere >= 0")
    return x


def _intero(x, nome: str, minimo: Optional[int] = None) -> int:
    if isinstance(x, bool) or not isinstance(x, (int, np.integer)):
        raise FuoriDominio(f"{nome}: atteso un intero")
    x = int(x)
    if minimo is not None and x < minimo:
        raise FuoriDominio(f"{nome}: atteso >= {minimo}")
    return x


@dataclass(frozen=True)
class MolecolaSigma:
    """Costanti in Hz. due_I1, due_I2 = 2I (interi ≥ 0). z_N, z1, z2 = g·μ_N·B/h (vedi zeeman_hz). dE = d·E/h ≥ 0."""

    due_I1: int
    due_I2: int
    B: float
    D: float = 0.0
    c1: float = 0.0
    c2: float = 0.0
    c3: float = 0.0
    c4: float = 0.0
    eQq1: float = 0.0
    eQq2: float = 0.0
    z_N: float = 0.0
    z1: float = 0.0
    z2: float = 0.0
    dE: float = 0.0

    def __post_init__(self):
        s = object.__setattr__
        s(self, "due_I1", _intero(self.due_I1, "due_I1", 0))
        s(self, "due_I2", _intero(self.due_I2, "due_I2", 0))
        if max(self.due_I1, self.due_I2) > DUE_I_MAX:
            raise FuoriDominio(f"due_I1, due_I2: al massimo {DUE_I_MAX} (I ≤ {DUE_I_MAX // 2})")
        s(self, "B", _reale(self.B, "B", positivo=True))
        s(self, "D", _reale(self.D, "D", non_negativo=True))
        for nome in ("c1", "c2", "c3", "c4", "eQq1", "eQq2", "z_N", "z1", "z2"):
            s(self, nome, _reale(getattr(self, nome), nome))
        s(self, "dE", _reale(self.dE, "dE", non_negativo=True))
        if self.due_I1 < 2 and self.eQq1 != 0.0:
            raise FuoriDominio("eQq1: il quadrupolo richiede I1 >= 1 (diatomic-py lo azzera; qui è FuoriDominio)")
        if self.due_I2 < 2 and self.eQq2 != 0.0:
            raise FuoriDominio("eQq2: il quadrupolo richiede I2 >= 1")

    @property
    def N_fis(self) -> Optional[int]:
        if self.D == 0.0:
            return None
        q = Fraction(self.B) / (2 * Fraction(self.D))
        N = int(math.isqrt(int(q))) + 1
        while N >= 0 and N * (N + 1) >= q:
            N -= 1
        return N


# ── aritmetica esatta: somme di c·√q con c, q razionali ─────────────────────────────────────────────────────────────
Termini = Tuple[Tuple[Fraction, Fraction], ...]          # ((coef, q), ...) = Σ coef·√q


def _mul(a: Termini, b: Termini) -> Termini:
    return tuple((ca * cb, qa * qb) for ca, qa in a for cb, qb in b if ca * cb != 0)


def _add(*ts: Termini) -> Termini:
    acc: Dict[Fraction, Fraction] = {}
    for t in ts:
        for c, q in t:
            acc[q] = acc.get(q, Fraction(0)) + c
    return tuple((c, q) for q, c in acc.items() if c != 0)


def _rad(q: Fraction, coef: Fraction = Fraction(1)) -> Termini:
    return ((coef, q),) if coef != 0 and q != 0 else ()


def _num(c) -> Termini:
    c = Fraction(c)
    return ((c, Fraction(1)),) if c != 0 else ()


@lru_cache(maxsize=None)
def _tre_j(dj1: int, dj2: int, dj3: int, dm1: int, dm2: int, dm3: int) -> Termini:
    """3j(j1 j2 j3; m1 m2 m3) esatto come ±√q, argomenti raddoppiati (interi)."""
    from sympy import Rational, sign
    from sympy.physics.wigner import wigner_3j
    v = wigner_3j(Rational(dj1, 2), Rational(dj2, 2), Rational(dj3, 2), Rational(dm1, 2), Rational(dm2, 2), Rational(dm3, 2))
    if v == 0:
        return ()
    q = Rational(v ** 2)
    if not q.is_Rational:
        raise ArithmeticError(f"3j non razionale al quadrato: {v}")
    s = int(sign(v))
    return ((Fraction(s), Fraction(int(q.p), int(q.q))),)


def _segno(n: int) -> Fraction:
    """(−1)^n esatto anche per n negativo (** con esponente negativo darebbe un float)."""
    return Fraction(1) if n % 2 == 0 else Fraction(-1)


def _c_k(k: int, N: int, MN: int, Np: int, MNp: int, q: int) -> Termini:
    """⟨N M_N| C^k_q |N′ M_N′⟩ = (−1)^{M_N} √((2N+1)(2N′+1)) 3j(N k N′; −M_N q M_N′) 3j(N k N′; 0 0 0)."""
    if MNp + q != MN or abs(N - Np) > k:
        return ()
    a = _tre_j(2 * N, 2 * k, 2 * Np, -2 * MN, 2 * q, 2 * MNp)
    b = _tre_j(2 * N, 2 * k, 2 * Np, 0, 0, 0)
    if not a or not b:
        return ()
    return _mul(_mul(a, b), _rad(Fraction((2 * N + 1) * (2 * Np + 1)), _segno(MN)))


def _scala_su(dI: int, dM: int) -> Fraction:
    """⟨M+1| I₊ |M⟩² = I(I+1) − M(M+1), con 2I = dI, 2M = dM."""
    return Fraction(dI * (dI + 2) - dM * (dM + 2), 4)


def _t2_spin(dI1: int, dI2: int, p: int, dM1: int, dM2: int, dM1p: int, dM2p: int) -> Termini:
    """⟨M₁ M₂| T²_p(I₁,I₂) |M₁′ M₂′⟩ dagli operatori scala (stesse forme di diatomic-py makeT2)."""
    d1, d2 = dM1 - dM1p, dM2 - dM2p                           # variazioni (raddoppiate): ±2 = scala, 0 = z
    if d1 + d2 != 2 * p:
        return ()
    M1p, M2p = Fraction(dM1p, 2), Fraction(dM2p, 2)
    su1 = _scala_su(dI1, dM1p) if d1 == 2 else None            # ⟨M₁′+1|I₁₊|M₁′⟩²
    giu1 = _scala_su(dI1, dM1p - 2) if d1 == -2 else None      # ⟨M₁′−1|I₁₋|M₁′⟩² = I(I+1) − M′(M′−1)
    su2 = _scala_su(dI2, dM2p) if d2 == 2 else None
    giu2 = _scala_su(dI2, dM2p - 2) if d2 == -2 else None
    h = Fraction(1, 2)
    if p == 2 and d1 == 2 and d2 == 2:
        return _rad(su1 * su2, h)
    if p == -2 and d1 == -2 and d2 == -2:
        return _rad(giu1 * giu2, h)
    if p == 1:                                                 # −½(I₁₊ I₂z + I₁z I₂₊)
        if d1 == 2 and d2 == 0:
            return _rad(su1, -h * M2p)
        if d1 == 0 and d2 == 2:
            return _rad(su2, -h * M1p)
        return ()
    if p == -1:                                                # +½(I₁₋ I₂z + I₁z I₂₋)
        if d1 == -2 and d2 == 0:
            return _rad(giu1, h * M2p)
        if d1 == 0 and d2 == -2:
            return _rad(giu2, h * M1p)
        return ()
    if p == 0:                                                 # (1/√6)(2 I₁z I₂z − ½(I₁₊I₂₋ + I₁₋I₂₊))
        r6 = Fraction(1, 6)
        if d1 == 0 and d2 == 0:
            return _rad(r6, 2 * M1p * M2p)
        if d1 == 2 and d2 == -2:
            return _rad(su1 * giu2 * r6, -h)
        if d1 == -2 and d2 == 2:
            return _rad(giu1 * su2 * r6, -h)
    return ()


def _t2_quad(dI: int, q: int, dM: int, dMp: int) -> Termini:
    """⟨M| T²_q(Q) |M′⟩ = (−1)^{I−M} 3j(I 2 I; −M q M′) / 3j(I 2 I; −I 0 I) (normalizzazione di diatomic-py)."""
    if dMp + 2 * q != dM:
        return ()
    a = _tre_j(dI, 4, dI, -dM, 2 * q, dMp)
    b = _tre_j(dI, 4, dI, -dI, 0, dI)
    if not a or not b:
        return ()
    (sa, qa), = a
    (sb, qb), = b
    return ((sa * sb * _segno((dI - dM) // 2), qa / qb),)


def _scalare(dJ: int, dMJ: int, dMJp: int, dI: int, dM: int, dMp: int) -> Termini:
    """⟨M_J M| J·I |M_J′ M′⟩ = M_J M δ + ½(⟨J₊⟩⟨I₋⟩ + ⟨J₋⟩⟨I₊⟩)."""
    if dMJ == dMJp and dM == dMp:
        return _num(Fraction(dMJ, 2) * Fraction(dM, 2))
    if dMJ == dMJp + 2 and dM == dMp - 2:
        return _rad(_scala_su(dJ, dMJp) * _scala_su(dI, dMp - 2), Fraction(1, 2))
    if dMJ == dMJp - 2 and dM == dMp + 2:
        return _rad(_scala_su(dJ, dMJp - 2) * _scala_su(dI, dMp), Fraction(1, 2))
    return ()


def _stati(m: MolecolaSigma, dMF: int, L: int) -> List[Tuple[int, int, int, int]]:
    """Stati (N, M_N, 2M₁, 2M₂) del settore M_F con N ≤ L, ordinati per N (poi M_N, M₁, M₂ decrescenti)."""
    out = []
    for N in range(L + 1):
        for MN in range(N, -N - 1, -1):
            for dM1 in range(m.due_I1, -m.due_I1 - 1, -2):
                dM2 = dMF - 2 * MN - dM1
                if -m.due_I2 <= dM2 <= m.due_I2 and (dM2 - m.due_I2) % 2 == 0:
                    out.append((N, MN, dM1, dM2))
    return out


def dimensione_settore(m: MolecolaSigma, due_MF: int, L: int) -> int:
    """Numero di stati del settore M_F = due_MF/2 con N ≤ L. Ingressi chiusi (FuoriDominio)."""
    if not isinstance(m, MolecolaSigma):
        raise FuoriDominio(f"atteso una MolecolaSigma, trovato {type(m).__name__}")
    return len(_stati(m, _intero(due_MF, "due_MF"), _intero(L, "L", 0)))


def _elemento(m: MolecolaSigma, a, b) -> Termini:
    """⟨a| H |b⟩ come Σ c·√q (costanti float prese come Fraction esatte)."""
    N, MN, dM1, dM2 = a
    Np, MNp, dM1p, dM2p = b
    t: List[Termini] = []
    if a == b:
        x = N * (N + 1)
        t.append(_num(Fraction(m.B) * x - Fraction(m.D) * x * x))
        t.append(_num(-(Fraction(m.z_N) * MN + Fraction(m.z1) * Fraction(dM1, 2) + Fraction(m.z2) * Fraction(dM2, 2))))
    if N == Np:
        if dM2 == dM2p and m.c1 != 0.0:
            t.append(_mul(_num(m.c1), _scalare(2 * N, 2 * MN, 2 * MNp, m.due_I1, dM1, dM1p)))
        if dM1 == dM1p and m.c2 != 0.0:
            t.append(_mul(_num(m.c2), _scalare(2 * N, 2 * MN, 2 * MNp, m.due_I2, dM2, dM2p)))
        if MN == MNp and m.c4 != 0.0:
            t.append(_mul(_num(m.c4), _scalare(m.due_I1, dM1, dM1p, m.due_I2, dM2, dM2p)))
    if abs(N - Np) <= 2 and abs(MN - MNp) <= 2:
        q = MN - MNp
        if m.c3 != 0.0:                                                    # −√6 c₃ Σ_q (−1)^q C²_q · T²_{−q}(I₁,I₂)
            cq = _c_k(2, N, MN, Np, MNp, q)
            if cq:
                sp = _t2_spin(m.due_I1, m.due_I2, -q, dM1, dM2, dM1p, dM2p)
                if sp:
                    t.append(_mul(_mul(_rad(Fraction(6), -Fraction(m.c3) * _segno(q)), cq), sp))
        for eQq, dI, dM, dMp, altro in ((m.eQq1, m.due_I1, dM1, dM1p, dM2 == dM2p),
                                        (m.eQq2, m.due_I2, dM2, dM2p, dM1 == dM1p)):
            if eQq != 0.0 and altro:                                       # ¼ eQq Σ_q (−1)^q T²_q(Q) · C²_{−q}
                qq = (dM - dMp) // 2
                if (dM - dMp) % 2 == 0 and abs(qq) <= 2:
                    tq = _t2_quad(dI, qq, dM, dMp)
                    ce = _c_k(2, N, MN, Np, MNp, -qq)
                    if tq and ce:
                        t.append(_mul(_mul(_num(Fraction(eQq) * _segno(qq) / 4), tq), ce))
    if abs(N - Np) == 1 and MN == MNp and dM1 == dM1p and dM2 == dM2p and m.dE != 0.0:
        t.append(_mul(_num(-Fraction(m.dE)), _c_k(1, N, MN, Np, MNp, 0)))
    return _add(*t)


def _matrice_simbolica(m: MolecolaSigma, dMF: int, Lmax: int, scad: Optional[float] = None):
    stati = _stati(m, dMF, Lmax)
    n = len(stati)
    el: Dict[Tuple[int, int], Termini] = {}
    for i in range(n):
        if scad is not None and time.time() > scad:
            raise TempoScaduto(f"scadenza superata costruendo la matrice a L = {Lmax}")
        for j in range(i, n):
            if abs(stati[i][0] - stati[j][0]) > 2:
                continue
            v = _elemento(m, stati[i], stati[j])
            if v:
                el[(i, j)] = v
    return stati, el


def _arb_di(fl, t: Termini):
    s = fl.arb(0)
    for c, q in t:
        v = fl.arb(fl.fmpq(c.numerator, c.denominator))
        if q != 1:
            v = v * fl.arb(fl.fmpq(q.numerator, q.denominator)).sqrt()
        s = s + v
    return s


def _float_di(t: Termini) -> float:
    return sum(float(c) * math.sqrt(float(q)) for c, q in t)


def _conta_sotto_banda(fl, diag, fuori: Dict[Tuple[int, int], object], w: int, x) -> Optional[int]:
    """Autovalori < x della simmetrica (diag, fuori[(i,j)] per j < i, |i−j| ≤ w) via LDLᵀ in Arb; None se un pivot è incerto."""
    n = len(diag)
    D: List = []
    L: List[Dict[int, object]] = []
    neg = 0
    for i in range(n):
        Li: Dict[int, object] = {}
        for j in range(max(0, i - w), i):
            s = fuori.get((i, j))
            s = fl.arb(0) if s is None else s
            Lj = L[j]
            for t_, ljt in Lj.items():
                lit = Li.get(t_)
                if lit is not None:
                    s = s - lit * ljt * D[t_]
            if s != 0 or not s.is_exact():
                Li[j] = s / D[j]
        d = diag[i] - x
        for t_, lit in Li.items():
            d = d - lit * lit * D[t_]
        if d < 0:
            neg += 1
        elif not (d > 0):
            return None
        D.append(d)
        L.append(Li)
    return neg


def _norma_1_inf(fl, righe: Dict[int, object], colonne: Dict[int, object]):
    """√(‖V‖₁ ‖V‖_∞) da somme assolute di righe e colonne (palle Arb): limite superiore di ‖V‖₂."""
    r = max(righe.values()) if righe else fl.arb(0)
    c = max(colonne.values()) if colonne else fl.arb(0)
    return (r * c).sqrt()


def _norma_spin(fl, m: MolecolaSigma):
    """K_T e K_Q: norme (≤ √(‖·‖₁‖·‖_∞)) delle componenti di T²(I₁,I₂) e T²(Q_i) su tutto lo spazio di spin."""
    def norma(elem):
        righe: Dict[int, object] = {}
        colonne: Dict[int, object] = {}
        for (i, j), v in elem.items():
            a = abs(v)
            righe[i] = righe.get(i, fl.arb(0)) + a
            colonne[j] = colonne.get(j, fl.arb(0)) + a
        return _norma_1_inf(fl, righe, colonne)
    spins = [(dM1, dM2) for dM1 in range(m.due_I1, -m.due_I1 - 1, -2) for dM2 in range(m.due_I2, -m.due_I2 - 1, -2)]
    KT = fl.arb(0)
    if m.c3 != 0.0:
        for p in range(-2, 3):
            el = {}
            for i, (a1, a2) in enumerate(spins):
                for j, (b1, b2) in enumerate(spins):
                    t = _t2_spin(m.due_I1, m.due_I2, p, a1, a2, b1, b2)
                    if t:
                        el[(i, j)] = _arb_di(fl, t)
            KT += norma(el)
        KT = KT * fl.arb(6).sqrt() * abs(fl.arb(m.c3))
    KQ = fl.arb(0)
    for eQq, dI in ((m.eQq1, m.due_I1), (m.eQq2, m.due_I2)):
        if eQq != 0.0:
            s = fl.arb(0)
            for q in range(-2, 3):
                el = {}
                for i, a in enumerate(range(dI, -dI - 1, -2)):
                    for j, b in enumerate(range(dI, -dI - 1, -2)):
                        t = _t2_quad(dI, q, a, b)
                        if t:
                            el[(i, j)] = _arb_di(fl, t)
                s += norma(el)
            KQ += s * abs(fl.arb(eQq)) / 4
    return KT, KQ


def _m_max(m: MolecolaSigma, dMF: int) -> Fraction:
    """|M_N| ≤ |M_F| + I₁ + I₂ nel settore: limite sul termine Zeeman rotazionale più stretto di N."""
    return abs(Fraction(dMF, 2)) + Fraction(m.due_I1, 2) + Fraction(m.due_I2, 2)


def _g_esterno(m: MolecolaSigma, dMF: int, N: int, K: Fraction) -> Fraction:
    """g(N) in Fraction (K ≥ K_T + K_Q già maggiorato): limite inferiore del blocco N nel settore M_F."""
    I1, I2 = Fraction(m.due_I1, 2), Fraction(m.due_I2, 2)
    x = N * (N + 1)
    return (Fraction(m.B) * x - Fraction(m.D) * x * x
            - (abs(Fraction(m.z_N)) * min(Fraction(N), _m_max(m, dMF)) + abs(Fraction(m.z1)) * I1 + abs(Fraction(m.z2)) * I2)
            - (abs(Fraction(m.c1)) * I1 + abs(Fraction(m.c2)) * I2) * (N + 1)
            - abs(Fraction(m.c4)) * (I1 + 1) * (I2 + 1) - K - Fraction(m.dE))


def _g_crescente(m: MolecolaSigma, dMF: int, L1: int) -> bool:
    """g(N+1) − g(N) ≥ 0 per ogni N ≥ L1 (fino a N_fis − 1 se D > 0), con incrementi esatti in Fraction:
    h(N) = 2B(N+1) − 4D(N+1)³ − (|c₁|I₁ + |c₂|I₂) − (|z_N| se N+1 ≤ M_max, altrimenti 0)."""
    I1, I2 = Fraction(m.due_I1, 2), Fraction(m.due_I2, 2)
    a = abs(Fraction(m.c1)) * I1 + abs(Fraction(m.c2)) * I2
    B, D, zN, Mmax = Fraction(m.B), Fraction(m.D), abs(Fraction(m.z_N)), _m_max(m, dMF)

    def h(N):
        return 2 * B * (N + 1) - 4 * D * (N + 1) ** 3 - a - (zN if N + 1 <= Mmax else 0)
    if D == 0:
        return h(L1) >= 0                       # h non decrescente in N
    return all(h(N) >= 0 for N in range(L1, m.N_fis))


def _limite_esterno(fl, m: MolecolaSigma, dMF: int, L: int, normaV):
    """(g, η, t): g = g(L+1) in Arb con K_T + K_Q di Arb, η = ‖V‖ (qualsiasi η > 0 vale), t = g − ‖V‖²/η.
    g(N) = B N(N+1) − D[N(N+1)]² − Zeeman(N) − (|c₁|I₁ + |c₂|I₂)(N+1) − |c₄|(I₁+1)(I₂+1) − (K_T + K_Q) − dE."""
    KT, KQ = _norma_spin(fl, m)
    K = KT + KQ
    I1, I2 = fl.arb(fl.fmpq(m.due_I1, 2)), fl.arb(fl.fmpq(m.due_I2, 2))
    N = L + 1
    x = N * (N + 1)
    Mm = _m_max(m, dMF)
    zterm = abs(fl.arb(m.z_N)) * _arb_fraz(fl, min(Fraction(N), Mm)) + abs(fl.arb(m.z1)) * I1 + abs(fl.arb(m.z2)) * I2
    g = (_arb_fraz(fl, Fraction(m.B)) * x - _arb_fraz(fl, Fraction(m.D)) * x * x - zterm
         - (abs(fl.arb(m.c1)) * I1 + abs(fl.arb(m.c2)) * I2) * (N + 1)
         - abs(fl.arb(m.c4)) * (I1 + 1) * (I2 + 1) - K - fl.arb(m.dE))
    eta_f = max(float(normaV.upper()), m.B * 1e-30)
    eta = fl.arb(eta_f)
    return g, eta_f, g - normaV * normaV / eta


def _approssimati(stati, el, k: int) -> np.ndarray:
    """Solo per scegliere i punti di prova: non entra nella dimostrazione."""
    n = len(stati)
    M = np.zeros((n, n))
    for (i, j), t in el.items():
        M[i, j] = M[j, i] = _float_di(t)
    return np.linalg.eigvalsh(M)[:k]


def _tenta(fl, m: MolecolaSigma, dMF: int, k: int, larghezza: float, L: int, scad):
    Lmax = L + 2 if m.N_fis is None else min(L + 2, m.N_fis)      # mai stati oltre N_fis (fuori modello)
    stati, el = _matrice_simbolica(m, dMF, Lmax, scad)
    n_in = sum(1 for s in stati if s[0] <= L)
    if n_in < k:
        raise FuoriDominio(f"il settore 2M_F = {dMF} con N ≤ {L} ha solo {n_in} stati: meno di k = {k}")
    arb = {ij: _arb_di(fl, t) for ij, t in el.items()}
    diag = [arb.get((i, i), fl.arb(0)) for i in range(n_in)]
    fuori = {(j, i): v for (i, j), v in arb.items() if i < j < n_in}
    w = max((j - i for (i, j) in el if j < n_in), default=0)
    # blocco esterno
    if Lmax == L:                                                  # modello finito tutto incluso (D > 0, L = N_fis)
        diagA, t_est, eta_f = diag, None, 0.0
    else:
        righe: Dict[int, object] = {}
        colonne: Dict[int, object] = {}
        for (i, j), v in arb.items():
            if i < n_in <= j:
                a = abs(v)
                righe[i] = righe.get(i, fl.arb(0)) + a
                colonne[j] = colonne.get(j, fl.arb(0)) + a
        normaV = _norma_1_inf(fl, righe, colonne)
        if not _g_crescente(m, dMF, L + 1):
            return None                                            # a questo L il blocco esterno non è dominato
        g, eta_f, t_est = _limite_esterno(fl, m, dMF, L, normaV)
        eta = fl.arb(eta_f)
        diagA = list(diag)
        for i in righe:
            diagA[i] = diag[i] - eta
    approx = _approssimati(stati[:n_in], {ij: t for ij, t in el.items() if ij[1] < n_in}, k)
    bassi, alti = [], []
    for j in range(k):
        delta = max(abs(float(approx[j])), m.B) * larghezza / 4
        for _ in range(60):
            if scad is not None and time.time() > scad:
                raise TempoScaduto(f"scadenza superata a L = {L}")
            lo = Fraction(float(approx[j])) - Fraction(delta)
            hi = Fraction(float(approx[j])) + Fraction(delta)
            n_hi = _conta_sotto_banda(fl, diag, fuori, w, _arb_fraz(fl, hi))
            n_lo = _conta_sotto_banda(fl, diagA, fuori, w, _arb_fraz(fl, lo))
            if n_hi is not None and n_lo is not None and n_hi >= j + 1 and n_lo <= j:
                break
            delta *= 2
        else:
            return None
        if t_est is not None and not (t_est > _arb_fraz(fl, hi)):
            return None
        bassi.append(lo)
        alti.append(hi)
    return tuple(bassi), tuple(alti), eta_f


def _arb_fraz(fl, f: Fraction):
    return fl.arb(fl.fmpq(f.numerator, f.denominator))


def livelli_molecola_garantiti(m: MolecolaSigma, due_MF: int, k: int = 4, larghezza: float = 1e-12, *,
                               scadenza: Optional[float] = None, L_iniziale: Optional[int] = None,
                               L_limite: int = L_LIMITE, prec: int = PREC_MIN) -> Intervalli:
    """Primi k livelli di H nel settore M_F = due_MF/2 come intervalli garantiti. `larghezza` relativa a
    max(|E_j|, B). Si ferma al primo L con stato GARANTITO; se un L dà solo LARGO si prova L+2 finché la larghezza
    si dimezza, e si restituisce il risultato più stretto (sempre valido). FuoriDominio se nessun L ≤ L_limite
    dimostra; TempoScaduto oltre `scadenza` secondi."""
    if not isinstance(m, MolecolaSigma):
        raise FuoriDominio(f"atteso una MolecolaSigma, trovato {type(m).__name__}")
    dMF = _intero(due_MF, "due_MF")
    if (dMF - m.due_I1 - m.due_I2) % 2 != 0:
        raise FuoriDominio("due_MF: parità incompatibile con 2I1 + 2I2 (M_F deve essere intero o semintero come I1+I2)")
    k = _intero(k, "k", 1)
    if k > K_MAX:
        raise FuoriDominio(f"k: al massimo {K_MAX}")
    larghezza = _reale(larghezza, "larghezza", positivo=True)
    L_limite = _intero(L_limite, "L_limite", 0)
    if L_limite > L_LIMITE_MAX:
        raise FuoriDominio(f"L_limite: al massimo {L_LIMITE_MAX}")
    prec = _intero(prec, "prec", 2)
    if prec > PREC_MAX:
        raise FuoriDominio(f"prec: al massimo {PREC_MAX}")
    if scadenza is not None:
        scadenza = _reale(scadenza, "scadenza", positivo=True)
    fl = _flint()
    t0 = time.time()
    scad = None if scadenza is None else t0 + scadenza
    # L minimo: il settore deve avere almeno k stati
    L = 0
    while len(_stati(m, dMF, L)) < k:
        L += 1
        if L > L_limite:
            raise FuoriDominio(f"il settore 2M_F = {dMF} non ha k = {k} stati entro L_limite = {L_limite}")
        if scad is not None and time.time() > scad:
            raise TempoScaduto(f"scadenza di {scadenza} s superata cercando il L minimo")
    if L_iniziale is not None:
        L = _intero(L_iniziale, "L_iniziale", 0)
    else:
        extra = 2 * math.sqrt(m.dE / m.B)                   # dE/B può valere inf (1e300/1e-300): niente int(inf)
        L = L + 2 + (int(extra) if extra <= L_limite else L_limite + 1)
    if m.N_fis is not None:
        if m.N_fis < L:
            if L_iniziale is not None:
                raise FuoriDominio(f"L_iniziale = {L} supera N_fis = {m.N_fis}: il modello con D è definito su N ≤ N_fis")
            L = m.N_fis
        L_limite = min(L_limite, m.N_fis)
    if L > L_limite:
        raise FuoriDominio(f"L iniziale {L} > L_limite {L_limite}")
    vecchia = fl.ctx.prec
    migliore: Optional[Intervalli] = None
    try:
        while True:
            p = max(prec, PREC_MIN)
            while p <= PREC_MAX:
                if scad is not None and time.time() > scad:
                    raise TempoScaduto(f"scadenza di {scadenza} s superata a L = {L}")
                fl.ctx.prec = p
                ris = _tenta(fl, m, dMF, k, larghezza, L, scad)
                if ris is not None:
                    bassi, alti, eta = ris
                    larg = max(float(a - b) for a, b in zip(alti, bassi))
                    obiettivo = larghezza * max(max(abs(float(b)) for b in bassi), m.B)
                    stringhe = tuple((str(float(b)), str(float(a))) for b, a in zip(bassi, alti))
                    iv = Intervalli(bassi, alti, stringhe, larg, "GARANTITO" if larg <= obiettivo else "LARGO",
                                    L, p, eta, round(time.time() - t0, 3))
                    if iv.stato == "GARANTITO":
                        return iv
                    # LARGO: valido, ma si prova un L più grande (la larghezza da η cala con L) finché si dimezza
                    if migliore is not None and not (larg < migliore.larghezza_max / 2):
                        return replace(migliore, secondi=round(time.time() - t0, 3))
                    migliore = iv
                    break
                p *= 2
            if L >= L_limite:
                break
            L = min(L + 2, L_limite)
        if migliore is not None:
            return replace(migliore, secondi=round(time.time() - t0, 3))
        raise FuoriDominio(f"nessun intervallo dimostrato entro L_limite = {L_limite}")
    finally:
        fl.ctx.prec = vecchia


def transizione(iv: Intervalli, i: int, iv2: Intervalli, j: int) -> Tuple[Fraction, Fraction]:
    """E_j(iv2) − E_i(iv) garantito (anche tra settori diversi): [basso_j − alto_i, alto_j − basso_i].
    Ingressi chiusi: indici fuori dagli intervalli dati → FuoriDominio (NEMESIS R5)."""
    if not isinstance(iv, Intervalli) or not isinstance(iv2, Intervalli):
        raise FuoriDominio("attesi due Intervalli")
    i = _intero(i, "i", 0)
    j = _intero(j, "j", 0)
    if i >= len(iv.bassi) or j >= len(iv2.bassi):
        raise FuoriDominio(f"indici {i}, {j} oltre i livelli disponibili ({len(iv.bassi)}, {len(iv2.bassi)})")
    return iv2.bassi[j] - iv.alti[i], iv2.alti[j] - iv.bassi[i]
