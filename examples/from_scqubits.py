# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Start from the scqubits object you already have: guaranteed intervals of ITS Hamiltonian and the verdict on its
own levels at its own cutoff, in one line. Needs: pip install ".[scqubits]"."""
import scqubits as sq

from qraft_ra import guaranteed_from_scqubits

sq.settings.PROGRESSBAR_DISABLED = True

ok = guaranteed_from_scqubits(sq.Transmon(EJ=15.0, EC=0.3, ng=0.25, ncut=30), 4)
print(ok.kind, "ncut", ok.cutoff, "->", ok.verdict.overall, "| f01 guaranteed:",
      [f"{float(x):.9f}" for x in ok.intervals.transition(0, 1)], "GHz")

bad = guaranteed_from_scqubits(sq.Transmon(EJ=20000.0, EC=1.0, ng=0.0, ncut=30), 4)
print(bad.kind, "ncut", bad.cutoff, "->", bad.verdict.overall, "| level 3 off by", bad.verdict.per_level[3][1])

flx = guaranteed_from_scqubits(sq.Fluxonium(EJ=3.395, EC=0.479, EL=0.132, flux=0.5, cutoff=110), 3, 1e-9)
print(flx.kind, "cutoff", flx.cutoff, "->", flx.verdict.overall, "| f01 guaranteed (MHz):",
      [f"{float(x) * 1e3:.6f}" for x in flx.intervals.transition(0, 1)])
