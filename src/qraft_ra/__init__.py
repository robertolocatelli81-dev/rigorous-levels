# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra: mathematically guaranteed eigenvalue intervals for the charge-basis rotor (transmon, cos mφ:
intervallo_garantito), the spherical rotor in a field (rotore_sferico_garantito), the 1Σ molecule with hyperfine,
Zeeman and Stark terms (molecola_iperfine_garantita); a float spectrum with a declared error (rotore_spettro); the
scqubits convergence warning with the declared threshold rule "soglia-scq/1.0" (scqubits_adattatore); a sandboxed
multiport that runs external solvers under bubblewrap and compares them with the intervals (multiporta, porte_runner);
the guaranteed per-level error of the Duffing model against the transmon (duffing_vs_transmon).
QRAFT-RA is an internal model, not an external validator."""

__version__ = "0.2.0"
