# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra/duffing_vs_transmon.py — GUARANTEED per-level error of the Duffing model against the full transmon.

The dynamics stacks (qutip-qip circuitqed.py:84-120, dynamiqs benchmarks/systems.py:58-82) use
H_D = ω a†a + (α/2) a†a†aa; its levels are exact and diagonal in Fock: E^D_j = ω j + (α/2) j (j − 1). The full
transmon H = 4E_C(n − n_g)² − E_J cos φ has levels E_j enclosed by the intervals of qraft_ra/guaranteed_intervals.py.
Here:
  variant "spectrum": ω = E_1 − E_0 and α = (E_2 − E_1) − (E_1 − E_0) taken from the GUARANTEED intervals (by
                      construction δ_0 = δ_1 = δ_2 = 0): δ_j = (E_j − E_0) − E^D_j for j ≥ 3 as an exact interval;
  variant "koch":     ω = √(8 E_J E_C) − E_C and α = −E_C (Koch et al. 2007, eq. 2.11-2.12, first order): δ_j for
                      j ≥ 1, with √(8E_JE_C) enclosed in an Arb ball converted to a rational interval.
Closed inputs (OutOfDomain with the reason). Measured on 200 transmons of the device regime (2026-11-11): |δ_3| ≥ 1 MHz
in 200 of 200 (median 34 MHz). QRAFT-RA is an internal model, not an external validator."""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional, Tuple

from qraft_ra._compat import add_field_aliases, deprecated_function
from qraft_ra.guaranteed_intervals import Intervals, OutOfDomain, _flint, guaranteed_levels
from qraft_ra.rotor_spectrum import Rotor

__all__ = ["DuffingError", "duffing_error", "duffing_levels", "OutOfDomain"]

VARIANTS = ("spectrum", "koch")     # 0.2.0: "spettro", "koch"
K_MAX = 20


@dataclass(frozen=True)
class DuffingError:
    variant: str
    omega: Tuple[Fraction, Fraction]          # interval of ω (GHz)
    alpha: Tuple[Fraction, Fraction]          # interval of α (GHz)
    delta: Tuple[Tuple[Fraction, Fraction], ...]   # for j < k: interval of (E_j − E_0) − E^D_j
    intervals: Intervals                      # the transmon levels used
    E_C: float

    def delta_float(self):
        return tuple((float(a), float(b)) for a, b in self.delta)

    def delta_over_EC(self):
        return tuple((float(a) / self.E_C, float(b) / self.E_C) for a, b in self.delta)


def _real(x, name, positive=False):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise OutOfDomain(f"{name}: expected a finite real number")
    try:
        x = float(x)
    except OverflowError:
        raise OutOfDomain(f"{name}: expected a finite real number") from None
    if not math.isfinite(x) or (positive and x <= 0):
        raise OutOfDomain(f"{name}: expected a finite real{' > 0' if positive else ''}")
    return x


def duffing_levels(omega: Fraction, alpha: Fraction, j: int) -> Fraction:
    """E^D_j = ω j + (α/2) j (j − 1), exact."""
    return omega * j + alpha * j * (j - 1) / 2


def _sqrt_interval(fl, x: Fraction, prec: int = 128) -> Tuple[Fraction, Fraction]:
    """Rational [low, high] enclosing √x (Arb ball → ends as Fractions)."""
    old_prec = fl.ctx.prec
    fl.ctx.prec = prec
    try:
        s = fl.arb(fl.fmpq(x.numerator, x.denominator)).sqrt()
        lo = Fraction(str(s.lower().str(40, radius=False)))
        hi = Fraction(str(s.upper().str(40, radius=False)))
    finally:
        fl.ctx.prec = old_prec
    # the 40-digit strings are ROUNDED, not directed outwards: they are widened until the inclusion is verified in
    # EXACT arithmetic (Fraction); the final inclusion is proven by the check, not by the string
    return _widen(lo, hi, x)


def _widen(lo: Fraction, hi: Fraction, x: Fraction) -> Tuple[Fraction, Fraction]:
    """Rational [lo', hi'] with lo' ≤ √x ≤ hi' (x ≥ 0), starting from a guess [lo, hi] (the rounded strings of Arb).
    Validity in EXACT arithmetic: hi' ≥ 0 and hi'² ≥ x; lo' ≤ 0 or lo'² ≤ x.
    hi: if negative it restarts from max(x, 1) (max(x,1)² ≥ x), then grows with a doubling step (always finite: hi > 0
    increasing). lo: if the guess does not hold it falls back to x / hi' ((x/hi')² = x²/hi'² ≤ x): no loop that could
    jump over √x (reviewer, 2026-11-11: with lo ≥ ~10√x or lo negative the decrement loop did not terminate)."""
    if x < 0:
        raise ArithmeticError("square root of a negative number")
    if hi < 0:
        hi = max(x, Fraction(1))
    step = max(abs(hi), Fraction(1)) * Fraction(1, 10 ** 35)
    while hi * hi < x:
        hi += step
        step *= 2
    if lo > 0 and lo * lo > x:
        lo = x / hi if hi > 0 else Fraction(0)
    if not (lo <= hi) or hi < 0 or hi * hi < x or (lo > 0 and lo * lo > x):
        raise ArithmeticError("interval of the square root not verified")
    return lo, hi


def duffing_error(E_C: float, E_J: float, n_g: float = 0.0, k: int = 6, variant: str = "spectrum", *,
                  width: float = 1e-12, deadline: Optional[float] = None) -> DuffingError:
    """Guaranteed per-level error of the Duffing model against the transmon (units of E_C, E_J; GHz by convention)."""
    E_C = _real(E_C, "E_C", positive=True)
    E_J = _real(E_J, "E_J", positive=True)
    n_g = _real(n_g, "n_g")
    if isinstance(k, bool) or not isinstance(k, int) or k < 3 or k > K_MAX:
        raise OutOfDomain(f"k: expected an integer in [3, {K_MAX}] (δ is meaningful from j = 3; ω and α use the first three levels)")
    if variant not in VARIANTS:
        raise OutOfDomain(f"variant {variant!r} not in {VARIANTS}")
    iv = guaranteed_levels(Rotor(E_C=E_C, cosines=((1, -E_J),), n_g=n_g), k, width, deadline=deadline)
    b, a = iv.low, iv.high
    if variant == "spectrum":
        omega = (b[1] - a[0], a[1] - b[0])
        f12 = (b[2] - a[1], a[2] - b[1])
        alpha = (f12[0] - omega[1], f12[1] - omega[0])
    else:
        fl = _flint()
        r = _sqrt_interval(fl, 8 * Fraction(E_J) * Fraction(E_C))
        omega = (r[0] - Fraction(E_C), r[1] - Fraction(E_C))
        alpha = (Fraction(-E_C), Fraction(-E_C))
    delta = []
    for j in range(k):
        tr = (b[j] - a[0], a[j] - b[0])                                     # E_j − E_0
        d_lo = duffing_levels(omega[0] if j >= 0 else omega[1], alpha[0] if j >= 2 else alpha[1], j)
        d_hi = duffing_levels(omega[1], alpha[1] if j >= 2 else alpha[0], j)
        # E^D_j is increasing in ω (j ≥ 0) and in α (j ≥ 2: j(j−1) ≥ 0): the extremes are at the ends
        delta.append((tr[0] - d_hi, tr[1] - d_lo))
    return DuffingError(variant, omega, alpha, tuple(delta), iv, E_C)


# deprecated Italian names of 0.2.0 (DeprecationWarning on use; removed in a later release)
add_field_aliases(DuffingError, {"variante": "variant", "intervalli": "intervals"})
DuffingError.delta_su_EC = deprecated_function(DuffingError.delta_over_EC, "delta_su_EC")
