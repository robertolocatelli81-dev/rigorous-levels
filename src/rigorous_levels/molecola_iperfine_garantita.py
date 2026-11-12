# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""rigorous_levels.molecola_iperfine_garantita — DEPRECATED alias of rigorous_levels.hyperfine_molecule (the Italian names of 0.2.0).

Importing this module and using any name from it emits a DeprecationWarning that names the English replacement.
Keyword arguments keep their 0.2.0 names here and are translated; the fields of the results have Italian aliases on
the English classes. States are the English constants of 0.3.0 (GARANTITO is "GUARANTEED"). Removed in a later release."""
from rigorous_levels import hyperfine_molecule as _new
from rigorous_levels._compat import _warn, deprecated_class, deprecated_function, deprecated_module  # noqa: F401

from rigorous_levels.hyperfine_molecule import (K_MAX, MU_N_HZ_PER_T, PREC_MAX, PREC_MIN, ArbMissing, DeadlineExceeded,
                                         OutOfDomain, SigmaMolecule, guaranteed_molecule_levels, sector_dimension,
                                         transition, zeeman_hz)

L_LIMITE, DUE_I_MAX, L_LIMITE_MAX = _new.L_LIMIT, _new.TWO_I_MAX, _new.L_LIMIT_MAX
FuoriDominio, ArbAssente, TempoScaduto = OutOfDomain, ArbMissing, DeadlineExceeded
MolecolaSigma = deprecated_class(SigmaMolecule, "MolecolaSigma", {"due_I1": "two_I1", "due_I2": "two_I2"})
livelli_molecola_garantiti = deprecated_function(guaranteed_molecule_levels, "livelli_molecola_garantiti",
                                                 {"due_MF": "two_MF", "larghezza": "width", "scadenza": "deadline",
                                                  "L_iniziale": "L_initial", "L_limite": "L_limit"})
transizione = deprecated_function(transition, "transizione")
dimensione_settore = deprecated_function(sector_dimension, "dimensione_settore", {"due_MF": "two_MF"})

deprecated_module("molecola_iperfine_garantita", "hyperfine_molecule")
