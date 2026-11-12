# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""rigorous_levels: mathematically guaranteed eigenvalue intervals for the charge-basis rotor (transmon, cos mφ:
guaranteed_intervals), the spherical rotor in a field (spherical_rotor), the 1Σ molecule with hyperfine, Zeeman and
Stark terms (hyperfine_molecule), the Mathieu characteristic values a_r(q), b_r(q) (mathieu), the fluxonium in the
oscillator basis (fluxonium), parameters given as intervals (parameter_balls) and matrix elements ⟨v_i|n|v_j⟩,
⟨v_i|cos mφ|v_j⟩, ⟨v_i|sin mφ|v_j⟩ between enclosed eigenvectors (matrix_elements); a float spectrum with a declared
error (rotor_spectrum); the scqubits convergence warning with the declared threshold rule "scq-threshold/1.0" and the
entry from scqubits objects (scqubits_adapter); a sandboxed multiport that runs external solvers inside one of the
isolation engines and compares them with the intervals (multiport, port_runner, isolation); the guaranteed per-level
error of the Duffing model against the transmon (duffing_vs_transmon).

The public English API is exposed here (`from rigorous_levels import Rotor, guaranteed_levels, ...`). The Italian module
names of 0.2.0 are kept as deprecated aliases (DeprecationWarning). This package is not an external
validator."""

__version__ = "0.3.0"

from rigorous_levels.guaranteed_intervals import (GUARANTEED, WIDE, ArbMissing, DeadlineExceeded, Intervals, OutOfDomain,  # noqa: E402
                                           guaranteed_levels)
from rigorous_levels.rotor_spectrum import NOT_CONVERGED, OK, InputRejected, Rotor, Spectrum, spectrum  # noqa: E402
from rigorous_levels.spherical_rotor import SphericalRotor, guaranteed_sphere_levels  # noqa: E402
from rigorous_levels.hyperfine_molecule import SigmaMolecule, guaranteed_molecule_levels, sector_dimension, zeeman_hz  # noqa: E402
from rigorous_levels.mathieu import MathieuValue, mathieu_a, mathieu_b, mathieu_value  # noqa: E402
from rigorous_levels.fluxonium import Fluxonium, guaranteed_fluxonium_levels  # noqa: E402
from rigorous_levels.parameter_balls import RotorBall, guaranteed_levels_over_box  # noqa: E402
from rigorous_levels.matrix_elements import MatrixElement, guaranteed_matrix_element  # noqa: E402
from rigorous_levels.duffing_vs_transmon import DuffingError, duffing_error  # noqa: E402
from rigorous_levels.scqubits_adapter import (OK_FLOAT_FLOOR, UNCHECKED, ScqubitsCheck, ScqubitsMissing, ScqubitsSpectrum,  # noqa: E402
                                       assert_inside, check, guaranteed_from_scqubits, scqubits_spectrum)
from rigorous_levels.multiport import (ENGINES, PORTS, Output, Request, SandboxMissing, Verdict, compare, run_port,  # noqa: E402
                                run_ports, site_packages_of)

__all__ = ["__version__", "GUARANTEED", "WIDE", "OK", "NOT_CONVERGED", "UNCHECKED", "OK_FLOAT_FLOOR",
           "ArbMissing", "DeadlineExceeded", "OutOfDomain", "InputRejected", "ScqubitsMissing", "SandboxMissing",
           "Intervals", "Rotor", "Spectrum", "SphericalRotor", "SigmaMolecule", "MathieuValue", "Fluxonium", "RotorBall", "MatrixElement",
           "DuffingError", "ScqubitsSpectrum", "ScqubitsCheck", "Request", "Output", "Verdict", "ENGINES", "PORTS",
           "guaranteed_levels", "spectrum", "guaranteed_sphere_levels", "guaranteed_molecule_levels", "sector_dimension",
           "zeeman_hz", "mathieu_a", "mathieu_b", "mathieu_value", "guaranteed_fluxonium_levels",
           "guaranteed_levels_over_box", "guaranteed_matrix_element", "duffing_error", "scqubits_spectrum", "guaranteed_from_scqubits",
           "check", "assert_inside", "run_port", "run_ports", "compare", "site_packages_of"]
