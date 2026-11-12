# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""rigorous_levels.intervallo_garantito — DEPRECATED alias of rigorous_levels.guaranteed_intervals (the Italian names of 0.2.0).

Importing this module and using any name from it emits a DeprecationWarning that names the English replacement.
Keyword arguments keep their 0.2.0 names here and are translated; the fields of the results have Italian aliases on
the English classes. States are the English constants of 0.3.0 (GARANTITO is "GUARANTEED"). Removed in a later release."""
from rigorous_levels import guaranteed_intervals as _new
from rigorous_levels._compat import _warn, deprecated_class, deprecated_function, deprecated_module  # noqa: F401

from rigorous_levels.guaranteed_intervals import (K_MAX, M_MAX, PREC_MAX, PREC_MIN, ArbMissing, DeadlineExceeded, Intervals,
                                           OutOfDomain, as_strings, check_domain, guaranteed_levels)

N_LIMITE, CIFRE = _new.N_LIMIT, _new.DIGITS
GARANTITO, LARGO = _new.GUARANTEED, _new.WIDE
Intervalli, FuoriDominio, ArbAssente, TempoScaduto = Intervals, OutOfDomain, ArbMissing, DeadlineExceeded
livelli_garantiti = deprecated_function(guaranteed_levels, "livelli_garantiti",
                                        {"larghezza": "width", "scadenza": "deadline", "N_iniziale": "N_initial",
                                         "N_limite": "N_limit"})
controlla_dominio = deprecated_function(check_domain, "controlla_dominio")
a_stringhe = deprecated_function(as_strings, "a_stringhe")

deprecated_module("intervallo_garantito", "guaranteed_intervals")
