# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""rigorous_levels/hyperfine_molecule.py — ¹Σ molecule (rotation + hyperfine + Zeeman + Stark) with levels as GUARANTEED
intervals [low, high] with respect to the truncation N ≤ L.

    H = B N² − D (N²)² + c₁ N·I₁ + c₂ N·I₂ + c₄ I₁·I₂ − √6 c₃ T²(C)·T²(I₁,I₂) + ¼ Σ_i (eQq)_i T²(Q_i)·T²(∇E)
        − dE C¹₀(θ) − (z_N N_z + z₁ I₁z + z₂ I₂z)                                   (all in Hz)

Uncoupled basis |N M_N⟩|I₁ M₁⟩|I₂ M₂⟩ with the fields E and B along z: M_F = M_N + M₁ + M₂ is conserved and one
M_F sector is treated at a time. Form of Aldegunde et al., PRA 78, 033434 (2008) eq. 3 (+c₃ I₁·T·I₂, T dipolar) and of
Blackmore et al. 2022 (the diatomic-py paper, arXiv:2205.05686, eq. 5b: −c₃√6 T²(C)·T²(I_A,I_B)): the two coincide
because √6 T²(C)·T²(I₁,I₂) = 3(I₁·r̂)(I₂·r̂) − I₁·I₂ = −I₁·T·I₂.
MEASURED SIGN (2026-11-10; durham-qlm/diatomic-py #15): the CODE of diatomic-py 2.1.0 (`tensor_nuclear`) uses
+√6 c₃, the opposite sign of its paper; with the paper's sign the 16 transitions of Gregory et al. 2016
(PRA 94, 041403(R)) are reproduced within 94 Hz, with the code's sign they are not (up to 1.96 kHz). Here the paper's
sign holds; the comparison with diatomic-py in the tests passes c₃ → −c₃ (declared).
The matrix elements are rebuilt in Arb balls from square roots of exact rationals (3j symbols from sympy) and
compared with diatomic-py in the tests (a check of the construction, not of the proof).

Guarantee (Teschl, Theorem 4.12(i) and Corollary 4.11; the argument of rigorous_levels/guaranteed_intervals.py and of the
sphere):
  A = compression of H to N ≤ L; V = coupling of A with N ∈ {L+1, L+2} (only the Stark term, ΔN = 1, and the rank-2
  terms, ΔN = 2, leave A); C = block N ≥ L+1.
  - above: λ_j(H) ≤ λ_j(A);
  - below: H ≥ (A − η P_B) ⊕ (C − ‖V‖²/η) as forms (Young on the coupling only), P_B = projector on the states of A
    with a non-zero row in V, ‖V‖₂ ≤ √(‖V‖₁‖V‖_∞) in Arb; λ_min(C) ≥ g(L+1) with g (block Gershgorin)
      g(N) = B N(N+1) − D[N(N+1)]² − (|z_N| min(N, |M_F|+I₁+I₂) + |z₁| I₁ + |z₂| I₂) − (|c₁| I₁ + |c₂| I₂)(N+1)
             − |c₄|(I₁+1)(I₂+1)
             − (K_T + K_Q) − dE,
    increasing on [L+1, N_phys] (checked with exact increments); if t = g(L+1) − ‖V‖²/η > high_j then
    λ_j(H) ≥ λ_j(A − η P_B).
  - counts "eigenvalues < x" by banded LDLᵀ in Arb balls; an uncertain pivot doubles the precision or moves the point.
With D > 0 the model is DEFINED on N ≤ N_phys = max{N : N(N+1) < B/(2D)} (declared, as for the sphere).
Declared hypotheses: the float64 constants are exact; Arb/FLINT and sympy (3j) are correct.
Measurements (2026-11-10/11, author's repository): 0 violations on 197 random and extreme cases by an independent
reviewer (the mutant with the wrong sign of η gives 50); RbCs with the constants of Gregory et al. 2016 reproduces
their 16 hyperfine transitions within 100 Hz with intervals 7 mHz wide.

What it does NOT say: that H describes the molecule (missing terms: AC polarizability, non-parallel fields).
This package is not an external validator.
Names: this module was `molecola_iperfine_garantita` in 0.2.0 (deprecated aliases in that module).
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, replace
from fractions import Fraction
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import numpy as np

from rigorous_levels._compat import add_field_aliases
from rigorous_levels._deterministic import dense_lowest
from rigorous_levels.guaranteed_intervals import ArbMissing, DeadlineExceeded, Intervals, OutOfDomain, _flint

__all__ = ["SigmaMolecule", "guaranteed_molecule_levels", "transition", "sector_dimension", "zeeman_hz",
           "OutOfDomain", "ArbMissing", "DeadlineExceeded"]

L_LIMIT = 16           # banded LDLᵀ in pure Python: at L = 16 an RbCs sector has ~500 states (seconds per count)
PREC_MIN, PREC_MAX = 128, 1024
K_MAX = 100
TWO_I_MAX = 40         # 2I ≤ 40 (I ≤ 20): beyond every known nuclear spin; without a cap the sector grows without limit
L_LIMIT_MAX = 64       # cap of L_limit: beyond it the O(n²) construction meets no reasonable deadline
MU_N_HZ_PER_T = 7.6225932188e6      # μ_N/h, CODATA 2018 (scipy.constants "nuclear magneton in MHz/T" × 1e6)


def zeeman_hz(g: float, B_gauss: float) -> float:
    """Zeeman coefficient in Hz: g · μ_N/h · B (B in gauss). Closed inputs (OutOfDomain)."""
    return _real(g, "g") * MU_N_HZ_PER_T * _real(B_gauss, "B_gauss") * 1e-4


def _real(x, name: str, *, positive=False, non_negative=False) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float, np.floating)):
        raise OutOfDomain(f"{name}: expected a finite real number")
    try:
        x = float(x)
    except OverflowError:                                   # int beyond float64 (10**400): out of domain, not a crash
        raise OutOfDomain(f"{name}: expected a finite real number (integer beyond float64)") from None
    if not math.isfinite(x):
        raise OutOfDomain(f"{name}: expected a finite real number")
    if positive and x <= 0:
        raise OutOfDomain(f"{name}: must be > 0")
    if non_negative and x < 0:
        raise OutOfDomain(f"{name}: must be >= 0")
    return x


def _integer(x, name: str, minimum: Optional[int] = None) -> int:
    if isinstance(x, bool) or not isinstance(x, (int, np.integer)):
        raise OutOfDomain(f"{name}: expected an integer")
    x = int(x)
    if minimum is not None and x < minimum:
        raise OutOfDomain(f"{name}: expected >= {minimum}")
    return x


@dataclass(frozen=True)
class SigmaMolecule:
    """Constants in Hz. two_I1, two_I2 = 2I (integers ≥ 0). z_N, z1, z2 = g·μ_N·B/h (see zeeman_hz). dE = d·E/h ≥ 0."""

    two_I1: int
    two_I2: int
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
        s(self, "two_I1", _integer(self.two_I1, "two_I1", 0))
        s(self, "two_I2", _integer(self.two_I2, "two_I2", 0))
        if max(self.two_I1, self.two_I2) > TWO_I_MAX:
            raise OutOfDomain(f"two_I1, two_I2: at most {TWO_I_MAX} (I ≤ {TWO_I_MAX // 2})")
        s(self, "B", _real(self.B, "B", positive=True))
        s(self, "D", _real(self.D, "D", non_negative=True))
        for name in ("c1", "c2", "c3", "c4", "eQq1", "eQq2", "z_N", "z1", "z2"):
            s(self, name, _real(getattr(self, name), name))
        s(self, "dE", _real(self.dE, "dE", non_negative=True))
        if self.two_I1 < 2 and self.eQq1 != 0.0:
            raise OutOfDomain("eQq1: the quadrupole requires I1 >= 1 (diatomic-py zeroes it; here it is OutOfDomain)")
        if self.two_I2 < 2 and self.eQq2 != 0.0:
            raise OutOfDomain("eQq2: the quadrupole requires I2 >= 1")

    @property
    def N_phys(self) -> Optional[int]:
        if self.D == 0.0:
            return None
        q = Fraction(self.B) / (2 * Fraction(self.D))
        N = int(math.isqrt(int(q))) + 1
        while N >= 0 and N * (N + 1) >= q:
            N -= 1
        return N


# ── exact arithmetic: sums of c·√q with rational c, q ─────────────────────────────────────────────────────────────
Terms = Tuple[Tuple[Fraction, Fraction], ...]          # ((coef, q), ...) = Σ coef·√q


def _mul(a: Terms, b: Terms) -> Terms:
    return tuple((ca * cb, qa * qb) for ca, qa in a for cb, qb in b if ca * cb != 0)


def _add(*ts: Terms) -> Terms:
    acc: Dict[Fraction, Fraction] = {}
    for t in ts:
        for c, q in t:
            acc[q] = acc.get(q, Fraction(0)) + c
    return tuple((c, q) for q, c in acc.items() if c != 0)


def _rad(q: Fraction, coef: Fraction = Fraction(1)) -> Terms:
    return ((coef, q),) if coef != 0 and q != 0 else ()


def _num(c) -> Terms:
    c = Fraction(c)
    return ((c, Fraction(1)),) if c != 0 else ()


@lru_cache(maxsize=None)
def _three_j(dj1: int, dj2: int, dj3: int, dm1: int, dm2: int, dm3: int) -> Terms:
    """Exact 3j(j1 j2 j3; m1 m2 m3) as ±√q, doubled (integer) arguments."""
    from sympy import Rational, sign
    from sympy.physics.wigner import wigner_3j
    v = wigner_3j(Rational(dj1, 2), Rational(dj2, 2), Rational(dj3, 2), Rational(dm1, 2), Rational(dm2, 2), Rational(dm3, 2))
    if v == 0:
        return ()
    q = Rational(v ** 2)
    if not q.is_Rational:
        raise ArithmeticError(f"3j not rational when squared: {v}")
    s = int(sign(v))
    return ((Fraction(s), Fraction(int(q.p), int(q.q))),)


def _sign(n: int) -> Fraction:
    """Exact (−1)^n also for negative n (** with a negative exponent would give a float)."""
    return Fraction(1) if n % 2 == 0 else Fraction(-1)


def _c_k(k: int, N: int, MN: int, Np: int, MNp: int, q: int) -> Terms:
    """⟨N M_N| C^k_q |N′ M_N′⟩ = (−1)^{M_N} √((2N+1)(2N′+1)) 3j(N k N′; −M_N q M_N′) 3j(N k N′; 0 0 0)."""
    if MNp + q != MN or abs(N - Np) > k:
        return ()
    a = _three_j(2 * N, 2 * k, 2 * Np, -2 * MN, 2 * q, 2 * MNp)
    b = _three_j(2 * N, 2 * k, 2 * Np, 0, 0, 0)
    if not a or not b:
        return ()
    return _mul(_mul(a, b), _rad(Fraction((2 * N + 1) * (2 * Np + 1)), _sign(MN)))


def _ladder_up(dI: int, dM: int) -> Fraction:
    """⟨M+1| I₊ |M⟩² = I(I+1) − M(M+1), with 2I = dI, 2M = dM."""
    return Fraction(dI * (dI + 2) - dM * (dM + 2), 4)


def _t2_spin(dI1: int, dI2: int, p: int, dM1: int, dM2: int, dM1p: int, dM2p: int) -> Terms:
    """⟨M₁ M₂| T²_p(I₁,I₂) |M₁′ M₂′⟩ from the ladder operators (same forms as diatomic-py makeT2)."""
    d1, d2 = dM1 - dM1p, dM2 - dM2p                           # changes (doubled): ±2 = ladder, 0 = z
    if d1 + d2 != 2 * p:
        return ()
    M1p, M2p = Fraction(dM1p, 2), Fraction(dM2p, 2)
    up1 = _ladder_up(dI1, dM1p) if d1 == 2 else None           # ⟨M₁′+1|I₁₊|M₁′⟩²
    dn1 = _ladder_up(dI1, dM1p - 2) if d1 == -2 else None      # ⟨M₁′−1|I₁₋|M₁′⟩² = I(I+1) − M′(M′−1)
    up2 = _ladder_up(dI2, dM2p) if d2 == 2 else None
    dn2 = _ladder_up(dI2, dM2p - 2) if d2 == -2 else None
    h = Fraction(1, 2)
    if p == 2 and d1 == 2 and d2 == 2:
        return _rad(up1 * up2, h)
    if p == -2 and d1 == -2 and d2 == -2:
        return _rad(dn1 * dn2, h)
    if p == 1:                                                 # −½(I₁₊ I₂z + I₁z I₂₊)
        if d1 == 2 and d2 == 0:
            return _rad(up1, -h * M2p)
        if d1 == 0 and d2 == 2:
            return _rad(up2, -h * M1p)
        return ()
    if p == -1:                                                # +½(I₁₋ I₂z + I₁z I₂₋)
        if d1 == -2 and d2 == 0:
            return _rad(dn1, h * M2p)
        if d1 == 0 and d2 == -2:
            return _rad(dn2, h * M1p)
        return ()
    if p == 0:                                                 # (1/√6)(2 I₁z I₂z − ½(I₁₊I₂₋ + I₁₋I₂₊))
        r6 = Fraction(1, 6)
        if d1 == 0 and d2 == 0:
            return _rad(r6, 2 * M1p * M2p)
        if d1 == 2 and d2 == -2:
            return _rad(up1 * dn2 * r6, -h)
        if d1 == -2 and d2 == 2:
            return _rad(dn1 * up2 * r6, -h)
    return ()


def _t2_quad(dI: int, q: int, dM: int, dMp: int) -> Terms:
    """⟨M| T²_q(Q) |M′⟩ = (−1)^{I−M} 3j(I 2 I; −M q M′) / 3j(I 2 I; −I 0 I) (normalization of diatomic-py)."""
    if dMp + 2 * q != dM:
        return ()
    a = _three_j(dI, 4, dI, -dM, 2 * q, dMp)
    b = _three_j(dI, 4, dI, -dI, 0, dI)
    if not a or not b:
        return ()
    (sa, qa), = a
    (sb, qb), = b
    return ((sa * sb * _sign((dI - dM) // 2), qa / qb),)


def _scalar(dJ: int, dMJ: int, dMJp: int, dI: int, dM: int, dMp: int) -> Terms:
    """⟨M_J M| J·I |M_J′ M′⟩ = M_J M δ + ½(⟨J₊⟩⟨I₋⟩ + ⟨J₋⟩⟨I₊⟩)."""
    if dMJ == dMJp and dM == dMp:
        return _num(Fraction(dMJ, 2) * Fraction(dM, 2))
    if dMJ == dMJp + 2 and dM == dMp - 2:
        return _rad(_ladder_up(dJ, dMJp) * _ladder_up(dI, dMp - 2), Fraction(1, 2))
    if dMJ == dMJp - 2 and dM == dMp + 2:
        return _rad(_ladder_up(dJ, dMJp - 2) * _ladder_up(dI, dMp), Fraction(1, 2))
    return ()


def _states(m: SigmaMolecule, dMF: int, L: int) -> List[Tuple[int, int, int, int]]:
    """States (N, M_N, 2M₁, 2M₂) of the sector M_F with N ≤ L, ordered by N (then M_N, M₁, M₂ decreasing)."""
    out = []
    for N in range(L + 1):
        for MN in range(N, -N - 1, -1):
            for dM1 in range(m.two_I1, -m.two_I1 - 1, -2):
                dM2 = dMF - 2 * MN - dM1
                if -m.two_I2 <= dM2 <= m.two_I2 and (dM2 - m.two_I2) % 2 == 0:
                    out.append((N, MN, dM1, dM2))
    return out


def sector_dimension(m: SigmaMolecule, two_MF: int, L: int) -> int:
    """Number of states of the sector M_F = two_MF/2 with N ≤ L. Closed inputs (OutOfDomain)."""
    if not isinstance(m, SigmaMolecule):
        raise OutOfDomain(f"expected a SigmaMolecule, got {type(m).__name__}")
    return len(_states(m, _integer(two_MF, "two_MF"), _integer(L, "L", 0)))


def _element(m: SigmaMolecule, a, b) -> Terms:
    """⟨a| H |b⟩ as Σ c·√q (the float constants taken as exact Fractions)."""
    N, MN, dM1, dM2 = a
    Np, MNp, dM1p, dM2p = b
    t: List[Terms] = []
    if a == b:
        x = N * (N + 1)
        t.append(_num(Fraction(m.B) * x - Fraction(m.D) * x * x))
        t.append(_num(-(Fraction(m.z_N) * MN + Fraction(m.z1) * Fraction(dM1, 2) + Fraction(m.z2) * Fraction(dM2, 2))))
    if N == Np:
        if dM2 == dM2p and m.c1 != 0.0:
            t.append(_mul(_num(m.c1), _scalar(2 * N, 2 * MN, 2 * MNp, m.two_I1, dM1, dM1p)))
        if dM1 == dM1p and m.c2 != 0.0:
            t.append(_mul(_num(m.c2), _scalar(2 * N, 2 * MN, 2 * MNp, m.two_I2, dM2, dM2p)))
        if MN == MNp and m.c4 != 0.0:
            t.append(_mul(_num(m.c4), _scalar(m.two_I1, dM1, dM1p, m.two_I2, dM2, dM2p)))
    if abs(N - Np) <= 2 and abs(MN - MNp) <= 2:
        q = MN - MNp
        if m.c3 != 0.0:                                                    # −√6 c₃ Σ_q (−1)^q C²_q · T²_{−q}(I₁,I₂)
            cq = _c_k(2, N, MN, Np, MNp, q)
            if cq:
                sp = _t2_spin(m.two_I1, m.two_I2, -q, dM1, dM2, dM1p, dM2p)
                if sp:
                    t.append(_mul(_mul(_rad(Fraction(6), -Fraction(m.c3) * _sign(q)), cq), sp))
        for eQq, dI, dM, dMp, other in ((m.eQq1, m.two_I1, dM1, dM1p, dM2 == dM2p),
                                        (m.eQq2, m.two_I2, dM2, dM2p, dM1 == dM1p)):
            if eQq != 0.0 and other:                                       # ¼ eQq Σ_q (−1)^q T²_q(Q) · C²_{−q}
                qq = (dM - dMp) // 2
                if (dM - dMp) % 2 == 0 and abs(qq) <= 2:
                    tq = _t2_quad(dI, qq, dM, dMp)
                    ce = _c_k(2, N, MN, Np, MNp, -qq)
                    if tq and ce:
                        t.append(_mul(_mul(_num(Fraction(eQq) * _sign(qq) / 4), tq), ce))
    if abs(N - Np) == 1 and MN == MNp and dM1 == dM1p and dM2 == dM2p and m.dE != 0.0:
        t.append(_mul(_num(-Fraction(m.dE)), _c_k(1, N, MN, Np, MNp, 0)))
    return _add(*t)


def _symbolic_matrix(m: SigmaMolecule, dMF: int, Lmax: int, dl: Optional[float] = None):
    states = _states(m, dMF, Lmax)
    n = len(states)
    el: Dict[Tuple[int, int], Terms] = {}
    for i in range(n):
        if dl is not None and time.perf_counter() > dl:
            raise DeadlineExceeded(f"deadline exceeded while building the matrix at L = {Lmax}")
        for j in range(i, n):
            if abs(states[i][0] - states[j][0]) > 2:
                continue
            v = _element(m, states[i], states[j])
            if v:
                el[(i, j)] = v
    return states, el


def _arb_of(fl, t: Terms):
    s = fl.arb(0)
    for c, q in t:
        v = fl.arb(fl.fmpq(c.numerator, c.denominator))
        if q != 1:
            v = v * fl.arb(fl.fmpq(q.numerator, q.denominator)).sqrt()
        s = s + v
    return s


def _float_of(t: Terms) -> float:
    return math.fsum(float(c) * math.sqrt(float(q)) for c, q in t)


def _count_below_banded(fl, diag, off: Dict[Tuple[int, int], object], w: int, x) -> Optional[int]:
    """Eigenvalues < x of the symmetric matrix (diag, off[(i,j)] for j < i, |i−j| ≤ w) by LDLᵀ in Arb; None if a
    pivot is uncertain."""
    n = len(diag)
    D: List = []
    L: List[Dict[int, object]] = []
    neg = 0
    for i in range(n):
        Li: Dict[int, object] = {}
        for j in range(max(0, i - w), i):
            s = off.get((i, j))
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


def _norm_1_inf(fl, rows: Dict[int, object], cols: Dict[int, object]):
    """√(‖V‖₁ ‖V‖_∞) from absolute row and column sums (Arb balls): an upper bound of ‖V‖₂."""
    r = max(rows.values()) if rows else fl.arb(0)
    c = max(cols.values()) if cols else fl.arb(0)
    return (r * c).sqrt()


def _spin_norm(fl, m: SigmaMolecule):
    """K_T and K_Q: norms (≤ √(‖·‖₁‖·‖_∞)) of the components of T²(I₁,I₂) and T²(Q_i) on the whole spin space."""
    def norm(elem):
        rows: Dict[int, object] = {}
        cols: Dict[int, object] = {}
        for (i, j), v in elem.items():
            a = abs(v)
            rows[i] = rows.get(i, fl.arb(0)) + a
            cols[j] = cols.get(j, fl.arb(0)) + a
        return _norm_1_inf(fl, rows, cols)
    spins = [(dM1, dM2) for dM1 in range(m.two_I1, -m.two_I1 - 1, -2) for dM2 in range(m.two_I2, -m.two_I2 - 1, -2)]
    KT = fl.arb(0)
    if m.c3 != 0.0:
        for p in range(-2, 3):
            el = {}
            for i, (a1, a2) in enumerate(spins):
                for j, (b1, b2) in enumerate(spins):
                    t = _t2_spin(m.two_I1, m.two_I2, p, a1, a2, b1, b2)
                    if t:
                        el[(i, j)] = _arb_of(fl, t)
            KT += norm(el)
        KT = KT * fl.arb(6).sqrt() * abs(fl.arb(m.c3))
    KQ = fl.arb(0)
    for eQq, dI in ((m.eQq1, m.two_I1), (m.eQq2, m.two_I2)):
        if eQq != 0.0:
            s = fl.arb(0)
            for q in range(-2, 3):
                el = {}
                for i, a in enumerate(range(dI, -dI - 1, -2)):
                    for j, b in enumerate(range(dI, -dI - 1, -2)):
                        t = _t2_quad(dI, q, a, b)
                        if t:
                            el[(i, j)] = _arb_of(fl, t)
                s += norm(el)
            KQ += s * abs(fl.arb(eQq)) / 4
    return KT, KQ


def _m_max(m: SigmaMolecule, dMF: int) -> Fraction:
    """|M_N| ≤ |M_F| + I₁ + I₂ in the sector: a bound on the rotational Zeeman term tighter than N."""
    return abs(Fraction(dMF, 2)) + Fraction(m.two_I1, 2) + Fraction(m.two_I2, 2)


def _g_outer(m: SigmaMolecule, dMF: int, N: int, K: Fraction) -> Fraction:
    """g(N) in Fraction (K ≥ K_T + K_Q already bounded): lower bound of the block N in the sector M_F."""
    I1, I2 = Fraction(m.two_I1, 2), Fraction(m.two_I2, 2)
    x = N * (N + 1)
    return (Fraction(m.B) * x - Fraction(m.D) * x * x
            - (abs(Fraction(m.z_N)) * min(Fraction(N), _m_max(m, dMF)) + abs(Fraction(m.z1)) * I1 + abs(Fraction(m.z2)) * I2)
            - (abs(Fraction(m.c1)) * I1 + abs(Fraction(m.c2)) * I2) * (N + 1)
            - abs(Fraction(m.c4)) * (I1 + 1) * (I2 + 1) - K - Fraction(m.dE))


def _g_increasing(m: SigmaMolecule, dMF: int, L1: int) -> bool:
    """g(N+1) − g(N) ≥ 0 for every N ≥ L1 (up to N_phys − 1 if D > 0), with exact increments in Fraction:
    h(N) = 2B(N+1) − 4D(N+1)³ − (|c₁|I₁ + |c₂|I₂) − (|z_N| if N+1 ≤ M_max, else 0)."""
    I1, I2 = Fraction(m.two_I1, 2), Fraction(m.two_I2, 2)
    a = abs(Fraction(m.c1)) * I1 + abs(Fraction(m.c2)) * I2
    B, D, zN, Mmax = Fraction(m.B), Fraction(m.D), abs(Fraction(m.z_N)), _m_max(m, dMF)

    def h(N):
        return 2 * B * (N + 1) - 4 * D * (N + 1) ** 3 - a - (zN if N + 1 <= Mmax else 0)
    if D == 0:
        return h(L1) >= 0                       # h non-decreasing in N
    return all(h(N) >= 0 for N in range(L1, m.N_phys))


def _outer_bound(fl, m: SigmaMolecule, dMF: int, L: int, normV):
    """(g, η, t): g = g(L+1) in Arb with the K_T + K_Q of Arb, η = ‖V‖ (any η > 0 is valid), t = g − ‖V‖²/η.
    g(N) = B N(N+1) − D[N(N+1)]² − Zeeman(N) − (|c₁|I₁ + |c₂|I₂)(N+1) − |c₄|(I₁+1)(I₂+1) − (K_T + K_Q) − dE."""
    KT, KQ = _spin_norm(fl, m)
    K = KT + KQ
    I1, I2 = fl.arb(fl.fmpq(m.two_I1, 2)), fl.arb(fl.fmpq(m.two_I2, 2))
    N = L + 1
    x = N * (N + 1)
    Mm = _m_max(m, dMF)
    zterm = abs(fl.arb(m.z_N)) * _arb_frac(fl, min(Fraction(N), Mm)) + abs(fl.arb(m.z1)) * I1 + abs(fl.arb(m.z2)) * I2
    g = (_arb_frac(fl, Fraction(m.B)) * x - _arb_frac(fl, Fraction(m.D)) * x * x - zterm
         - (abs(fl.arb(m.c1)) * I1 + abs(fl.arb(m.c2)) * I2) * (N + 1)
         - abs(fl.arb(m.c4)) * (I1 + 1) * (I2 + 1) - K - fl.arb(m.dE))
    eta_f = max(float(normV.upper()), m.B * 1e-30)
    eta = fl.arb(eta_f)
    return g, eta_f, g - normV * normV / eta


def _approximate(states, el, k: int) -> np.ndarray:
    """Only to choose the trial points: it enters no proof. Dense Householder + Sturm bisection in floats
    (_deterministic): the same numbers on every machine."""
    n = len(states)
    M = [[0.0] * n for _ in range(n)]
    for (i, j), t in el.items():
        M[i][j] = M[j][i] = _float_of(t)
    return np.array(dense_lowest(M, k))


def _attempt(fl, m: SigmaMolecule, dMF: int, k: int, width: float, L: int, dl):
    Lmax = L + 2 if m.N_phys is None else min(L + 2, m.N_phys)      # never states beyond N_phys (outside the model)
    states, el = _symbolic_matrix(m, dMF, Lmax, dl)
    n_in = sum(1 for s in states if s[0] <= L)
    if n_in < k:
        raise OutOfDomain(f"the sector 2M_F = {dMF} with N ≤ {L} has only {n_in} states: fewer than k = {k}")
    arb = {ij: _arb_of(fl, t) for ij, t in el.items()}
    diag = [arb.get((i, i), fl.arb(0)) for i in range(n_in)]
    off = {(j, i): v for (i, j), v in arb.items() if i < j < n_in}
    w = max((j - i for (i, j) in el if j < n_in), default=0)
    # outer block
    if Lmax == L:                                                  # finite model fully included (D > 0, L = N_phys)
        diagA, t_out, eta_f = diag, None, 0.0
    else:
        rows: Dict[int, object] = {}
        cols: Dict[int, object] = {}
        for (i, j), v in arb.items():
            if i < n_in <= j:
                a = abs(v)
                rows[i] = rows.get(i, fl.arb(0)) + a
                cols[j] = cols.get(j, fl.arb(0)) + a
        normV = _norm_1_inf(fl, rows, cols)
        if not _g_increasing(m, dMF, L + 1):
            return None                                            # at this L the outer block is not dominated
        g, eta_f, t_out = _outer_bound(fl, m, dMF, L, normV)
        eta = fl.arb(eta_f)
        diagA = list(diag)
        for i in rows:
            diagA[i] = diag[i] - eta
    approx = _approximate(states[:n_in], {ij: t for ij, t in el.items() if ij[1] < n_in}, k)
    low, high = [], []
    for j in range(k):
        delta = max(abs(float(approx[j])), m.B) * width / 4
        for _ in range(60):
            if dl is not None and time.perf_counter() > dl:
                raise DeadlineExceeded(f"deadline exceeded at L = {L}")
            lo = Fraction(float(approx[j])) - Fraction(delta)
            hi = Fraction(float(approx[j])) + Fraction(delta)
            n_hi = _count_below_banded(fl, diag, off, w, _arb_frac(fl, hi))
            n_lo = _count_below_banded(fl, diagA, off, w, _arb_frac(fl, lo))
            if n_hi is not None and n_lo is not None and n_hi >= j + 1 and n_lo <= j:
                break
            delta *= 2
        else:
            return None
        if t_out is not None and not (t_out > _arb_frac(fl, hi)):
            return None
        low.append(lo)
        high.append(hi)
    return tuple(low), tuple(high), eta_f


def _arb_frac(fl, f: Fraction):
    return fl.arb(fl.fmpq(f.numerator, f.denominator))


def guaranteed_molecule_levels(m: SigmaMolecule, two_MF: int, k: int = 4, width: float = 1e-12, *,
                               deadline: Optional[float] = None, L_initial: Optional[int] = None,
                               L_limit: int = L_LIMIT, prec: int = PREC_MIN) -> Intervals:
    """First k levels of H in the sector M_F = two_MF/2 as guaranteed intervals. `width` is relative to
    max(|E_j|, B). Stops at the first L with state GUARANTEED; if an L gives only WIDE, L+2 is tried while the width
    halves, and the narrowest result (always valid) is returned. OutOfDomain if no L ≤ L_limit proves anything;
    DeadlineExceeded beyond `deadline` seconds."""
    if not isinstance(m, SigmaMolecule):
        raise OutOfDomain(f"expected a SigmaMolecule, got {type(m).__name__}")
    dMF = _integer(two_MF, "two_MF")
    if (dMF - m.two_I1 - m.two_I2) % 2 != 0:
        raise OutOfDomain("two_MF: parity incompatible with 2I1 + 2I2 (M_F must be integer or half-integer like I1+I2)")
    k = _integer(k, "k", 1)
    if k > K_MAX:
        raise OutOfDomain(f"k: at most {K_MAX}")
    width = _real(width, "width", positive=True)
    L_limit = _integer(L_limit, "L_limit", 0)
    if L_limit > L_LIMIT_MAX:
        raise OutOfDomain(f"L_limit: at most {L_LIMIT_MAX}")
    prec = _integer(prec, "prec", 2)
    if prec > PREC_MAX:
        raise OutOfDomain(f"prec: at most {PREC_MAX}")
    if deadline is not None:
        deadline = _real(deadline, "deadline", positive=True)
    fl = _flint()
    t0 = time.perf_counter()
    dl = None if deadline is None else t0 + deadline
    # smallest L: the sector must have at least k states
    L = 0
    while len(_states(m, dMF, L)) < k:
        L += 1
        if L > L_limit:
            raise OutOfDomain(f"the sector 2M_F = {dMF} has no k = {k} states within L_limit = {L_limit}")
        if dl is not None and time.perf_counter() > dl:
            raise DeadlineExceeded(f"deadline of {deadline} s exceeded while looking for the smallest L")
    if L_initial is not None:
        L = _integer(L_initial, "L_initial", 0)
    else:
        extra = 2 * math.sqrt(m.dE / m.B)                   # dE/B may be inf (1e300/1e-300): no int(inf)
        L = L + 2 + (int(extra) if extra <= L_limit else L_limit + 1)
    if m.N_phys is not None:
        if m.N_phys < L:
            if L_initial is not None:
                raise OutOfDomain(f"L_initial = {L} exceeds N_phys = {m.N_phys}: the model with D is defined on N ≤ N_phys")
            L = m.N_phys
        L_limit = min(L_limit, m.N_phys)
    if L > L_limit:
        raise OutOfDomain(f"initial L {L} > L_limit {L_limit}")
    old_prec = fl.ctx.prec
    best: Optional[Intervals] = None
    try:
        while True:
            p = max(prec, PREC_MIN)
            while p <= PREC_MAX:
                if dl is not None and time.perf_counter() > dl:
                    raise DeadlineExceeded(f"deadline of {deadline} s exceeded at L = {L}")
                fl.ctx.prec = p
                res = _attempt(fl, m, dMF, k, width, L, dl)
                if res is not None:
                    low, high, eta = res
                    w = max(float(a - b) for a, b in zip(high, low))
                    target = width * max(max(abs(float(b)) for b in low), m.B)
                    strings = tuple((str(float(b)), str(float(a))) for b, a in zip(low, high))
                    iv = Intervals(low, high, strings, w, "GUARANTEED" if w <= target else "WIDE",
                                   L, p, eta, round(time.perf_counter() - t0, 3))
                    if iv.state == "GUARANTEED":
                        return iv
                    # WIDE: valid, but a larger L is tried (the width from η falls with L) while it halves
                    if best is not None and not (w < best.max_width / 2):
                        return replace(best, seconds=round(time.perf_counter() - t0, 3))
                    best = iv
                    break
                p *= 2
            if L >= L_limit:
                break
            L = min(L + 2, L_limit)
        if best is not None:
            return replace(best, seconds=round(time.perf_counter() - t0, 3))
        raise OutOfDomain(f"no interval proven within L_limit = {L_limit}")
    finally:
        fl.ctx.prec = old_prec


def transition(iv: Intervals, i: int, iv2: Intervals, j: int) -> Tuple[Fraction, Fraction]:
    """Guaranteed E_j(iv2) − E_i(iv) (also between different sectors): [low_j − high_i, high_j − low_i].
    Closed inputs: indices beyond the given intervals → OutOfDomain."""
    if not isinstance(iv, Intervals) or not isinstance(iv2, Intervals):
        raise OutOfDomain("expected two Intervals")
    i = _integer(i, "i", 0)
    j = _integer(j, "j", 0)
    if i >= len(iv.low) or j >= len(iv2.low):
        raise OutOfDomain(f"indices {i}, {j} beyond the available levels ({len(iv.low)}, {len(iv2.low)})")
    return iv2.low[j] - iv.high[i], iv2.high[j] - iv.low[i]


# deprecated Italian field names of 0.2.0 (DeprecationWarning on use; removed in a later release)
add_field_aliases(SigmaMolecule, {"due_I1": "two_I1", "due_I2": "two_I2", "N_fis": "N_phys"})
