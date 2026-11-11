# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra.rotor_spectrum — spectrum of the rotor on S¹ with a declared error.

    H = 4 E_C (n − n_g)² + Σ_m [ c_m cos(mφ) + s_m sin(mφ) ]

The sign lives in the coefficient, never in the constructor: `Rotor.transmon` puts −E_J on cos φ, `Rotor.kite`
puts +E_J2 on cos 2φ as written in Eq. 1 of arXiv:2603.13114.

What it adds to `eigh` on a fixed basis:
  - the basis grows until the low spectrum stops moving, otherwise the state is NOT_CONVERGED;
  - a check with a second method (collocation on a phase grid);
  - a float64 floor (`floor`) reported with every spectrum;
  - closed inputs: unknown key, NaN, inf, non-integer harmonic = refusal with a reason.

Standard quantum mechanics (Koch et al. 2007 and later). State OK means "the number is the one of this H", not
"this H describes the chip". QRAFT-RA is an internal model, not an external validator.
Names: this module was `rotore_spettro` in 0.2.0 (deprecated aliases in that module).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

import numpy as np
from scipy.linalg import eig_banded, eigh

from qraft_ra._compat import add_field_aliases, deprecated_function

OK = "OK"
NOT_CONVERGED = "NOT_CONVERGED"          # 0.2.0: NON_CONVERGENTE

NMAX_LIMIT = 2000  # largest basis: dim = 2·NMAX_LIMIT + 1
EPS = float(np.finfo(float).eps)


class InputRejected(ValueError):
    """Input outside the grammar of the rotor."""


def _finite_real(x, name: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float, np.integer, np.floating)):
        raise InputRejected(f"{name}: expected a number, got {type(x).__name__}")
    try:
        v = float(x)
    except OverflowError:                       # int beyond float64 (10**400): refused, not a crash
        raise InputRejected(f"{name}: not finite (integer beyond float64)") from None
    if not math.isfinite(v):
        raise InputRejected(f"{name}: not finite")
    return v


def _harmonics(arm: Mapping, name: str) -> Tuple[Tuple[int, float], ...]:
    out = []
    for m, c in arm.items():
        if isinstance(m, bool) or not isinstance(m, (int, np.integer)) or m < 1:
            raise InputRejected(f"{name}: harmonic {m!r} is not an integer >= 1")
        out.append((int(m), _finite_real(c, f"{name}[{m}]")))
    return tuple(sorted(out))


@dataclass(frozen=True)
class Rotor:
    """H = 4 E_C (n − n_g)² + Σ_m c_m cos(mφ) + Σ_m s_m sin(mφ). Energies in any unit (GHz here)."""

    E_C: float
    cosines: Tuple[Tuple[int, float], ...] = ()
    sines: Tuple[Tuple[int, float], ...] = ()
    n_g: float = 0.0

    def __post_init__(self):
        ec = _finite_real(self.E_C, "E_C")
        if ec <= 0:
            raise InputRejected("E_C must be positive")
        object.__setattr__(self, "E_C", ec)
        object.__setattr__(self, "n_g", _finite_real(self.n_g, "n_g"))
        for name in ("cosines", "sines"):
            value = getattr(self, name)
            try:
                mapping = value if isinstance(value, Mapping) else dict(value)
            except (TypeError, ValueError):
                raise InputRejected(f"{name}: expected a mapping m -> coefficient") from None
            object.__setattr__(self, name, _harmonics(mapping, name))

    @classmethod
    def transmon(cls, E_C: float, E_J: float, n_g: float = 0.0) -> "Rotor":
        """U = −E_J cos φ."""
        return cls(E_C, {1: -_finite_real(E_J, "E_J")}, n_g=n_g)

    @classmethod
    def kite(cls, E_C: float, E_J2: float, E_J1: float = 0.0, E_Jphi: float = 0.0,
             phi_ext: float = math.pi, n_g: float = 0.0) -> "Rotor":
        """Eq. 1–2 of arXiv:2603.13114: U = +E_J2 cos 2φ − E_J1 cos φ − E_Jφ sin φ (φ_ext − π)."""
        s = -_finite_real(E_Jphi, "E_Jphi") * (_finite_real(phi_ext, "phi_ext") - math.pi)
        return cls(E_C, {2: _finite_real(E_J2, "E_J2"), 1: -_finite_real(E_J1, "E_J1")},
                   {1: s}, n_g=n_g)

    @property
    def potential_energy(self) -> float:
        return sum(abs(c) for _, c in self.cosines) + sum(abs(s) for _, s in self.sines)

    def with_n_g(self, n_g: float) -> "Rotor":
        return Rotor(self.E_C, dict(self.cosines), dict(self.sines), n_g)

    def matrix(self, nmax: int) -> Tuple[np.ndarray, np.ndarray]:
        """Hamiltonian in the charge basis n = −nmax…nmax. Real if there are no sines."""
        ns = np.arange(-nmax, nmax + 1)
        dim = len(ns)
        H = np.zeros((dim, dim), dtype=complex if self.sines else float)
        H[np.arange(dim), np.arange(dim)] = 4.0 * self.E_C * (ns - self.n_g) ** 2
        for m, c in self.cosines:
            if m < dim:
                i = np.arange(dim - m)
                H[i + m, i] += c / 2.0
                H[i, i + m] += c / 2.0
        for m, s in self.sines:
            if m < dim:
                i = np.arange(dim - m)  # e^{imφ}|n⟩ = |n+m⟩, sin = (e^{imφ} − e^{−imφ}) / 2i
                H[i + m, i] += -0.5j * s
                H[i, i + m] += 0.5j * s
        return H, ns

    def potential(self, phi: np.ndarray) -> np.ndarray:
        U = np.zeros_like(phi)
        for m, c in self.cosines:
            U = U + c * np.cos(m * phi)
        for m, s in self.sines:
            U = U + s * np.sin(m * phi)
        return U


@dataclass(frozen=True)
class Spectrum:
    """First k eigenvalues, with how far they can be trusted."""

    energies: Tuple[float, ...]
    error: float            # estimate: max of the change on doubling the basis and the gap to the second method
    floor: float         # below this difference float64 cannot tell values apart
    nmax: int
    state: str
    eigenvectors: Optional[np.ndarray] = None
    ns: Optional[np.ndarray] = None


def _initial_nmax(r: Rotor, k: int) -> int:
    # the low wave function is about (U/E_C)^(1/4) wide in charge; k levels add ~√k
    width = (max(r.potential_energy, r.E_C) / r.E_C) ** 0.25
    return int(math.ceil(abs(r.n_g))) + max(12, int(6 * width * math.sqrt(k + 1)))


def _eigenvalues(r: Rotor, nmax: int, k: int):
    H, ns = r.matrix(nmax)
    b = min(max((m for m, _ in r.cosines + r.sines), default=0), len(ns) - 1)
    bande = np.zeros((b + 1, len(ns)), dtype=H.dtype)  # H is banded: the cost grows with n, not n³
    for d in range(b + 1):
        bande[b - d, d:] = np.diagonal(H, d)
    E, V = eig_banded(bande, lower=False, select="i", select_range=(0, k - 1))
    return E, V, ns, float(np.abs(H).sum(axis=1).max())


def _collocation(r: Rotor, nmax: int, k: int) -> np.ndarray:
    """Second method: H on a phase grid; n_g enters as a gauge phase on the spectral derivative."""
    G = 2 * nmax + 1
    phi = 2.0 * np.pi * np.arange(G) / G
    ns = np.fft.fftfreq(G, 1.0 / G)
    F = np.exp(-1j * np.outer(ns, phi)) / math.sqrt(G)
    T = (F.conj().T * (4.0 * r.E_C * (ns - r.n_g) ** 2)) @ F
    H = T + np.diag(r.potential(phi))
    return eigh(0.5 * (H + H.conj().T), eigvals_only=True, subset_by_index=[0, k - 1])


def spectrum(r: Rotor, k: int = 6, tol: float = 1e-9, *, two_methods: bool = True,
            nmax_limit: int = NMAX_LIMIT) -> Spectrum:
    """First k levels with absolute error ≤ tol (same unit as E_C), or state NOT_CONVERGED.

    The basis doubles until two consecutive bases agree within tol. A fixed basis, such as nmax=60
    or ncut=30, cannot notice that it is too small: this function does.
    """
    if isinstance(k, bool) or not isinstance(k, (int, np.integer)) or k < 1:
        raise InputRejected("k must be an integer >= 1")
    t = _finite_real(tol, "tol")
    if t <= 0:
        raise InputRejected("tol must be positive")
    if isinstance(nmax_limit, bool) or not isinstance(nmax_limit, (int, np.integer)) or not 1 <= nmax_limit <= NMAX_LIMIT:
        raise InputRejected(f"nmax_limit must be an integer in [1, {NMAX_LIMIT}]")
    if not isinstance(r, Rotor):
        raise InputRejected(f"expected a Rotor, got {type(r).__name__}")
    nmax = min(_initial_nmax(r, int(k)), int(nmax_limit))
    E, V, ns, norma = _eigenvalues(r, nmax, k)
    while True:
        n2 = 2 * nmax
        if n2 > nmax_limit:
            pav = 8.0 * EPS * norma * math.sqrt(k)
            return Spectrum(tuple(float(e) for e in E), math.inf, pav, nmax, NOT_CONVERGED)
        E2, V2, ns2, norma = _eigenvalues(r, n2, k)
        variazione = float(np.max(np.abs(E2 - E)))
        nmax, E, V, ns = n2, E2, V2, ns2
        if variazione <= t:
            break
    pav = 8.0 * EPS * norma * math.sqrt(k)
    error = max(variazione, pav)
    state = OK
    if two_methods:
        scarto = float(np.max(np.abs(_collocation(r, nmax // 2, k) - E)))
        error = max(error, scarto)
        if scarto > max(t, pav):
            state = NOT_CONVERGED
    return Spectrum(tuple(float(e) for e in E), error, pav, nmax, state, V, ns)


# deprecated Italian names of 0.2.0 (DeprecationWarning on use; removed in a later release)
add_field_aliases(Rotor, {"coseni": "cosines", "seni": "sines", "energia_potenziale": "potential_energy"})
Rotor.con_n_g = deprecated_function(Rotor.with_n_g, "con_n_g")
Rotor.matrice = deprecated_function(Rotor.matrix, "matrice")
Rotor.potenziale = deprecated_function(Rotor.potential, "potenziale")
add_field_aliases(Spectrum, {"energie": "energies", "errore": "error", "pavimento": "floor", "stato": "state",
                             "autovettori": "eigenvectors"})
