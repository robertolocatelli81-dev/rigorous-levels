# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra.guaranteed_intervals — rotor levels as GUARANTEED intervals [low, high].

    H = 4 E_C (n − n_g)² + Σ_m c_m cos(mφ)        (same H as qraft_ra.rotor_spectrum, cosines only, 1 ≤ m ≤ 24)

For j < k:   λ_j(H_N′) ≤ λ_j(H) ≤ λ_j(H_N)

  - H_N is the compression of H to the charges |n| ≤ N. The upper bound comes from Rayleigh–Ritz
    (Teschl, Mathematical Methods in Quantum Mechanics, Theorem 4.12(i)).
  - H_N′ is H_N with the diagonal lowered by α·|c_m|/2 on the sites coupled outside I. Since H ≥ H_N′ ⊕ H_O′
    as forms (2bxy ≥ −|b|(αx² + y²/α)), Teschl's Corollary 4.11 gives the lower bound, provided
    H_O′ ≥ L_out > λ_{k−1}(H_N′), with L_out = 4E_C(N+1−|n_g|)² − Σ_m (|c_m|/2)(1 + max(1, 1/α)).
  - The eigenvalues of H_N and H_N′ are counted with Sylvester's law of inertia: banded A − xI = L D Lᵀ, computed
    with Arb balls (python-flint). A pivot of uncertain sign raises the precision or moves the point: a count that
    is not proven is never used.

Full argument and sources: docs/PROOF.md. python-flint is optional: if it is missing, the error `ArbMissing` gives
the reason and no number is returned. Names: this module was `intervallo_garantito` in 0.2.0 (deprecated aliases).

What it does NOT say: that H describes a device. The interval contains the true value of THIS H. Correctness rests
on Arb/FLINT and on this code. QRAFT-RA is an internal model, not an external validator.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, Decimal
from fractions import Fraction
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.linalg import eig_banded

from qraft_ra._compat import add_field_aliases, deprecated_function

K_MAX = 20            # largest number of levels
M_MAX = 24            # largest harmonic m (raised from 8 to 24 on 2026-11-09)
N_LIMIT = 4000       # largest basis: dim = 2·N_LIMIT + 1
PREC_MIN, PREC_MAX = 128, 1024
DIGITS = 24            # significant digits of the decimal strings, rounded outwards
GUARANTEED, WIDE = "GUARANTEED", "WIDE"   # states (0.2.0: GARANTITO, LARGO)


class ArbMissing(RuntimeError):
    """python-flint is not installed: no interval."""


class OutOfDomain(ValueError):
    """Input outside the domain where the theorem is applied here (reason in the message)."""


class DeadlineExceeded(RuntimeError):
    """The deadline given by the caller has passed."""


def _finite(x) -> bool:
    """math.isfinite without the OverflowError of an int beyond float64 (10**400)."""
    try:
        return math.isfinite(float(x))
    except OverflowError:
        return False


def _flint():
    try:
        import flint
    except ImportError as e:
        raise ArbMissing(f"python-flint is not installed ({e}): no guaranteed interval") from None
    return flint


@dataclass(frozen=True)
class Intervals:
    """k intervals [low, high] that contain λ_j(H), as exact fractions and as decimal strings."""

    low: Tuple[Fraction, ...]
    high: Tuple[Fraction, ...]
    strings: Tuple[Tuple[str, str], ...]
    max_width: float     # max_j (high − low), rounded up to 24 digits, then converted to float
    state: str               # GUARANTEED: max_width ≤ target; WIDE: valid intervals, but wider
    N: int
    prec: int
    alpha: float
    seconds: float

    def contains(self, j: int, value) -> bool:
        v = Fraction(value) if not isinstance(value, str) else Fraction(Decimal(value))
        return self.low[j] <= v <= self.high[j]

    def transition(self, i: int, j: int) -> Tuple[Fraction, Fraction]:
        """Guaranteed E_j − E_i: [low_j − high_i, high_j − low_i]."""
        return self.low[j] - self.high[i], self.high[j] - self.low[i]


# ── domain ──────────────────────────────────────────────────────────────────
def check_domain(r, k: int) -> None:
    if isinstance(k, bool) or not isinstance(k, (int, np.integer)) or not 1 <= k <= K_MAX:
        raise OutOfDomain(f"k must be an integer between 1 and {K_MAX}")
    # The theorem needs E_C > 0 and distinct integer harmonics 1 ≤ m: the Rotor constructor guarantees it, any other
    # object with the same attributes does not (m = 0, a repeated m or E_C < 0 gave false intervals before 2026-11-08).
    from qraft_ra.rotor_spectrum import Rotor
    if not isinstance(r, Rotor):
        raise OutOfDomain(f"expected a Rotor, got {type(r).__name__}")
    ms = [m for m, _ in r.cosines]
    if (any(isinstance(m, bool) or not isinstance(m, int) or m < 1 for m in ms) or len(set(ms)) != len(ms)
            or not (isinstance(r.E_C, float) and r.E_C > 0)):
        raise OutOfDomain("altered Rotor: E_C > 0 and distinct integer harmonics >= 1 are required")
    if any(s != 0.0 for _, s in r.sines):
        raise OutOfDomain("sin(mφ) terms: the matrix is complex, no interval is implemented")
    for m, _ in r.cosines:
        if m > M_MAX:
            raise OutOfDomain(f"harmonic {m} beyond the limit {M_MAX}")
    for x in (r.E_C, r.n_g, *(c for _, c in r.cosines)):
        if not math.isfinite(x):
            raise OutOfDomain("parameter not finite")


# ── inertia count in Arb ───────────────────────────────────────────────
def _count_below(arb, diag: Sequence, bande: Dict[int, object], x) -> Optional[int]:
    """Number of eigenvalues < x of the symmetric banded matrix (diag, constant bands), or None if a pivot
    has an uncertain sign. A − xI = L D Lᵀ without pivoting; if every D_i has a certain sign, the factorization
    really exists and (Sylvester) the D_i < 0 are the eigenvalues below x."""
    w = max(bande, default=0)
    n = len(diag)
    D: List = []
    L: List[Dict[int, object]] = []      # L[i][j] for i − w ≤ j < i
    negativi = 0
    for i in range(n):
        Li: Dict[int, object] = {}
        for j in range(max(0, i - w), i):
            s = bande.get(i - j)
            s = arb(0) if s is None else s
            Lj = L[j]
            for t in range(max(0, i - w), j):
                lit = Li.get(t)
                ljt = Lj.get(t)
                if lit is not None and ljt is not None:
                    s = s - lit * ljt * D[t]
            if s != 0 or not s.is_exact():
                Li[j] = s / D[j]
        d = diag[i] - x
        for t, lit in Li.items():
            d = d - lit * lit * D[t]
        if d < 0:
            negativi += 1
        elif not d > 0:
            return None
        D.append(d)
        L.append(Li)
    return negativi


# ── matrices in exact form (Fraction) ───────────────────────────────────────
def _matrix(r, N: int, alpha: Optional[Fraction]):
    """Diagonal and bands of H_N (alpha None) or of H_N′ (lowered by α|b| where a coupling leaves I).
    All in Fraction: the float64 inputs are exact numbers."""
    EC, ng = Fraction(r.E_C), Fraction(r.n_g)
    bande = {m: Fraction(c) / 2 for m, c in r.cosines if c != 0.0}
    diag = []
    for n in range(-N, N + 1):
        d = 4 * EC * (n - ng) ** 2
        if alpha is not None:
            for m, b in bande.items():
                for s in (m, -m):
                    if abs(n + s) > N:
                        d -= alpha * abs(b)
        diag.append(d)
    return diag, bande


def _choose_alpha(mezzo: Fraction, margine: Fraction) -> Fraction:
    """α > 0 such that Σ(|c_m|/2)/α ≈ margin/2 (exact dyadic). It affects only the width, not the validity:
    the validity is decided by the check L_out > λ_{k−1}(H_N′)."""
    if mezzo == 0:
        return Fraction(1)
    return Fraction(float(mezzo / (margine / 2)))


def _l_out(r, N: int, alpha: Fraction) -> Fraction:
    """Proven lower bound of H_O′ (docs/PROOF.md, step (b)): min_{|n|>N} 4E_C(n−n_g)² minus, for each harmonic,
    |c_m|/2 from the partner outside and |c_m|/(2α) (or |c_m|/2 if α > 1) from the partner inside. Needs N ≥ |n_g|."""
    absng = abs(Fraction(r.n_g))
    if N < absng:
        raise OutOfDomain("N < |n_g|: the minimum of the diagonal outside the basis is not at N+1")
    mezzo = sum(abs(Fraction(c)) / 2 for _, c in r.cosines if c != 0.0)
    return 4 * Fraction(r.E_C) * (N + 1 - absng) ** 2 - mezzo * (1 + max(Fraction(1), 1 / alpha))


def _arb_from_fraction(flint, f: Fraction):
    arb = flint.arb
    return arb(f.numerator) / arb(f.denominator)


def _float_estimates(diag, bande, k: int) -> np.ndarray:
    w = max(bande, default=0)
    n = len(diag)
    ab = np.zeros((w + 1, n))
    ab[w, :] = [float(d) for d in diag]
    for m, b in bande.items():
        ab[w - m, m:] = float(b)
    return eig_banded(ab, lower=False, eigvals_only=True, select="i", select_range=(0, k - 1))


def _first_order_shift(diag_su, diag_giu, bande, k: int) -> float:
    """max_j Σ_i v_j(i)² (d_i − d_i′), with v_j the float eigenvectors of H_N: estimate of λ_j(H_N) − λ_j(H_N′)
    without subtracting two large eigenvalues. Only for the filter: it enters no bound."""
    w = max(bande, default=0)
    n = len(diag_su)
    ab = np.zeros((w + 1, n))
    ab[w, :] = [float(d) for d in diag_su]
    for m, b in bande.items():
        ab[w - m, m:] = float(b)
    _, V = eig_banded(ab, lower=False, select="i", select_range=(0, k - 1))
    dd = np.array([float(a - b) for a, b in zip(diag_su, diag_giu)])
    return float(np.max((V ** 2 * dd[:, None]).sum(axis=0)))


def _enclose(flint, diag, bande, k: int, target: Fraction, prec: int, deadline):
    """For j < k, exact (a_j, b_j) with #eigenvalues<a_j ≤ j and #eigenvalues<b_j ≥ j+1, hence a_j ≤ λ_j < b_j."""
    cache: Dict[int, tuple] = {}
    norma = max(abs(float(d)) for d in diag) + 2 * sum(abs(float(b)) for b in bande.values())
    stime = _float_estimates(diag, bande, k)
    delta0 = Fraction(max(1e3 * 2.2e-16 * len(diag) * max(norma, 1.0), 1e-9))
    low, high = [], []
    pmax = prec

    def conta(x: Fraction) -> int:
        nonlocal pmax
        c, p = _count_arb(flint, diag, bande, cache, x, prec, deadline)
        pmax = max(pmax, p)
        return c

    for j in range(k):
        g = Fraction(float(stime[j]))
        d = delta0
        a = g - d
        while True:
            c = conta(a)
            if 0 <= c <= j:
                break
            d *= 4
            a = g - d
        d = delta0
        b = g + d
        while True:
            c = conta(b)
            if c >= j + 1:
                break
            d *= 4
            b = g + d
        while b - a > target:
            m = _halve(a, b)
            c = conta(m)
            if c < 0:                     # uncertain sign even at PREC_MAX: move the point, never guess
                m = a + (b - a) * 3 / 8
                m = _round_dyadic(m, a, b)
                c = conta(m)
                if c < 0:
                    break
            if c <= j:
                a = m
            else:
                b = m
        low.append(a)
        high.append(b)
    return low, high, pmax


def _halve(a: Fraction, b: Fraction) -> Fraction:
    return _round_dyadic((a + b) / 2, a, b)


def _round_dyadic(m: Fraction, a: Fraction, b: Fraction) -> Fraction:
    """A short dyadic near m inside (a, b): keeps the conversions to Arb exact."""
    larg = b - a
    e = 0
    while Fraction(1, 2 ** e) > larg / 8:
        e += 1
    q = Fraction(math.floor(m * 2 ** e), 2 ** e)
    return q if a < q < b else m


def _count_arb(flint, diag, bande, cache: Dict, x: Fraction, prec: int, deadline) -> Tuple[int, int]:
    """Proven count at x. The entries are converted to Arb balls at the current precision (cached per precision);
    if a pivot has an uncertain sign the precision doubles up to PREC_MAX. Returns (count or −1, precision)."""
    p = prec
    while p <= PREC_MAX:
        if deadline is not None and time.monotonic() > deadline:
            raise DeadlineExceeded("deadline exceeded during a count")
        old = flint.ctx.prec
        flint.ctx.prec = p
        try:
            if p not in cache:
                cache[p] = ([_arb_from_fraction(flint, d) for d in diag],
                            {m: _arb_from_fraction(flint, b) for m, b in bande.items()})
            diag_a, bande_a = cache[p]
            c = _count_below(flint.arb, diag_a, bande_a, _arb_from_fraction(flint, x))
        finally:
            flint.ctx.prec = old
        if c is not None:
            return c, p
        p *= 2
    return -1, p


def _decimal(f: Fraction, verso_alto: bool) -> str:
    ctx = Context(prec=DIGITS, rounding=ROUND_CEILING if verso_alto else ROUND_FLOOR)
    v = ctx.divide(Decimal(f.numerator), Decimal(f.denominator))
    return format(v, "e") if v != 0 else "0"


def guaranteed_levels(r, k: int = 6, width: float = 1e-12, *, deadline: Optional[float] = None,
                      N_initial: Optional[int] = None, N_limit: int = N_LIMIT, prec: int = PREC_MIN) -> Intervals:
    """First k levels of H as guaranteed intervals. `width` is the target width (GHz, or the unit of E_C);
    `deadline` is a time in seconds after which DeadlineExceeded is raised (cooperative check)."""
    check_domain(r, k)
    if isinstance(width, bool) or not isinstance(width, (int, float)) or not _finite(width) or width <= 0:
        raise OutOfDomain("width must be a finite number > 0")
    for name, v, minimo in (("N_initial", N_initial, 0), ("N_limit", N_limit, 1), ("prec", prec, 2)):
        if v is None and name == "N_initial":
            continue
        if isinstance(v, bool) or not isinstance(v, int) or v < minimo:
            raise OutOfDomain(f"{name}: expected an integer >= {minimo}")
    if prec > PREC_MAX:
        raise OutOfDomain(f"prec beyond {PREC_MAX}")
    if N_limit > N_LIMIT or (N_initial is not None and N_initial > N_LIMIT):
        raise OutOfDomain(f"N_limit, N_initial: at most {N_LIMIT}")
    if deadline is not None and (isinstance(deadline, bool) or not isinstance(deadline, (int, float))
                                 or not _finite(deadline) or deadline < 0):
        raise OutOfDomain("deadline: expected a finite number >= 0 or None")
    flint = _flint()
    t0 = time.monotonic()
    deadline = None if deadline is None else t0 + float(deadline)
    U = sum(abs(c) for _, c in r.cosines)
    absng = abs(Fraction(r.n_g))
    if N_initial is None:
        N = int(math.ceil(abs(r.n_g))) + max(12, int(6 * (max(U, r.E_C) / r.E_C) ** 0.25 * math.sqrt(k + 1)))
    else:
        N = int(N_initial)
    N = max(N, int(math.ceil(abs(r.n_g))), (k + 1) // 2)
    obiettivo = Fraction(width)
    ultimo = None
    incerto = False            # a count kept an uncertain sign even at PREC_MAX
    while N <= N_limit:
        if deadline is not None and time.monotonic() > deadline:
            raise DeadlineExceeded("deadline exceeded")
        diag_su, bande = _matrix(r, N, None)
        stime = _float_estimates(diag_su, bande, k)
        d_out = 4 * Fraction(r.E_C) * (N + 1 - absng) ** 2
        mezzo = sum(abs(b) for b in bande.values())          # Σ |c_m| / 2
        margine = d_out - 2 * mezzo - Fraction(float(stime[-1]))
        if margine <= 0:
            N *= 2
            continue
        alpha = _choose_alpha(mezzo, margine)
        if alpha <= 0:
            N *= 2
            continue
        diag_giu, _ = _matrix(r, N, alpha)
        # float filter (proves nothing): if H_N and H_N′ already differ by more than the target, the basis grows.
        # First-order estimate Σ_i v_j(i)² (d_i − d_i′), not the difference of two float eigenvalues: that one is
        # rounding noise (≈ 6e-8 at E_C = 1e6) and pushed N up to 2080, beyond 30 s.
        if N * 2 <= N_limit and _first_order_shift(diag_su, diag_giu, bande, k) > float(obiettivo) / 4:
            N *= 2
            continue
        L_out = _l_out(r, N, alpha)
        target = obiettivo / 8
        alti_b, high, p1 = _enclose(flint, diag_su, bande, k, target, prec, deadline)
        low, alti_giu, p2 = _enclose(flint, diag_giu, bande, k, target, prec, deadline)
        incerto = incerto or max(p1, p2) > PREC_MAX
        if not L_out > alti_giu[-1]:
            N *= 2
            continue
        if any(lo > hi for lo, hi in zip(low, high)):
            raise RuntimeError("empty interval: violation of the theorem or a defect of this code")  # pragma: no cover
        strings = tuple((_decimal(lo, False), _decimal(hi, True)) for lo, hi in zip(low, high))
        bassi_s = tuple(Fraction(Decimal(s[0])) for s in strings)
        alti_s = tuple(Fraction(Decimal(s[1])) for s in strings)
        larg = max(h - l for l, h in zip(bassi_s, alti_s))
        ultimo = Intervals(bassi_s, alti_s, strings, float(_decimal(larg, True)),
                            GUARANTEED if larg <= obiettivo else WIDE, N, min(max(p1, p2), PREC_MAX), float(alpha),
                            time.monotonic() - t0)
        if larg <= obiettivo or N * 2 > N_limit:
            return ultimo
        N *= 2
    if ultimo is not None:
        return ultimo
    if incerto:
        raise OutOfDomain(f"counts with an uncertain sign even at {PREC_MAX} bits: the ends are too wide for the "
                          f"condition on L_out to hold with N ≤ {N_limit}")
    raise OutOfDomain(f"no basis N ≤ {N_limit} satisfies the condition on L_out")


def as_strings(iv: Intervals) -> List[List[str]]:
    return [list(s) for s in iv.strings]


# deprecated Italian field names of 0.2.0 (DeprecationWarning on use; removed in a later release)
add_field_aliases(Intervals, {"bassi": "low", "alti": "high", "stringhe": "strings", "larghezza_max": "max_width",
                              "stato": "state", "secondi": "seconds"})
Intervals.contiene = deprecated_function(Intervals.contains, "contiene")
Intervals.transizione = deprecated_function(Intervals.transition, "transizione")
