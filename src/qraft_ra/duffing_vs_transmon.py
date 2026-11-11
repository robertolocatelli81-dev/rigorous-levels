# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra/duffing_vs_transmon.py — errore GARANTITO, per livello, del modello di Duffing rispetto al transmon completo.

Specifica (scritta prima): gtm/qraft_duffing_20261111/SPECIFICA_DUFFING_v0.1.md. Gli stack di dinamica (qutip-qip
circuitqed.py:84-120, dynamiqs benchmarks/systems.py:58-82) usano H_D = ω a†a + (α/2) a†a†aa; i suoi livelli sono
esatti e diagonali in Fock: E^D_j = ω j + (α/2) j (j − 1). Il transmon completo H = 4E_C(n − n_g)² − E_J cos φ ha
livelli E_j racchiusi dagli intervalli di qraft_ra/intervallo_garantito.py. Qui:
  variante "spettro": ω = E_1 − E_0 e α = (E_2 − E_1) − (E_1 − E_0) presi dagli INTERVALLI garantiti (per costruzione
                      δ_0 = δ_1 = δ_2 = 0): δ_j = (E_j − E_0) − E^D_j per j ≥ 3 come intervallo esatto in Fraction;
  variante "koch":    ω = √(8 E_J E_C) − E_C e α = −E_C (Koch et al. 2007, eq. 2.11-2.12, 1° ordine): δ_j per j ≥ 1,
                      con √(8E_JE_C) racchiusa in una palla Arb (python-flint) convertita in intervallo razionale.
Ingressi chiusi (FuoriDominio col motivo). QRAFT-RA è un modello interno, non un validatore esterno."""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional, Tuple

from qraft_ra.intervallo_garantito import FuoriDominio, Intervalli, livelli_garantiti, _flint
from qraft_ra.rotore_spettro import Rotore

__all__ = ["ErroreDuffing", "errore_duffing", "livelli_duffing", "FuoriDominio"]

VARIANTI = ("spettro", "koch")
K_MAX = 20


@dataclass(frozen=True)
class ErroreDuffing:
    variante: str
    omega: Tuple[Fraction, Fraction]          # intervallo di ω (GHz)
    alpha: Tuple[Fraction, Fraction]          # intervallo di α (GHz)
    delta: Tuple[Tuple[Fraction, Fraction], ...]   # per j < k: intervallo di (E_j − E_0) − E^D_j
    intervalli: Intervalli                    # i livelli del transmon usati
    E_C: float

    def delta_float(self):
        return tuple((float(a), float(b)) for a, b in self.delta)

    def delta_su_EC(self):
        return tuple((float(a) / self.E_C, float(b) / self.E_C) for a, b in self.delta)


def _reale(x, nome, positivo=False):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise FuoriDominio(f"{nome}: atteso un numero reale finito")
    try:
        x = float(x)
    except OverflowError:
        raise FuoriDominio(f"{nome}: atteso un numero reale finito") from None
    if not math.isfinite(x) or (positivo and x <= 0):
        raise FuoriDominio(f"{nome}: atteso un reale finito{' > 0' if positivo else ''}")
    return x


def livelli_duffing(omega: Fraction, alpha: Fraction, j: int) -> Fraction:
    """E^D_j = ω j + (α/2) j (j − 1), esatto."""
    return omega * j + alpha * j * (j - 1) / 2


def _sqrt_intervallo(fl, x: Fraction, prec: int = 128) -> Tuple[Fraction, Fraction]:
    """[basso, alto] razionali che racchiudono √x (palla Arb → estremi in Fraction)."""
    vecchia = fl.ctx.prec
    fl.ctx.prec = prec
    try:
        s = fl.arb(fl.fmpq(x.numerator, x.denominator)).sqrt()
        lo = Fraction(str(s.lower().str(40, radius=False)))
        hi = Fraction(str(s.upper().str(40, radius=False)))
    finally:
        fl.ctx.prec = vecchia
    # le stringhe a 40 cifre sono ARROTONDATE, non dirette verso l'esterno: si allargano finché l'inclusione è
    # verificata in aritmetica ESATTA (Fraction); l'inclusione finale è dimostrata dal controllo, non dalla stringa
    return _allarga(lo, hi, x)


def _allarga(lo: Fraction, hi: Fraction, x: Fraction) -> Tuple[Fraction, Fraction]:
    """Restituisce [lo', hi'] razionali con lo' ≤ √x ≤ hi' (x ≥ 0), partendo da un'ipotesi [lo, hi] (le stringhe
    arrotondate di Arb). Validità in aritmetica ESATTA: hi' ≥ 0 e hi'² ≥ x; lo' ≤ 0 oppure lo'² ≤ x.
    hi: se negativo riparte da max(x, 1) (max(x,1)² ≥ x), poi cresce con passo che raddoppia (sempre finito: hi > 0
    crescente). lo: se l'ipotesi non vale si ripiega su x / hi' ((x/hi')² = x²/hi'² ≤ x): nessun ciclo che possa
    scavalcare √x (NEMESIS 11/11: con lo ≥ ~10√x o lo negativo il ciclo per decrementi non terminava)."""
    if x < 0:
        raise ArithmeticError("radice di un numero negativo")
    if hi < 0:
        hi = max(x, Fraction(1))
    passo = max(abs(hi), Fraction(1)) * Fraction(1, 10 ** 35)
    while hi * hi < x:
        hi += passo
        passo *= 2
    if lo > 0 and lo * lo > x:
        lo = x / hi if hi > 0 else Fraction(0)
    if not (lo <= hi) or hi < 0 or hi * hi < x or (lo > 0 and lo * lo > x):
        raise ArithmeticError("intervallo della radice non verificato")
    return lo, hi


def errore_duffing(E_C: float, E_J: float, n_g: float = 0.0, k: int = 6, variante: str = "spettro", *,
                   larghezza: float = 1e-12, scadenza: Optional[float] = None) -> ErroreDuffing:
    """Errore garantito per livello del Duffing rispetto al transmon (unità di E_C, E_J; GHz per convenzione)."""
    E_C = _reale(E_C, "E_C", positivo=True)
    E_J = _reale(E_J, "E_J", positivo=True)
    n_g = _reale(n_g, "n_g")
    if isinstance(k, bool) or not isinstance(k, int) or k < 3 or k > K_MAX:
        raise FuoriDominio(f"k: atteso un intero in [3, {K_MAX}] (δ ha senso da j = 3; ω e α usano i primi tre livelli)")
    if variante not in VARIANTI:
        raise FuoriDominio(f"variante {variante!r} non in {VARIANTI}")
    iv = livelli_garantiti(Rotore(E_C=E_C, coseni=((1, -E_J),), n_g=n_g), k, larghezza, scadenza=scadenza)
    b, a = iv.bassi, iv.alti
    if variante == "spettro":
        omega = (b[1] - a[0], a[1] - b[0])
        f12 = (b[2] - a[1], a[2] - b[1])
        alpha = (f12[0] - omega[1], f12[1] - omega[0])
    else:
        fl = _flint()
        r = _sqrt_intervallo(fl, 8 * Fraction(E_J) * Fraction(E_C))
        omega = (r[0] - Fraction(E_C), r[1] - Fraction(E_C))
        alpha = (Fraction(-E_C), Fraction(-E_C))
    delta = []
    for j in range(k):
        tr = (b[j] - a[0], a[j] - b[0])                                     # E_j − E_0
        d_lo = livelli_duffing(omega[0] if j >= 0 else omega[1], alpha[0] if j >= 2 else alpha[1], j)
        d_hi = livelli_duffing(omega[1], alpha[1] if j >= 2 else alpha[0], j)
        # E^D_j è crescente in ω (j ≥ 0) e in α (j ≥ 2: j(j−1) ≥ 0): estremi ai bordi
        delta.append((tr[0] - d_hi, tr[1] - d_lo))
    return ErroreDuffing(variante, omega, alpha, tuple(delta), iv, E_C)
