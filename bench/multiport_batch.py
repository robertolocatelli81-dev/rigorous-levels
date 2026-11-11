# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Multiport batches (docs/PORT_CONTRACT.md §8): 100 transmon cases through `python_rotor` and `numpy_rotor` in ONE
sandbox process (`run_ports`) against 10 single runs (`run_port`), on the strongest engine available.

    python bench/multiport_batch.py OUT.json

Reports the seconds per case of the batch, the seconds per single run, and that every batch output equals the
single-run output of the same request (same levels). The README claim is "< 0.5 s per case on 100 cases"."""
import json
import os
import site
import sys
import sysconfig
import time

import numpy as np

from qraft_ra import Request, run_port, run_ports
from qraft_ra.isolation import select_engine

SITE = tuple(p for p in (sysconfig.get_path("purelib"), site.getusersitepackages()) if p and os.path.isdir(p))


def cases():
    rng = np.random.default_rng(20261108)
    out = []
    for _ in range(100):
        ec = float(rng.uniform(0.05, 1.0))
        rap = float(10 ** rng.uniform(0, 3))
        ng = float(rng.uniform(0, 1))
        out.append({"type": "cos_rotor", "E_C": ec, "E_J": ec * rap, "n_g": ng})
    return out


def main(out):
    engine, _ = select_engine()
    doc = {"engine": engine, "ports": {}}
    for port in ("python_rotor", "numpy_rotor"):
        reqs = [Request(port, m, 6, {"ncut": 30}, seconds=30, site_packages=SITE) for m in cases()]
        t = time.perf_counter()
        outs = run_ports(reqs, engine=engine)
        batch = time.perf_counter() - t
        t = time.perf_counter()
        singles = [run_port(r, engine=engine) for r in reqs[:10]]
        single = (time.perf_counter() - t) / 10
        ok = sum(u.state == "OK" for u in outs)
        same = sum(u.levels == s.levels for u, s in zip(outs[:10], singles))
        doc["ports"][port] = {"cases": len(reqs), "batch_seconds_total": batch, "batch_seconds_per_case": batch / len(reqs),
                              "single_seconds_per_case": single, "ok": ok, "equal_to_single_runs": f"{same} of 10"}
        print(port, json.dumps(doc["ports"][port]))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1])
