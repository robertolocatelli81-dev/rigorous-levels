# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra/matrix_elements.py — GUARANTEED matrix elements ⟨v_i|X|v_j⟩ between eigenvectors of the charge-basis
rotor, for X = n (charge), cos mφ, sin mφ: what enters T1 (Purcell, charge coupling), g, Rabi rates.

    H = 4E_C(n − n_g)² + Σ_m c_m cos(mφ)       (cosines only, as in guaranteed_intervals)

Eigenvectors are not computed rigorously: the float eigenvectors ψ_j of the truncated H_N are taken as approximations
of the true eigenvectors v_j of H and the error is BOUNDED (docs/PROOF.md):

  - residual: r_j = (H − λ̃_j) ψ_j is computed EXACTLY (Fraction: ψ_j has finite support, H maps it to a finite
    vector, λ̃_j = midpoint of the guaranteed enclosure of λ_j); ε_j = ‖r_j‖/‖ψ_j‖;
  - gap: δ_j = min(λ̃_j − high_{j−1}, low_{j+1} − λ̃_j) from the guaranteed enclosures of the neighbouring levels
    (k + 1 levels are enclosed); if the enclosures overlap, nothing is proven (OutOfDomain: the level is not
    separated at this width);
  - spectral theorem: ‖(1 − P_j) ψ_j‖ ≤ ε_j / δ_j =: s_j, and with the phase of v_j fixed by ⟨v_j, ψ_j⟩ ≥ 0,
    ‖ψ_j − v_j‖² = ‖(1 − P_j)ψ_j‖² + (1 − ⟨v_j, ψ_j⟩)² ≤ s_j² + s_j⁴ (needs s_j < 1);  e_j := s_j (1 + s_j²) ≥ √(s_j² + s_j⁴);
  - bounded X (‖cos mφ‖ = ‖sin mφ‖ = 1): |⟨v_i|X|v_j⟩ − ⟨ψ_i|X|ψ_j⟩| ≤ e_i + e_j;
  - X = n (unbounded): |⟨v_i|n|v_j⟩ − ⟨ψ_i|n|ψ_j⟩| ≤ e_i ‖n v_j‖ + ‖n ψ_i‖ e_j, with ‖n ψ_i‖ exact and
    ‖n v_j‖ ≤ ‖(n − n_g) v_j‖ + |n_g|, ‖(n − n_g) v_j‖² = ⟨v_j|(H − V)|v_j⟩/(4E_C) ≤ (high_j + Σ|c_m|)/(4E_C).
  ⟨ψ_i|X|ψ_j⟩ is exact (Fraction). Square roots are bounded above by integer square roots. The sin element of real
  vectors is purely imaginary: `value` is Im⟨ψ_i|sin mφ|ψ_j⟩ with ⟨n+m|sin mφ|n⟩ = 1/(2i), i.e. the element is
  i·value. The sign of a matrix element follows the sign convention of ψ (⟨v_j, ψ_j⟩ ≥ 0): compare |value|.

Every quantity is rational except the two integer square roots; the enclosure [low, high] is rigorous for the H
written, truncation included (the residual is against the full operator), under the hypotheses of guaranteed_intervals.
QRAFT-RA is an internal model, not an external validator."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, Optional, Tuple

import numpy as np

from qraft_ra._deterministic import band_eigenvector, band_lowest
from qraft_ra.guaranteed_intervals import GUARANTEED, Intervals, OutOfDomain, guaranteed_levels
from qraft_ra.rotor_spectrum import InputRejected, Rotor

__all__ = ["MatrixElement", "guaranteed_matrix_element", "OutOfDomain"]

OPERATORS = ("n", "cos", "sin")
K_MAX = 20


@dataclass(frozen=True)
class MatrixElement:
    operator: str
    m: int                      # harmonic for cos/sin (0 for n)
    i: int
    j: int
    low: Fraction
    high: Fraction
    value: float                # ⟨ψ_i|X|ψ_j⟩ (exact, as float)
    max_width: float
    sin_bounds: Tuple[float, float]     # s_i, s_j: bounds on ‖(1 − P)ψ‖
    gaps: Tuple[float, float]           # δ_i, δ_j
    residuals: Tuple[float, float]      # ε_i, ε_j
    intervals: Intervals                # the k + 1 guaranteed levels used
    N: int
    seconds: float

    def contains(self, x) -> bool:
        return self.low <= Fraction(x) <= self.high


def _sqrt_upper(x: Fraction) -> Fraction:
    """A rational ≥ √x for x ≥ 0: √(p/q) = √(pq)/q ≤ (isqrt(pq) + 1)/q."""
    if x < 0:
        raise ArithmeticError("square root of a negative number")
    return Fraction(math.isqrt(x.numerator * x.denominator) + 1, x.denominator)


def _sqrt_lower(x: Fraction) -> Fraction:
    """A rational ≤ √x for x ≥ 0: isqrt(pq)/q."""
    if x < 0:
        raise ArithmeticError("square root of a negative number")
    return Fraction(math.isqrt(x.numerator * x.denominator), x.denominator)


def _vectors(r: Rotor, N: int, k: int):
    """Float eigenvectors of H_N, as dicts n -> Fraction (exact values of the float entries): bisection estimates of
    the k lowest eigenvalues, then inverse iteration, in floats that are the same on every machine (_deterministic:
    no BLAS/LAPACK; sign fixed by the largest entry > 0). They enter the bound only through the exact residual."""
    EC, ng = Fraction(r.E_C), Fraction(r.n_g)
    ns = range(-N, N + 1)
    dim = 2 * N + 1
    diag = [float(4 * EC * (n - ng) ** 2) for n in ns]
    bands = {m: [c / 2.0] * (dim - m) for m, c in r.cosines if c != 0.0 and m < dim}
    out = []
    for lam in band_lowest(diag, bands, k):
        v = band_eigenvector(diag, bands, lam)
        out.append({n: Fraction(x) for n, x in zip(ns, v) if x != 0.0})
    return out


def _apply_H(r: Rotor, v: Dict[int, Fraction]) -> Dict[int, Fraction]:
    EC, ng = Fraction(r.E_C), Fraction(r.n_g)
    out: Dict[int, Fraction] = {}
    for n, x in v.items():
        out[n] = out.get(n, Fraction(0)) + 4 * EC * (n - ng) ** 2 * x
        for m, c in r.cosines:
            b = Fraction(c) / 2
            if b:
                out[n + m] = out.get(n + m, Fraction(0)) + b * x
                out[n - m] = out.get(n - m, Fraction(0)) + b * x
    return out


def _norm2(v: Dict[int, Fraction]) -> Fraction:
    return sum(x * x for x in v.values())


def _element(op: str, m: int, u: Dict[int, Fraction], v: Dict[int, Fraction]) -> Fraction:
    """⟨u|X|v⟩ exact for real vectors: n; cos mφ = ½(|n+m⟩⟨n| + h.c.); Im of sin mφ = ½(|n+m⟩⟨n| − |n−m⟩⟨n|)·(1/i)."""
    if op == "n":
        return sum(u[n] * x * n for n, x in v.items() if n in u)
    s = Fraction(0)
    for n, x in v.items():
        up, dn = u.get(n + m), u.get(n - m)
        if op == "cos":
            s += ((up or 0) + (dn or 0)) * x / 2
        else:                                   # ⟨n+m| sin mφ |n⟩ = 1/(2i), ⟨n−m| sin mφ |n⟩ = −1/(2i): Im part
            s += ((up or 0) - (dn or 0)) * x / 2 * -1
    return s


def guaranteed_matrix_element(r: Rotor, i: int, j: int, operator: str = "n", m: int = 1, k: Optional[int] = None,
                              width: float = 1e-12, *, deadline: Optional[float] = None) -> MatrixElement:
    """Guaranteed enclosure of ⟨v_i|X|v_j⟩ (X = n, cos mφ or sin mφ) for the rotor `r`; `k` levels are used
    (default max(i, j) + 2, at least max(i, j) + 2 so that the gap above level max(i, j) is known)."""
    if not isinstance(r, Rotor):
        raise OutOfDomain(f"expected a Rotor, got {type(r).__name__}")
    if r.sines:
        raise OutOfDomain("sin(mφ) terms: not covered (complex matrix)")
    for name, v in (("i", i), ("j", j)):
        if isinstance(v, bool) or not isinstance(v, (int, np.integer)) or v < 0 or v >= K_MAX - 1:
            raise OutOfDomain(f"{name}: expected an integer in [0, {K_MAX - 2}]")
    i, j = int(i), int(j)
    if operator not in OPERATORS:
        raise OutOfDomain(f"operator {operator!r} not in {OPERATORS}")
    if isinstance(m, bool) or not isinstance(m, int) or m < 1:
        raise OutOfDomain("m: expected an integer >= 1")
    if operator == "n":
        m = 0
    kk = max(i, j) + 2 if k is None else k
    if isinstance(kk, bool) or not isinstance(kk, int) or kk < max(i, j) + 2 or kk > K_MAX:
        raise OutOfDomain(f"k: expected an integer in [{max(i, j) + 2}, {K_MAX}]")
    t0 = time.perf_counter()
    try:
        iv = guaranteed_levels(r, kk, width, deadline=deadline)
    except InputRejected as e:
        raise OutOfDomain(str(e)) from None
    vecs = _vectors(r, iv.N, kk)
    EC = Fraction(r.E_C)
    normV = sum(abs(Fraction(c)) for _, c in r.cosines)
    sin_b, gaps, eps, errs = [], [], [], []
    for idx in (i, j):
        psi = vecs[idx]
        lam = (iv.low[idx] + iv.high[idx]) / 2
        res = _apply_H(r, psi)
        for n, x in psi.items():
            res[n] -= lam * x
        e = _sqrt_upper(_norm2(res) / _norm2(psi))
        d_lo = lam - iv.high[idx - 1] if idx > 0 else None
        d_hi = iv.low[idx + 1] - lam
        delta = d_hi if d_lo is None else min(d_lo, d_hi)
        if delta <= 0:
            raise OutOfDomain(f"level {idx} is not separated from its neighbours at width {width}: no eigenvector bound")
        s = e / delta
        if s >= 1:
            raise OutOfDomain(f"level {idx}: residual {float(e):.3e} over gap {float(delta):.3e} gives no eigenvector bound")
        sin_b.append(s)
        gaps.append(delta)
        eps.append(e)
        errs.append(s * (1 + s * s))
    psi_i, psi_j = vecs[i], vecs[j]
    val_un = _element(operator, m, psi_i, psi_j)                    # exact, unnormalised
    nn = _norm2(psi_i) * _norm2(psi_j)                               # ‖ψ_i‖²‖ψ_j‖², exact
    cands = (val_un / _sqrt_upper(nn), val_un / _sqrt_lower(nn))     # the normalised element lies between them
    v_lo, v_hi = min(cands), max(cands)
    val = (v_lo + v_hi) / 2
    if operator == "n":
        ng = abs(Fraction(r.n_g))
        n_psi_i = _sqrt_upper(sum((x * n) ** 2 for n, x in psi_i.items()) / _norm2(psi_i))      # ‖nψ_i‖/‖ψ_i‖
        n_v_j = _sqrt_upper((iv.high[j] + normV) / (4 * EC)) + ng
        err = errs[0] * n_v_j + n_psi_i * errs[1]
    else:
        err = errs[0] + errs[1]
    low, high = v_lo - err, v_hi + err
    return MatrixElement(operator, m, i, j, low, high, float(val), float(high - low),
                         (float(sin_b[0]), float(sin_b[1])), (float(gaps[0]), float(gaps[1])),
                         (float(eps[0]), float(eps[1])), iv, iv.N, round(time.perf_counter() - t0, 3))
