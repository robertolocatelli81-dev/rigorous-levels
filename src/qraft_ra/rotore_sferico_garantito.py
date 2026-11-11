# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra/rotore_sferico_garantito.py — rotore SFERICO in campo: livelli come INTERVALLI GARANTITI [basso, alto].

    H = B N(N+1) − D_c [N(N+1)]² − dE cos θ,   M fisso
        (molecola polare lineare: B costante rotazionale, D_c distorsione centrifuga, dE = dipolo × campo)

Base |N, M⟩ con N ≥ |M|: diagonale f(N) = B N(N+1) − D_c [N(N+1)]²; cos θ accoppia solo N ↔ N+1, con
    c_N = sqrt( ((N+1)² − M²) / ((2N+1)(2N+3)) )           (Brown–Carrington), e ‖cos θ‖ ≤ 1.
Stesso argomento di qraft_ra/intervallo_garantito.py (Q6), sulla sfera invece che sul cerchio:
  - limite SUPERIORE: λ_j(H) ≤ λ_j(H_L), H_L compressione di H su N ≤ L (Rayleigh–Ritz, Teschl Teorema 4.12(i));
  - limite INFERIORE: per η > 0, 2bxy ≥ −|b|(x²η/|b| + y²|b|/η) sul solo accoppiamento L ↔ L+1 dà
        H ≥ (H_L − η e_L e_Lᵀ) ⊕ H_O′,   H_O′ ≥ t = f(L+1) − dE − (dE c_L)²/η;
    se t supera il limite superiore del livello j, λ_j(H) ≥ λ_j(H_L − η e_L e_Lᵀ) (Teschl Corollario 4.11);
  - «quanti autovalori < x» con la legge d'inerzia di Sylvester sui pivot LDLᵀ della tridiagonale, in palle Arb
    (python-flint). Un pivot di segno incerto fa salire la precisione o spostare il punto: mai un conteggio non dimostrato.
Distorsione centrifuga (D_c > 0): f è uno sviluppo valido solo dove cresce, cioè per N(N+1) < B/(2 D_c). Il modello
è quindi DEFINITO sulla base finita N ≤ N_fis = max{N : N(N+1) < B/(2D_c)} (dichiarato, non un'approssimazione nascosta):
lì f è crescente e il minimo del blocco esterno è f(L+1); se L raggiunge N_fis non c'è blocco esterno e i due limiti
vengono dalla stessa matrice finita. Con D_c = 0 la base è infinita come prima.
Lavora in unità assolute (le stesse di B e D, per esempio MHz): nessuna divisione in virgola mobile entra nella
dimostrazione. Ipotesi dichiarate: la H è quella dei parametri float64 esatti; correttezza di Arb/FLINT.
Prova di concetto e misure: gtm/qraft_sfera_20261110/ (PREREG, ESITO).

Cosa NON dice: che la H descriva una molecola. Non contiene la struttura iperfine (per quella: diatomic-py, integrazione
in qraft_ra/rotore_sferico_iperfine.py).
QRAFT-RA è un modello interno, non un validatore esterno.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional, Tuple

import numpy as np

from qraft_ra.intervallo_garantito import ArbAssente, FuoriDominio, Intervalli, TempoScaduto, _flint

__all__ = ["RotoreSferico", "livelli_sfera_garantiti", "FuoriDominio", "ArbAssente", "TempoScaduto"]

L_LIMITE = 20000
PREC_MIN, PREC_MAX = 128, 1024
K_MAX = 200


def _reale(x, nome: str, positivo: bool) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise FuoriDominio(f"{nome}: atteso un numero reale finito")
    try:
        x = float(x)
    except OverflowError:                                   # int oltre il float (es. 10**400): fuori dominio, non crash
        raise FuoriDominio(f"{nome}: atteso un numero reale finito (intero oltre il float64)") from None
    if not math.isfinite(x):
        raise FuoriDominio(f"{nome}: atteso un numero reale finito")
    if (positivo and x <= 0) or x < 0:
        raise FuoriDominio(f"{nome}: deve essere {'> 0' if positivo else '>= 0'}")
    return x


def _intero(x, nome: str, minimo: Optional[int] = None) -> int:
    if isinstance(x, bool) or not isinstance(x, (int, np.integer)):
        raise FuoriDominio(f"{nome}: atteso un intero")
    x = int(x)
    if minimo is not None and x < minimo:
        raise FuoriDominio(f"{nome}: atteso >= {minimo}")
    return x


@dataclass(frozen=True)
class RotoreSferico:
    """H = B N(N+1) − D_c [N(N+1)]² − dE cos θ con proiezione M fissa; dE, D_c nelle stesse unità di B."""

    B: float
    dE: float = 0.0
    M: int = 0
    Dc: float = 0.0

    def __post_init__(self):
        object.__setattr__(self, "B", _reale(self.B, "B", True))
        object.__setattr__(self, "dE", _reale(self.dE, "dE", False))
        object.__setattr__(self, "M", _intero(self.M, "M"))
        object.__setattr__(self, "Dc", _reale(self.Dc, "Dc", False))

    @property
    def N_fis(self) -> Optional[int]:
        """Massimo N del modello (None = base infinita): N(N+1) < B/(2 D_c)."""
        if self.Dc == 0.0:
            return None
        q = Fraction(self.B) / (2 * Fraction(self.Dc))
        N = int(math.isqrt(int(q))) + 1
        while N >= 0 and N * (N + 1) >= q:
            N -= 1
        return N


def _c2(N: int, M: int) -> Fraction:
    return Fraction((N + 1) ** 2 - M * M, (2 * N + 1) * (2 * N + 3))


def _approssimati(r: RotoreSferico, L: int, k: int) -> np.ndarray:
    """Solo per scegliere i punti di prova: non entra nella dimostrazione."""
    Ns = np.arange(abs(r.M), L + 1)
    c = np.sqrt([float(_c2(int(N), r.M)) for N in Ns[:-1]])
    x = Ns * (Ns + 1.0)
    T = np.diag(r.B * x - r.Dc * x * x) - r.dE * (np.diag(c, 1) + np.diag(c, -1))
    return np.linalg.eigvalsh(T)[:k]


def _palla(fl, x):
    f = Fraction(x)
    return fl.arb(fl.fmpq(f.numerator, f.denominator))


def _conta_sotto(diag, off2, x) -> Optional[int]:
    """Autovalori < x della tridiagonale simmetrica (diagonale, quadrati dei fuori-diagonale); None se un pivot è incerto."""
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


def _tenta(fl, r: RotoreSferico, k: int, larghezza: float, L: int):
    """Intervalli per i primi k livelli con il taglio L, o None se a questo L non si dimostra."""
    M = abs(r.M)
    Ns = range(M, L + 1)
    B, D, Dc = _palla(fl, r.B), _palla(fl, r.dE), _palla(fl, r.Dc)

    def f(N):                                     # diagonale esatta: B x − D_c x², x = N(N+1)
        x = N * (N + 1)
        return B * x - Dc * x * x
    diag = [f(N) for N in Ns]
    off2 = [D * D * _palla(fl, _c2(N, M)) for N in range(M, L)]
    if r.N_fis is not None and L >= r.N_fis:      # modello finito tutto incluso: nessun blocco esterno
        diagA, t, eta_f = diag, None, 0.0
    else:
        cL2 = _palla(fl, _c2(L, M))
        eta_f = max(r.dE * math.sqrt(float(_c2(L, M))), r.B * 1e-30)  # scelta di η (qualsiasi η > 0 è valida)
        eta = _palla(fl, eta_f)
        diagA = list(diag)
        diagA[-1] = diag[-1] - eta
        t = f(L + 1) - D - D * D * cL2 / eta      # f crescente su N ≤ N_fis: il minimo del blocco esterno è f(L+1)
    approx = _approssimati(r, L, k)
    bassi, alti = [], []
    for j in range(k):
        delta = max(abs(float(approx[j])), r.B) * larghezza / 4
        for _ in range(60):
            lo = Fraction(float(approx[j])) - Fraction(delta)
            hi = Fraction(float(approx[j])) + Fraction(delta)
            n_hi = _conta_sotto(diag, off2, _palla(fl, hi))
            n_lo = _conta_sotto(diagA, off2, _palla(fl, lo))
            if n_hi is not None and n_lo is not None and n_hi >= j + 1 and n_lo <= j:
                break
            delta *= 2
        else:
            return None
        if t is not None and not (t > _palla(fl, hi)):
            return None
        bassi.append(lo)
        alti.append(hi)
    return tuple(bassi), tuple(alti), eta_f


def livelli_sfera_garantiti(r: RotoreSferico, k: int = 6, larghezza: float = 1e-12, *,
                            scadenza: Optional[float] = None, L_iniziale: Optional[int] = None,
                            L_limite: int = L_LIMITE, prec: int = PREC_MIN) -> Intervalli:
    """Primi k livelli di H (per la M data) come intervalli garantiti. `larghezza` è l'obiettivo relativo a
    max(|E_j|, B); `scadenza` in secondi (TempoScaduto). FuoriDominio se non si dimostra entro L_limite."""
    if not isinstance(r, RotoreSferico):
        raise FuoriDominio(f"atteso un RotoreSferico, trovato {type(r).__name__}")
    k = _intero(k, "k", 1)
    if k > K_MAX:
        raise FuoriDominio(f"k: al massimo {K_MAX}")
    larghezza = _reale(larghezza, "larghezza", True)
    L_limite = _intero(L_limite, "L_limite", abs(r.M) + k)
    prec = _intero(prec, "prec", 2)
    if scadenza is not None:
        scadenza = _reale(scadenza, "scadenza", True)
    fl = _flint()
    t0 = time.time()
    if L_iniziale is not None:
        L = _intero(L_iniziale, "L_iniziale", abs(r.M) + k)
    else:
        extra = 2 * math.sqrt(r.dE / r.B)                   # dE/B può valere inf: niente int(inf)
        L = abs(r.M) + k + 10 + (int(extra) if extra <= L_limite else L_limite + 1)
    if r.N_fis is not None:
        if r.N_fis < abs(r.M) + k - 1:
            raise FuoriDominio(f"il modello con D_c ha solo N ≤ {r.N_fis}: meno di k = {k} livelli per M = {r.M}")
        L = min(L, r.N_fis)
        L_limite = min(L_limite, r.N_fis)
    vecchia = fl.ctx.prec
    try:
        while L <= L_limite:
            p = max(prec, PREC_MIN)
            while p <= PREC_MAX:
                if scadenza is not None and time.time() - t0 > scadenza:
                    raise TempoScaduto(f"scadenza di {scadenza} s superata a L = {L}")
                fl.ctx.prec = p
                ris = _tenta(fl, r, k, larghezza, L)
                if ris is not None:
                    bassi, alti, eta = ris
                    larg = max(float(a - b) for a, b in zip(alti, bassi))
                    obiettivo = larghezza * max(max(abs(float(b)) for b in bassi), r.B)
                    stringhe = tuple((str(float(b)), str(float(a))) for b, a in zip(bassi, alti))
                    return Intervalli(bassi, alti, stringhe, larg, "GARANTITO" if larg <= obiettivo else "LARGO",
                                      L, p, eta, round(time.time() - t0, 3))
                p *= 2
            if L >= L_limite:
                break
            L = min(int(L * 1.5) + 5, L_limite)          # l'ultimo tentativo è sempre L_limite (N_fis se D_c > 0)
        raise FuoriDominio(f"nessun intervallo dimostrato entro L_limite = {L_limite}")
    finally:
        fl.ctx.prec = vecchia


def transizione(iv: Intervalli, i: int, iv2: Intervalli, j: int) -> Tuple[Fraction, Fraction]:
    """E_j(iv2) − E_i(iv) garantito (anche tra M diverse): [basso_j − alto_i, alto_j − basso_i]."""
    return iv2.bassi[j] - iv.alti[i], iv2.alti[j] - iv.bassi[i]
