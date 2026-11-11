# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra/scqubits_adapter.py — scqubits as an optional engine, with the convergence warning scqubits does not give.

scqubits (BSD-3, https://scqubits.readthedocs.io) diagonalizes the transmon on a charge basis truncated at the `ncut`
chosen by the user; its documentation leaves the convergence check to the user. With ncut = 30 it is wrong without a
warning beyond E_J/E_C ≈ 7700 (measured 2026-11-07). Here:

  - `available()`: lazy import; if scqubits is missing it says so, and every computation raises `ScqubitsMissing`
    with the reason.
  - `scqubits_spectrum(r, k, ncut, check=...)`:
      check="none"      scqubits' number as it is (state UNCHECKED, error None);
      check="doubling"  also computes at 2·ncut; estimated error = max_j |E_j(ncut) − E_j(2·ncut)|; state
                        NOT_CONVERGED if it exceeds the threshold. The energies returned are those at ncut;
      check="auto"      doubles ncut until the shift is ≤ tol (or NCUT_LIMIT: NOT_CONVERGED).
    Default threshold, rule "scq-threshold/1.0" (docs/THRESHOLD_RULE.md, written before the code on 2026-11-11 as
    "soglia-scq/1.0"; same rule, renamed in 0.3.0): DECLARED unit (`unit` ∈ GHz/MHz/Hz, closed list; the rule is
    covariant); physical = min(1e-6 GHz, 1e-6·(E[k−1]−E[0])) with E at 2·ncut; floor = 32·eps·(‖H(ncut)‖₂+‖H(2ncut)‖₂)
    with ‖H(n)‖₂ ≤ 4E_C(n+|n_g|)²+E_J (Gershgorin); threshold = max(floor, physical or `tol`); which one decided is in
    the field `threshold_origin` (absolute/relative/user/floor); if the floor decides, the state is OK_FLOAT_FLOOR.
    The old relative rule (1e-6·max(1, largest transition), units hidden in the max) was removed in 0.2.0.
  - `engine="process"` imports scqubits IN the process (declared: other people's code, not trusted);
    `engine="sandbox"` runs the port `scqubits_transmon` of qraft_ra/multiport.py in the sandbox (fail-closed: without a
    sandbox engine no number).
  - `compare(r, k)`: cross-check against our solver (`rotor_spectrum.spectrum`), shift on the transitions E_j − E_0.

Why doubling gives no false alarm: the charge bases are nested, so (Cauchy, Rayleigh–Ritz)
E_j(ncut) ≥ E_j(2·ncut) ≥ true E_j. The shift on doubling is a LOWER bound of the true error: if it exceeds the
threshold, the true error does, provided the scale of the threshold (the transitions at 2·ncut) is the true one,
that is, 2·ncut is enough. The converse (large true error with a small shift) is not excluded by the mathematics: it
is measured on the bench (2000 + 1200 runs in the device regime, 1080 outside it, 0 results marked OK outside the
threshold); at the border, within ±1e-4 relative of the threshold, misses and false alarms exist (reviewer, 2026-11-08).

Domain: only the transmon U = −E_J cos φ with E_J > 0 (`scqubits.Transmon`). Any other `Rotor` = refusal.
Names: this module was `scqubits_adattatore` in 0.2.0 (deprecated aliases in that module).
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np

from qraft_ra._compat import add_field_aliases
from qraft_ra.rotor_spectrum import (NOT_CONVERGED, OK, InputRejected, Rotor, _finite_real,
                                     spectrum as _our_spectrum)

UNCHECKED = "UNCHECKED"                 # 0.2.0: NON_CONTROLLATO
OK_FLOAT_FLOOR = "OK_FLOAT_FLOOR"       # 0.2.0: OK_LIMITE_FLOAT
CHECKS = ("none", "doubling", "auto")   # 0.2.0: nessuno, raddoppio, auto
ENGINES = ("process", "sandbox")        # 0.2.0: processo, sandbox
UNITS = {"GHz": 1.0, "MHz": 1e3, "Hz": 1e9}      # factor GHz → declared unit
NCUT_LIMIT = 1920
RULE = "scq-threshold/1.0"              # 0.2.0: "soglia-scq/1.0", same rule (docs/THRESHOLD_RULE.md)
TOL_ABS_GHZ = 1e-6
TOL_REL = 1e-6
FLOOR_FACTOR = 32
EPS = 2.0 ** -52
ORIGINS = ("absolute", "relative", "user", "floor")   # 0.2.0: assoluta, relativa, utente, pavimento


class ScqubitsMissing(RuntimeError):
    """scqubits is not installed: no number, only the reason."""


def _import_scqubits():
    try:
        import scqubits as sq            # lazy import: optional dependency
    except ImportError as e:
        raise ScqubitsMissing(f"scqubits is not installed ({e}); install scqubits==4.3.1 or use "
                              f"qraft_ra.rotor_spectrum.spectrum") from None
    sq.settings.PROGRESSBAR_DISABLED = True
    return sq


def available() -> Dict:
    try:
        sq = _import_scqubits()
    except ScqubitsMissing as e:
        return {"present": False, "version": None, "reason": str(e)}
    return {"present": True, "version": sq.__version__, "reason": None}


@dataclass(frozen=True)
class ScqubitsSpectrum:
    energies: Tuple[float, ...]
    error: Optional[float]         # estimated error (a lower bound of the true one); None if unchecked
    threshold: Optional[float]
    ncut: int
    state: str
    engine: str
    threshold_origin: Optional[str] = None   # absolute | relative | user | floor (None if unchecked)
    floor: Optional[float] = None            # 32·eps·(‖H(ncut)‖₂ + ‖H(2ncut)‖₂), declared unit
    unit: str = "GHz"
    rule: str = RULE


def _transmon(r: Rotor) -> Tuple[float, float, float]:
    if not isinstance(r, Rotor):
        raise InputRejected(f"expected a Rotor, got {type(r).__name__}")
    if r.sines or len(r.cosines) != 1 or r.cosines[0][0] != 1 or not r.cosines[0][1] < 0:
        raise InputRejected("outside the domain of the adapter: only U = −E_J cos φ with E_J > 0 (scqubits.Transmon)")
    return r.E_C, -r.cosines[0][1], r.n_g


def _integer(x, name: str, minimum: int) -> int:
    if isinstance(x, bool) or not isinstance(x, (int, np.integer)) or x < minimum:
        raise InputRejected(f"{name} must be an integer >= {minimum}")
    return int(x)


def _eigenvalues(sq, ec: float, ej: float, ng: float, ncut: int, k: int) -> np.ndarray:
    t = sq.Transmon(EJ=ej, EC=ec, ng=ng, ncut=ncut, truncated_dim=k)
    return np.asarray(t.eigenvals(evals_count=k), dtype=float)


def _eigenvalues_sandbox(ec: float, ej: float, ng: float, ncut: int, k: int, unit: str, seconds: int) -> Tuple[np.ndarray, str]:
    """The port scqubits_transmon of the multiport, in the sandbox. No number if the sandbox or scqubits are missing."""
    from qraft_ra import multiport as MP
    import site
    import sysconfig
    sp = tuple(p for p in (sysconfig.get_path("purelib"), site.getusersitepackages()) if p and os.path.isdir(p))
    r = MP.Request("scqubits_transmon", {"type": "cos_rotor", "E_C": ec, "E_J": ej, "n_g": ng}, k, {"ncut": ncut},
                   unit=unit, seconds=seconds, mem_mib=4096, site_packages=sp)
    u = MP.run_port(r)
    if u.state != "OK":
        raise ScqubitsMissing(f"port scqubits_transmon: {u.state}: {u.reason}")
    if u.unit != unit or len(u.levels) != k:      # closed contract: the unit and the number of levels requested
        raise ScqubitsMissing(f"port scqubits_transmon: unit {u.unit!r}/{len(u.levels)} levels ≠ {unit!r}/{k}")
    return np.asarray(u.levels, dtype=float), u.solver_version


def norm_H(ec: float, ej: float, ng: float, ncut: int) -> float:
    """Upper bound of ‖H(ncut)‖₂ (Gershgorin on the symmetric tridiagonal): 4E_C(ncut+|n_g|)² + E_J."""
    return 4.0 * ec * (ncut + abs(ng)) ** 2 + ej


def threshold_rule(E2: np.ndarray, ec: float, ej: float, ng: float, ncut: int, tol: Optional[float],
                   unit: str) -> Tuple[float, str, float]:
    """(threshold, origin, floor) by "scq-threshold/1.0". E2 = energies at 2·ncut in the declared unit."""
    u = UNITS[unit]
    floor = FLOOR_FACTOR * EPS * (norm_H(ec, ej, ng, ncut) + norm_H(ec, ej, ng, 2 * ncut))
    if tol is not None:
        physical, origin = tol, "user"
    else:
        absolute = TOL_ABS_GHZ * u
        if len(E2) > 1:
            rel = TOL_REL * float(E2[-1] - E2[0])
            physical, origin = (rel, "relative") if rel < absolute else (absolute, "absolute")
        else:
            physical, origin = absolute, "absolute"
    if floor > physical:
        return floor, "floor", floor
    return physical, origin, floor


def _verdict(E: np.ndarray, E2: np.ndarray, ec, ej, ng, ncut, tol, unit):
    err = float(np.max(np.abs(E - E2)))
    s, origin, floor = threshold_rule(E2, ec, ej, ng, ncut, tol, unit)
    if err > s:
        state = NOT_CONVERGED
    else:
        state = OK_FLOAT_FLOOR if origin == "floor" else OK
    return err, s, origin, floor, state


def scqubits_spectrum(r: Rotor, k: int = 6, ncut: int = 30, *, check: str = "doubling",
                      tol: Optional[float] = None, unit: str = "GHz", engine: str = "process",
                      seconds: int = 120) -> ScqubitsSpectrum:
    """Spectrum of the transmon through scqubits with the convergence warning (rule "scq-threshold/1.0"). Closed inputs."""
    k = _integer(k, "k", 1)
    ncut = _integer(ncut, "ncut", 1)
    if check not in CHECKS:
        raise InputRejected(f"check {check!r} unknown: allowed {CHECKS}")
    if not isinstance(unit, str) or unit not in UNITS:
        raise InputRejected(f"unit {unit!r} unknown: allowed {tuple(UNITS)}")
    if engine not in ENGINES:
        raise InputRejected(f"engine {engine!r} unknown: allowed {ENGINES}")
    seconds = _integer(seconds, "seconds", 1)
    if tol is not None:
        tol = _finite_real(tol, "tol")
        if tol <= 0:
            raise InputRejected("tol must be positive")
    if 2 * ncut + 1 < k:
        raise InputRejected(f"ncut={ncut} gives {2 * ncut + 1} states, fewer than the k={k} requested")
    ec, ej, ng = _transmon(r)
    if engine == "process":
        sq = _import_scqubits()
        engine_str = f"scqubits {sq.__version__} (process)"

        def compute(n):
            return _eigenvalues(sq, ec, ej, ng, n, k)
    else:
        version = {}

        def compute(n):
            E, v = _eigenvalues_sandbox(ec, ej, ng, n, k, unit, seconds)
            version["v"] = v
            return E
        engine_str = None
    E = compute(ncut)
    if engine_str is None:
        engine_str = f"{version['v']} (sandbox)"
    if check == "none":
        return ScqubitsSpectrum(tuple(float(e) for e in E), None, None, ncut, UNCHECKED, engine_str, None, None, unit)
    if check == "doubling":
        E2 = compute(2 * ncut)
        err, s, origin, floor, state = _verdict(E, E2, ec, ej, ng, ncut, tol, unit)
        return ScqubitsSpectrum(tuple(float(e) for e in E), err, s, ncut, state, engine_str, origin, floor, unit)
    while True:                                   # auto
        if 2 * ncut > NCUT_LIMIT:
            s, origin, floor = threshold_rule(E, ec, ej, ng, ncut, tol, unit)
            return ScqubitsSpectrum(tuple(float(e) for e in E), math.inf, s, ncut, NOT_CONVERGED, engine_str, origin, floor, unit)
        E2 = compute(2 * ncut)
        err, s, origin, floor, state = _verdict(E, E2, ec, ej, ng, ncut, tol, unit)
        ncut, E = 2 * ncut, E2
        if state != NOT_CONVERGED:
            return ScqubitsSpectrum(tuple(float(e) for e in E), err, s, ncut, state, engine_str, origin, floor, unit)


@dataclass(frozen=True)
class ScqubitsCheck:
    """Guaranteed intervals for the H of a scqubits object, and the verdict on its own levels at its own cutoff."""

    kind: str                       # "Transmon" | "Fluxonium"
    intervals: object               # qraft_ra.guaranteed_intervals.Intervals
    levels: Tuple[float, ...]       # the object's eigenvals at its cutoff (ncut / cutoff), GHz
    verdict: object                 # qraft_ra.multiport.Verdict: INSIDE / INSIDE_TOLERANCE / OUTSIDE per level
    tolerance: float                # float tolerance used (GHz): the adapter's floor rule on the object's cutoff
    cutoff: int


def guaranteed_from_scqubits(qubit, k: int = 6, width: float = 1e-10, *, deadline: Optional[float] = None) -> ScqubitsCheck:
    """One line from an object the user already has: `scqubits.Transmon(EJ, EC, ng, ncut)` or
    `scqubits.Fluxonium(EJ, EC, EL, flux, cutoff)` → guaranteed intervals of ITS H (same convention: GHz, h = 1) and
    the verdict of its own `eigenvals()` against them, with the float tolerance 32·eps·‖H‖ declared. Anything else
    is refused (closed list of classes, read by name and attributes: scqubits is not imported here)."""
    from qraft_ra import multiport as MP
    from qraft_ra.guaranteed_intervals import guaranteed_levels
    name = type(qubit).__name__
    k = _integer(k, "k", 1)
    if name == "Transmon":
        ec, ej, ng, cut = (float(getattr(qubit, a)) for a in ("EC", "EJ", "ng", "ncut"))
        iv = guaranteed_levels(Rotor.transmon(ec, ej, n_g=ng), k, width, deadline=deadline)
        cut = int(cut)
        tol = FLOOR_FACTOR * EPS * norm_H(ec, ej, ng, cut)
    elif name == "Fluxonium":
        from qraft_ra.fluxonium import Fluxonium, guaranteed_fluxonium_levels
        ec, ej, el, flux, cut = (float(getattr(qubit, a)) for a in ("EC", "EJ", "EL", "flux", "cutoff"))
        iv = guaranteed_fluxonium_levels(Fluxonium(E_C=ec, E_J=ej, E_L=el, flux=flux), k, width, deadline=deadline)
        cut = int(cut)
        tol = FLOOR_FACTOR * EPS * (math.sqrt(8 * el * ec) * (cut + 0.5) + ej)        # Gershgorin: ω(N+½) + E_J
    else:
        raise InputRejected(f"expected a scqubits Transmon or Fluxonium, got {name}")
    levels = tuple(float(x) for x in qubit.eigenvals(evals_count=k))
    out = MP.Output("numpy_rotor", f"scqubits {name} cutoff {cut}", levels, "GHz", "OK", "", 0.0, "process")
    return ScqubitsCheck(name, iv, levels, MP.compare(iv, "GHz", out, tolerance=tol), tol, cut)


def compare(r: Rotor, k: int = 6, *, tol_ours: float = 1e-11, tol_scq: float = 1e-10) -> Dict:
    """Cross-check: scqubits (auto) against our solver. Shift on the transitions E_j − E_0 and on the absolute
    energies, in GHz. If one of the two does not converge, it says so and gives no shift."""
    a = scqubits_spectrum(r, k, check="auto", tol=tol_scq)
    b = _our_spectrum(r, k, tol_ours)
    if a.state not in (OK, OK_FLOAT_FLOOR) or b.state != OK:
        return {"state": NOT_CONVERGED, "scqubits": a.state, "ours": b.state, "threshold_origin": a.threshold_origin,
                "transition_shift": None, "absolute_shift": None}
    ea, eb = np.array(a.energies), np.array(b.energies)
    return {"state": OK, "scqubits": a.state, "ours": b.state, "threshold_origin": a.threshold_origin,
            "transition_shift": float(np.max(np.abs((ea - ea[0]) - (eb - eb[0])))),
            "absolute_shift": float(np.max(np.abs(ea - eb))), "ncut": a.ncut, "nmax": b.nmax,
            "engine": a.engine}


# deprecated Italian field names of 0.2.0 (DeprecationWarning on use; removed in a later release)
add_field_aliases(ScqubitsSpectrum, {"energie": "energies", "errore": "error", "soglia": "threshold", "stato": "state",
                                     "motore": "engine", "soglia_origine": "threshold_origin", "pavimento": "floor",
                                     "unita": "unit", "regola": "rule"})
