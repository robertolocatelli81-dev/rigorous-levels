# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra.scqubits_adattatore — DEPRECATED alias of qraft_ra.scqubits_adapter (the Italian names of 0.2.0).

Importing this module and using any name from it emits a DeprecationWarning that names the English replacement.
Keyword arguments keep their 0.2.0 names here and are translated; the fields of the results have Italian aliases on
the English classes. States are the English constants of 0.3.0 (GARANTITO is "GUARANTEED"). Removed in a later release."""
from qraft_ra import scqubits_adapter as _new
from qraft_ra._compat import _warn, deprecated_class, deprecated_function, deprecated_module  # noqa: F401

from qraft_ra.scqubits_adapter import (EPS, NCUT_LIMIT, TOL_REL, ScqubitsMissing, ScqubitsSpectrum, available, compare,
                                       norm_H, scqubits_spectrum, threshold_rule)

NON_CONTROLLATO, OK_LIMITE_FLOAT, REGOLA = _new.UNCHECKED, _new.OK_FLOAT_FLOOR, _new.RULE
NON_CONVERGENTE, OK = _new.NOT_CONVERGED, _new.OK
CONTROLLI, MOTORI, UNITA, ORIGINI = _new.CHECKS, _new.ENGINES, _new.UNITS, _new.ORIGINS
NCUT_LIMITE, TOL_ASS_GHZ, FATTORE_PAVIMENTO = NCUT_LIMIT, _new.TOL_ABS_GHZ, _new.FLOOR_FACTOR
ScqubitsAssente, SpettroScq = ScqubitsMissing, ScqubitsSpectrum
_CONTROLLO = {"nessuno": "none", "raddoppio": "doubling", "auto": "auto"}
_MOTORE = {"processo": "process", "sandbox": "sandbox"}


def spettro_scqubits(r, k=6, ncut=30, *, controllo="raddoppio", tol=None, unita="GHz", motore="processo", secondi=120):
    """Deprecated: use scqubits_spectrum (check=, unit=, engine=, seconds=; values "none"/"doubling"/"auto",
    "process"/"sandbox")."""
    _warn("spettro_scqubits", "scqubits_spectrum")
    return scqubits_spectrum(r, k, ncut, check=_CONTROLLO.get(controllo, controllo), tol=tol, unit=unita,
                             engine=_MOTORE.get(motore, motore), seconds=secondi)


disponibile = deprecated_function(available, "disponibile")
soglia_regola = deprecated_function(threshold_rule, "soglia_regola")
confronta = deprecated_function(compare, "confronta", {"tol_nostro": "tol_ours"})

deprecated_module("scqubits_adattatore", "scqubits_adapter")
