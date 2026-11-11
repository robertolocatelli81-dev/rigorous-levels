# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra/scqubits_adattatore.py — scqubits come motore opzionale, con l'avviso di convergenza che scqubits non dà.

scqubits (BSD-3, https://scqubits.readthedocs.io) diagonalizza il transmon su una base di carica troncata a `ncut`
scelto dall'utente; la sua documentazione lascia all'utente il controllo della convergenza. Con ncut=30 sbaglia
senza dirlo oltre E_J/E_C ≈ 7700 (ESITO 07/11). Qui:

  - `disponibile()`: import pigro; se scqubits manca lo dice, e ogni calcolo solleva `ScqubitsAssente` col motivo.
  - `spettro_scqubits(r, k, ncut, controllo=...)`:
      controllo="nessuno"   il numero di scqubits così com'è (stato NON_CONTROLLATO, errore None);
      controllo="raddoppio" calcola anche a 2·ncut; errore stimato = max_j |E_j(ncut) − E_j(2·ncut)|; stato
                            NON_CONVERGENTE se supera la soglia. Le energie restituite sono quelle a ncut;
      controllo="auto"      raddoppia ncut finché lo spostamento è ≤ tol (o NCUT_LIMITE: NON_CONVERGENTE).
    Soglia predefinita, regola "soglia-scq/1.0" (gtm/qraft_soglia_20261111/SPECIFICA_SOGLIA_v1.0.md, scritta prima
    del codice l'11/11/2026): unità DICHIARATA (`unita` ∈ GHz/MHz/Hz, lista chiusa; la regola è covariante);
    fisica = min(1e-6 GHz, 1e-6·(E[k−1]−E[0])) con E a 2·ncut; pavimento = 32·eps·(‖H(ncut)‖₂+‖H(2ncut)‖₂) con
    ‖H(n)‖₂ ≤ 4E_C(n+|n_g|)²+E_J (Gershgorin); soglia = max(pavimento, fisica o `tol`); l'origine del max è nel
    campo `soglia_origine` (assoluta/relativa/utente/pavimento); se decide il pavimento lo stato è OK_LIMITE_FLOAT.
    Regola vecchia (relativa 1e-6·max(1, transizione massima), unità nascoste nel max): tolta.
  - `motore="processo"` importa scqubits NEL processo (codice altrui non fidato, dichiarato); `motore="sandbox"`
    esegue la porta `scqubits_transmon` di qraft_ra/multiporta.py dentro bwrap (fail-closed: senza bwrap nessun numero).
  - `confronta(r, k)`: controllo incrociato col nostro solutore (`rotore_spettro.spettro`), scarto sulle
    transizioni E_j − E_0.

Perché il raddoppio non dà falsi allarmi: le basi di carica sono annidate, quindi (Cauchy, Rayleigh–Ritz)
E_j(ncut) ≥ E_j(2·ncut) ≥ E_j vero. Lo spostamento al raddoppio è un limite INFERIORE dell'errore vero: se supera
la soglia, l'errore vero la supera, a patto che la scala della soglia (transizioni a 2·ncut) sia quella vera, cioè
che 2·ncut basti. Il contrario (errore vero grande con spostamento piccolo) non è escluso dalla matematica: è
misurato nel banco (Q2); al confine, entro ±1e-4 relativo dalla soglia, mancati e falsi allarmi esistono (NEMESIS
08/11).

Dominio: solo il transmon U = −E_J cos φ con E_J > 0 (`scqubits.Transmon`). Qualunque altro `Rotore` = rifiuto.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np

from qraft_ra.rotore_spettro import (NON_CONVERGENTE, OK, IngressoRifiutato, Rotore, _reale_finito,
                                  spettro as _spettro_nostro)

NON_CONTROLLATO = "NON_CONTROLLATO"
OK_LIMITE_FLOAT = "OK_LIMITE_FLOAT"
CONTROLLI = ("nessuno", "raddoppio", "auto")
MOTORI = ("processo", "sandbox")
UNITA = {"GHz": 1.0, "MHz": 1e3, "Hz": 1e9}      # fattore GHz → unità dichiarata
NCUT_LIMITE = 1920
REGOLA = "soglia-scq/1.0"
TOL_ASS_GHZ = 1e-6
TOL_REL = 1e-6
FATTORE_PAVIMENTO = 32
EPS = 2.0 ** -52
ORIGINI = ("assoluta", "relativa", "utente", "pavimento")


class ScqubitsAssente(RuntimeError):
    """scqubits non è installato: nessun numero, solo il motivo."""


def _importa():
    try:
        import scqubits as sq            # import pigro: dipendenza opzionale
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
    errore: Optional[float]        # errore stimato (limite inferiore dell'errore vero); None se non controllato
    soglia: Optional[float]
    ncut: int
    stato: str
    motore: str
    soglia_origine: Optional[str] = None   # assoluta | relativa | utente | pavimento (None se non controllato)
    pavimento: Optional[float] = None      # 32·eps·(‖H(ncut)‖₂ + ‖H(2ncut)‖₂), unità dichiarata
    unita: str = "GHz"
    regola: str = REGOLA


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


def _autovalori_sandbox(ec: float, ej: float, ng: float, ncut: int, k: int, unita: str, secondi: int) -> Tuple[np.ndarray, str]:
    """La porta scqubits_transmon della multiporta, dentro bwrap. Nessun numero se la sandbox o scqubits mancano."""
    from qraft_ra import multiporta as MP
    import site
    import sysconfig
    sp = tuple(p for p in (sysconfig.get_path("purelib"), site.getusersitepackages()) if p and __import__("os").path.isdir(p))
    r = MP.Richiesta("scqubits_transmon", {"tipo": "rotore_cos", "E_C": ec, "E_J": ej, "n_g": ng}, k, {"ncut": ncut},
                     unita=unita, secondi=secondi, mem_mib=4096, site_packages=sp)
    u = MP.esegui_porta(r)
    if u.stato != "OK":
        raise ScqubitsAssente(f"porta scqubits_transmon: {u.stato}: {u.motivo}")
    if u.unita != unita or len(u.livelli) != k:      # contratto chiuso: unità e numero di livelli quelli chiesti (NEMESIS 11/11)
        raise ScqubitsAssente(f"porta scqubits_transmon: unità {u.unita!r}/{len(u.livelli)} livelli ≠ {unita!r}/{k}")
    return np.asarray(u.livelli, dtype=float), u.versione_solutore


def norma_H(ec: float, ej: float, ng: float, ncut: int) -> float:
    """Limite superiore di ‖H(ncut)‖₂ (Gershgorin sulla tridiagonale simmetrica): 4E_C(ncut+|n_g|)² + E_J."""
    return 4.0 * ec * (ncut + abs(ng)) ** 2 + ej


def soglia_regola(E2: np.ndarray, ec: float, ej: float, ng: float, ncut: int, tol: Optional[float],
                  unita: str) -> Tuple[float, str, float]:
    """(soglia, origine, pavimento) secondo "soglia-scq/1.0". E2 = energie a 2·ncut nell'unità dichiarata."""
    u = UNITA[unita]
    pav = FATTORE_PAVIMENTO * EPS * (norma_H(ec, ej, ng, ncut) + norma_H(ec, ej, ng, 2 * ncut))
    if tol is not None:
        fisica, origine = tol, "utente"
    else:
        ass = TOL_ASS_GHZ * u
        if len(E2) > 1:
            rel = TOL_REL * float(E2[-1] - E2[0])
            fisica, origine = (rel, "relativa") if rel < ass else (ass, "assoluta")
        else:
            fisica, origine = ass, "assoluta"
    if pav > fisica:
        return pav, "pavimento", pav
    return fisica, origine, pav


def _verdetto(E: np.ndarray, E2: np.ndarray, ec, ej, ng, ncut, tol, unita, motore_str):
    err = float(np.max(np.abs(E - E2)))
    s, origine, pav = soglia_regola(E2, ec, ej, ng, ncut, tol, unita)
    if err > s:
        stato = NON_CONVERGENTE
    else:
        stato = OK_LIMITE_FLOAT if origine == "pavimento" else OK
    return err, s, origine, pav, stato


def spettro_scqubits(r: Rotore, k: int = 6, ncut: int = 30, *, controllo: str = "raddoppio",
                     tol: Optional[float] = None, unita: str = "GHz", motore: str = "processo",
                     secondi: int = 120) -> SpettroScq:
    """Spettro del transmon via scqubits con l'avviso di convergenza (regola "soglia-scq/1.0"). Ingressi chiusi."""
    k = _intero(k, "k", 1)
    ncut = _intero(ncut, "ncut", 1)
    if controllo not in CONTROLLI:
        raise IngressoRifiutato(f"controllo {controllo!r} sconosciuto: ammessi {CONTROLLI}")
    if not isinstance(unita, str) or unita not in UNITA:
        raise IngressoRifiutato(f"unita {unita!r} sconosciuta: ammesse {tuple(UNITA)}")
    if motore not in MOTORI:
        raise IngressoRifiutato(f"motore {motore!r} sconosciuto: ammessi {MOTORI}")
    secondi = _intero(secondi, "secondi", 1)
    if tol is not None:
        tol = _reale_finito(tol, "tol")
        if tol <= 0:
            raise IngressoRifiutato("tol deve essere positiva")
    if 2 * ncut + 1 < k:
        raise IngressoRifiutato(f"ncut={ncut} dà {2 * ncut + 1} stati, meno dei k={k} richiesti")
    ec, ej, ng = _transmon(r)
    if motore == "processo":
        sq = _importa()
        motore_str = f"scqubits {sq.__version__} (processo)"

        def calcola(n):
            return _autovalori(sq, ec, ej, ng, n, k)
    else:
        versione = {}

        def calcola(n):
            E, v = _autovalori_sandbox(ec, ej, ng, n, k, unita, secondi)
            versione["v"] = v
            return E
        motore_str = None
    E = calcola(ncut)
    if motore_str is None:
        motore_str = f"{versione['v']} (sandbox bwrap)"
    if controllo == "nessuno":
        return SpettroScq(tuple(float(e) for e in E), None, None, ncut, NON_CONTROLLATO, motore_str, None, None, unita)
    if controllo == "raddoppio":
        E2 = calcola(2 * ncut)
        err, s, origine, pav, stato = _verdetto(E, E2, ec, ej, ng, ncut, tol, unita, motore_str)
        return SpettroScq(tuple(float(e) for e in E), err, s, ncut, stato, motore_str, origine, pav, unita)
    while True:                                   # auto
        if 2 * ncut > NCUT_LIMITE:
            s, origine, pav = soglia_regola(E, ec, ej, ng, ncut, tol, unita)
            return SpettroScq(tuple(float(e) for e in E), math.inf, s, ncut, NON_CONVERGENTE, motore_str, origine, pav, unita)
        E2 = calcola(2 * ncut)
        err, s, origine, pav, stato = _verdetto(E, E2, ec, ej, ng, ncut, tol, unita, motore_str)
        ncut, E = 2 * ncut, E2
        if stato != NON_CONVERGENTE:
            return SpettroScq(tuple(float(e) for e in E), err, s, ncut, stato, motore_str, origine, pav, unita)


def confronta(r: Rotore, k: int = 6, *, tol_nostro: float = 1e-11, tol_scq: float = 1e-10) -> Dict:
    """Controllo incrociato: scqubits (auto) contro il nostro solutore. Scarto sulle transizioni E_j − E_0 e sulle
    energie assolute, in GHz. Se uno dei due non converge, lo dice e non dà lo scarto."""
    a = spettro_scqubits(r, k, controllo="auto", tol=tol_scq)
    b = _spettro_nostro(r, k, tol_nostro)
    if a.stato not in (OK, OK_LIMITE_FLOAT) or b.stato != OK:
        return {"stato": NON_CONVERGENTE, "scqubits": a.stato, "nostro": b.stato, "soglia_origine": a.soglia_origine,
                "scarto_transizioni": None, "scarto_assoluto": None}
    ea, eb = np.array(a.energie), np.array(b.energie)
    return {"stato": OK, "scqubits": a.stato, "nostro": b.stato, "soglia_origine": a.soglia_origine,
            "scarto_transizioni": float(np.max(np.abs((ea - ea[0]) - (eb - eb[0])))),
            "scarto_assoluto": float(np.max(np.abs(ea - eb))), "ncut": a.ncut, "nmax": b.nmax,
            "motore": a.motore}
