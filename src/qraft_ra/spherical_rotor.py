# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra/spherical_rotor.py — SPHERICAL rotor in a field: levels as GUARANTEED intervals [low, high].

    H = B N(N+1) − D_c [N(N+1)]² − dE cos θ,   fixed M
        (linear polar molecule: B rotational constant, D_c centrifugal distortion, dE = dipole × field)

Basis |N, M⟩ with N ≥ |M|: diagonal f(N) = B N(N+1) − D_c [N(N+1)]²; cos θ couples only N ↔ N+1, with
    c_N = sqrt( ((N+1)² − M²) / ((2N+1)(2N+3)) )           (Brown–Carrington), and ‖cos θ‖ ≤ 1.
Same argument as qraft_ra/guaranteed_intervals.py, on the sphere instead of the circle:
  - UPPER bound: λ_j(H) ≤ λ_j(H_L), H_L the compression of H to N ≤ L (Rayleigh–Ritz, Teschl Theorem 4.12(i));
  - LOWER bound: for η > 0, 2bxy ≥ −|b|(x²η/|b| + y²|b|/η) on the single coupling L ↔ L+1 gives
        H ≥ (H_L − η e_L e_Lᵀ) ⊕ H_O′,   H_O′ ≥ t = f(L+1) − dE − (dE c_L)²/η;
    if t exceeds the upper bound of level j, λ_j(H) ≥ λ_j(H_L − η e_L e_Lᵀ) (Teschl Corollary 4.11);
  - "how many eigenvalues < x" by Sylvester's law of inertia on the LDLᵀ pivots of the tridiagonal, in Arb balls
    (python-flint). A pivot of uncertain sign raises the precision or moves the point: never an unproven count.
Centrifugal distortion (D_c > 0): f is an expansion valid only where it grows, that is for N(N+1) < B/(2 D_c). The
model is therefore DEFINED on the finite basis N ≤ N_phys = max{N : N(N+1) < B/(2D_c)} (declared, not a hidden
approximation): there f is increasing and the minimum of the outer block is f(L+1); if L reaches N_phys there is no
outer block and both bounds come from the same finite matrix. With D_c = 0 the basis is infinite as before.
Works in absolute units (those of B and D, for example MHz): no floating-point division enters the proof.
Declared hypotheses: H is the one of the exact float64 parameters; Arb/FLINT is correct.
Measurements (2026-11-10, author's repository): the intervals contain the numpy reference at a much larger truncation
in 177 of 177 cuts; RbCs at 1.2 V/cm gives 130.3 Hz of Stark shift for M = ±1 (Blackmore et al. 2018: 129 Hz).

What it does NOT say: that H describes a molecule. No hyperfine structure (for that: qraft_ra/hyperfine_molecule.py).
QRAFT-RA is an internal model, not an external validator.
Names: this module was `rotore_sferico_garantito` in 0.2.0 (deprecated aliases in that module).
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional, Tuple

import numpy as np

from qraft_ra._compat import add_field_aliases
from qraft_ra.guaranteed_intervals import ArbMissing, DeadlineExceeded, Intervals, OutOfDomain, _flint

__all__ = ["SphericalRotor", "guaranteed_sphere_levels", "transition", "OutOfDomain", "ArbMissing", "DeadlineExceeded"]

L_LIMIT = 20000
PREC_MIN, PREC_MAX = 128, 1024
K_MAX = 200


def _real(x, name: str, positive: bool) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise OutOfDomain(f"{name}: expected a finite real number")
    try:
        x = float(x)
    except OverflowError:                                   # int beyond float64 (10**400): out of domain, not a crash
        raise OutOfDomain(f"{name}: expected a finite real number (integer beyond float64)") from None
    if not math.isfinite(x):
        raise OutOfDomain(f"{name}: expected a finite real number")
    if (positive and x <= 0) or x < 0:
        raise OutOfDomain(f"{name}: must be {'> 0' if positive else '>= 0'}")
    return x


def _integer(x, name: str, minimum: Optional[int] = None) -> int:
    if isinstance(x, bool) or not isinstance(x, (int, np.integer)):
        raise OutOfDomain(f"{name}: expected an integer")
    x = int(x)
    if minimum is not None and x < minimum:
        raise OutOfDomain(f"{name}: expected >= {minimum}")
    return x


@dataclass(frozen=True)
class SphericalRotor:
    """H = B N(N+1) − D_c [N(N+1)]² − dE cos θ with fixed projection M; dE, D_c in the units of B."""

    B: float
    dE: float = 0.0
    M: int = 0
    Dc: float = 0.0

    def __post_init__(self):
        object.__setattr__(self, "B", _real(self.B, "B", True))
        object.__setattr__(self, "dE", _real(self.dE, "dE", False))
        object.__setattr__(self, "M", _integer(self.M, "M"))
        if abs(self.M) > L_LIMIT:
            raise OutOfDomain(f"M: |M| at most {L_LIMIT} (the basis starts at N = |M|)")
        object.__setattr__(self, "Dc", _real(self.Dc, "Dc", False))

    @property
    def N_phys(self) -> Optional[int]:
        """Largest N of the model (None = infinite basis): N(N+1) < B/(2 D_c)."""
        if self.Dc == 0.0:
            return None
        q = Fraction(self.B) / (2 * Fraction(self.Dc))
        N = int(math.isqrt(int(q))) + 1
        while N >= 0 and N * (N + 1) >= q:
            N -= 1
        return N


def _c2(N: int, M: int) -> Fraction:
    return Fraction((N + 1) ** 2 - M * M, (2 * N + 1) * (2 * N + 3))


def _approximate(r: SphericalRotor, L: int, k: int) -> np.ndarray:
    """Only to choose the trial points: it enters no proof."""
    Ns = np.arange(abs(r.M), L + 1)
    c = np.sqrt([float(_c2(int(N), r.M)) for N in Ns[:-1]])
    x = Ns * (Ns + 1.0)
    T = np.diag(r.B * x - r.Dc * x * x) - r.dE * (np.diag(c, 1) + np.diag(c, -1))
    return np.linalg.eigvalsh(T)[:k]


def _ball(fl, x):
    f = Fraction(x)
    return fl.arb(fl.fmpq(f.numerator, f.denominator))


def _count_below(diag, off2, x) -> Optional[int]:
    """Eigenvalues < x of the symmetric tridiagonal (diagonal, squares of the off-diagonal); None if a pivot is uncertain."""
    n = 0
    d = diag[0] - x
    for i in range(len(diag)):
        if i > 0:
            d = diag[i] - x - off2[i - 1] / d
        if d < 0:
            n += 1
        elif not (d > 0):
            return None
    return n


def _attempt(fl, r: SphericalRotor, k: int, width: float, L: int):
    """Intervals for the first k levels with the cut L, or None if nothing is proven at this L."""
    M = abs(r.M)
    Ns = range(M, L + 1)
    B, D, Dc = _ball(fl, r.B), _ball(fl, r.dE), _ball(fl, r.Dc)

    def f(N):                                     # exact diagonal: B x − D_c x², x = N(N+1)
        x = N * (N + 1)
        return B * x - Dc * x * x
    diag = [f(N) for N in Ns]
    off2 = [D * D * _ball(fl, _c2(N, M)) for N in range(M, L)]
    if r.N_phys is not None and L >= r.N_phys:    # finite model fully included: no outer block
        diagA, t, eta_f = diag, None, 0.0
    else:
        cL2 = _ball(fl, _c2(L, M))
        eta_f = max(r.dE * math.sqrt(float(_c2(L, M))), r.B * 1e-30)  # choice of η (any η > 0 is valid)
        eta = _ball(fl, eta_f)
        diagA = list(diag)
        diagA[-1] = diag[-1] - eta
        t = f(L + 1) - D - D * D * cL2 / eta      # f increasing on N ≤ N_phys: the minimum of the outer block is f(L+1)
    approx = _approximate(r, L, k)
    low, high = [], []
    for j in range(k):
        delta = max(abs(float(approx[j])), r.B) * width / 4
        for _ in range(60):
            lo = Fraction(float(approx[j])) - Fraction(delta)
            hi = Fraction(float(approx[j])) + Fraction(delta)
            n_hi = _count_below(diag, off2, _ball(fl, hi))
            n_lo = _count_below(diagA, off2, _ball(fl, lo))
            if n_hi is not None and n_lo is not None and n_hi >= j + 1 and n_lo <= j:
                break
            delta *= 2
        else:
            return None
        if t is not None and not (t > _ball(fl, hi)):
            return None
        low.append(lo)
        high.append(hi)
    return tuple(low), tuple(high), eta_f


def guaranteed_sphere_levels(r: SphericalRotor, k: int = 6, width: float = 1e-12, *,
                             deadline: Optional[float] = None, L_initial: Optional[int] = None,
                             L_limit: int = L_LIMIT, prec: int = PREC_MIN) -> Intervals:
    """First k levels of H (for the given M) as guaranteed intervals. `width` is the target relative to
    max(|E_j|, B); `deadline` in seconds (DeadlineExceeded). OutOfDomain if nothing is proven within L_limit."""
    if not isinstance(r, SphericalRotor):
        raise OutOfDomain(f"expected a SphericalRotor, got {type(r).__name__}")
    k = _integer(k, "k", 1)
    if k > K_MAX:
        raise OutOfDomain(f"k: at most {K_MAX}")
    width = _real(width, "width", True)
    L_limit = _integer(L_limit, "L_limit", abs(r.M) + k)
    if L_limit > L_LIMIT:
        raise OutOfDomain(f"L_limit: at most {L_LIMIT}")
    prec = _integer(prec, "prec", 2)
    if prec > PREC_MAX:
        raise OutOfDomain(f"prec: at most {PREC_MAX}")
    if deadline is not None:
        deadline = _real(deadline, "deadline", True)
    fl = _flint()
    t0 = time.time()
    if L_initial is not None:
        L = _integer(L_initial, "L_initial", abs(r.M) + k)
    else:
        extra = 2 * math.sqrt(r.dE / r.B)                   # dE/B may be inf: no int(inf)
        L = abs(r.M) + k + 10 + (int(extra) if extra <= L_limit else L_limit + 1)
    if r.N_phys is not None:
        if r.N_phys < abs(r.M) + k - 1:
            raise OutOfDomain(f"the model with D_c has only N ≤ {r.N_phys}: fewer than k = {k} levels for M = {r.M}")
        L = min(L, r.N_phys)
        L_limit = min(L_limit, r.N_phys)
    old_prec = fl.ctx.prec
    try:
        while L <= L_limit:
            p = max(prec, PREC_MIN)
            while p <= PREC_MAX:
                if deadline is not None and time.time() - t0 > deadline:
                    raise DeadlineExceeded(f"deadline of {deadline} s exceeded at L = {L}")
                fl.ctx.prec = p
                res = _attempt(fl, r, k, width, L)
                if res is not None:
                    low, high, eta = res
                    w = max(float(a - b) for a, b in zip(high, low))
                    target = width * max(max(abs(float(b)) for b in low), r.B)
                    strings = tuple((str(float(b)), str(float(a))) for b, a in zip(low, high))
                    return Intervals(low, high, strings, w, "GUARANTEED" if w <= target else "WIDE",
                                     L, p, eta, round(time.time() - t0, 3))
                p *= 2
            if L >= L_limit:
                break
            L = min(int(L * 1.5) + 5, L_limit)          # the last attempt is always L_limit (N_phys if D_c > 0)
        raise OutOfDomain(f"no interval proven within L_limit = {L_limit}")
    finally:
        fl.ctx.prec = old_prec


def transition(iv: Intervals, i: int, iv2: Intervals, j: int) -> Tuple[Fraction, Fraction]:
    """Guaranteed E_j(iv2) − E_i(iv) (also between different M): [low_j − high_i, high_j − low_i]."""
    return iv2.low[j] - iv.high[i], iv2.high[j] - iv.low[i]


# deprecated Italian field names of 0.2.0 (DeprecationWarning on use; removed in a later release)
add_field_aliases(SphericalRotor, {"N_fis": "N_phys"})
