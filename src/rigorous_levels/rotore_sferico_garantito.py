# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""rigorous_levels.rotore_sferico_garantito — DEPRECATED alias of rigorous_levels.spherical_rotor (the Italian names of 0.2.0).

Importing this module and using any name from it emits a DeprecationWarning that names the English replacement.
Keyword arguments keep their 0.2.0 names here and are translated; the fields of the results have Italian aliases on
the English classes. States are the English constants of 0.3.0 (GARANTITO is "GUARANTEED"). Removed in a later release."""
from rigorous_levels import spherical_rotor as _new
from rigorous_levels._compat import _warn, deprecated_class, deprecated_function, deprecated_module  # noqa: F401

from rigorous_levels.spherical_rotor import (K_MAX, PREC_MAX, PREC_MIN, ArbMissing, DeadlineExceeded, OutOfDomain,
                                      SphericalRotor, guaranteed_sphere_levels, transition)

L_LIMITE = _new.L_LIMIT
FuoriDominio, ArbAssente, TempoScaduto = OutOfDomain, ArbMissing, DeadlineExceeded
RotoreSferico = deprecated_class(SphericalRotor, "RotoreSferico")
livelli_sfera_garantiti = deprecated_function(guaranteed_sphere_levels, "livelli_sfera_garantiti",
                                              {"larghezza": "width", "scadenza": "deadline", "L_iniziale": "L_initial",
                                               "L_limite": "L_limit"})
transizione = deprecated_function(transition, "transizione")

deprecated_module("rotore_sferico_garantito", "spherical_rotor")
