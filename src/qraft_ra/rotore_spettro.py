# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra.rotore_spettro — spectrum of the rotor on S¹ with a declared error.

    H = 4 E_C (n − n_g)² + Σ_m [ c_m cos(mφ) + s_m sin(mφ) ]

The sign lives in the coefficient, never in the constructor: `Rotore.transmon` puts −E_J on cos φ, `Rotore.kite`
puts +E_J2 on cos 2φ as written in Eq. 1 of arXiv:2603.13114.

What it adds to `eigh` on a fixed basis:
  - the basis grows until the low spectrum stops moving, otherwise the state is NON_CONVERGENTE;
  - a check with a second method (collocation on a phase grid);
  - a float64 floor (`pavimento`) reported with every spectrum;
  - closed inputs: unknown key, NaN, inf, non-integer harmonic = refusal with a reason.

Standard quantum mechanics (Koch et al. 2007 and later). State OK means "the number is the one of this H", not
"this H describes the chip". QRAFT-RA is an internal model, not an external validator.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

import numpy as np
from scipy.linalg import eig_banded, eigh

OK = "OK"
NON_CONVERGENTE = "NON_CONVERGENTE"

NMAX_LIMITE = 2000  # largest basis: dim = 2·NMAX_LIMITE + 1
EPS = float(np.finfo(float).eps)


class IngressoRifiutato(ValueError):
    """Input outside the grammar of the rotor."""


def _reale_finito(x, nome: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float, np.integer, np.floating)):
        raise IngressoRifiutato(f"{nome}: atteso un numero, trovato {type(x).__name__}")
    v = float(x)
    if not math.isfinite(v):
        raise IngressoRifiutato(f"{nome}: non finito")
    return v


def _armoniche(arm: Mapping, nome: str) -> Tuple[Tuple[int, float], ...]:
    out = []
    for m, c in arm.items():
        if isinstance(m, bool) or not isinstance(m, (int, np.integer)) or m < 1:
            raise IngressoRifiutato(f"{nome}: armonica {m!r} non è un intero >= 1")
        out.append((int(m), _reale_finito(c, f"{nome}[{m}]")))
    return tuple(sorted(out))


@dataclass(frozen=True)
class Rotore:
    """H = 4 E_C (n − n_g)² + Σ_m c_m cos(mφ) + Σ_m s_m sin(mφ). Energies in any unit (GHz here)."""

    E_C: float
    coseni: Tuple[Tuple[int, float], ...] = ()
    seni: Tuple[Tuple[int, float], ...] = ()
    n_g: float = 0.0

    def __post_init__(self):
        ec = _reale_finito(self.E_C, "E_C")
        if ec <= 0:
            raise IngressoRifiutato("E_C deve essere positiva")
        object.__setattr__(self, "E_C", ec)
        object.__setattr__(self, "n_g", _reale_finito(self.n_g, "n_g"))
        for nome in ("coseni", "seni"):
            valore = getattr(self, nome)
            try:
                mappa = valore if isinstance(valore, Mapping) else dict(valore)
            except (TypeError, ValueError):
                raise IngressoRifiutato(f"{nome}: atteso un dizionario m -> coefficiente") from None
            object.__setattr__(self, nome, _armoniche(mappa, nome))

    @classmethod
    def transmon(cls, E_C: float, E_J: float, n_g: float = 0.0) -> "Rotore":
        """U = −E_J cos φ."""
        return cls(E_C, {1: -_reale_finito(E_J, "E_J")}, n_g=n_g)

    @classmethod
    def kite(cls, E_C: float, E_J2: float, E_J1: float = 0.0, E_Jphi: float = 0.0,
             phi_ext: float = math.pi, n_g: float = 0.0) -> "Rotore":
        """Eq. 1–2 of arXiv:2603.13114: U = +E_J2 cos 2φ − E_J1 cos φ − E_Jφ sin φ (φ_ext − π)."""
        s = -_reale_finito(E_Jphi, "E_Jphi") * (_reale_finito(phi_ext, "phi_ext") - math.pi)
        return cls(E_C, {2: _reale_finito(E_J2, "E_J2"), 1: -_reale_finito(E_J1, "E_J1")},
                   {1: s}, n_g=n_g)

    @property
    def energia_potenziale(self) -> float:
        return sum(abs(c) for _, c in self.coseni) + sum(abs(s) for _, s in self.seni)

    def con_n_g(self, n_g: float) -> "Rotore":
        return Rotore(self.E_C, dict(self.coseni), dict(self.seni), n_g)

    def matrice(self, nmax: int) -> Tuple[np.ndarray, np.ndarray]:
        """Hamiltonian in the charge basis n = −nmax…nmax. Real if there are no sines."""
        ns = np.arange(-nmax, nmax + 1)
        dim = len(ns)
        H = np.zeros((dim, dim), dtype=complex if self.seni else float)
        H[np.arange(dim), np.arange(dim)] = 4.0 * self.E_C * (ns - self.n_g) ** 2
        for m, c in self.coseni:
            if m < dim:
                i = np.arange(dim - m)
                H[i + m, i] += c / 2.0
                H[i, i + m] += c / 2.0
        for m, s in self.seni:
            if m < dim:
                i = np.arange(dim - m)  # e^{imφ}|n⟩ = |n+m⟩, sin = (e^{imφ} − e^{−imφ}) / 2i
                H[i + m, i] += -0.5j * s
                H[i, i + m] += 0.5j * s
        return H, ns

    def potenziale(self, phi: np.ndarray) -> np.ndarray:
        U = np.zeros_like(phi)
        for m, c in self.coseni:
            U = U + c * np.cos(m * phi)
        for m, s in self.seni:
            U = U + s * np.sin(m * phi)
        return U


@dataclass(frozen=True)
class Spettro:
    """First k eigenvalues, with how far they can be trusted."""

    energie: Tuple[float, ...]
    errore: float            # estimate: max of the change on doubling the basis and the gap to the second method
    pavimento: float         # below this difference float64 cannot tell values apart
    nmax: int
    stato: str
    autovettori: Optional[np.ndarray] = None
    ns: Optional[np.ndarray] = None


def _nmax_iniziale(r: Rotore, k: int) -> int:
    # the low wave function is about (U/E_C)^(1/4) wide in charge; k levels add ~√k
    larghezza = (max(r.energia_potenziale, r.E_C) / r.E_C) ** 0.25
    return int(math.ceil(abs(r.n_g))) + max(12, int(6 * larghezza * math.sqrt(k + 1)))


def _autovalori(r: Rotore, nmax: int, k: int):
    H, ns = r.matrice(nmax)
    b = min(max((m for m, _ in r.coseni + r.seni), default=0), len(ns) - 1)
    bande = np.zeros((b + 1, len(ns)), dtype=H.dtype)  # H is banded: the cost grows with n, not n³
    for d in range(b + 1):
        bande[b - d, d:] = np.diagonal(H, d)
    E, V = eig_banded(bande, lower=False, select="i", select_range=(0, k - 1))
    return E, V, ns, float(np.abs(H).sum(axis=1).max())


def _collocazione(r: Rotore, nmax: int, k: int) -> np.ndarray:
    """Second method: H on a phase grid; n_g enters as a gauge phase on the spectral derivative."""
    G = 2 * nmax + 1
    phi = 2.0 * np.pi * np.arange(G) / G
    ns = np.fft.fftfreq(G, 1.0 / G)
    F = np.exp(-1j * np.outer(ns, phi)) / math.sqrt(G)
    T = (F.conj().T * (4.0 * r.E_C * (ns - r.n_g) ** 2)) @ F
    H = T + np.diag(r.potenziale(phi))
    return eigh(0.5 * (H + H.conj().T), eigvals_only=True, subset_by_index=[0, k - 1])


def spettro(r: Rotore, k: int = 6, tol: float = 1e-9, *, doppio_metodo: bool = True,
            nmax_limite: int = NMAX_LIMITE) -> Spettro:
    """First k levels with absolute error ≤ tol (same unit as E_C), or state NON_CONVERGENTE.

    The basis doubles until two consecutive bases agree within tol. A fixed basis, such as nmax=60
    or ncut=30, cannot notice that it is too small: this function does.
    """
    if isinstance(k, bool) or not isinstance(k, (int, np.integer)) or k < 1:
        raise IngressoRifiutato("k deve essere un intero >= 1")
    t = _reale_finito(tol, "tol")
    if t <= 0:
        raise IngressoRifiutato("tol deve essere positiva")
    nmax = min(_nmax_iniziale(r, int(k)), nmax_limite)
    E, V, ns, norma = _autovalori(r, nmax, k)
    while True:
        n2 = 2 * nmax
        if n2 > nmax_limite:
            pav = 8.0 * EPS * norma * math.sqrt(k)
            return Spettro(tuple(float(e) for e in E), math.inf, pav, nmax, NON_CONVERGENTE)
        E2, V2, ns2, norma = _autovalori(r, n2, k)
        variazione = float(np.max(np.abs(E2 - E)))
        nmax, E, V, ns = n2, E2, V2, ns2
        if variazione <= t:
            break
    pav = 8.0 * EPS * norma * math.sqrt(k)
    errore = max(variazione, pav)
    stato = OK
    if doppio_metodo:
        scarto = float(np.max(np.abs(_collocazione(r, nmax // 2, k) - E)))
        errore = max(errore, scarto)
        if scarto > max(t, pav):
            stato = NON_CONVERGENTE
    return Spettro(tuple(float(e) for e in E), errore, pav, nmax, stato, V, ns)

