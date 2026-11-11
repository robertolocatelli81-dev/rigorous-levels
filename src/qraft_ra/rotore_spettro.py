# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra.rotore_spettro — DEPRECATED alias of qraft_ra.rotor_spectrum (the Italian names of 0.2.0).

Importing this module and using any name from it emits a DeprecationWarning that names the English replacement.
Keyword arguments keep their 0.2.0 names here and are translated; the fields of the results have Italian aliases on
the English classes. States are the English constants of 0.3.0 (GARANTITO is "GUARANTEED"). Removed in a later release."""
from qraft_ra import rotor_spectrum as _new
from qraft_ra._compat import _warn, deprecated_class, deprecated_function, deprecated_module  # noqa: F401

from qraft_ra.rotor_spectrum import EPS, OK, InputRejected, Rotor, Spectrum, spectrum

NMAX_LIMITE, NON_CONVERGENTE = _new.NMAX_LIMIT, _new.NOT_CONVERGED
IngressoRifiutato = InputRejected
Rotore = deprecated_class(Rotor, "Rotore", {"coseni": "cosines", "seni": "sines"})
Spettro = Spectrum
spettro = deprecated_function(spectrum, "spettro", {"doppio_metodo": "two_methods", "nmax_limite": "nmax_limit"})

deprecated_module("rotore_spettro", "rotor_spectrum")
