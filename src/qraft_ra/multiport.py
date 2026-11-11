# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra/multiport.py — MULTIPORT: a closed, versioned interface ("qraft-port/0.2", docs/PORT_CONTRACT.md) through
which an EXTERNAL solver runs inside a sandbox and its result is compared with the guaranteed intervals.

Other people's code is untrusted by construction: it runs in a separate process inside one of the declared ISOLATION
ENGINES (closed list `ENGINES`), each with the same contract and the same positive controls (tests S1–S7):
  - "bwrap"  (Linux): `bwrap --unshare-all` (no network, new PID/IPC/UTS namespaces), ONLY /usr, /lib, /lib64, /bin,
             /etc, the declared site-packages and the pieces of an interpreter outside /usr mounted read-only; the
             real HOME is NOT mounted (HOME = tmpfs); writable only the single output file; `--clearenv` and a minimal
             environment for bwrap itself.
  - "podman", "docker" (Linux, macOS, Windows with a Linux container runtime): `run --network none --read-only
             --cap-drop ALL --security-opt no-new-privileges` as a non-root user, tmpfs /tmp, the declared
             site-packages and the work folder mounted read-only, the image taken ONLY from the local store (never
             pulled), a kill on timeout from the host. Before the first run a PROBE inside the same image checks that
             the container sees only the loopback interface, is not root and cannot write its root: if the engine is
             missing, the image is absent or the probe fails, nothing runs (`SandboxMissing`).
Inside every engine the runner sets its own rlimits (CPU, address space, file size, processes): on cgroups v1 rootless
podman the container's `--memory`/`--pids-limit` are ignored with a warning (measured 2026-11-11), so they are not
relied upon anywhere. FAIL-CLOSED: without a working engine `SandboxMissing`, no fallback (a silent fallback from a
sandbox to a plain subprocess is a vulnerability: CVE-2026-57144 in another product).
The output is a JSON validated against a CLOSED schema (unknown key, wrong type, NaN, length ≠ k, different unit or
contract = INVALID / NOT_COMPARABLE with the reason). Per-level verdict: INSIDE / INSIDE_TOLERANCE / OUTSIDE (with
the distance) / NOT_COMPARABLE (with the reason), in exact fractions.
Runner: qraft_ra/port_runner.py. Specification: docs/PORT_CONTRACT.md (written before the code).
What it is NOT: a certificate of the computation; a virtual machine; a judgement on the physics of the other solver.
QRAFT-RA is an internal model, not an external validator.
Names: this module was `multiporta` in 0.2.0 (deprecated aliases in that module); the contract "qraft-porta/0.1"
(Italian keys) is superseded by "qraft-port/0.2" and is no longer accepted."""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from qraft_ra import isolation
from qraft_ra._compat import add_field_aliases
from qraft_ra.guaranteed_intervals import Intervals, OutOfDomain
from qraft_ra.isolation import ENGINES, SandboxMissing  # noqa: F401

__all__ = ["CONTRACT", "PORTS", "ENGINES", "Request", "Output", "Verdict", "SandboxMissing", "run_port", "compare",
           "validate_output", "read_output", "OutOfDomain"]

CONTRACT = "qraft-port/0.2"
UNITS = {"GHz": Fraction(10 ** 9), "MHz": Fraction(10 ** 6), "Hz": Fraction(1)}
SECONDS_MAX, MEM_MIB_MAX, LEVELS_MAX = 3600, 65536, 10000       # declared caps (seconds 2**31 gave OverflowError)
OUTPUT_MAX_BYTES = 1 << 20                                      # the output is read for at most 1 MiB
OUTPUT_MAX_DEPTH = 32                                           # largest nesting of [ and { in the output
TMPFS_BYTES = isolation.TMPFS_BYTES                              # /tmp, /home, /dev/shm of the sandbox: RAM cap
JMAX_TLF = 20                                                   # tlf_centrex: J ≤ 20 = 1764 states, 0.4 s, 47 MiB
PORTS = ("numpy_rotor", "python_rotor", "test_wrong", "scqubits_transmon", "diatomic_py", "test_network", "test_write",
         "test_loop", "test_memory", "test_dirty_output", "test_hostile",
         "metal_hcpb", "metal_mathieu", "sqcircuit_transmon", "pyepr_fock", "centrex_tlf")
MODELS: Dict[str, Tuple[str, ...]] = {
    "cos_rotor": ("type", "E_C", "E_J", "n_g"),
    "sigma_molecule": ("type", "two_I1", "two_I2", "two_MF", "B", "D", "c1", "c2", "c3", "c4", "eQq1", "eQq2",
                       "z_N", "z1", "z2", "dE"),
    "tlf_centrex": ("type", "E_Vcm", "B_G", "Jmax", "two_MF"),      # constants = those of centrex-tlf (XConstants)
}
# ports of the public targets: CLOSED truncation (exact keys, integers ≥ 1) and a fixed model (unknown keys, 15.9 and
# "15" passed silently through int() in the runner before 2026-11-11). The older ports stay open (declared).
TRUNCATIONS: Dict[str, Tuple[str, ...]] = {"metal_hcpb": ("nlevels",), "metal_mathieu": (), "sqcircuit_transmon": ("ncut",),
                                           "pyepr_fock": ("cos_trunc", "fock_trunc"), "centrex_tlf": ()}
PORT_MODEL = {"metal_hcpb": "cos_rotor", "metal_mathieu": "cos_rotor", "sqcircuit_transmon": "cos_rotor",
              "pyepr_fock": "cos_rotor", "centrex_tlf": "tlf_centrex"}
OUTPUT_KEYS = ("contract", "port", "solver_version", "levels", "unit", "state", "reason", "seconds")
RUNNER = Path(__file__).resolve().parent / "port_runner.py"
RO_MOUNTS = isolation.RO_MOUNTS
def _finite(x) -> bool:
    """Finite real number (int or float, not bool), huge integers included: never an OverflowError."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    try:
        return math.isfinite(float(x))
    except OverflowError:
        return False


def _real(x, name):
    if not _finite(x):
        raise OutOfDomain(f"{name}: expected a finite real number")
    return float(x)


def _integer(x, name, minimum=None):
    if isinstance(x, bool) or not isinstance(x, int):
        raise OutOfDomain(f"{name}: expected an integer")
    if minimum is not None and x < minimum:
        raise OutOfDomain(f"{name}: expected >= {minimum}")
    return x


@dataclass(frozen=True)
class Request:
    port: str
    model: Dict[str, object]
    levels: int
    truncation: Dict[str, object]
    unit: str = "GHz"
    seconds: int = 60
    mem_mib: int = 1024
    site_packages: Tuple[str, ...] = ()

    def __post_init__(self):
        if self.port not in PORTS:
            raise OutOfDomain(f"port {self.port!r} not in the closed list {PORTS}")
        if not isinstance(self.model, dict) or not isinstance(self.model.get("type"), str) \
                or self.model.get("type") not in MODELS:
            raise OutOfDomain(f"model: type not in the closed list {tuple(MODELS)}")
        expected = MODELS[self.model["type"]]
        unknown = set(self.model) - set(expected)
        missing = set(expected) - set(self.model)
        if unknown or missing:
            raise OutOfDomain(f"model {self.model['type']}: unknown keys {sorted(unknown)}, missing {sorted(missing)}")
        for c in expected[1:]:
            if c.startswith("two_") or c == "Jmax":
                _integer(self.model[c], f"model.{c}")
            else:
                _real(self.model[c], f"model.{c}")
        if self.model["type"] == "tlf_centrex":       # sector and basis closed BEFORE the sandbox
            jm, dmf = self.model["Jmax"], self.model["two_MF"]
            if not 0 <= jm <= JMAX_TLF:
                raise OutOfDomain(f"model.Jmax: expected 0 <= Jmax <= {JMAX_TLF}")
            if dmf % 2 or abs(dmf) > 2 * jm + 2:
                raise OutOfDomain("model.two_MF: expected even (I1 = I2 = 1/2, integer J) with |M_F| <= Jmax + 1")
        _integer(self.levels, "levels", 1)
        if self.levels > LEVELS_MAX:
            raise OutOfDomain(f"levels: at most {LEVELS_MAX}")
        if not isinstance(self.truncation, dict) or not all(isinstance(k, str) for k in self.truncation):
            raise OutOfDomain("truncation: expected a dict with string keys")
        for k, v in self.truncation.items():
            if isinstance(v, bool) or not isinstance(v, (int, float, str)) or (isinstance(v, float) and not math.isfinite(v)):
                raise OutOfDomain(f"truncation.{k}: expected an int, a finite float or a string")
        if self.port in TRUNCATIONS:
            if self.model["type"] != PORT_MODEL[self.port]:
                raise OutOfDomain(f"port {self.port}: expected model {PORT_MODEL[self.port]!r}")
            if set(self.truncation) != set(TRUNCATIONS[self.port]):
                raise OutOfDomain(f"port {self.port}: truncation with exactly the keys {TRUNCATIONS[self.port]}")
            for k in TRUNCATIONS[self.port]:
                _integer(self.truncation[k], f"truncation.{k}", 1)
        if not isinstance(self.unit, str) or self.unit not in UNITS:
            raise OutOfDomain(f"unit: not in {tuple(UNITS)}")
        _integer(self.seconds, "seconds", 1)
        _integer(self.mem_mib, "mem_mib", 16)
        if self.seconds > SECONDS_MAX or self.mem_mib > MEM_MIB_MAX:
            raise OutOfDomain(f"limits: seconds ≤ {SECONDS_MAX}, mem_mib ≤ {MEM_MIB_MAX}")
        if not isinstance(self.site_packages, tuple) or not all(isinstance(p, str) and os.path.isdir(p) for p in self.site_packages):
            raise OutOfDomain("site_packages: expected a tuple of existing folders")
        # only site-/dist-packages folders (real path): a mounted user home would expose its hidden folders
        if not all(os.path.basename(os.path.realpath(p)) in ("site-packages", "dist-packages") for p in self.site_packages):
            raise OutOfDomain("site_packages: only site-packages or dist-packages folders are allowed")

    def json(self) -> Dict[str, object]:
        return {"contract": CONTRACT, "port": self.port, "model": dict(self.model), "levels": self.levels,
                "truncation": dict(self.truncation), "unit": self.unit,
                "limits": {"seconds": self.seconds, "mem_mib": self.mem_mib}, "site_packages": list(self.site_packages)}


@dataclass(frozen=True)
class Output:
    port: str
    solver_version: str
    levels: Tuple[float, ...]
    unit: str
    state: str            # OK | ERROR | INVALID
    reason: str
    seconds: float
    sandbox: str


def validate_output(doc: object, r: Request) -> Tuple[Optional[Output], str]:
    """CLOSED schema: (Output, "") if valid, (None, reason) otherwise. No unknown key passes."""
    if not isinstance(doc, dict):
        return None, "output is not a JSON object"
    unknown = set(doc) - set(OUTPUT_KEYS)
    missing = set(OUTPUT_KEYS) - set(doc)
    if unknown or missing:
        return None, f"unknown keys {sorted(unknown)}, missing {sorted(missing)}"
    if doc["contract"] != CONTRACT:
        return None, f"contract {doc['contract']!r} ≠ {CONTRACT}"
    if doc["port"] != r.port:
        return None, f"port {doc['port']!r} ≠ {r.port!r}"
    for c in ("solver_version", "reason", "state", "unit"):
        if not isinstance(doc[c], str):
            return None, f"{c}: expected a string"
    if doc["state"] not in ("OK", "ERROR"):
        return None, f"state {doc['state']!r} not in (OK, ERROR)"
    if doc["unit"] not in UNITS:
        return None, f"unit {doc['unit']!r} not in {tuple(UNITS)}"
    if not _finite(doc["seconds"]):
        return None, "seconds: expected a finite number"
    lev = doc["levels"]
    if not isinstance(lev, list):
        return None, "levels: expected a list"
    if doc["state"] == "OK":
        if len(lev) != r.levels:
            return None, f"levels: {len(lev)} values, expected {r.levels}"
        for x in lev:
            if not _finite(x):
                return None, "levels: expected finite real numbers"
    else:
        lev = []                       # ERROR: the levels are not needed and are not converted (never an exception)
    return Output(doc["port"], doc["solver_version"], tuple(float(x) for x in lev), doc["unit"], doc["state"],
                  doc["reason"], float(doc["seconds"]), ""), ""


def _no_dup(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError(f"duplicate key {k!r}")
        d[k] = v
    return d


def _no_constant(name):
    raise ValueError(f"non-JSON constant {name}")


def _json_depth(text: str, limit: int) -> int:
    """Largest nesting of [ and { outside JSON strings, in one linear pass without recursion or regex; it stops as
    soon as it exceeds `limit`. A malformed text gives some number: the parser then rejects it."""
    p = m = 0
    in_string = escape = False
    for ch in text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "[" or ch == "{":
            p += 1
            if p > m:
                m = p
                if m > limit:
                    return m
        elif ch == "]" or ch == "}":
            p -= 1
    return m


def read_output(path: str) -> Tuple[Optional[object], str]:
    """Reads output.json as a REGULAR file (O_NOFOLLOW), at most OUTPUT_MAX_BYTES, strict JSON: no NaN/Infinity, no
    duplicate keys, nesting at most OUTPUT_MAX_DEPTH levels, counted BEFORE the parser (the parser's recursion limit
    changes between Python versions: on CPython 3.14.10 an object nested 100 000 times passed).
    (doc, "") or (None, reason)."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError as e:
        return None, f"no readable output: {type(e).__name__}"
    try:
        import stat as _stat
        if not _stat.S_ISREG(os.fstat(fd).st_mode):
            return None, "output is not a regular file"
        with os.fdopen(fd, "rb") as f:
            fd = -1
            data = f.read(OUTPUT_MAX_BYTES + 1)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(data) > OUTPUT_MAX_BYTES:
        return None, f"output over {OUTPUT_MAX_BYTES} bytes"
    try:
        text = data.decode("utf-8")
        if _json_depth(text, OUTPUT_MAX_DEPTH) > OUTPUT_MAX_DEPTH:
            return None, f"output nested beyond {OUTPUT_MAX_DEPTH} levels"
        return json.loads(text, object_pairs_hook=_no_dup, parse_constant=_no_constant), ""
    except (ValueError, RecursionError) as e:
        return None, f"output not JSON: {type(e).__name__}: {str(e)[:200]}"


def run_port(r: Request, python: Optional[str] = None, *, engine: str = "auto", image: Optional[str] = None) -> Output:
    """Runs the port inside an isolation engine and returns the validated Output (state INVALID with the reason if
    the schema fails, the process was killed or wrote no JSON). Never an exception for a defect of the external code.
    `engine`: "auto" (the strongest available, docs/PORT_CONTRACT.md §6.0) or one of ENGINES; the one used is named in
    `Output.sandbox`. `python` (bwrap, sandbox-exec, appcontainer): the interpreter to run, by default the current one.
    `image` (containers): a LOCAL image, by default python:<major>.<minor>-slim of the current interpreter."""
    if not isinstance(r, Request):
        raise OutOfDomain("expected a Request")
    if engine not in ENGINES:
        raise OutOfDomain(f"engine {engine!r} not in the closed list {ENGINES}")
    if engine == "auto":
        engine, _ = isolation.select_engine(image)
    else:
        isolation.probe(engine, image)                 # fail-closed before anything is written
    work = tempfile.mkdtemp(prefix="qraft_port_")
    outdir = tempfile.mkdtemp(prefix="qraft_out_")
    try:
        with open(os.path.join(work, "request.json"), "w", encoding="utf-8") as f:
            json.dump(r.json(), f)
        shutil.copy(RUNNER, os.path.join(work, isolation.RUNNER_NAME))
        out_path = os.path.join(outdir, "output.json")
        open(out_path, "wb").close()               # the ONLY writable file of the port
        open(os.path.join(work, "output.json"), "wb").close()   # mount point for the engines that bind the file
        rc, timed_out, descr = isolation.run(engine, work, out_path, r.seconds, r.mem_mib, list(r.site_packages),
                                             python, image)
        descr = f"{engine}: {descr}"
        if timed_out:
            return _invalid(r, f"timeout: over {r.seconds + 5} s", float(r.seconds + 5), descr)
        err_path = os.path.join(work, "stderr.txt")
        tail = ""
        if os.path.isfile(err_path):
            with open(err_path, "rb") as ferr:
                ferr.seek(max(0, os.path.getsize(err_path) - 600))
                tail = ferr.read().decode("utf-8", "replace")
        if os.path.getsize(out_path) == 0:
            return _invalid(r, f"no output (exit code {rc}): {tail}", 0.0, descr)
        doc, reason = read_output(out_path)
        if doc is None:
            return _invalid(r, reason, 0.0, descr)
        u, reason = validate_output(doc, r)
        if u is None:
            return _invalid(r, f"schema: {reason}", 0.0, descr)
        if u.state == "OK" and rc != 0:      # specification §3.2: exit code ≠ 0 → not comparable
            return _invalid(r, f"state OK but exit code {rc}: {tail}", 0.0, descr)
        return Output(u.port, u.solver_version, u.levels, u.unit, u.state, u.reason, u.seconds, descr)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(outdir, ignore_errors=True)


def _invalid(r: Request, reason: str, seconds: float, descr: str) -> Output:
    return Output(r.port, "", (), r.unit, "INVALID", reason, seconds, descr)


@dataclass(frozen=True)
class Verdict:
    overall: str                                  # INSIDE | INSIDE_TOLERANCE | OUTSIDE | NOT_COMPARABLE
    per_level: Tuple[Tuple[str, str], ...]        # (INSIDE|INSIDE_TOLERANCE|OUTSIDE, distance)
    reason: str


def compare(iv: Intervals, intervals_unit: str, u: Output, tolerance: float = 0.0) -> Verdict:
    """Exact comparison (Fraction): E_j of the output converted to the unit of the intervals with factors 10^n.
    `tolerance` (same unit as the intervals, ≥ 0, default 0) is the noise DECLARED by the caller for the float solver
    (eigvalsh: ~eps·‖H‖, measured 1e-13 GHz at ncut 30): a level outside by less is INSIDE_TOLERANCE, with the
    distance; beyond it is OUTSIDE. Closed list of verdicts."""
    if not isinstance(iv, Intervals):
        raise OutOfDomain("expected Intervals")
    if intervals_unit not in UNITS:
        raise OutOfDomain(f"intervals_unit: not in {tuple(UNITS)}")
    if not isinstance(u, Output):
        raise OutOfDomain("expected an Output")
    tol = Fraction(_real(tolerance, "tolerance"))
    if tol < 0:
        raise OutOfDomain("tolerance: expected >= 0")
    if u.state != "OK":
        return Verdict("NOT_COMPARABLE", (), f"output {u.state}: {u.reason}")
    if u.unit not in UNITS or not all(_finite(x) for x in u.levels):
        raise OutOfDomain("Output OK with an unknown unit or non-finite levels")
    k = len(u.levels)
    if k == 0:
        return Verdict("NOT_COMPARABLE", (), "no level")
    if k != len(iv.low):                            # never an INSIDE on a part of the levels without saying so
        return Verdict("NOT_COMPARABLE", (), f"levels of the output {k} ≠ intervals {len(iv.low)}")
    factor = UNITS[u.unit] / UNITS[intervals_unit]
    rows: List[Tuple[str, str]] = []
    for j in range(k):
        e = Fraction(u.levels[j]) * factor
        if iv.low[j] <= e <= iv.high[j]:
            rows.append(("INSIDE", "0"))
        else:
            d = iv.low[j] - e if e < iv.low[j] else e - iv.high[j]
            rows.append(("INSIDE_TOLERANCE" if d <= tol else "OUTSIDE", f"{float(d):.6e} {intervals_unit}"))
    states = {s for s, _ in rows}
    overall = "OUTSIDE" if "OUTSIDE" in states else ("INSIDE_TOLERANCE" if "INSIDE_TOLERANCE" in states else "INSIDE")
    return Verdict(overall, tuple(rows), f"{k} levels compared, intervals {iv.state} (max width {iv.max_width:.3e})")


# deprecated Italian field names of 0.2.0 (DeprecationWarning on use; removed in a later release)
add_field_aliases(Request, {"porta": "port", "modello": "model", "livelli": "levels", "troncamento": "truncation",
                            "unita": "unit", "secondi": "seconds"})
add_field_aliases(Output, {"porta": "port", "versione_solutore": "solver_version", "livelli": "levels", "unita": "unit",
                           "stato": "state", "motivo": "reason", "secondi": "seconds"})
add_field_aliases(Verdict, {"complessivo": "overall", "per_livello": "per_level", "motivo": "reason"})
