# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra.scqubits_adattatore — scqubits as an optional engine, with the convergence warning scqubits does not give.

scqubits (BSD-3, https://scqubits.readthedocs.io) diagonalizes the transmon in a charge basis truncated at the `ncut`
chosen by the user; its documentation leaves the convergence check to the user. With ncut=30 it is wrong without
saying so on 65 of the 200 benchmark cases, all at E_J/E_C ≥ 7744 (README, "Measurements"). Here:

  - `disponibile()`: lazy import; if scqubits is missing it says so, and every computation raises `ScqubitsAssente`
    with the reason.
  - `spettro_scqubits(r, k, ncut, controllo=...)`:
      controllo="nessuno"   the scqubits number as it is (state NON_CONTROLLATO, error None);
      controllo="raddoppio" also computes at 2·ncut; estimated error = max_j |E_j(ncut) − E_j(2·ncut)|; state
                            NON_CONVERGENTE if it exceeds the threshold. The energies returned are those at ncut;
      controllo="auto"      doubles ncut until the shift is ≤ tol (or NCUT_LIMITE: NON_CONVERGENTE).
    The default threshold is relative: 1e-6 · max(1, largest transition); `tol` in GHz replaces it.
  - `confronta(r, k)`: cross-check against our solver (`rotore_spettro.spettro`), difference on the transitions
    E_j − E_0.

Why doubling gives no false alarms: the charge bases are nested, so (Cauchy, Rayleigh–Ritz)
E_j(ncut) ≥ E_j(2·ncut) ≥ true E_j. The shift on doubling is a LOWER bound of the true error: if it exceeds the
threshold, the true error exceeds it, provided the scale of the threshold (transitions at 2·ncut) is the true one,
that is, provided 2·ncut is enough. The opposite (large true error, small shift) is not excluded by the mathematics:
it is only measured on the benchmark. Within ±1e-4 relative of the threshold, misses and false alarms exist.

Domain: only the transmon U = −E_J cos φ with E_J > 0 (`scqubits.Transmon`). Any other `Rotore` = refusal.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np

from qraft_ra.rotore_spettro import (NON_CONVERGENTE, OK, IngressoRifiutato, Rotore, _reale_finito,
                                     spettro as _spettro_nostro)

NON_CONTROLLATO = "NON_CONTROLLATO"
CONTROLLI = ("nessuno", "raddoppio", "auto")
NCUT_LIMITE = 1920
SOGLIA_RELATIVA = 1e-6


class ScqubitsAssente(RuntimeError):
    """scqubits is not installed: no number, only the reason."""


def _importa():
    try:
        import scqubits as sq            # lazy import: optional dependency
    except ImportError as e:
        raise ScqubitsAssente(f"scqubits non installato ({e}); installare scqubits==4.3.1 oppure usare "
                              f"qraft_ra.rotore_spettro.spettro") from None
    sq.settings.PROGRESSBAR_DISABLED = True
    return sq


def disponibile() -> Dict:
    try:
        sq = _importa()
    except ScqubitsAssente as e:
        return {"presente": False, "versione": None, "motivo": str(e)}
    return {"presente": True, "versione": sq.__version__, "motivo": None}


@dataclass(frozen=True)
class SpettroScq:
    energie: Tuple[float, ...]
    errore: Optional[float]        # estimated error (lower bound of the true error); None if not checked
    soglia: Optional[float]
    ncut: int
    stato: str
    motore: str


def _transmon(r: Rotore) -> Tuple[float, float, float]:
    if not isinstance(r, Rotore):
        raise IngressoRifiutato(f"atteso un Rotore, trovato {type(r).__name__}")
    if r.seni or len(r.coseni) != 1 or r.coseni[0][0] != 1 or not r.coseni[0][1] < 0:
        raise IngressoRifiutato("fuori dal dominio dell'adattatore: solo U = −E_J cos φ con E_J > 0 "
                                "(scqubits.Transmon)")
    return r.E_C, -r.coseni[0][1], r.n_g


def _intero(x, nome: str, minimo: int) -> int:
    if isinstance(x, bool) or not isinstance(x, (int, np.integer)) or x < minimo:
        raise IngressoRifiutato(f"{nome} deve essere un intero >= {minimo}")
    return int(x)


def _autovalori(sq, ec: float, ej: float, ng: float, ncut: int, k: int) -> np.ndarray:
    t = sq.Transmon(EJ=ej, EC=ec, ng=ng, ncut=ncut, truncated_dim=k)
    return np.asarray(t.eigenvals(evals_count=k), dtype=float)


def _soglia(E: np.ndarray, tol: Optional[float]) -> float:
    if tol is not None:
        return tol
    return SOGLIA_RELATIVA * max(1.0, float(np.max(np.diff(E))) if len(E) > 1 else 1.0)


def spettro_scqubits(r: Rotore, k: int = 6, ncut: int = 30, *, controllo: str = "raddoppio",
                     tol: Optional[float] = None) -> SpettroScq:
    k = _intero(k, "k", 1)
    ncut = _intero(ncut, "ncut", 1)
    if controllo not in CONTROLLI:
        raise IngressoRifiutato(f"controllo {controllo!r} sconosciuto: ammessi {CONTROLLI}")
    if tol is not None:
        tol = _reale_finito(tol, "tol")
        if tol <= 0:
            raise IngressoRifiutato("tol deve essere positiva")
    if 2 * ncut + 1 < k:
        raise IngressoRifiutato(f"ncut={ncut} dà {2 * ncut + 1} stati, meno dei k={k} richiesti")
    ec, ej, ng = _transmon(r)
    sq = _importa()
    motore = f"scqubits {sq.__version__}"
    E = _autovalori(sq, ec, ej, ng, ncut, k)
    if controllo == "nessuno":
        return SpettroScq(tuple(float(e) for e in E), None, None, ncut, NON_CONTROLLATO, motore)
    if controllo == "raddoppio":
        E2 = _autovalori(sq, ec, ej, ng, 2 * ncut, k)
        err = float(np.max(np.abs(E - E2)))
        s = _soglia(E2, tol)
        return SpettroScq(tuple(float(e) for e in E), err, s, ncut, OK if err <= s else NON_CONVERGENTE, motore)
    while True:                                   # auto
        if 2 * ncut > NCUT_LIMITE:
            return SpettroScq(tuple(float(e) for e in E), math.inf, _soglia(E, tol), ncut, NON_CONVERGENTE, motore)
        E2 = _autovalori(sq, ec, ej, ng, 2 * ncut, k)
        err = float(np.max(np.abs(E - E2)))
        ncut, E = 2 * ncut, E2
        s = _soglia(E, tol)
        if err <= s:
            return SpettroScq(tuple(float(e) for e in E), err, s, ncut, OK, motore)


def confronta(r: Rotore, k: int = 6, *, tol_nostro: float = 1e-11, tol_scq: float = 1e-10) -> Dict:
    """Cross-check: scqubits (auto) against our solver. Difference on the transitions E_j − E_0 and on the
    absolute energies, in GHz. If one of the two does not converge, it says so and gives no difference."""
    a = spettro_scqubits(r, k, controllo="auto", tol=tol_scq)
    b = _spettro_nostro(r, k, tol_nostro)
    if a.stato != OK or b.stato != OK:
        return {"stato": NON_CONVERGENTE, "scqubits": a.stato, "nostro": b.stato,
                "scarto_transizioni": None, "scarto_assoluto": None}
    ea, eb = np.array(a.energie), np.array(b.energie)
    return {"stato": OK, "scqubits": a.stato, "nostro": b.stato,
            "scarto_transizioni": float(np.max(np.abs((ea - ea[0]) - (eb - eb[0])))),
            "scarto_assoluto": float(np.max(np.abs(ea - eb))), "ncut": a.ncut, "nmax": b.nmax,
            "motore": a.motore}
