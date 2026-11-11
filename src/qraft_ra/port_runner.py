# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra/port_runner.py — runner of the PORTS of the multiport: it runs INSIDE the sandbox (bwrap, podman, docker),
never in the process of QRAFT-RA. Reads <folder>/request.json, runs the port (closed list), writes <folder>/output.json.
Specification: docs/PORT_CONTRACT.md (contract "qraft-port/0.2").
The `test_*` ports exist ONLY for the positive controls of the sandbox (network, writes, time, memory, dirty output,
wrong solver, hostile behaviour). None of them is a solver.
This file imports nothing from QRAFT-RA: it is self-contained (numpy and the solvers come from the declared
site-packages)."""
import json
import math
import os
import sys
import time
import traceback

try:
    import resource                 # absent on Windows and under WASI: there the engine carries the limits
except ImportError:                 # pragma: no cover
    resource = None
try:
    import socket                   # the WASI build has the module; AF_INET connections fail there by construction
except ImportError:                 # pragma: no cover
    socket = None

CONTRACT = "qraft-port/0.2"
H_PLANCK = 6.62607015e-34


def _output_dir(folder: str) -> str:
    """Where output.json goes: the work folder (bwrap, containers bind the file there) or QRAFT_OUTPUT_DIR (engines
    that cannot bind a single file into a read-only folder: sandbox-exec, appcontainer, wasm)."""
    return os.environ.get("QRAFT_OUTPUT_DIR") or folder


def _rlimit(seconds: int, mem_mib: int) -> None:
    if resource is None:
        return
    resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds))
    resource.setrlimit(resource.RLIMIT_AS, (mem_mib * 1024 * 1024, mem_mib * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024, 64 * 1024 * 1024))
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (16, 16))
    except (ValueError, OSError):
        pass


def _numpy_rotor(model: dict, k: int, ncut: int):
    import numpy as np
    EC, EJ, ng = model["E_C"], model["E_J"], model["n_g"]
    n = np.arange(-ncut, ncut + 1)
    H = np.diag(4.0 * EC * (n - ng) ** 2) - 0.5 * EJ * (np.eye(2 * ncut + 1, k=1) + np.eye(2 * ncut + 1, k=-1))
    return [float(x) for x in np.linalg.eigvalsh(H)[:k]]


def port_numpy_rotor(r):
    return _numpy_rotor(r["model"], r["levels"], int(r["truncation"]["ncut"])), "numpy"


def _python_rotor(model: dict, k: int, ncut: int):
    """The same tridiagonal in pure Python (no numpy, so it runs under WASI too): the k lowest eigenvalues by
    bisection on the Sturm count (Barth–Martin–Wilkinson 1967), float64, to about 1e-13 relative."""
    EC, EJ, ng = model["E_C"], model["E_J"], model["n_g"]
    diag = [4.0 * EC * (n - ng) ** 2 for n in range(-ncut, ncut + 1)]
    off2 = (0.5 * EJ) ** 2
    n = len(diag)

    def count(x):
        c, d = 0, 1.0
        for i in range(n):
            d = diag[i] - x - (off2 / d if i else 0.0)
            if d == 0.0:
                d = 1e-300
            if d < 0:
                c += 1
        return c
    bound = max(abs(v) for v in diag) + abs(EJ) + 1.0
    out = []
    for j in range(k):
        lo, hi = -bound, bound
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if count(mid) >= j + 1:
                hi = mid
            else:
                lo = mid
            if hi - lo <= 1e-14 * max(1.0, abs(mid)):
                break
        out.append(0.5 * (lo + hi))
    return out


def port_python_rotor(r):
    return _python_rotor(r["model"], r["levels"], int(r["truncation"]["ncut"])), "pure Python (Sturm bisection)"


def port_test_wrong(r):
    """Deliberately wrong solver: truncation ncut = 3 and levels shifted by +1e-3 (pure Python: runs everywhere)."""
    return [x + 1e-3 for x in _python_rotor(r["model"], r["levels"], 3)], "python ncut 3 + 1e-3"


def port_scqubits_transmon(r):
    import scqubits
    m = r["model"]
    t = scqubits.Transmon(EJ=m["E_J"], EC=m["E_C"], ng=m["n_g"], ncut=int(r["truncation"]["ncut"]))
    return [float(x) for x in t.eigenvals(evals_count=r["levels"])], f"scqubits {scqubits.__version__}"


def port_diatomic_py(r):
    """¹Σ molecule through diatomic-py 2.1.0 in the requested M_F sector. Maps c3 → −c3: the diatomic-py code uses
    +√6 c3 T²(C)·T²(I1,I2), its paper (eq. 5b), Aldegunde 2008 and Gregory 2016 the opposite sign
    (durham-qlm/diatomic-py #15): the port declares it in the field solver_version."""
    import numpy as np
    from diatomic import operators as op
    from diatomic.systems import SingletSigmaMolecule
    import importlib.metadata
    m = r["model"]
    h = H_PLANCK
    mol = SingletSigmaMolecule(Ii=(m["two_I1"] / 2, m["two_I2"] / 2), Nmax=int(r["truncation"]["N_max"]),
                               Brot=m["B"] * h, Drot=m["D"] * h, Ci=(m["c1"] * h, m["c2"] * h), C4=m["c4"] * h,
                               C3=-m["c3"] * h, Qi=(m["eQq1"] * h, m["eQq2"] * h), d0=1.0, MuN=1.0, Mui=(1.0, 1.0))
    if m["two_I1"] % 2 == 0:
        mol.Ii = (m["two_I1"] // 2, mol.Ii[1])
    if m["two_I2"] % 2 == 0:
        mol.Ii = (mol.Ii[0], m["two_I2"] // 2)
    H = op.hyperfine_ham(mol) / h
    N_vec, I1_vec, I2_vec = op.generate_vecs(mol.Nmax, mol.Ii[0], mol.Ii[1])
    H = H - (m["z_N"] * N_vec[2] + m["z1"] * I1_vec[2] + m["z2"] * I2_vec[2])
    if m["dE"] != 0.0:
        H = H - m["dE"] * op.expanded_unit_dipole_operator(mol, 0)
    H = np.asarray(H).real
    basis = list(op.uncoupled_basis_iter(mol.Nmax, mol.Ii[0], mol.Ii[1]))
    ii = [i for i, (N, MN, M1, M2) in enumerate(basis) if int(round(2 * (float(MN) + float(M1) + float(M2)))) == m["two_MF"]]
    ev = np.linalg.eigvalsh(H[np.ix_(ii, ii)])[:r["levels"]]
    return [float(x) for x in ev], f"diatomic-py {importlib.metadata.version('diatomic-py')} (c3 → −c3)"


def port_test_network(r):
    """Tries a TCP connection to the given port on 127.0.0.1: outside the sandbox it succeeds, inside it must fail."""
    if socket is None:
        raise RuntimeError("network blocked: no socket module")
    try:
        with socket.create_connection(("127.0.0.1", int(r["truncation"]["tcp_port"])), timeout=2):
            pass
    except (OSError, ValueError, NotImplementedError, AttributeError) as e:    # AttributeError: WASI's _socket
        raise RuntimeError(f"network blocked: {type(e).__name__}: {e}")
    return _numpy_rotor(r["model"], r["levels"], 30), "network REACHED"


def port_test_write(r):
    """Tries to write in HOME and at the given path, and to see the user's real home: reports what succeeded."""
    results = []
    for p in (os.path.join(os.environ.get("HOME", "/nonexistent"), "qraft_port_test.txt"), r["truncation"]["path"]):
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write("test")
            results.append(f"WRITTEN {p}")
        except OSError as e:
            results.append(f"blocked {p}: {type(e).__name__}")
    results.append("real_home_visible=" + str(os.path.isdir(r["truncation"]["real_home"])))
    results.append(f"pid={os.getpid()}")                       # new PID namespace: a small pid
    raise RuntimeError("; ".join(results))


def port_test_loop(r):
    while True:
        time.sleep(0.01)


def port_test_memory(r):
    """Allocates and touches `mib` MiB with a bytearray (no numpy: runs under WASI too)."""
    try:
        a = bytearray(int(r["truncation"]["mib"]) * 1024 * 1024)
    except OverflowError:                 # a 32-bit address space (wasm32) cannot even index the request
        raise MemoryError("allocation beyond the address space")
    a[::65536] = b"\x01" * len(a[::65536])
    return [float(sum(a[::65536]))], "memory ALLOCATED"


def port_test_hostile(r):
    """Positive controls (mode in truncation.mode): reads the environment of every visible process, replaces
    output.json with a symlink, fills the disk, writes OK and then kills itself, forks, burns CPU, floods stdout."""
    t = r["truncation"]
    mode = t["mode"]
    if mode == "environment":
        name = t["name"].encode()
        seen = []
        try:
            pids = [x for x in os.listdir("/proc") if x.isdigit()]
        except OSError:                      # no /proc (WASI): nothing to read, which is the point
            pids = []
        for pid in pids:
            try:
                with open(f"/proc/{pid}/environ", "rb") as f:
                    if any(v.split(b"=")[0] == name for v in f.read().split(b"\0")):
                        seen.append(pid)
            except OSError:
                pass
        if name.decode() in os.environ:
            seen.append("os.environ")
        raise RuntimeError(f"environment: {t['name']} seen in {seen}")
    if mode == "symlink":
        try:
            os.unlink(os.path.join(_output_dir(sys.argv[1]), "output.json"))
            os.symlink(t["target"], os.path.join(_output_dir(sys.argv[1]), "output.json"))
            result = "symlink DONE"
        except OSError as e:
            result = f"symlink blocked: {type(e).__name__}"
        raise RuntimeError(result)
    if mode == "disk":
        written = 0
        for i in range(int(t["files"])):
            try:
                with open(os.path.join(t["where"], f"f{i}"), "wb") as f:
                    for _ in range(int(t["mib"])):
                        f.write(b"\0" * 1048576)
                        written += 1
            except OSError as e:
                raise RuntimeError(f"disk: {written} MiB then {type(e).__name__}")
        raise RuntimeError(f"disk: {written} MiB written")
    if mode == "write":
        try:
            with open(t["path"], "w", encoding="utf-8") as f:
                f.write("x")
            raise RuntimeError(f"write: WRITTEN {t['path']}")
        except OSError as e:
            raise RuntimeError(f"write: blocked {type(e).__name__}")
    if mode == "fork":
        n = 0
        if not hasattr(os, "fork"):
            raise RuntimeError("fork: 0")                 # no fork on this platform (WASI, Windows)
        try:
            for _ in range(64):
                if os.fork() == 0:
                    time.sleep(3)
                    os._exit(0)
                n += 1
        except OSError:
            pass
        raise RuntimeError(f"fork: {n}")
    if mode == "cpu":
        while True:
            pass
    if mode == "stdout":
        block = "x" * 1048576
        for _ in range(int(t["mib"])):
            sys.stdout.write(block)
        sys.stdout.flush()
        raise RuntimeError("stdout written")
    if mode == "ok_then_crash":
        with open(os.path.join(_output_dir(sys.argv[1]), "output.json"), "w", encoding="utf-8") as f:
            json.dump({"contract": CONTRACT, "port": r["port"], "solver_version": "x", "levels": [0.0] * r["levels"],
                       "unit": r["unit"], "state": "OK", "reason": "", "seconds": 0.0}, f)
        if hasattr(os, "kill"):
            os.kill(os.getpid(), 9)                  # ignored when the runner is PID 1 (containers): then _exit
        os._exit(137)
    raise RuntimeError(f"mode {mode!r} unknown")


def port_test_dirty_output(r):
    out = _python_rotor(r["model"], r["levels"], 30)
    return out, "dirty", {"unknown_key": 1}


# ── ports of the public targets (2026-11-11) ────────────────────────────────────────────────────────────────────
def port_metal_hcpb(r):
    """qiskit-metal Hcpb (transmon_charge_basis.py, read from their repository, mounted read-only): eigh_tridiagonal on
    4E_C(n−n_g)² − (E_J/2)(|n⟩⟨n+1| + h.c.), n ∈ [−nlevels, nlevels+1]."""
    import transmon_charge_basis as tcb
    m = r["model"]
    h = tcb.Hcpb(nlevels=int(r["truncation"]["nlevels"]), Ej=m["E_J"], Ec=m["E_C"], ng=m["n_g"])
    return [float(x) for x in h.evals[:r["levels"]]], "qiskit-metal Hcpb (transmon_charge_basis.py, repo HEAD 2026-11-11)"


def port_metal_mathieu(r):
    """qiskit-metal transmon_CPB_analytic.mathieu_level(m, n_g, E_J, E_C): Mathieu characteristic values (scipy)."""
    import transmon_CPB_analytic as tca
    m = r["model"]
    out = [float(tca.mathieu_level(j, m["n_g"], m["E_J"], m["E_C"])) for j in range(r["levels"])]
    return out, "qiskit-metal mathieu_level (transmon_CPB_analytic.py, repo HEAD 2026-11-11)"


def port_sqcircuit_transmon(r):
    """SQcircuit: one capacitor + one junction. E_C passed to SQcircuit IN GHz (its own constants e, ħ: units.py) and
    the junction's own capacitance subtracted (VerySmallCap = 1e-20 F, elements.py:235-238 and :489-490), so that the
    TOTAL capacitance seen by SQcircuit gives exactly E_C (the shift 2.8e-7…1.3e-6 GHz came for 88 % from those
    1e-20 F and for 12 % from the truncated constants)."""
    import importlib.metadata
    import SQcircuit as sq
    m = r["model"]
    sq.set_unit_cap("fF")
    sq.set_unit_JJ("GHz")
    sq.set_unit_freq("GHz")
    junction = sq.Junction(value=m["E_J"], unit="GHz")
    c_tot = float(sq.Capacitor(value=m["E_C"], unit="GHz").get_value("F"))
    c_shunt = c_tot - float(junction.cap.get_value("F"))
    if not c_shunt > 0:
        raise ValueError("E_C too large: the junction's own capacitance exceeds the total one")
    circ = sq.Circuit({(0, 1): [sq.Capacitor(value=c_shunt, unit="F"), junction]})
    circ.set_trunc_nums([int(r["truncation"]["ncut"])])
    circ.set_charge_offset(1, m["n_g"])
    efreqs, _ = circ.diag(n_eig=r["levels"])
    return [float(x) for x in efreqs], (f"SQcircuit {importlib.metadata.version('SQcircuit')} "
                                        f"(C shunt = {c_shunt * 1e15:.9f} fF + junction {float(junction.cap.get_value('F')):.1e} F)")


def port_pyepr_fock(r):
    """pyEPR black_box_hamiltonian: one mode, f_lin = √(8E_JE_C), L_J = (Φ₀/2π)²/E_J, φ_zpf = (2E_C/E_J)^¼; cosine
    Taylor-expanded to cos_trunc (without 1 − φ²/2) on Fock fock_trunc. Levels read AS pyEPR does (make_dispersive):
    for the Fock state j the eigenstate of largest overlap, not the k lowest eigenvalues (with a large fock_trunc the
    basis reaches the neighbouring wells φ ≈ ±2π of the NON-compact phase and the lowest ones are spurious states
    with ⟨n⟩ ≈ 22). The non-compact phase does not represent n_g: n_g ≠ 0 → error with the reason (never silently
    ignored). Output in GHz, the constant and φ² excluded from their model: compare the TRANSITIONS."""
    import importlib.metadata
    import numpy as np
    from pyEPR.calcs.back_box_numeric import black_box_hamiltonian
    from pyEPR.calcs.constants import fluxQ
    m = r["model"]
    if m["n_g"] != 0:
        raise ValueError("pyEPR (non-compact phase, Fock basis) does not represent n_g: n_g = 0 required")
    h = 6.62607015e-34
    EJ, EC = m["E_J"] * 1e9, m["E_C"] * 1e9                       # Hz
    f_lin = (8.0 * EJ * EC) ** 0.5
    Lj = fluxQ ** 2 / (EJ * h)
    phi_zpf = (2.0 * EC / EJ) ** 0.25
    H = black_box_hamiltonian([f_lin], [Lj], [[fluxQ * phi_zpf]], cos_trunc=int(r["truncation"]["cos_trunc"]),
                              fock_trunc=int(r["truncation"]["fock_trunc"]))
    w, V = np.linalg.eigh(H.full())
    k = r["levels"]
    if k > V.shape[0]:
        raise ValueError("levels requested beyond fock_trunc")
    chosen = [int(np.argmax(np.abs(V[j, :]) ** 2)) for j in range(k)]
    if len(set(chosen)) != k:
        raise ValueError(f"ambiguous assignment by overlap: {chosen}")
    return [float(w[i]) / 1e9 for i in chosen], (f"pyEPR {importlib.metadata.version('pyEPR-quantum')} "
                                                 "black_box_hamiltonian (levels by overlap with the Fock state)")


def port_centrex_tlf(r):
    """CeNTREX-TlF: H of the X state in the uncoupled basis (Hff + E·HS + B·HZ, fields along z), sector M_F."""
    import importlib.metadata
    import numpy as np
    from centrex_tlf.hamiltonian import (generate_uncoupled_hamiltonian_X,
                                         generate_uncoupled_hamiltonian_X_function)
    from centrex_tlf.states import generate_uncoupled_states_ground
    m = r["model"]
    QN = generate_uncoupled_states_ground(Js=np.arange(0, int(m["Jmax"]) + 1))
    Hf = generate_uncoupled_hamiltonian_X_function(generate_uncoupled_hamiltonian_X(QN))
    M = Hf(np.array([0.0, 0.0, m["E_Vcm"]]), np.array([0.0, 0.0, m["B_G"]])) / (2 * np.pi)      # rad/s → Hz
    ii = [i for i, s in enumerate(QN) if int(round(2 * (s.mJ + s.m1 + s.m2))) == m["two_MF"]]
    sub = M[np.ix_(ii, ii)]
    if np.abs(sub.imag).max() > 1e-6 * max(1.0, np.abs(sub).max()):
        raise RuntimeError("non-negligible imaginary part in the sector")
    ev = np.linalg.eigvalsh(sub.real)[:r["levels"]]
    return [float(x) for x in ev], f"centrex-tlf {importlib.metadata.version('centrex-tlf')} (sector 2M_F = {m['two_MF']}, J ≤ {m['Jmax']})"


PORTS = {
    "numpy_rotor": port_numpy_rotor,
    "python_rotor": port_python_rotor,
    "test_wrong": port_test_wrong,
    "scqubits_transmon": port_scqubits_transmon,
    "diatomic_py": port_diatomic_py,
    "test_network": port_test_network,
    "test_write": port_test_write,
    "test_loop": port_test_loop,
    "test_memory": port_test_memory,
    "test_dirty_output": port_test_dirty_output,
    "test_hostile": port_test_hostile,
    "metal_hcpb": port_metal_hcpb,
    "metal_mathieu": port_metal_mathieu,
    "sqcircuit_transmon": port_sqcircuit_transmon,
    "pyepr_fock": port_pyepr_fock,
    "centrex_tlf": port_centrex_tlf,
}


def main(folder: str) -> int:
    t0 = time.time()
    for v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(v, "1")               # before numpy: BLAS threads under RLIMIT_AS fail (SIGINT)
    with open(os.path.join(folder, "request.json"), encoding="utf-8") as f:
        r = json.load(f)
    output = {"contract": CONTRACT, "port": r.get("port"), "solver_version": "", "levels": [],
              "unit": r.get("unit"), "state": "ERROR", "reason": "", "seconds": 0.0}
    try:
        if r.get("contract") != CONTRACT:
            raise RuntimeError(f"contract {r.get('contract')!r} is not {CONTRACT}")
        _rlimit(int(r["limits"]["seconds"]), int(r["limits"]["mem_mib"]))
        for sp in r.get("site_packages", []):
            sys.path.insert(0, sp)
        fn = PORTS.get(r["port"])
        if fn is None:
            raise RuntimeError(f"port {r['port']!r} not in the closed list")
        res = fn(r)
        levels, version = res[0], res[1]
        if len(res) > 2:
            output.update(res[2])
        if any(not math.isfinite(x) for x in levels):
            raise RuntimeError("levels not finite")
        output.update(levels=levels, solver_version=version, state="OK")
    except BaseException as e:  # noqa: BLE001 — whatever happens, the output is a JSON with the reason
        tb = traceback.format_exc().strip().splitlines()
        output["reason"] = (f"{type(e).__name__}: {e}" + (" | " + " / ".join(tb[-3:-1]) if not isinstance(e, RuntimeError) else ""))[:600]
    output["seconds"] = round(time.time() - t0, 3)
    with open(os.path.join(_output_dir(folder), "output.json"), "w", encoding="utf-8") as f:
        json.dump(output, f)
    return 0 if output["state"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
