# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""rigorous_levels/fluxonium.py — fluxonium levels as GUARANTEED intervals [low, high] in the oscillator (Fock) basis.

    H = 4 E_C n² + (E_L/2) φ² − E_J cos(φ − φ_ext),    φ_ext = 2π·flux   (flux in units of Φ₀; energies in GHz)

H_0 = 4E_C n² + (E_L/2) φ² = ω (a†a + ½) with ω = √(8 E_L E_C) and φ = φ_zpf (a + a†), φ_zpf = (2E_C/E_L)^{1/4}
(same convention as scqubits.Fluxonium). V = −E_J cos(φ − φ_ext) is bounded, ‖V‖ ≤ E_J, and dense in Fock:
    e^{iφ} = D(iφ_zpf),  ⟨m|D|n⟩ = i^{|m−n|} φ_zpf^{|m−n|} e^{−φ_zpf²/2} √(min(m,n)!/max(m,n)!) L_{min}^{(|m−n|)}(φ_zpf²)
so cos(φ − φ_ext)_{mn} = cos(π(|m−n|/2 − 2·flux)) · g_{mn} with g real: a real symmetric matrix, built in Arb balls
(python-flint) from the exact rationals 2E_C/E_L, 8E_LE_C, the exponential, the square roots and the Laguerre
recurrence; cos(π·x) with x an exact rational of the float `flux` (cos_pi).

Guarantee (docs/PROOF.md): P = projector on the first N Fock states, Q = 1 − P.
  - above: λ_j(H) ≤ λ_j(PHP)                                                        (Rayleigh–Ritz);
  - below: for every coupling pair (i < N, o ≥ N), 2 V_io x_i x_o ≥ −|V_io| (x_i² + x_o²), so as forms
           H ≥ (PHP − diag(r_i)) ⊕ (QH_0Q + QVQ − diag(c_o)),  r_i = Σ_{o≥N} |V_io|,  c_o = Σ_{i<N} |V_io|;
           QH_0Q ≥ ω(N+½), QVQ ≥ −E_J, hence the outer block ≥ t = ω(N+½) − E_J − max_o c_o, and if t > high_j then
           λ_j(H) ≥ λ_j(PHP − diag(r_i))                                           (Teschl Corollary 4.11).
           The couplings with o < N + N2 are computed in Arb; beyond, |⟨i|D|o⟩| ≤ y^{d/2} √(o!/i!)/d! (DLMF 18.14.8,
           d = o − i, y = φ_zpf²) gives explicit geometric tails for r_i and max_o c_o. r_i is O(E_J) only for i near
           N, where the low eigenvectors are negligible: λ_j(PHP) − λ_j(PHP − diag r) shrinks super-exponentially
           with N (the operator norm ‖PVQ‖ does NOT: cos φ couples neighbouring Fock states with O(1) amplitude).
  - counts "eigenvalues < x" of the dense N×N matrices by LDLᵀ in Arb balls (an uncertain pivot raises the
    precision or moves the point). The float64 parameters are exact numbers; Arb/FLINT is assumed correct.
N grows (×1.5) until the width target holds, up to N_LIMIT (dense LDLᵀ in pure Python costs ~N³/6 Arb operations
per count: seconds at N ≈ 100, declared). `Intervals.alpha` carries max_o c_o (the outer lowering), `N` the inner cut.

What it does NOT say: that this one-mode H describes a device (no array modes, no quasiparticles, no charge noise).
This package is not an external validator."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional, Tuple

import numpy as np

from rigorous_levels._deterministic import dense_lowest
from rigorous_levels.guaranteed_intervals import ArbMissing, DeadlineExceeded, Intervals, OutOfDomain, _flint, _refuse_overflow
from rigorous_levels.hyperfine_molecule import _count_below_banded

__all__ = ["Fluxonium", "guaranteed_fluxonium_levels", "cos_matrix", "OutOfDomain", "ArbMissing", "DeadlineExceeded"]

K_MAX = 20
N_LIMIT = 240
PREC_MIN, PREC_MAX = 128, 1024
GUARANTEED, WIDE = "GUARANTEED", "WIDE"


def _real(x, name: str, positive: bool = False) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float, np.integer, np.floating)):
        raise OutOfDomain(f"{name}: expected a finite real number")
    try:
        x = float(x)
    except OverflowError:
        raise OutOfDomain(f"{name}: expected a finite real number (integer beyond float64)") from None
    if not math.isfinite(x) or (positive and x <= 0):
        raise OutOfDomain(f"{name}: expected a finite real number{' > 0' if positive else ''}")
    return x


@dataclass(frozen=True)
class Fluxonium:
    """E_C, E_J, E_L > 0 (GHz or any one unit); flux = Φ_ext/Φ₀ (0.5 = half flux quantum)."""

    E_C: float
    E_J: float
    E_L: float
    flux: float = 0.0

    def __post_init__(self):
        s = object.__setattr__
        s(self, "E_C", _real(self.E_C, "E_C", True))
        s(self, "E_J", _real(self.E_J, "E_J", True))
        s(self, "E_L", _real(self.E_L, "E_L", True))
        s(self, "flux", _real(self.flux, "flux"))

    @property
    def omega(self) -> float:
        return math.sqrt(8.0 * self.E_L * self.E_C)

    @property
    def phi_zpf(self) -> float:
        return math.sqrt(math.sqrt(2.0 * self.E_C / self.E_L))       # sqrt is correctly rounded: no libm pow


def _fmpq(fl, f: Fraction):
    return fl.fmpq(f.numerator, f.denominator)


def _laguerre_table(fl, nmax: int, alpha: int, x):
    """L_n^{(α)}(x) for n = 0…nmax by the three-term recurrence, in Arb."""
    out = [fl.arb(1)]
    if nmax >= 1:
        out.append(fl.arb(1 + alpha) - x)
    for n in range(1, nmax):
        out.append(((fl.arb(2 * n + 1 + alpha) - x) * out[n] - fl.arb(n + alpha) * out[n - 1]) / fl.arb(n + 1))
    return out


def cos_matrix(fl, N: int, phi2, flux: Fraction, scale: int = 1):
    """N×N Arb matrix of cos(scale·(φ − φ_ext)) in the Fock basis, phi2 = φ_zpf² (Arb ball), φ_ext = 2π·flux.
    ⟨m|cos(s(φ − φ_ext))|n⟩ = cos(π(d/2 − 2·s·flux)) · (sφ)^d e^{−s²φ²/2} √(min!/max!) L_min^{(d)}(s²φ²), d = |m − n|."""
    y = phi2 * (scale * scale)                        # (sφ_zpf)²
    sy = y.sqrt()
    e = (-y / 2).exp()
    rows = [[None] * N for _ in range(N)]
    for d in range(N):
        lag = _laguerre_table(fl, N - 1 - d, d, y)
        pref = fl.arb.cos_pi_fmpq(_fmpq(fl, Fraction(d, 2) - 2 * scale * flux)) * e * sy ** d
        for n in range(N - d):
            m = n + d
            ratio = Fraction(1)
            for j in range(n + 1, m + 1):
                ratio /= j
            v = pref * fl.arb(_fmpq(fl, ratio)).sqrt() * lag[n]
            rows[m][n] = rows[n][m] = v
    return fl.arb_mat(rows)


def _laguerre_bound_tail(fl, y, N: int, N2: int):
    """Rigorous bounds on the couplings beyond the computed block (DLMF 18.14.8: |L_n^{(α)}(x)| ≤ ((α+1)_n/n!) e^{x/2}
    for x ≥ 0, α ≥ 0), so that |⟨i|cos(φ−φ_ext)|o⟩| ≤ |⟨i|D|o⟩| ≤ v(i, o) = y^{d/2} √(o!/i!) / d!, d = o − i.
    For o ≥ o0 = N + N2 and i < N the ratio v(i, o+1)/v(i, o) = √(y (o+1)) / (o + 1 − i) ≤ ρ = √(y (o0+1)) / (N2 + 1);
    if ρ ≤ 1/2 then Σ_{o ≥ o0} v(i, o) ≤ 2 v(i, o0) (row tail of site i) and max_{o ≥ o0} Σ_{i<N} v(i, o) ≤ Σ_{i<N} v(i, o0)
    (column tail). Returns (row tails r_i for i < N, column tail bound, ρ ok) in Arb."""
    o0 = N + N2
    rho = (y * (o0 + 1)).sqrt() / (N2 + 1)
    ok = bool(rho <= fl.arb(fl.fmpq(1, 2)))
    rows, col = [], fl.arb(0)
    for i in range(N):
        d = o0 - i
        ratio = Fraction(1)
        for j in range(i + 1, o0 + 1):
            ratio *= j
        v = y ** fl.arb(fl.fmpq(d, 2)) * fl.arb(_fmpq(fl, ratio)).sqrt() / fl.arb(math.factorial(d))
        rows.append(2 * v)
        col += v
    return rows, col, ok


def _bounds(fl, f: Fluxonium, N: int, N2: int):
    """(C, ω, E_J, r, c_max, t): the cosine matrix on N + N2 states, the per-site lowerings r_i = Σ_{o≥N} |V_io|
    (computed up to N + N2, tail beyond), c_max ≥ max_o Σ_{i<N} |V_io| and the outer bound t = ω(N+½) − E_J − c_max.
    None if N2 is too small for the tail bound (ρ > ½)."""
    EC, EJ, EL = Fraction(f.E_C), Fraction(f.E_J), Fraction(f.E_L)
    flux = Fraction(f.flux)
    omega = fl.arb(_fmpq(fl, 8 * EL * EC)).sqrt()
    y = fl.arb(_fmpq(fl, 2 * EC / EL)).sqrt()                        # φ_zpf² = √(2E_C/E_L)
    EJa = fl.arb(_fmpq(fl, EJ))
    M = N + N2
    C = cos_matrix(fl, M, y, flux, 1)
    tails, col_tail, ok = _laguerre_bound_tail(fl, y, N, N2)
    if not ok:
        return None
    r = []
    for i in range(N):
        s = tails[i]
        for o in range(N, M):
            s += abs(C[i, o])
        r.append(EJa * s)
    cmax = col_tail
    for o in range(N, M):
        s = fl.arb(0)
        for i in range(N):
            s += abs(C[i, o])
        cmax = max(cmax, s)
    cmax = EJa * cmax
    half = fl.arb(fl.fmpq(1, 2))
    t_out = omega * (N + half) - EJa - cmax
    return C, omega, EJa, r, cmax, t_out


def _attempt(fl, f: Fluxonium, k: int, width: float, N: int, N2: int, dl: Optional[float]):
    """Intervals with N inner Fock states, or None (bounds from _bounds; counts by dense LDLᵀ)."""
    b = _bounds(fl, f, N, N2)
    if b is None:
        return None                                                  # N2 too small for the tail bound: grow
    C, omega, EJa, r, cmax, t_out = b
    half = fl.arb(fl.fmpq(1, 2))
    diag = [omega * (m + half) - EJa * C[m, m] for m in range(N)]
    diagB = [diag[i] - r[i] for i in range(N)]
    off = {(i, j): -EJa * C[i, j] for i in range(N) for j in range(i)}
    A = [[float(diag[i]) if i == j else float(-EJa * C[i, j]) for j in range(N)] for i in range(N)]
    approx = dense_lowest(A, k)                                      # same floats on every machine (_deterministic)
    low, high = [], []
    for j in range(k):
        delta = width / 4
        for _ in range(60):
            if dl is not None and time.perf_counter() > dl:
                raise DeadlineExceeded(f"deadline exceeded at N = {N}")
            lo = Fraction(float(approx[j])) - Fraction(delta)
            hi = Fraction(float(approx[j])) + Fraction(delta)
            n_hi = _count_below_banded(fl, diag, off, N - 1, fl.arb(_fmpq(fl, hi)))
            n_lo = _count_below_banded(fl, diagB, off, N - 1, fl.arb(_fmpq(fl, lo)))
            if n_hi is not None and n_lo is not None and n_hi >= j + 1 and n_lo <= j:
                break
            delta *= 2
        else:
            return None
        if not t_out > fl.arb(_fmpq(fl, hi)):
            return None
        low.append(lo)
        high.append(hi)
    return tuple(low), tuple(high), float(cmax.upper())


@_refuse_overflow
def guaranteed_fluxonium_levels(f: Fluxonium, k: int = 6, width: float = 1e-10, *, deadline: Optional[float] = None,
                                N_initial: Optional[int] = None, N_limit: int = N_LIMIT, prec: int = PREC_MIN) -> Intervals:
    """First k levels of H as guaranteed intervals (absolute width target `width`, unit of E_C). OutOfDomain if
    nothing is proven within N_limit Fock states; DeadlineExceeded beyond `deadline` seconds."""
    if not isinstance(f, Fluxonium):
        raise OutOfDomain(f"expected a Fluxonium, got {type(f).__name__}")
    if isinstance(k, bool) or not isinstance(k, (int, np.integer)) or k < 1 or k > K_MAX:
        raise OutOfDomain(f"k: expected an integer in [1, {K_MAX}]")
    k = int(k)
    width = _real(width, "width", True)
    if isinstance(N_limit, bool) or not isinstance(N_limit, int) or N_limit < k + 2 or N_limit > N_LIMIT:
        raise OutOfDomain(f"N_limit: expected an integer in [{k + 2}, {N_LIMIT}]")
    if isinstance(prec, bool) or not isinstance(prec, int) or prec < 2 or prec > PREC_MAX:
        raise OutOfDomain(f"prec: expected an integer in [2, {PREC_MAX}]")
    if deadline is not None:
        deadline = _real(deadline, "deadline", True)
    phi2 = math.sqrt(2.0 * f.E_C / f.E_L) if f.E_L > 0 else math.inf     # φ_zpf², float (inf if it overflows)
    if not math.isfinite(phi2) or phi2 > N_LIMIT:              # bounds N2 ≤ 2.5·N_LIMIT + 8
        # NEMESIS 0.3.0: E_C = 1e17 made N2 = 2.5·√(φ²N) unbounded and the cosine matrix on N + N2 states exhausted
        # the memory (host OOM); the oscillator basis cannot hold these levels within N_limit anyway
        raise OutOfDomain(f"φ_zpf² = √(2E_C/E_L) = {phi2:.3g}: beyond N_LIMIT = {N_LIMIT} (the levels need more Fock states than N_LIMIT)")
    fl = _flint()
    t0 = time.perf_counter()
    dl = None if deadline is None else t0 + deadline
    if N_initial is None:
        N = max(2 * k + 12, int(6 * phi2) + 16)
    else:
        if isinstance(N_initial, bool) or not isinstance(N_initial, int) or N_initial < k + 2:
            raise OutOfDomain(f"N_initial: expected an integer >= {k + 2}")
        N = N_initial
    N = min(N, N_limit)
    old_prec = fl.ctx.prec
    best: Optional[Intervals] = None
    try:
        while True:
            p = max(prec, PREC_MIN)
            while p <= PREC_MAX:
                if dl is not None and time.perf_counter() > dl:
                    raise DeadlineExceeded(f"deadline of {deadline} s exceeded at N = {N}")
                fl.ctx.prec = p
                res = _attempt(fl, f, k, width, N, max(40, int(2.5 * math.sqrt(phi2 * N)) + 8), dl)
                if res is not None:
                    low, high, b = res
                    w = max(float(a - c) for a, c in zip(high, low))
                    strings = tuple((str(float(c)), str(float(a))) for c, a in zip(low, high))
                    iv = Intervals(low, high, strings, w, GUARANTEED if w <= width else WIDE, N, p, b,
                                   round(time.perf_counter() - t0, 3))
                    if iv.state == GUARANTEED:
                        return iv
                    if best is not None and not (w < best.max_width / 2):
                        return best
                    best = iv
                    break
                p *= 2
            if N >= N_limit:
                break
            N = min(int(N * 1.5) + 2, N_limit)
        if best is not None:
            return best
        raise OutOfDomain(f"no interval proven within N_limit = {N_limit}")
    finally:
        fl.ctx.prec = old_prec
