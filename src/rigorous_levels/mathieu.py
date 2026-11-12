# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""rigorous_levels/mathieu.py — Mathieu characteristic values a_r(q), b_r(q) as GUARANTEED intervals [low, high].

    y'' + (a − 2q cos 2z) y = 0            (DLMF 28.2.1), q any finite real (negative and large included)

The characteristic values are the eigenvalues of four symmetric tridiagonal matrices on the Fourier sectors
(DLMF 28.4, Fourier coefficients of ce_r and se_r), here written as Jacobi matrices:

    a_{2n}:    basis cos 2kz, k ≥ 0:  d_k = (2k)²,    off-diagonal q, except (0,1) = √2·q (symmetrized)
    b_{2n+2}:  basis sin 2kz, k ≥ 1:  d_k = (2k)²,    off-diagonal q
    a_{2n+1}:  basis cos(2k+1)z:      d_k = (2k+1)², d_0 = 1 + q, off-diagonal q
    b_{2n+1}:  basis sin(2k+1)z:      d_k = (2k+1)², d_0 = 1 − q, off-diagonal q

and a_r, b_r is the n-th eigenvalue (counted from 0) of its sector: n = r/2, r/2 − 1, (r−1)/2, (r−1)/2. b_0 does not
exist. This is the same operator as the charge-basis rotor with E_C = 1, n_g = ν/2 and coefficient 2q on cos φ
(`guaranteed_intervals`), split by parity: the sectors are what tells a_r from b_r.

Guarantee (docs/PROOF.md, the argument of the spherical rotor on a different lattice): with the cut K,
  - above:  λ_n(H) ≤ λ_n(H_K)                                     (Rayleigh–Ritz, Teschl Theorem 4.12(i));
  - below:  for η > 0, 2q x_K x_{K+1} ≥ −η x_K² − (q²/η) x_{K+1}², so H ≥ (H_K − η e_K e_Kᵀ) ⊕ H_O′ with
            H_O′ ≥ t = min(d_{K+1} − |q| − q²/η, d_{K+2} − 2|q|)   (Gershgorin as a form on the outer block, whose
            first site has one outer neighbour and the others two; d_k is increasing for k ≥ 0);
            if t > high_n then λ_n(H) ≥ λ_n(H_K − η e_K e_Kᵀ)         (Teschl Corollary 4.11);
  - counts "eigenvalues < x" by the LDLᵀ pivots of the tridiagonal in Arb balls (python-flint): the squares of the
    off-diagonal entries (q², 2q²) are exact rationals, so no irrational number enters the matrix.
The float64 q is an exact number; the interval contains a_r(q) of THAT q. Declared hypothesis: Arb/FLINT is correct.

Why this exists: scipy.special.mathieu_a/mathieu_b return the value of another order for some (r, q) (scipy issues
#4479, #14526; 522 wrong values on r ≤ 12, |q| ≤ 400 with scipy 1.10.1 … 1.18.1, measured 2026-11-11; fixed on
scipy main by PR #25128, milestone 2.0.0). qiskit-metal's `mathieu_level` inherits it (qiskit-metal #1252). Here the
order is guaranteed by the count, not by a root finder.
This package is not an external validator."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional, Tuple

import numpy as np

from rigorous_levels._deterministic import tridiagonal_lowest
from rigorous_levels.guaranteed_intervals import ArbMissing, DeadlineExceeded, OutOfDomain, _finite, _flint, _refuse_overflow
from rigorous_levels.spherical_rotor import _ball, _count_below

__all__ = ["MathieuValue", "mathieu_value", "mathieu_a", "mathieu_b", "sector", "OutOfDomain", "ArbMissing",
           "DeadlineExceeded"]

R_MAX = 200
K_LIMIT = 20000
PREC_MIN, PREC_MAX = 128, 1024
GUARANTEED, WIDE = "GUARANTEED", "WIDE"


@dataclass(frozen=True)
class MathieuValue:
    """[low, high] ∋ a_r(q) or b_r(q), exact Fractions; `width` relative target reached (GUARANTEED) or not (WIDE)."""

    kind: str                 # "a" | "b"
    r: int
    q: float
    low: Fraction
    high: Fraction
    strings: Tuple[str, str]
    max_width: float
    state: str
    K: int                    # cut of the Fourier basis used
    prec: int
    eta: float
    seconds: float

    def contains(self, value) -> bool:
        return self.low <= Fraction(value) <= self.high

    def mid(self) -> float:
        return float((self.low + self.high) / 2)


def sector(kind: str, r: int) -> Tuple[int, int, int]:
    """(ν, k0, n): parity ν of the sector, first basis index k0, index n of the eigenvalue in the sector."""
    if kind not in ("a", "b"):
        raise OutOfDomain(f"kind {kind!r}: expected 'a' or 'b'")
    if isinstance(r, bool) or not isinstance(r, (int, np.integer)) or r < 0 or r > R_MAX:
        raise OutOfDomain(f"r: expected an integer in [0, {R_MAX}]")
    r = int(r)
    if kind == "b" and r == 0:
        raise OutOfDomain("b_0(q) does not exist (no odd solution of order 0)")
    if r % 2 == 0:
        return 0, (0 if kind == "a" else 1), (r // 2 if kind == "a" else r // 2 - 1)
    return 1, 0, (r - 1) // 2


def _real_q(q) -> float:
    if isinstance(q, bool) or not isinstance(q, (int, float, np.integer, np.floating)):
        raise OutOfDomain(f"q: expected a finite real number, got {type(q).__name__}")
    try:
        q = float(q)
    except OverflowError:
        raise OutOfDomain("q: expected a finite real number (integer beyond float64)") from None
    if not math.isfinite(q):
        raise OutOfDomain("q: expected a finite real number")
    return q


def _matrix(kind: str, nu: int, k0: int, K: int, q: Fraction):
    """Exact diagonal and squared off-diagonal of the sector matrix on k0 ≤ k ≤ K."""
    diag = [Fraction((2 * k + nu) ** 2) for k in range(k0, K + 1)]
    if nu == 1:
        diag[0] += q if kind == "a" else -q
    off2 = [q * q] * (K - k0)
    if nu == 0 and kind == "a" and off2:
        off2[0] = 2 * q * q
    return diag, off2


def _estimate(diag, off2, n: int) -> float:
    """λ_n of the sector matrix rounded to floats, by Sturm bisection (_deterministic: the same float on every
    machine). Only to choose the trial points."""
    return tridiagonal_lowest([float(x) for x in diag], [float(x) for x in off2], n + 1, first=n)[0]


def _attempt(fl, kind: str, nu: int, k0: int, n: int, q: Fraction, K: int, width: float):
    diag, off2 = _matrix(kind, nu, k0, K, q)
    dA = [_ball(fl, x) for x in diag]
    oA = [_ball(fl, x) for x in off2]
    absq = abs(q)
    if absq == 0:                                    # no coupling: the sector matrix is diagonal and exact
        eta, t = Fraction(0), None
        dB = dA
    else:
        eta = absq                                   # any η > 0 is valid; η = |q| makes q²/η = |q|
        d1 = Fraction((2 * (K + 1) + nu) ** 2)
        d2 = Fraction((2 * (K + 2) + nu) ** 2)
        t = min(d1 - absq - q * q / eta, d2 - 2 * absq)
        dB = list(dA)
        dB[-1] = dA[-1] - _ball(fl, eta)
    est = _estimate(diag, off2, n)
    delta = max(abs(est), 1.0) * width / 4
    for _ in range(60):
        lo = Fraction(est) - Fraction(delta)
        hi = Fraction(est) + Fraction(delta)
        n_hi = _count_below(dA, oA, _ball(fl, hi))
        n_lo = _count_below(dB, oA, _ball(fl, lo))
        if n_hi is not None and n_lo is not None and n_hi >= n + 1 and n_lo <= n:
            break
        delta *= 2
    else:
        return None
    if t is not None and not t > hi:
        return None
    return lo, hi, float(eta)


@_refuse_overflow
def mathieu_value(kind: str, r: int, q, width: float = 1e-12, *, deadline: Optional[float] = None,
                  K_initial: Optional[int] = None, K_limit: int = K_LIMIT, prec: int = PREC_MIN) -> MathieuValue:
    """a_r(q) (kind "a") or b_r(q) (kind "b") as a guaranteed interval; `width` is relative to max(|a|, 1)."""
    nu, k0, n = sector(kind, r)
    qf = _real_q(q)
    if isinstance(width, bool) or not isinstance(width, (int, float)) or not _finite(width) or width <= 0:
        raise OutOfDomain("width: expected a finite number > 0")
    if isinstance(K_limit, bool) or not isinstance(K_limit, int) or K_limit < k0 + n + 1:
        raise OutOfDomain(f"K_limit: expected an integer >= {k0 + n + 1}")
    if K_limit > K_LIMIT:
        raise OutOfDomain(f"K_limit: at most {K_LIMIT}")
    if isinstance(prec, bool) or not isinstance(prec, int) or prec < 2 or prec > PREC_MAX:
        raise OutOfDomain(f"prec: expected an integer in [2, {PREC_MAX}]")
    if deadline is not None and (isinstance(deadline, bool) or not isinstance(deadline, (int, float))
                                 or not _finite(deadline) or deadline <= 0):
        raise OutOfDomain("deadline: expected a finite number > 0 or None")
    fl = _flint()
    t0 = time.perf_counter()
    qe = Fraction(qf)
    if K_initial is None:
        K = k0 + n + 12 + int(1.5 * math.sqrt(abs(qf)))
    else:
        if isinstance(K_initial, bool) or not isinstance(K_initial, int) or K_initial < k0 + n + 1:
            raise OutOfDomain(f"K_initial: expected an integer >= {k0 + n + 1}")
        K = K_initial
    K = min(K, K_limit)
    old_prec = fl.ctx.prec
    try:
        while True:
            p = max(prec, PREC_MIN)
            while p <= PREC_MAX:
                if deadline is not None and time.perf_counter() - t0 > deadline:
                    raise DeadlineExceeded(f"deadline of {deadline} s exceeded at K = {K}")
                fl.ctx.prec = p
                res = _attempt(fl, kind, nu, k0, n, qe, K, width)
                if res is not None:
                    lo, hi, eta = res
                    w = float(hi - lo)
                    target = width * max(abs(float(lo)), 1.0)
                    return MathieuValue(kind, int(r), qf, lo, hi, (str(float(lo)), str(float(hi))), w,
                                        GUARANTEED if w <= target else WIDE, K, p, eta, round(time.perf_counter() - t0, 3))
                p *= 2
            if K >= K_limit:
                break
            K = min(int(K * 1.5) + 5, K_limit)
        raise OutOfDomain(f"no interval proven within K_limit = {K_limit}")
    finally:
        fl.ctx.prec = old_prec


def mathieu_a(r: int, q, width: float = 1e-12, *, deadline: Optional[float] = None, K_initial: Optional[int] = None,
              K_limit: int = K_LIMIT, prec: int = PREC_MIN) -> MathieuValue:
    """Even characteristic value a_r(q), r ≥ 0."""
    return mathieu_value("a", r, q, width, deadline=deadline, K_initial=K_initial, K_limit=K_limit, prec=prec)


def mathieu_b(r: int, q, width: float = 1e-12, *, deadline: Optional[float] = None, K_initial: Optional[int] = None,
              K_limit: int = K_LIMIT, prec: int = PREC_MIN) -> MathieuValue:
    """Odd characteristic value b_r(q), r ≥ 1."""
    return mathieu_value("b", r, q, width, deadline=deadline, K_initial=K_initial, K_limit=K_limit, prec=prec)
