# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra.multiporta — DEPRECATED alias of qraft_ra.multiport (the Italian names of 0.2.0).

Importing this module and using any name from it emits a DeprecationWarning that names the English replacement.
Keyword arguments keep their 0.2.0 names here and are translated; the fields of the results have Italian aliases on
the English classes. States are the English constants of 0.3.0 (GARANTITO is "GUARANTEED"). Removed in a later release."""
from qraft_ra import multiport as _new
from qraft_ra._compat import _warn, deprecated_class, deprecated_function, deprecated_module  # noqa: F401

from qraft_ra.multiport import (CONTRACT, ENGINES, JMAX_TLF, MEM_MIB_MAX, OUTPUT_MAX_BYTES, OUTPUT_MAX_DEPTH, PORTS,
                                RUNNER, Output, OutOfDomain, Request, SandboxMissing, Verdict, compare, read_output,
                                run_port, validate_output)

CONTRATTO, PORTE, MODELLI, UNITA, CHIAVI_USCITA = CONTRACT, PORTS, _new.MODELS, _new.UNITS, _new.OUTPUT_KEYS
SECONDI_MAX, LIVELLI_MAX, USCITA_MAX_BYTE, USCITA_MAX_PROFONDITA = _new.SECONDS_MAX, _new.LEVELS_MAX, OUTPUT_MAX_BYTES, OUTPUT_MAX_DEPTH
TMPFS_BYTE, MONTAGGI_RO = _new.TMPFS_BYTES, _new.RO_MOUNTS
FuoriDominio, SandboxAssente, Uscita, Verdetto = OutOfDomain, SandboxMissing, Output, Verdict
Intervalli = _new.Intervals
Richiesta = deprecated_class(Request, "Richiesta", {"porta": "port", "modello": "model", "livelli": "levels",
                                                    "troncamento": "truncation", "unita": "unit", "secondi": "seconds"})
esegui_porta = deprecated_function(run_port, "esegui_porta")
confronta = deprecated_function(compare, "confronta", {"tolleranza": "tolerance"})
valida_uscita = deprecated_function(validate_output, "valida_uscita")
leggi_uscita = deprecated_function(read_output, "leggi_uscita")

deprecated_module("multiporta", "multiport")
