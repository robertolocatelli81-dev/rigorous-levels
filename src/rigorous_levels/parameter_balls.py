# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""rigorous_levels/parameter_balls.py — levels of the charge-basis rotor when the PARAMETERS are intervals (boxes).

    H(E_C, c) = 4 E_C (n − n_g)² + Σ_m c_m cos(mφ),   E_C ∈ [E_C⁻, E_C⁺],  c_m ∈ [c_m⁻, c_m⁺],  n_g exact

A laboratory knows E_J and E_C with an uncertainty (fit, fabrication spread); the question is "where can level j be
for ANY parameter in the box". Two facts of the operator give it with two guaranteed computations (docs/PROOF.md):

  (i)  E_C ↦ λ_j is non-decreasing: H(E_C⁺) − H(E_C⁻) = 4(E_C⁺ − E_C⁻)(n − n_g)² ≥ 0 as a form, so
       λ_j(E_C⁻, c) ≤ λ_j(E_C, c) ≤ λ_j(E_C⁺, c)                     (Teschl, Corollary 4.11);
  (ii) c ↦ λ_j is Lipschitz with constant Σ_m |Δc_m|: H(E_C, c) − H(E_C, c′) = Σ (c_m − c′_m) cos(mφ) is bounded
       with norm ≤ Σ |c_m − c′_m| (‖cos mφ‖ = 1), so |λ_j(E_C, c) − λ_j(E_C, c′)| ≤ Σ |c_m − c′_m|
       (Weyl's inequality for a bounded perturbation; Teschl, Theorem 4.10 with the min-max principle).

Hence, with c⁰ the midpoint of the box of c and ρ = Σ_m (c_m⁺ − c_m⁻)/2:
       low_j(E_C⁻, c⁰) − ρ ≤ λ_j(E_C, c) ≤ high_j(E_C⁺, c⁰) + ρ      for every (E_C, c) in the box.
  (iii) n_g ↦ λ_j: H(n_g) is the Floquet (Bloch) operator of Hill's equation −y″ + V y with quasi-momentum θ = 2π n_g
       on the unit cell (φ ↦ e^{i n_g φ} conjugation), so λ_j(n_g) is 1-periodic, even, and on [0, ½] each band
       function is monotone (Reed–Simon IV, Theorem XIII.89; Eastham 1973, Theorem 2.3.1; for the Mathieu case
       DLMF 28.12(i): a_ν(q) is monotone in ν on each band). Hence on an interval [a, b] of n_g the extremes of λ_j
       are attained at a, b and at the band edges 0 and ½ (mod 1) that fall inside [a, b].

Hence, with c⁰ the midpoint of the box of c, ρ = Σ_m (c_m⁺ − c_m⁻)/2 and G the set of candidate n_g (the ends plus the
band edges inside), for every (E_C, c, n_g) in the box:
       min_{g∈G} low_j(E_C⁻, c⁰, g) − ρ ≤ λ_j(E_C, c, n_g) ≤ max_{g∈G} high_j(E_C⁺, c⁰, g) + ρ.
The result is rigorous and may be much wider than the true spread of the levels (the Lipschitz constant 1 in each
c_m is attained only by a level that follows −E_J cos φ rigidly): the width reported is the width of the box
interval, and `RotorBall` reports ρ separately. An n_g interval longer than 1 is the whole band (G = {0, ½}).
This package is not an external validator."""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, Mapping, Optional, Tuple

from rigorous_levels.guaranteed_intervals import GUARANTEED, WIDE, Intervals, OutOfDomain, guaranteed_levels
from rigorous_levels.rotor_spectrum import InputRejected, Rotor

__all__ = ["RotorBall", "guaranteed_levels_over_box", "OutOfDomain"]


def _interval(x, name: str, positive: bool = False) -> Tuple[float, float]:
    """[lo, hi] from a number (exact) or a pair; finite, lo ≤ hi, both > 0 if `positive`."""
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        pair = (x, x)
    elif isinstance(x, (tuple, list)) and len(x) == 2:
        pair = tuple(x)
    else:
        raise OutOfDomain(f"{name}: expected a number or a pair (low, high)")
    out = []
    for v in pair:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise OutOfDomain(f"{name}: expected finite real numbers")
        try:
            v = float(v)
        except OverflowError:
            raise OutOfDomain(f"{name}: expected finite real numbers (integer beyond float64)") from None
        if not math.isfinite(v):
            raise OutOfDomain(f"{name}: expected finite real numbers")
        out.append(v)
    lo, hi = out
    if lo > hi:
        raise OutOfDomain(f"{name}: low > high")
    if positive and lo <= 0:
        raise OutOfDomain(f"{name}: must be > 0")
    return lo, hi


@dataclass(frozen=True)
class RotorBall:
    """E_C, every cosine coefficient and n_g as [low, high] (a number means exact)."""

    E_C: Tuple[float, float]
    cosines: Dict[int, Tuple[float, float]]
    n_g: Tuple[float, float] = (0.0, 0.0)

    def __post_init__(self):
        s = object.__setattr__
        s(self, "E_C", _interval(self.E_C, "E_C", positive=True))
        if not isinstance(self.cosines, Mapping) or not self.cosines:
            raise OutOfDomain("cosines: expected a non-empty mapping m -> (low, high)")
        cs = {}
        for m, c in self.cosines.items():
            if isinstance(m, bool) or not isinstance(m, int) or m < 1:
                raise OutOfDomain(f"cosines: harmonic {m!r} is not an integer >= 1")
            cs[m] = _interval(c, f"cosines[{m}]")
        s(self, "cosines", cs)
        s(self, "n_g", _interval(self.n_g, "n_g"))

    @classmethod
    def transmon(cls, E_C, E_J, n_g: float = 0.0) -> "RotorBall":
        """U = −E_J cos φ with E_C and E_J as numbers or (low, high) pairs."""
        lo, hi = _interval(E_J, "E_J", positive=True)
        return cls(E_C, {1: (-hi, -lo)}, n_g)

    @staticmethod
    def _mid(lo: float, hi: float) -> float:
        """The float midpoint used for the computations (lo/2 + hi/2: no overflow); it need not be the exact midpoint."""
        return lo / 2 + hi / 2

    @property
    def rho(self) -> Fraction:
        """ρ = Σ_m max(c⁰_m − c_m⁻, c_m⁺ − c⁰_m) with c⁰_m the FLOAT midpoint actually used (exact Fractions): the
        Lipschitz radius that covers the whole box even when the float midpoint is rounded (= Σ (c⁺ − c⁻)/2 when the
        midpoint is exact)."""
        out = Fraction(0)
        for lo, hi in self.cosines.values():
            c0 = Fraction(self._mid(lo, hi))
            out += max(c0 - Fraction(lo), Fraction(hi) - c0)
        return out

    def n_g_candidates(self) -> Tuple[float, ...]:
        """Where λ_j can be extremal, as exact floats in [0, 1): λ_j(n_g) is 1-periodic (n ↦ n + 1) and even (cosines
        only), so the n_g interval is mapped exactly into [0, 2) (or folded onto [0, M] when it contains 0) and the
        candidates are its ends and the band edges 0 and ½ inside it, reduced mod 1. Exact arithmetic, no float loop:
        an n_g beyond 2^53 made the old loop endless."""
        a, b = (Fraction(x) for x in self.n_g)
        if b - a >= 1:
            return (0.0, 0.5)
        if b <= 0:                                   # evenness: [a, b] ↦ [−b, −a], exact
            a, b = -b, -a
        if a < 0:                                    # contains 0: [a, b] folds onto [0, max(−a, b)], M < 1
            ends = (Fraction(0), max(-a, b))
        else:                                        # a ≥ 0: shift by floor(a), exact for floats (result < b)
            k = math.floor(a)
            ends = (a - k, b - k)                    # 0 ≤ a − k < 1, b − k < 2
        cands = {e - math.floor(e) for e in ends}
        for edge in (Fraction(0), Fraction(1, 2), Fraction(1), Fraction(3, 2)):
            if ends[0] <= edge <= ends[1]:
                cands.add(edge - math.floor(edge))
        out = tuple(sorted(float(x) for x in cands))
        if any(Fraction(x) != c for x, c in zip(out, sorted(cands))):      # never expected: refuse, do not round
            raise OutOfDomain("n_g: a candidate is not an exact float")
        return out

    def midpoint_rotor(self, E_C: float, n_g: float) -> Rotor:
        return Rotor(E_C, {m: self._mid(lo, hi) for m, (lo, hi) in self.cosines.items()}, n_g=n_g)


def guaranteed_levels_over_box(ball: RotorBall, k: int = 6, width: float = 1e-12, *,
                               deadline: Optional[float] = None) -> Intervals:
    """[low_j, high_j] containing λ_j(E_C, c, n_g) for EVERY point of the box: guaranteed computations at E_C⁻ and
    E_C⁺ (cosines at the midpoint) for each candidate n_g, widened by ρ. `width` is the target of each point
    computation; the state is GUARANTEED when every point computation is, WIDE otherwise; `alpha` carries ρ, `N` the
    largest cut, `seconds` the total."""
    if not isinstance(ball, RotorBall):
        raise OutOfDomain(f"expected a RotorBall, got {type(ball).__name__}")
    rho = ball.rho
    lows, highs, states, Ns, precs, secs = [], [], [], [], [], 0.0
    try:
        for g in ball.n_g_candidates():
            lo_c = guaranteed_levels(ball.midpoint_rotor(ball.E_C[0], g), k, width, deadline=deadline)
            hi_c = lo_c if ball.E_C[0] == ball.E_C[1] else guaranteed_levels(ball.midpoint_rotor(ball.E_C[1], g), k, width,
                                                                            deadline=deadline)
            lows.append(lo_c.low)
            highs.append(hi_c.high)
            states += [lo_c.state, hi_c.state]
            Ns += [lo_c.N, hi_c.N]
            precs += [lo_c.prec, hi_c.prec]
            secs += lo_c.seconds + (0.0 if hi_c is lo_c else hi_c.seconds)
    except InputRejected as e:
        raise OutOfDomain(str(e)) from None
    low = tuple(min(ls[j] for ls in lows) - rho for j in range(k))
    high = tuple(max(hs[j] for hs in highs) + rho for j in range(k))
    strings = tuple((str(float(a)), str(float(b))) for a, b in zip(low, high))
    w = max(float(b - a) for a, b in zip(low, high))
    state = GUARANTEED if all(s == GUARANTEED for s in states) else WIDE
    return Intervals(low, high, strings, w, state, max(Ns), max(precs), float(rho), secs)
