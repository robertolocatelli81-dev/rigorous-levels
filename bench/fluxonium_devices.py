# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Guaranteed fluxonium levels for published devices against scqubits.Fluxonium (PREREG D2.4 of 0.3.0).

    python bench/fluxonium_devices.py OUT.json        # needs rigorous_levels[scqubits]

Parameters as printed in the papers (GHz; read on 2026-11-11 through ar5iv renderings, not from the PDFs):
  Zhang et al., PRX 11, 011010 (2021), arXiv:2002.10653: E_C = 0.479, E_L = 0.132, E_J = 3.395; f01 = 14 MHz at Φ₀/2.
  Moskalenko et al., npj Quantum Inf. 8, 130 (2022), arXiv:2203.16302, Table 1 (two-tone spectroscopy fit, one-mode
  parameters of a two-mode model): qubit A E_J = 2.052, E_C = 0.567, E_L = 0.835, f10 = 688.224 MHz, f12 = 1.832 GHz;
  qubit B 2.061 / 0.567 / 0.835, 664.763 MHz, 1.835 GHz; qubit S 1.989 / 0.564 / 0.858, 750.123 MHz, 1.803 GHz, all at Φ₀/2.
The shift between the one-mode H with their parameters and their measured lines is REPORTED, not judged: it measures
the model and the rounding of the printed parameters, not this package (whose test is: scqubits inside the intervals
at cutoff 110, outside at cutoff 6).
"""
import json
import sys
import time

import scqubits as sq

from rigorous_levels import fluxonium as F

sq.settings.PROGRESSBAR_DISABLED = True
DEVICES = [
    {"name": "Zhang 2021 (PRX 11, 011010)", "E_C": 0.479, "E_J": 3.395, "E_L": 0.132, "flux": 0.5, "measured_MHz": {"f01": 14.0}},
    {"name": "Moskalenko 2022 qubit A", "E_C": 0.567, "E_J": 2.052, "E_L": 0.835, "flux": 0.5, "measured_MHz": {"f01": 688.224, "f12": 1832.0}},
    {"name": "Moskalenko 2022 qubit B", "E_C": 0.567, "E_J": 2.061, "E_L": 0.835, "flux": 0.5, "measured_MHz": {"f01": 664.763, "f12": 1835.0}},
    {"name": "Moskalenko 2022 qubit S", "E_C": 0.564, "E_J": 1.989, "E_L": 0.858, "flux": 0.5, "measured_MHz": {"f01": 750.123, "f12": 1803.0}},
]


def main(out):
    rows = []
    for d in DEVICES:
        f = F.Fluxonium(E_C=d["E_C"], E_J=d["E_J"], E_L=d["E_L"], flux=d["flux"])
        t = time.perf_counter()
        iv = F.guaranteed_fluxonium_levels(f, 4, 1e-9, deadline=900)
        secs = time.perf_counter() - t
        res = {"device": d["name"], "state": iv.state, "N": iv.N, "max_width_GHz": iv.max_width, "seconds": round(secs, 2),
               "levels": [list(s) for s in iv.strings]}
        for key, (i, j) in {"f01": (0, 1), "f12": (1, 2)}.items():
            lo, hi = iv.transition(i, j)
            res[key + "_MHz"] = [float(lo) * 1e3, float(hi) * 1e3]
            if key in d["measured_MHz"]:
                res[key + "_measured_MHz"] = d["measured_MHz"][key]
                res[key + "_shift_MHz"] = d["measured_MHz"][key] - float((lo + hi) / 2) * 1e3
        for cutoff in (110, 6):
            e = sq.Fluxonium(EJ=d["E_J"], EC=d["E_C"], EL=d["E_L"], flux=d["flux"], cutoff=cutoff).eigenvals(evals_count=4)
            res[f"scqubits_cutoff_{cutoff}_inside"] = [bool(float(iv.low[k]) - 1e-8 <= e[k] <= float(iv.high[k]) + 1e-8) for k in range(4)]
            res[f"scqubits_cutoff_{cutoff}_levels"] = [float(x) for x in e]
        rows.append(res)
        print(json.dumps(res))
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"scqubits": sq.__version__, "devices": rows}, f, indent=1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1])
