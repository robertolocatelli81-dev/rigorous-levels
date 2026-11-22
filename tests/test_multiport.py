# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Test di rigorous_levels/multiport.py + rigorous_levels/port_runner.py (10/11/2026). Specifica: note dell'autore (non pubblicate).
Controlli positivi S1-S7 della specifica: ognuno deve POTER fallire (il runner fuori sandbox fa ciò che dentro è bloccato)."""
import importlib.util
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest


from rigorous_levels import multiport as MP  # noqa: E402

FLINT = importlib.util.find_spec("flint") is not None


def _engines_available():
    """The engines whose fail-closed probe passes on this machine: the sandbox tests run once per engine and are
    SKIPPED with the probe's reason otherwise (bwrap needs user namespaces; containers need the local image;
    sandbox-exec needs macOS; appcontainer needs Windows; wasm needs wasmtime + RIGOROUS_LEVELS_PYTHON_WASM)."""
    from rigorous_levels import isolation
    ok, why = [], {}
    for e in isolation.ENGINE_ORDER:
        try:
            isolation.probe(e)
            ok.append(e)
        except (isolation.SandboxMissing, MP.OutOfDomain) as err:
            why[e] = str(err)[:160]
    return ok, why


ENGINES_OK, ENGINES_WHY = _engines_available()
BWRAP = "bwrap" in ENGINES_OK
NUMPY_ENGINES = [e for e in ENGINES_OK if e != "wasm"]      # wasm: CPython for WASI has no numpy (measured 2026-11-11)
import sysconfig  # noqa: E402

import site  # noqa: E402

# il venv di prova prende matplotlib (richiesto da scqubits) dal site user: entrambi dichiarati, in sola lettura
SITE = tuple(p for p in (sysconfig.get_path("purelib"), site.getusersitepackages()) if os.path.isdir(p))
ROTOR = {"type": "cos_rotor", "E_C": 0.3, "E_J": 15.0, "n_g": 0.25}


def request(port="numpy_rotor", **kw):
    base = dict(port=port, model=ROTOR, levels=6, truncation={"ncut": 30}, unit="GHz", seconds=20,
                mem_mib=1024, site_packages=SITE)
    base.update(kw)
    return MP.Request(**base)


# engines that run on host paths (no /work, /tmp of their own): the disk controls use the runner's $WORK and $TMP
HOST_PATH_ENGINES = ("sandbox-exec", "appcontainer")
# Windows: a process without these cannot start its socket layer (WinError 10106 without SYSTEMROOT, CI 2026-11-12)
WINDOWS_SYSTEM_ENV = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT")


def runner_direct(r, timeout=30):
    """Esegue il runner SENZA sandbox (solo nei test, come check positivo): ciò che qui riesce, dentro deve fallire.
    RIGOROUS_LEVELS_HOST_LIMITS=memory: fuori dalla sandbox nessuno impone la memoria, e macOS rifiuta RLIMIT_AS."""
    work = tempfile.mkdtemp(prefix="rigorous_levels_port_direct_")
    home = tempfile.mkdtemp(prefix="home_prova_")          # removed below with the work folder (21/11: left behind)
    try:
        with open(os.path.join(work, "request.json"), "w") as f:
            json.dump(r.json(), f)
        env = {"PATH": os.environ.get("PATH", ""), "HOME": home, "RIGOROUS_LEVELS_HOST_LIMITS": "memory"}
        if os.name == "nt":
            env.update({k: os.environ[k] for k in WINDOWS_SYSTEM_ENV if k in os.environ})
        subprocess.run([sys.executable, "-I", "-B", str(MP.RUNNER), work], capture_output=True, text=True, timeout=timeout,
                       env=env)
        with open(os.path.join(work, "output.json")) as f:
            return json.load(f)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)


class TestContrattoChiuso(unittest.TestCase):
    def test_richiesta_chiusa(self):
        for kw in (dict(port="inesistente"), dict(model={"type": "altro"}), dict(model={**ROTOR, "extra": 1}),
                   dict(model={"type": "cos_rotor", "E_C": 0.3}), dict(model={**ROTOR, "E_J": "15"}),
                   dict(model={**ROTOR, "E_J": float("nan")}), dict(levels=0), dict(levels=True),
                   dict(unit="eV"), dict(seconds=0), dict(mem_mib=1), dict(truncation=[30]),
                   dict(truncation={"ncut": float("inf")}), dict(truncation={1: 2}), dict(site_packages=("/nonexistent",)),
                   dict(site_packages=["x"])):
            with self.assertRaises(MP.OutOfDomain, msg=str(kw)):
                request(**kw)

    def test_uscita_chiusa_generativa(self):
        """S6: ogni deformazione dell'uscita valida è NON valida col reason; mai un'eccezione diversa."""
        r = request("numpy_rotor")
        buona = {"contract": MP.CONTRACT, "port": "numpy_rotor", "solver_version": "x", "levels": [0.0] * 6,
                 "unit": "GHz", "state": "OK", "reason": "", "seconds": 0.1}
        u, m = MP.validate_output(buona, r)
        self.assertIsNotNone(u, m)
        deformazioni = [dict(buona, extra=1), {k: v for k, v in buona.items() if k != "reason"},
                        dict(buona, contract="qraft-porta/0.1"), dict(buona, contract="qraft-port/0.2"), dict(buona, port="test_wrong"),
                        dict(buona, state="BOH"), dict(buona, state=1), dict(buona, unit="eV"),
                        dict(buona, levels=[0.0] * 5), dict(buona, levels=[0.0] * 7), dict(buona, levels="0"),
                        dict(buona, levels=[float("nan")] * 6), dict(buona, levels=[True] * 6),
                        dict(buona, levels=[0.0] * 5 + ["1"]), dict(buona, seconds="1"), dict(buona, seconds=float("inf")),
                        dict(buona, reason=None), dict(buona, solver_version=3), [buona], "x", None, 3]
        for d in deformazioni:
            u, m = MP.validate_output(d, r)
            self.assertIsNone(u, d)
            self.assertTrue(m, d)

    def test_confronta_esatto(self):
        from fractions import Fraction as F
        iv = MP.Intervals((F(1), F(2)), (F(1, 1) + F(1, 10 ** 9), F(2) + F(1, 10 ** 9)), (("1", "1"), ("2", "2")),
                           1e-9, "GUARANTEED", 10, 128, 0.0, 0.0)
        u_ok = MP.Output("numpy_rotor", "v", (1000.0, 2000.0), "MHz", "OK", "", 0.0, "")
        self.assertEqual(MP.compare(iv, "GHz", u_ok).overall, "INSIDE")
        u_fuori = MP.Output("numpy_rotor", "v", (1000.0, 2000.002), "MHz", "OK", "", 0.0, "")
        v = MP.compare(iv, "GHz", u_fuori)
        self.assertEqual(v.overall, "OUTSIDE")
        self.assertEqual(v.per_level[1][0], "OUTSIDE")
        self.assertIn("e-06 GHz", v.per_level[1][1])
        u_err = MP.Output("numpy_rotor", "v", (), "GHz", "ERROR", "boom", 0.0, "")
        self.assertEqual(MP.compare(iv, "GHz", u_err).overall, "NOT_COMPARABLE")
        with self.assertRaises(MP.OutOfDomain):
            MP.compare(iv, "eV", u_ok)


def _win_missing():
    raise MP.SandboxMissing("appcontainer: Windows API unavailable (test)")


def _peak_rss_bytes():
    """Peak resident size of this process: ru_maxrss (KiB on Linux, bytes on macOS) or PeakWorkingSetSize (Windows)."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                               "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                               "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        c = PMC()
        c.cb = ctypes.sizeof(c)
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        gpmi = ctypes.WinDLL("psapi").GetProcessMemoryInfo
        gpmi.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        if not gpmi(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            raise OSError("GetProcessMemoryInfo failed")
        return c.PeakWorkingSetSize
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


class _SandboxTests:
    """S1–S7 of docs/PORT_CONTRACT.md §6, run once per isolation engine available here (one subclass per engine).
    Every control must be ABLE to fail: the runner outside the sandbox does what inside must be blocked."""
    ENGINE = ""

    def run_port(self, r, **kw):
        return MP.run_port(r, engine=self.ENGINE, **kw)

    def run_ports(self, rs, **kw):
        return MP.run_ports(rs, engine=self.ENGINE, **kw)

    def skip_without_numpy(self):
        if self.ENGINE not in NUMPY_ENGINES:
            self.skipTest(f"{self.ENGINE}: no numpy inside (declared): solver ports cannot run")

    def test_s5_engine_missing_fail_closed(self):
        """S5: the engine missing → SandboxMissing, nothing runs (no fallback). Missing = its executable not on PATH;
        appcontainer has no executable: missing = the Windows API unavailable (_win refuses)."""
        from rigorous_levels import isolation
        original, probes, win = isolation.shutil.which, dict(isolation._PROBES), isolation._win
        isolation.shutil.which = lambda name: None
        isolation._win = _win_missing
        isolation._PROBES.clear()
        try:
            with self.assertRaises(MP.SandboxMissing):
                self.run_port(request("numpy_rotor"))
        finally:
            isolation.shutil.which, isolation._win = original, win
            isolation._PROBES.update(probes)

    def test_s5_probe_that_does_not_isolate_fail_closed(self):
        """S5: a probe that reports an open network / writable root / visible home → SandboxMissing."""
        from rigorous_levels import isolation
        probes = dict(isolation._PROBES)
        isolation._PROBES.clear()
        name = {"podman": "_probe_container", "docker": "_probe_container", "bwrap": "_probe_bwrap",
                "sandbox-exec": "_probe_sandbox_exec", "appcontainer": "_probe_appcontainer", "wasm": "_probe_wasm"}[self.ENGINE]
        original = getattr(isolation, name)

        def lying(*a, **k):
            raise MP.SandboxMissing("probe: does not isolate (test)")
        setattr(isolation, name, lying)
        try:
            with self.assertRaises(MP.SandboxMissing):
                self.run_port(request("numpy_rotor"))
        finally:
            setattr(isolation, name, original)
            isolation._PROBES.update(probes)

    def test_engine_named_in_output(self):
        u = self.run_port(request("test_dirty_output"))
        self.assertTrue(u.sandbox.startswith(self.ENGINE + ": "), u.sandbox)

    def test_batch_in_one_sandbox(self):
        """§8: 20 requests in one process give 20 outputs (OK, each validated against its own request), the same
        levels as single runs, a wrong port among them is ERROR without touching the others, and the batch is
        faster per case than single runs (the solver import is paid once)."""
        import time
        reqs = [request("python_rotor", model={**ROTOR, "E_J": 10.0 + i}) for i in range(20)]
        reqs[7] = request("test_wrong", model={**ROTOR, "E_J": 17.0})
        t0 = time.perf_counter()
        outs = self.run_ports(reqs)
        batch_time = time.perf_counter() - t0
        self.assertEqual(len(outs), 20)
        for i, (r, u) in enumerate(zip(reqs, outs)):
            self.assertEqual(u.state, "OK", (i, u))
            self.assertEqual(u.port, r.port)
            self.assertIn("batch of 20", u.sandbox)
        single = self.run_port(reqs[3])
        self.assertEqual(outs[3].levels, single.levels)
        t0 = time.perf_counter()
        self.run_port(reqs[0])
        self.run_port(reqs[1])
        two_single = time.perf_counter() - t0
        self.assertLess(batch_time / 20, two_single / 2, (batch_time, two_single))
        bad = request("test_hostile", truncation={"mode": "nope"})
        outs = self.run_ports([reqs[0], bad, reqs[1]])
        self.assertEqual([u.state for u in outs], ["OK", "ERROR", "OK"])
        self.assertIn("unknown", outs[1].reason)

    def test_batch_closed(self):
        with self.assertRaises(MP.OutOfDomain):
            self.run_ports([])
        with self.assertRaises(MP.OutOfDomain):
            self.run_ports([request("python_rotor"), "x"])
        with self.assertRaises(MP.OutOfDomain):
            self.run_ports(request("python_rotor"))

    def test_python_rotor_equals_numpy_rotor(self):
        """The pure-Python reference (Sturm bisection) agrees with numpy's eigvalsh within 1e-11 GHz: it is the
        solver every engine can run, wasm included."""
        u = self.run_port(request("python_rotor"))
        self.assertEqual(u.state, "OK", u)
        d = runner_direct(request("numpy_rotor"))
        self.assertEqual(d["state"], "OK", d)
        for a, b in zip(u.levels, d["levels"]):
            self.assertLess(abs(a - b), 1e-11, (a, b))

    def test_s7_solutore_giusto_e_sbagliato(self):
        if not FLINT:
            self.skipTest("python-flint assente")
        from rigorous_levels.guaranteed_intervals import guaranteed_levels
        from rigorous_levels.rotor_spectrum import Rotor
        iv = guaranteed_levels(Rotor(E_C=0.3, cosines=((1, -15.0),), n_g=0.25), 6, deadline=60)
        u = self.run_port(request("python_rotor" if self.ENGINE not in NUMPY_ENGINES else "numpy_rotor"))
        self.assertEqual(u.state, "OK", u)
        # eigvalsh float64: rumore ~1e-13 GHz (misurato), intervals larghi ~1e-13: senza tolerance è OUTSIDE di 1e-14
        self.assertIn(MP.compare(iv, "GHz", u).overall, ("INSIDE", "OUTSIDE"))
        v0 = MP.compare(iv, "GHz", u, tolerance=1e-12)
        self.assertIn(v0.overall, ("INSIDE", "INSIDE_TOLERANCE"), v0)
        self.assertTrue(all(float(d.split()[0]) <= 1e-12 for s, d in v0.per_level if s != "INSIDE"), v0)
        u2 = self.run_port(request("test_wrong"))
        self.assertEqual(u2.state, "OK", u2)
        v = MP.compare(iv, "GHz", u2, tolerance=1e-12)
        self.assertEqual(v.overall, "OUTSIDE")
        with self.assertRaises(MP.OutOfDomain):
            MP.compare(iv, "GHz", u2, tolerance=-1.0)
        self.assertTrue(any(s == "OUTSIDE" for s, _ in v.per_level))
        # unità diverse: la stessa uscita in MHz resta INSIDE
        u3 = MP.Output(u.port, u.solver_version, tuple(x * 1e3 for x in u.levels), "MHz", "OK", "", 0.0, "")
        self.assertEqual(MP.compare(iv, "GHz", u3, tolerance=1e-12).overall, v0.overall)

    def test_s1_rete_bloccata(self):
        with socket.socket() as srv:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            tcp_port = srv.getsockname()[1]
            r = request("test_network", truncation={"tcp_port": tcp_port})
            diretto = runner_direct(r)                       # check positivo: fuori dalla sandbox la rete c'è
            self.assertEqual(diretto["state"], "OK", diretto)
            self.assertIn("REACHED", diretto["solver_version"])
            u = self.run_port(r)
        self.assertEqual(u.state, "ERROR", u)
        self.assertIn("network blocked", u.reason)
        self.assertNotIn("REACHED", u.solver_version)

    def test_s2_scrittura_e_home_bloccate(self):
        fuori = tempfile.mkdtemp(prefix="rigorous_levels_fuori_")
        target = os.path.join(fuori, "scritto_dal_solutore.txt")
        real_home = os.path.expanduser("~")
        r = request("test_write", truncation={"path": target, "real_home": real_home})
        diretto = runner_direct(r)                           # check positivo: fuori dalla sandbox scrive
        self.assertIn(f"WRITTEN {target}", diretto["reason"])
        self.assertTrue(os.path.exists(target))
        os.remove(target)
        u = self.run_port(r)
        self.assertEqual(u.state, "ERROR")
        self.assertIn(f"blocked {target}", u.reason)
        self.assertIn("real_home_visible=False", u.reason)
        self.assertFalse(os.path.exists(target))
        self.assertFalse(os.path.exists(os.path.join(real_home, "rigorous_levels_port_test.txt")))
        shutil.rmtree(fuori, ignore_errors=True)

    def test_s3_tempo(self):
        u = self.run_port(request("test_loop", seconds=2))
        self.assertEqual(u.state, "INVALID", u)
        self.assertIn("timeout", u.reason)

    def test_s3_memoria(self):
        u = self.run_port(request("test_memory", truncation={"mib": 3000}, mem_mib=256))
        self.assertEqual(u.state, "ERROR", u)
        if self.ENGINE == "sandbox-exec":     # macOS refuses RLIMIT_AS: the host watchdog kills and says why
            self.assertRegex(u.reason, r"^memory: .* over the mem_mib cap of 256 MiB \(host watchdog\)$")
        else:
            self.assertIn("MemoryError", u.reason)
        self.assertNotIn("ALLOCATED", u.solver_version)
        d = runner_direct(request("test_memory", truncation={"mib": 300}, mem_mib=1024))  # the port does allocate
        self.assertEqual(d["state"], "OK", d)

    def test_s4_ambiente_pulito(self):
        """PYTHONPATH/HOME della sessione non arrivano: la port vede HOME = /tmp/nohome (inesistente)."""
        r = request("test_write", truncation={"path": "/tmp/fuori_work.txt", "real_home": os.path.expanduser("~")})
        os.environ["RIGOROUS_LEVELS_PROVA_AMBIENTE"] = "1"
        try:
            u = self.run_port(r)
        finally:
            os.environ.pop("RIGOROUS_LEVELS_PROVA_AMBIENTE", None)
        self.assertRegex(u.reason, r"blocked \S*nohome\S*rigorous_levels_port_test.txt")
        if self.ENGINE in ("bwrap", "podman", "docker"):          # new PID namespace: the runner has a small pid
            pid = int(u.reason.split("pid=")[1].split(";")[0].strip())
            self.assertLessEqual(pid, 10, u.reason)
        diretto = runner_direct(r)
        self.assertGreater(int(diretto["reason"].split("pid=")[1].split(";")[0].strip()), 10, diretto["reason"])

    def test_s6_uscita_sporca(self):
        u = self.run_port(request("test_dirty_output"))
        self.assertEqual(u.state, "INVALID", u)
        self.assertIn("unknown_key", u.reason)

    def test_scqubits_e_diatomic(self):
        self.skip_without_numpy()
        if importlib.util.find_spec("scqubits") is None or not FLINT:
            self.skipTest("scqubits o flint assenti")
        from rigorous_levels.guaranteed_intervals import guaranteed_levels
        from rigorous_levels.rotor_spectrum import Rotor
        iv = guaranteed_levels(Rotor(E_C=0.3, cosines=((1, -15.0),), n_g=0.25), 6, deadline=60)
        u = self.run_port(request("scqubits_transmon", mem_mib=4096, seconds=120))
        self.assertEqual(u.state, "OK", u)
        self.assertIn("scqubits", u.solver_version)
        self.assertIn(MP.compare(iv, "GHz", u, tolerance=1e-12).overall, ("INSIDE", "INSIDE_TOLERANCE"))
        if importlib.util.find_spec("diatomic") is None:
            self.skipTest("diatomic-py assente")
        from rigorous_levels import hyperfine_molecule as MI
        mol = dict(type="sigma_molecule", two_I1=3, two_I2=7, two_MF=12, B=490173.994e3, D=213.0, c1=29.4, c2=196.8,
                   c3=192.4, c4=19.019e3, eQq1=-809.29e3, eQq2=59.98e3, z_N=MI.zeeman_hz(0.0062, 181.541),
                   z1=MI.zeeman_hz(1.8295, 181.541), z2=MI.zeeman_hz(0.7331, 181.541), dE=0.0)
        m = MI.SigmaMolecule(**{k: v for k, v in mol.items() if k not in ("type", "two_MF")})
        iv6 = MI.guaranteed_molecule_levels(m, 12, 1, L_initial=3, L_limit=3, deadline=120, width=1e-11)
        u = self.run_port(request("diatomic_py", model=mol, levels=1, truncation={"N_max": 3}, unit="Hz", seconds=120, mem_mib=4096))
        self.assertEqual(u.state, "OK", u)
        self.assertIn("c3 → −c3", u.solver_version)
        self.assertIn(MP.compare(iv6, "Hz", u, tolerance=1e-3).overall, ("INSIDE", "INSIDE_TOLERANCE"), (iv6.strings, u))

    def test_ambiente_di_sessione_mai_visibile(self):
        """Nemmeno in /proc/1/environ (init di bwrap). Controllo positivo: fuori dalla sandbox la variabile si vede."""
        r = request("test_hostile", truncation={"mode": "environment", "name": "RIGOROUS_LEVELS_NEMESIS_ESCA"})
        os.environ["RIGOROUS_LEVELS_NEMESIS_ESCA"] = "esca"
        try:
            u = self.run_port(r)
            diretto = subprocess.run([sys.executable, "-c", "import os,sys; print('RIGOROUS_LEVELS_NEMESIS_ESCA' in os.environ)"],
                                     capture_output=True, text=True).stdout.strip()
        finally:
            os.environ.pop("RIGOROUS_LEVELS_NEMESIS_ESCA", None)
        self.assertEqual(u.state, "ERROR", u)
        self.assertIn("seen in []", u.reason)
        self.assertEqual(diretto, "True")


    def test_uscita_non_sostituibile_e_disco_limitato(self):
        u = self.run_port(request("test_hostile", truncation={"mode": "symlink", "target": "/etc/hostname"}))
        self.assertEqual(u.state, "ERROR", u)
        self.assertIn("symlink blocked", u.reason)
        host_paths = self.ENGINE in HOST_PATH_ENGINES
        u = self.run_port(request("test_hostile", truncation={"mode": "disk", "where": "$WORK" if host_paths else "/work",
                                                               "files": 2, "mib": 1}))
        self.assertRegex(u.reason, r"disk: 0 MiB then (OSError|PermissionError)")
        if host_paths:                        # no tmpfs: the scratch folder is on disk, its total watched from the host
            u = self.run_port(request("test_hostile", truncation={"mode": "disk", "where": "$TMP", "files": 6, "mib": 60}))
            self.assertEqual(u.state, "ERROR", u)
            self.assertRegex(u.reason, rf"^disk: \d+ MiB written over the {MP.TMPFS_BYTES >> 20} MiB cap \(host watchdog\)$")
            return
        for where in ("/tmp", "/dev/shm", "/home"):           # tmpfs in RAM: tetto per ciascuno (RLIMIT_AS non li conta)
            u = self.run_port(request("test_hostile", truncation={"mode": "disk", "where": where, "files": 6, "mib": 60}))
            self.assertRegex(u.reason, r"then (OSError|PermissionError|FileNotFoundError)", where)   # WASI: no /tmp at all
            self.assertLessEqual(int(u.reason.split("disk: ")[1].split(" MiB")[0]), MP.TMPFS_BYTES >> 20, where)


    def test_stdout_illimitato_non_entra_in_memoria(self):
        prima = _peak_rss_bytes()
        u = self.run_port(request("test_hostile", truncation={"mode": "stdout", "mib": 300}))
        dopo = _peak_rss_bytes()
        self.assertEqual(u.state, "ERROR", u)
        self.assertLess(dopo - prima, 100 << 20, (prima, dopo))            # con capture_output cresce di ≥ 300 MiB


    def test_site_packages_sola_lettura_e_rlimit(self):
        """Il site-packages montato non è scrivibile (il engine «process» importa da lì); NPROC, FSIZE e CPU mordono."""
        # name usa-e-getta, NON .pth, e rimosso comunque: un mutante che rende scrivibile il bind scriverebbe nel venv VERO
        target = os.path.join(SITE[0], f"rigorous_levels_nemesis_prova_{os.getpid()}.txt")
        try:
            u = self.run_port(request("test_hostile", truncation={"mode": "write", "path": target}))
            esiste = os.path.exists(target)
        finally:
            if os.path.exists(target):
                os.remove(target)
        self.assertIn("write: blocked", u.reason)
        self.assertFalse(esiste)
        u = self.run_port(request("test_hostile", truncation={"mode": "fork"}))
        self.assertLessEqual(int(u.reason.split("fork: ")[1]), 16, u.reason)
        u = self.run_port(request("test_hostile", truncation={"mode": "disk", "files": 1, "mib": 70,
                                                               "where": "$TMP" if self.ENGINE in HOST_PATH_ENGINES else "/tmp"}))
        if self.ENGINE == "wasm":                             # no rlimit and no writable scratch at all under WASI
            self.assertRegex(u.reason, r"disk: 0 MiB then FileNotFoundError")
        elif self.ENGINE == "appcontainer":                   # no RLIMIT_FSIZE on Windows: the host watchdog, after exit too
            self.assertEqual(u.state, "ERROR", u)
            self.assertRegex(u.reason, r"^disk: a file of \d+ MiB over the 64 MiB cap \(host watchdog\)$")
        else:
            self.assertRegex(u.reason, r"disk: 64 MiB then (OSError|PermissionError)")
        u = self.run_port(request("test_hostile", truncation={"mode": "cpu"}, seconds=2))
        if self.ENGINE == "appcontainer":                     # the Job's CPU limit or the host reading the Job's CPU time
            self.assertIn(u.state, ("INVALID", "ERROR"), u)
            if u.state == "ERROR":
                self.assertRegex(u.reason, r"^cpu: \d+\.\d s of CPU over the 2 s cap \(host watchdog\)$")
            self.assertNotIn("timeout", u.reason)             # never the caller's wall-clock timeout
            return
        self.assertEqual(u.state, "INVALID", u)
        if self.ENGINE == "wasm":                             # no rlimit under WASI: the engine/host timeout is the guard
            self.assertIn("timeout", u.reason)
        else:
            self.assertNotIn("timeout", u.reason)             # killed by RLIMIT_CPU, not by the caller's timeout


    def test_ok_poi_crash_non_valida(self):
        u = self.run_port(request("test_hostile", truncation={"mode": "ok_then_crash"}))
        self.assertEqual(u.state, "INVALID", u)
        self.assertIn("exit code", u.reason)



class TestNemesis20261111(unittest.TestCase):
    """Rilievi NEMESIS 11/11/2026: ogni caso ha il suo check positivo (fuori dalla sandbox / codice vecchio)."""

    def test_leggi_uscita_json_stretto(self):
        d = tempfile.mkdtemp(prefix="rigorous_levels_uscita_")
        try:
            p = os.path.join(d, "u.json")
            buona = {"contract": MP.CONTRACT, "port": "numpy_rotor", "solver_version": "x", "levels": [0.0] * 6,
                     "unit": "GHz", "state": "OK", "reason": "", "seconds": 0.1}
            casi = ["[" * 200000 + "]" * 200000, '{"a":' * 100000 + "1" + "}" * 100000,
                    json.dumps(buona)[:-1] + ', "state": "ERROR"}', json.dumps(buona).replace("[0.0,", "[NaN,"),
                    json.dumps(dict(buona, reason="x" * (MP.OUTPUT_MAX_BYTES + 1 - len(json.dumps(dict(buona, reason="")))))),
                    "\xff"]                          # JSON valido di esattamente OUTPUT_MAX_BYTES + 1 byte
            for c in casi:
                with open(p, "w", encoding="latin-1") as f:
                    f.write(c)
                doc, reason = MP.read_output(p)
                self.assertIsNone(doc, c[:40])
                self.assertTrue(reason)
            with open(p, "w") as f:
                json.dump(buona, f)
            self.assertEqual(MP.read_output(p)[0], buona)              # check positivo: la valida passa
            os.symlink(p, os.path.join(d, "link"))
            self.assertIsNone(MP.read_output(os.path.join(d, "link"))[0])
            if hasattr(os, "mkfifo"):
                os.mkfifo(os.path.join(d, "fifo"))
                self.assertIsNone(MP.read_output(os.path.join(d, "fifo"))[0])
            os.mkdir(os.path.join(d, "cartella"))
            self.assertIsNone(MP.read_output(os.path.join(d, "cartella"))[0])
            self.assertIsNone(MP.read_output(os.path.join(d, "assente"))[0])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_valida_uscita_mai_eccezione(self):
        r = request("numpy_rotor")
        buona = {"contract": MP.CONTRACT, "port": "numpy_rotor", "solver_version": "x", "levels": [0.0] * 6,
                 "unit": "GHz", "state": "OK", "reason": "", "seconds": 0.1}
        for d in (dict(buona, levels=[10 ** 400] + [0.0] * 5), dict(buona, seconds=10 ** 400),
                  dict(buona, state="ERROR", levels=["abc"]), dict(buona, state="ERROR", levels=[[1]])):
            u, m = MP.validate_output(d, r)
            if d["state"] == "OK":
                self.assertIsNone(u, m)
            else:
                self.assertEqual((u.state, u.levels), ("ERROR", ()))

    def test_richiesta_tetti_e_tipi(self):
        for kw in (dict(seconds=2 ** 31), dict(seconds=MP.SECONDS_MAX + 1), dict(mem_mib=MP.MEM_MIB_MAX + 1),
                   dict(levels=MP.LEVELS_MAX + 1), dict(unit=[]), dict(model={**ROTOR, "type": []}),
                   dict(model={**ROTOR, "E_C": 10 ** 400}), dict(site_packages=(os.path.expanduser("~"),)),
                   dict(site_packages=("/",))):
            with self.assertRaises(MP.OutOfDomain, msg=str(kw)[:80]):
                request(**kw)
        request(seconds=MP.SECONDS_MAX, mem_mib=MP.MEM_MIB_MAX, levels=6)     # check positivo: i tetti stessi passano

    def test_confronta_k_diversi_e_uscita_a_mano(self):
        from fractions import Fraction as F
        iv = MP.Intervals((F(1),), (F(1) + F(1, 10 ** 9),), (("1", "1"),), 1e-9, "GUARANTEED", 10, 128, 0.0, 0.0)
        u3 = MP.Output("numpy_rotor", "v", (1.0, 99.0, 1e9), "GHz", "OK", "", 0.0, "")
        self.assertEqual(MP.compare(iv, "GHz", u3).overall, "NOT_COMPARABLE")
        u1 = MP.Output("numpy_rotor", "v", (1.0,), "GHz", "OK", "", 0.0, "")
        self.assertEqual(MP.compare(iv, "GHz", u1).overall, "INSIDE")          # check positivo
        for u in (MP.Output("numpy_rotor", "v", (float("nan"),), "GHz", "OK", "", 0.0, ""),
                  MP.Output("numpy_rotor", "v", (1.0,), "eV", "OK", "", 0.0, "")):
            with self.assertRaises(MP.OutOfDomain):
                MP.compare(iv, "GHz", u)
        with self.assertRaises(MP.OutOfDomain):
            MP.compare(iv, "GHz", u1, tolerance=10 ** 400)





    def test_tolleranza_al_confine(self):
        from fractions import Fraction as F
        iv = MP.Intervals((F(1),), (F(1),), (("1", "1"),), 0.0, "GUARANTEED", 10, 128, 0.0, 0.0)
        u = MP.Output("numpy_rotor", "v", (1.5,), "GHz", "OK", "", 0.0, "")
        self.assertEqual(MP.compare(iv, "GHz", u, tolerance=0.5).overall, "INSIDE_TOLERANCE")
        self.assertEqual(MP.compare(iv, "GHz", u, tolerance=0.25).overall, "OUTSIDE")


    def test_bwrap_non_di_root_rifiutato(self):
        d = tempfile.mkdtemp(prefix="finto_bwrap_")
        finto = os.path.join(d, "bwrap")
        with open(finto, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(finto, 0o755)
        from rigorous_levels import isolation
        originale, probes = isolation.shutil.which, dict(isolation._PROBES)
        isolation.shutil.which = lambda name: finto
        isolation._PROBES.clear()
        try:
            with self.assertRaises(MP.SandboxMissing):
                MP.run_port(request("numpy_rotor"), engine="bwrap")
        finally:
            isolation.shutil.which = originale
            isolation._PROBES.update(probes)
            shutil.rmtree(d, ignore_errors=True)


class TestCI20261112Platforms(unittest.TestCase):
    """First CI run on macOS/Windows/ARM (2026-11-12): two product defects that Linux could not show."""

    def test_output_link_refused_without_o_nofollow(self):
        # Windows has no O_NOFOLLOW: a symlink output.json was followed and read
        from unittest import mock

        class SenzaNofollow:
            def __getattr__(self, name):
                if name == "O_NOFOLLOW":
                    raise AttributeError(name)
                return getattr(os, name)

        d = tempfile.mkdtemp(prefix="link_")
        try:
            p = os.path.join(d, "vera.json")
            with open(p, "w") as f:
                json.dump({"x": 1}, f)
            try:
                os.symlink(p, os.path.join(d, "link"))
            except (OSError, NotImplementedError) as e:
                self.skipTest(f"symlink not creatable here: {e}")
            with mock.patch.object(MP, "os", SenzaNofollow()):
                doc, reason = MP.read_output(os.path.join(d, "link"))
                self.assertIsNone(doc)
                self.assertIn("link", reason)
                self.assertEqual(MP.read_output(p)[0], {"x": 1})                    # positive control
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_docker_caps_processes_with_its_cgroup_not_rlimit_nproc(self):
        # rootful docker: --user is the host uid in the host user namespace, where RLIMIT_NPROC counts every process
        # of that user (CI linux 3.10: "can't start new thread")
        from rigorous_levels import isolation
        cmd = isolation._container_cmd("docker", "docker", "img", "n", 30, [], "/w", "/w/o.json")
        self.assertIn("--pids-limit", cmd)
        self.assertEqual(cmd[cmd.index("--pids-limit") + 1], str(isolation.CONTAINER_PIDS))
        self.assertEqual(isolation.CONTAINER_PIDS, 16)                                # the S7 cap of every engine
        self.assertIn("RIGOROUS_LEVELS_NPROC=cgroup", cmd)
        cmd = isolation._container_cmd("podman", "podman", "img", "n", 30, [], "/w", "/w/o.json")
        self.assertNotIn("RIGOROUS_LEVELS_NPROC=cgroup", cmd)                                   # podman: own user namespace

    def test_appcontainer_environment_has_system_variables_and_no_real_user_folders(self):
        from rigorous_levels import isolation
        s = tempfile.mkdtemp(prefix="ac_env_")
        try:
            env = isolation._appcontainer_base_env(s)
            for k in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "PATH", "USERPROFILE",
                      "LOCALAPPDATA", "APPDATA"):
                self.assertTrue(env.get(k), k)
            for k in ("USERPROFILE", "LOCALAPPDATA", "APPDATA"):                         # never the real folders
                self.assertTrue(env[k].startswith(s), (k, env[k]))
            self.assertEqual(set(env), {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "PATH",
                                        "USERPROFILE", "LOCALAPPDATA", "APPDATA"})        # closed list
        finally:
            shutil.rmtree(s, ignore_errors=True)

    @unittest.skipUnless(os.name == "posix", "a fake framework layout with POSIX paths")
    def test_macos_framework_binary_allowed_by_the_profile(self):
        from rigorous_levels import isolation
        d = os.path.realpath(tempfile.mkdtemp(prefix="framework_"))
        try:
            os.makedirs(os.path.join(d, "bin"))
            app = os.path.join(d, "Resources", "Python.app", "Contents", "MacOS")
            os.makedirs(app)
            stub = os.path.join(d, "bin", "python3.12")
            for f in (stub, os.path.join(app, "Python")):
                open(f, "w").close()
            self.assertEqual(isolation._macos_exec_targets(stub), [stub, os.path.join(app, "Python")])
            prof = isolation.seatbelt_profile(stub, [], "/tmp/x/o.json", "/tmp/x")
            self.assertIn(f'(allow process-exec (literal "{os.path.join(app, "Python")}"))', prof)
            os.remove(os.path.join(app, "Python"))                                     # no framework: stub only
            self.assertEqual(isolation._macos_exec_targets(stub), [stub])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    @unittest.skipUnless(os.name == "posix", "resource limits: POSIX")
    def test_runner_skips_rlimit_nproc_only_when_told(self):
        from unittest import mock
        from rigorous_levels import port_runner as R
        if R.resource is None:
            self.skipTest("resource absent")
        for env, attesa in (({"RIGOROUS_LEVELS_NPROC": "cgroup"}, False), ({}, True)):
            with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(R.resource, "setrlimit") as s:
                if not env:
                    os.environ.pop("RIGOROUS_LEVELS_NPROC", None)
                R._rlimit(10, 512)
                chiamati = [c.args[0] for c in s.call_args_list]
                self.assertEqual(R.resource.RLIMIT_NPROC in chiamati, attesa, env)


class TestCI20261112Watchdog(unittest.TestCase):
    """CI runs of 2026-11-12 on macOS and Windows: each test fails on the tree before the fix (positive control)."""

    class FakeResource:
        RLIMIT_CPU, RLIMIT_AS, RLIMIT_FSIZE, RLIMIT_NPROC, RLIM_INFINITY = 0, 5, 1, 7, -1

        def __init__(self, refuse=(), hard=None):
            self.refuse, self.hard, self.set = refuse, hard or {}, {}

        def getrlimit(self, which):
            return (self.RLIM_INFINITY, self.hard.get(which, self.RLIM_INFINITY))

        def setrlimit(self, which, value):
            if which in self.refuse:
                raise ValueError("current limit exceeds maximum limit")
            h = self.hard.get(which, self.RLIM_INFINITY)
            if h != self.RLIM_INFINITY and value[1] > h:
                raise ValueError("not allowed to raise maximum limit")
            self.set[which] = value

    def _rlimit(self, fake, env):
        from unittest import mock
        from rigorous_levels import port_runner as R
        with mock.patch.object(R, "resource", fake), mock.patch.dict(os.environ, env, clear=False):
            for k in ("RIGOROUS_LEVELS_HOST_LIMITS", "RIGOROUS_LEVELS_NPROC"):
                if k not in env:
                    os.environ.pop(k, None)
            R._rlimit(10, 512)

    def test_rlimit_refused_by_the_platform_stops_unless_the_engine_enforces_it(self):
        F = self.FakeResource
        f = F(refuse=(F.RLIMIT_AS,))
        with self.assertRaisesRegex(RuntimeError, "RLIMIT_AS cannot be set here"):
            self._rlimit(f, {})
        f = F(refuse=(F.RLIMIT_AS,))
        self._rlimit(f, {"RIGOROUS_LEVELS_HOST_LIMITS": "memory"})               # macOS + sandbox-exec: the host watches
        self.assertEqual(f.set, {F.RLIMIT_CPU: (10, 10), F.RLIMIT_FSIZE: (64 << 20, 64 << 20), F.RLIMIT_NPROC: (16, 16)})
        f = F(refuse=(F.RLIMIT_CPU,))                                   # host enforcement is per limit, not for all
        with self.assertRaisesRegex(RuntimeError, "RLIMIT_CPU"):
            self._rlimit(f, {"RIGOROUS_LEVELS_HOST_LIMITS": "memory"})
        with self.assertRaisesRegex(RuntimeError, "unknown limit"):
            self._rlimit(F(), {"RIGOROUS_LEVELS_HOST_LIMITS": "memory,everything"})

    def test_rlimit_never_above_a_lower_hard_limit(self):
        F = self.FakeResource
        f = F(hard={F.RLIMIT_NPROC: 8})
        self._rlimit(f, {})
        self.assertEqual(f.set[F.RLIMIT_NPROC], (8, 8))                  # before: (16, 16) refused, then skipped

    def _run_port_with(self, fake_run):
        from unittest import mock
        from rigorous_levels import isolation
        with mock.patch.object(isolation, "probe", lambda *a, **k: {}), mock.patch.object(isolation, "run", fake_run):
            return MP.run_port(request("python_rotor"), engine="bwrap")

    def test_output_removed_by_the_port_is_invalid_not_an_exception(self):
        def fake_run(engine, work, out_path, *a):
            os.remove(out_path)                                          # Windows, M grant: the port deleted it
            return 1, False, "fake", ""
        u = self._run_port_with(fake_run)
        self.assertEqual(u.state, "INVALID", u)
        self.assertIn("no output", u.reason)

    def test_host_limit_discards_what_the_port_wrote(self):
        def fake_run(engine, work, out_path, *a):
            with open(out_path, "w") as f:
                json.dump({"contract": MP.CONTRACT, "port": "python_rotor", "solver_version": "x", "levels": [0.0] * 6,
                           "unit": "GHz", "state": "OK", "reason": "", "seconds": 0.0}, f)
            return 0, False, "fake", "memory: 300 MiB resident over the mem_mib cap of 256 MiB (host watchdog)"
        u = self._run_port_with(fake_run)
        self.assertEqual((u.state, u.levels), ("ERROR", ()), u)
        self.assertIn("host watchdog", u.reason)

    def test_seatbelt_output_file_writable_data_only(self):
        from rigorous_levels import isolation
        out, scratch = os.path.join(os.sep, "rigorous_levels_x", "o.json"), os.path.join(os.sep, "rigorous_levels_x", "s")
        prof = isolation.seatbelt_profile(sys.executable, [], out, scratch)
        lit = isolation._sb_literal
        self.assertIn(f"(allow file-write-data (literal {lit(os.path.realpath(out))}))", prof)
        self.assertNotIn(f"file-write* (literal {lit(os.path.realpath(out))})", prof)   # unlink/create: a link there
        self.assertIn(f"(allow file-write* (subpath {lit(os.path.realpath(scratch))}))", prof)

    def test_cpu_reason_of_the_job(self):
        from rigorous_levels import isolation
        self.assertEqual(isolation.cpu_reason(20_000_000, 2), "")                       # exactly at the cap
        self.assertEqual(isolation.cpu_reason(23_000_000, 2), "cpu: 2.3 s of CPU over the 2 s cap (host watchdog)")

    def test_appcontainer_output_grant_without_delete(self):
        from rigorous_levels import isolation
        self.assertEqual(isolation.OUTPUT_GRANT, "(R,W)")                # M includes DELETE: output.json was removed

    def test_disk_reason_caps(self):
        from unittest import mock
        from rigorous_levels import isolation
        d = tempfile.mkdtemp(prefix="rigorous_levels_disk_")
        try:
            with mock.patch.object(isolation, "FILE_CAP", 4 << 20), mock.patch.object(isolation, "TMPFS_BYTES", 8 << 20):
                with open(os.path.join(d, "a"), "wb") as f:
                    f.write(b"\0" * (3 << 20))
                self.assertEqual(isolation.disk_reason([d]), "")                         # positive control
                os.makedirs(os.path.join(d, "sub"))
                for n in ("b", "sub/c"):
                    with open(os.path.join(d, n), "wb") as f:
                        f.write(b"\0" * (3 << 20))
                self.assertRegex(isolation.disk_reason([d]), r"^disk: 9 MiB written over the 8 MiB cap")
                self.assertEqual(isolation.disk_reason([d], base=(6 << 20, 0)), "")       # what was there before
                with open(os.path.join(d, "sub", "c"), "ab") as f:
                    f.write(b"\0" * (2 << 20))
                self.assertRegex(isolation.disk_reason([d]), r"^disk: a file of 5 MiB over the 4 MiB cap")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    @unittest.skipUnless(sys.platform.startswith("linux") or sys.platform == "darwin", "host watchdog: Linux/macOS")
    def test_run_watched_kills_over_memory_and_catches_a_short_peak(self):
        from rigorous_levels import isolation
        d = tempfile.mkdtemp(prefix="rigorous_levels_watch_")
        try:
            err = os.path.join(d, "err.txt")
            hold = "a = bytearray(400 << 20); a[::4096] = b'1' * len(a[::4096]); import time; time.sleep(20)"
            rc, to, why = isolation.run_watched([sys.executable, "-c", hold], 30, err, {}, 128 << 20, [d])
            self.assertRegex(why, r"^memory: \d+ MiB resident over the mem_mib cap of 128 MiB \(host watchdog\)$")
            self.assertFalse(to)
            peak = "a = bytearray(400 << 20); a[::4096] = b'1' * len(a[::4096]); del a"
            rc, to, why = isolation.run_watched([sys.executable, "-c", peak], 30, err, {}, 128 << 20, [d])
            self.assertRegex(why, r"^memory: ")                              # sampled or, after exit, the peak
            rc, to, why = isolation.run_watched([sys.executable, "-c", peak], 30, err, {}, 2048 << 20, [d])
            self.assertEqual((rc, to, why), (0, False, ""))                  # positive control: under the cap
            rc, to, why = isolation.run_watched([sys.executable, "-c", "import time; time.sleep(30)"], 1, err, {}, 0, [d])
            self.assertEqual((rc, to, why), (None, True, ""))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    @unittest.skipUnless(os.name == "posix", "host watchdog: POSIX process groups")
    def test_run_watched_disk_and_no_child_left_behind(self):
        from unittest import mock
        from rigorous_levels import isolation
        d = tempfile.mkdtemp(prefix="rigorous_levels_watch_")
        try:
            err = os.path.join(d, "err.txt")
            code = (f"import os, time\nif os.fork() == 0:\n    time.sleep(60); os._exit(0)\n"
                    f"open({os.path.join(d, 'big')!r}, 'wb').write(b'0' * (6 << 20))\n")
            with mock.patch.object(isolation, "FILE_CAP", 4 << 20):
                rc, to, why = isolation.run_watched([sys.executable, "-c", code], 30, err, {}, 0, [d])
            # the watchdog samples while the 6 MiB write is in progress: it may see 4.x or 5 MiB (measured 2026-11-12
            # under load: "5 MiB"); what is checked is the cap being enforced, not the sampling instant
            self.assertRegex(why, r"^disk: a file of [4-6] MiB over the 4 MiB cap \(host watchdog\)$")
            out = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True).stdout
            self.assertNotIn("time.sleep(60)", out)                          # the fork was killed with the group
        finally:
            shutil.rmtree(d, ignore_errors=True)

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() != 0, "chmod: POSIX non-root")
    def test_real_home_visible_means_listable(self):
        d = tempfile.mkdtemp(prefix="rigorous_levels_home_")
        try:
            os.chmod(d, 0o311)                                               # exists (isdir True), not listable
            r = request("test_write", truncation={"path": os.path.join(d, "x", "y"), "real_home": d})
            self.assertIn("real_home_visible=False", runner_direct(r)["reason"])
            os.chmod(d, 0o755)
            self.assertIn("real_home_visible=True", runner_direct(r)["reason"])   # positive control
        finally:
            os.chmod(d, 0o755)
            shutil.rmtree(d, ignore_errors=True)

    def test_devnull_redirected_only_when_nul_cannot_be_opened(self):
        from unittest import mock
        from rigorous_levels import port_runner as R
        d = tempfile.mkdtemp(prefix="rigorous_levels_nul_")
        alt = os.path.join(d, "devnull")
        original = os.devnull
        try:
            with mock.patch.dict(os.environ, {"RIGOROUS_LEVELS_DEVNULL": alt}):
                R._devnull()
                self.assertEqual(os.devnull, original)                       # NUL opens: untouched
                os.devnull = os.path.join(d, "no", "such")
                R._devnull()
                self.assertEqual(os.devnull, alt)
                self.assertEqual(os.path.getsize(alt), 0)
        finally:
            os.devnull = original
            shutil.rmtree(d, ignore_errors=True)


class TestNemesis030EngineTrust(unittest.TestCase):
    """NEMESIS 0.3.0: a user-owned «podman» first on PATH was chosen by engine="auto" and ran the port without
    isolation (network REACHED, Output.sandbox "podman run --network none ..."): the probe is measured from inside
    the engine, so an engine binary the user can replace forges it. Same rule as bwrap for every engine binary."""

    def _fake(self, name):
        d = tempfile.mkdtemp(prefix="finto_" + name + "_")
        finto = os.path.join(d, name)
        with open(finto, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(finto, 0o755)
        return d, finto

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "getuid") and os.getuid() != 0, "POSIX, non-root")
    def test_user_owned_engine_binaries_refused(self):
        from rigorous_levels import isolation
        originale, probes = isolation.shutil.which, dict(isolation._PROBES)
        try:
            for engine, call in (("podman", lambda: isolation.probe("podman")),
                                 ("docker", lambda: isolation.probe("docker")),
                                 ("wasmtime", lambda: isolation._wasm_parts())):
                d, finto = self._fake(engine)
                isolation.shutil.which = lambda name, f=finto: f
                isolation._PROBES.clear()
                try:
                    with self.assertRaises(MP.SandboxMissing, msg=engine) as cm:
                        call()
                    self.assertIn("not owned by root", str(cm.exception))
                finally:
                    shutil.rmtree(d, ignore_errors=True)
            isolation.shutil.which = originale
            isolation._PROBES.clear()
            self.assertEqual(isolation._trusted_exe("sh", "/bin/sh"), os.path.realpath("/bin/sh"))   # positive control
        finally:
            isolation.shutil.which = originale
            isolation._PROBES.clear()
            isolation._PROBES.update(probes)

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "getuid") and os.getuid() != 0, "POSIX, non-root")
    def test_trusted_engines_opt_in_is_exact_and_explicit(self):
        from rigorous_levels import isolation
        d, finto = self._fake("wasmtime")
        d, finto = os.path.realpath(d), os.path.realpath(finto)                   # macOS: /var -> /private/var
        vecchio = os.environ.pop("RIGOROUS_LEVELS_TRUSTED_ENGINES", None)
        try:
            with self.assertRaises(MP.SandboxMissing):                                   # not listed: refused
                isolation._trusted_exe("wasmtime", finto)
            os.environ["RIGOROUS_LEVELS_TRUSTED_ENGINES"] = os.path.join(d, "altro") + os.pathsep + d   # folder, not the file
            with self.assertRaises(MP.SandboxMissing):
                isolation._trusted_exe("wasmtime", finto)
            os.environ["RIGOROUS_LEVELS_TRUSTED_ENGINES"] = finto                                    # exact path: accepted
            self.assertEqual(isolation._trusted_exe("wasmtime", finto), finto)
            os.chmod(finto, 0o775)                                                         # group-writable: refused
            with self.assertRaises(MP.SandboxMissing) as cm:
                isolation._trusted_exe("wasmtime", finto)
            self.assertIn("writable by group or others", str(cm.exception))
        finally:
            os.environ.pop("RIGOROUS_LEVELS_TRUSTED_ENGINES", None)
            if vecchio is not None:
                os.environ["RIGOROUS_LEVELS_TRUSTED_ENGINES"] = vecchio
            shutil.rmtree(d, ignore_errors=True)

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "getuid") and os.getuid() != 0, "POSIX, non-root")
    def test_trusted_engines_entry_must_be_the_exact_real_path(self):
        from rigorous_levels import isolation
        d, finto = self._fake("wasmtime")
        d, finto = os.path.realpath(d), os.path.realpath(finto)
        link = os.path.join(d, "collegamento")
        os.symlink(finto, link)
        vecchio, cwd = os.environ.pop("RIGOROUS_LEVELS_TRUSTED_ENGINES", None), os.getcwd()
        try:
            os.chdir(d)
            for voce in ("wasmtime", "./wasmtime", link, finto + "/", " " + finto, d + "/../" + os.path.basename(d) + "/wasmtime"):
                os.environ["RIGOROUS_LEVELS_TRUSTED_ENGINES"] = voce
                with self.assertRaises(MP.SandboxMissing, msg=repr(voce)):
                    isolation._trusted_exe("wasmtime", finto)
            os.environ["RIGOROUS_LEVELS_TRUSTED_ENGINES"] = finto
            self.assertEqual(isolation._trusted_exe("wasmtime", link), finto)     # the real path is what runs
            self.assertEqual(isolation._VOUCHED.get("wasmtime"), finto)
        finally:
            os.chdir(cwd)
            os.environ.pop("RIGOROUS_LEVELS_TRUSTED_ENGINES", None)
            isolation._VOUCHED.pop("wasmtime", None)
            if vecchio is not None:
                os.environ["RIGOROUS_LEVELS_TRUSTED_ENGINES"] = vecchio
            shutil.rmtree(d, ignore_errors=True)

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "getuid") and os.getuid() != 0, "POSIX, non-root")
    def test_root_engine_runs_by_its_real_path_and_folder_must_be_root_owned(self):
        from rigorous_levels import isolation
        sh = os.path.realpath("/bin/sh")
        if os.stat(sh).st_uid != 0:
            self.skipTest("/bin/sh not owned by root")
        d = tempfile.mkdtemp(prefix="finto_link_")
        try:
            os.symlink(sh, os.path.join(d, "podman"))       # a symlink the user can retarget after the check
            self.assertEqual(isolation._trusted_exe("podman", os.path.join(d, "podman")), sh)
            try:
                os.link(sh, os.path.join(d, "docker"))     # hard link: root-owned file in a user folder
            except OSError:
                return                                      # fs.protected_hardlinks = 1: not possible here
            with self.assertRaises(MP.SandboxMissing) as cm:
                isolation._trusted_exe("docker", os.path.join(d, "docker"))
            self.assertIn("could be swapped", str(cm.exception))
        finally:
            shutil.rmtree(d, ignore_errors=True)
        # a root-owned folder writable by others (as /tmp): simulated, a hard link there could not be removed (sticky)
        real_stat = os.stat
        def fake_stat(p, *a, **k):
            st = real_stat(p, *a, **k)
            if p == os.path.dirname(sh):
                return os.stat_result((st.st_mode | 0o002,) + tuple(st)[1:])
            return st
        def user_stat(p, *a, **k):                     # a folder owned by the user, mode 0755, above a root binary
            st = real_stat(p, *a, **k)
            if p == os.path.dirname(sh):
                return os.stat_result((st.st_mode & ~0o022, st.st_ino, st.st_dev, st.st_nlink, 1000) + tuple(st)[5:])
            return st
        from unittest import mock
        for fs in (fake_stat, user_stat):
            with mock.patch.object(isolation.os, "stat", fs):
                with self.assertRaises(MP.SandboxMissing):
                    isolation._trusted_exe("podman", sh)

    @unittest.skipUnless(os.name == "posix", "POSIX")
    def test_engine_must_be_a_regular_file_and_root_clears_a_stale_vouch(self):
        from rigorous_levels import isolation
        with self.assertRaises(MP.SandboxMissing):
            isolation._trusted_exe("podman", "/usr/bin")              # a root-owned folder is not an engine
        isolation._VOUCHED["sh"] = "/x/sh"
        isolation._trusted_exe("sh", "/bin/sh")
        self.assertNotIn("sh", isolation._VOUCHED)

    def test_vouched_engine_named_in_the_description(self):
        from rigorous_levels import isolation
        originale = isolation._run_engine
        w = tempfile.mkdtemp()                  # run() records the work folder (PORT_CONTRACT §6.7): a real one
        try:
            isolation._run_engine = lambda *a, **k: (0, False, "wasmtime (WASI)")
            isolation._VOUCHED["wasmtime"] = "/x/wasmtime"
            self.assertIn("RIGOROUS_LEVELS_TRUSTED_ENGINES lists it", isolation.run("wasm", w, "o", 1, 1, [])[2])
            isolation._VOUCHED.pop("wasmtime")
            self.assertEqual(isolation.run("wasm", w, "o", 1, 1, [])[2], "wasmtime (WASI)")
        finally:
            isolation._run_engine = originale
            isolation._VOUCHED.pop("wasmtime", None)
            shutil.rmtree(w, ignore_errors=True)

    def test_any_root_refused_for_grants(self):
        from rigorous_levels import isolation
        roots = [os.path.abspath(os.sep)] + (["Q:\\", "\\\\server\\share\\"] if os.name == "nt" else [])
        for p in roots:                       # Windows: a drive other than the current one was not refused
            with self.assertRaises(MP.OutOfDomain, msg=p):
                isolation._refuse_home_or_ancestor(p, "appcontainer")
        d = tempfile.mkdtemp(prefix="non_radice_")
        try:
            isolation._refuse_home_or_ancestor(d, "appcontainer")                      # positive control: allowed
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_seatbelt_profile_refuses_a_home_prefix(self):
        from rigorous_levels import isolation
        home = isolation._user_homes()[0]
        with self.assertRaises(MP.OutOfDomain):
            isolation.seatbelt_profile(os.path.join(home, "bin", "python3"), [home], "/tmp/x/output.json", "/tmp/x")
        with self.assertRaises(MP.OutOfDomain):
            isolation.seatbelt_profile("/usr/bin/python3", ["/"], "/tmp/x/output.json", "/tmp/x")
        prof = isolation.seatbelt_profile("/usr/bin/python3", [os.path.join(home, "venv", "lib")], "/tmp/x/o.json", "/tmp/x")
        self.assertIn("(deny file-read* (subpath", prof)                                  # positive control


class TestBersagliTroncamentoChiuso(unittest.TestCase):
    """NEMESIS 11/11: le porte dei bersagli accettavano chiavi ignote, 15.9 e "15" nel truncation (int() nel runner)."""
    ROT = {"type": "cos_rotor", "E_C": 0.2, "E_J": 10.0, "n_g": 0.0}
    TLF = {"type": "tlf_centrex", "E_Vcm": 0.0, "B_G": 0.0, "Jmax": 1, "two_MF": 0}

    def test_troncamento_chiuso_per_porta(self):
        buoni = (("metal_hcpb", self.ROT, {"nlevels": 15}), ("metal_mathieu", self.ROT, {}),
                 ("sqcircuit_transmon", self.ROT, {"ncut": 30}), ("pyepr_fock", self.ROT, {"cos_trunc": 5, "fock_trunc": 10}),
                 ("centrex_tlf", self.TLF, {}))
        for port, mod, tr in buoni:
            MP.Request(port, dict(mod), 4, dict(tr))
            for cattivo in ({**tr, "unknown_key": 1}, {k: v + 0.5 for k, v in tr.items()},
                            {k: str(v) for k, v in tr.items()}, {k: True for k in tr}, {k: 0 for k in tr},
                            {k: -3 for k in tr}, {k: v for k, v in list(tr.items())[1:]}):
                if cattivo == tr:
                    continue
                with self.assertRaises(MP.OutOfDomain, msg=(port, cattivo)):
                    MP.Request(port, dict(mod), 4, cattivo)

    def test_modello_obbligato_e_jmax(self):
        with self.assertRaises(MP.OutOfDomain):
            MP.Request("metal_hcpb", dict(self.TLF), 4, {"nlevels": 15})
        with self.assertRaises(MP.OutOfDomain):
            MP.Request("centrex_tlf", dict(self.ROT), 4, {})
        with self.assertRaises(MP.OutOfDomain):
            MP.Request("centrex_tlf", {**self.TLF, "Jmax": -1}, 4, {})


from rigorous_levels import isolation  # noqa: E402


class TestPrefissoInterprete(unittest.TestCase):
    """NEMESIS 11/11 (pubblicazione 0.2.0): un python con sys.base_prefix = <casa>/.local (o = la casa, con HOME diversa) faceva
    montare l'intera cartella: la port leggeva <casa>/.local/share/keyrings. Si montano solo eseguibile, stdlib e libpython."""

    def _interprete(self, prefisso):
        v = f"python{sys.version_info.major}.{sys.version_info.minor}"
        os.makedirs(os.path.join(prefisso, "bin"))
        os.makedirs(os.path.join(prefisso, "lib"))
        exe = os.path.join(prefisso, "bin", v)
        shutil.copy2(os.path.realpath(sys.executable), exe)
        import sysconfig
        os.symlink(sysconfig.get_path("stdlib"), os.path.join(prefisso, "lib", v))
        bp = subprocess.run([exe, "-I", "-c", "import sys; print(sys.base_prefix)"], capture_output=True, text=True,
                            env={"PATH": "/usr/bin:/bin"}).stdout.strip()
        if os.path.realpath(bp) != os.path.realpath(prefisso):
            self.skipTest(f"l'interprete copiato non riconosce il prefisso ({bp!r})")
        return exe

    def test_prefisso_casa_local_mai_intero(self):
        casa = tempfile.mkdtemp(prefix="casa_finta_")
        vecchio = os.environ.get("HOME")
        os.environ["HOME"] = casa
        try:
            prefisso = os.path.join(casa, ".local")
            os.makedirs(os.path.join(prefisso, "share", "keyrings"))
            exe = self._interprete(prefisso)
            import sysconfig
            stdlib_reale = os.path.realpath(sysconfig.get_path("stdlib"))
            if not any(stdlib_reale.startswith(m + "/") for m in MP.RO_MOUNTS):
                with self.assertRaises(MP.OutOfDomain):     # stdlib (symlink) fuori dal prefisso: rifiuto, nessun montaggio
                    isolation.interpreter_pieces(exe)
                return
            pezzi = isolation.interpreter_pieces(exe)             # stdlib già sotto /usr: deve montare solo l'eseguibile
            segreto = os.path.realpath(os.path.join(prefisso, "share", "keyrings"))
            self.assertIn(os.path.realpath(exe), pezzi)
            for x in pezzi:                                   # nessun montaggio contains la cartella del segreto
                self.assertFalse(segreto == x or segreto.startswith(x + "/"), (x, pezzi))
                self.assertNotEqual(x, os.path.realpath(prefisso))
                self.assertTrue(x.startswith(os.path.realpath(prefisso) + "/"), (x, pezzi))   # mai fuori dal prefisso
        finally:
            if vecchio is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = vecchio
            shutil.rmtree(casa, ignore_errors=True)

    def test_prefisso_uguale_alla_casa_rifiutato(self):
        casa = tempfile.mkdtemp(prefix="casa_finta_")
        vecchio = os.environ.get("HOME")
        os.environ["HOME"] = casa
        try:
            exe = self._interprete(casa)                      # python installato con --prefix=$HOME
            with self.assertRaisesRegex(MP.OutOfDomain, "user's home"):
                isolation.interpreter_pieces(exe)
        finally:
            if vecchio is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = vecchio
            shutil.rmtree(casa, ignore_errors=True)

    def test_sonda_malformata_rifiutata(self):
        """La sonda dell'interprete è un JSON di 4 strings: altro (lunghezza, type, non JSON) = OutOfDomain, mai crash."""
        d = tempfile.mkdtemp(prefix="finto_python_")
        try:
            os.makedirs(os.path.join(d, "bin"))
            finto = os.path.join(d, "bin", "python3")
            for uscita in (json.dumps([d]), json.dumps([d, d, d, 4]), "non json", json.dumps({"a": d}), json.dumps([d, d, d, ""])):
                with open(finto, "w") as f:
                    f.write("#!/bin/sh\necho '" + uscita + "'\n")
                os.chmod(finto, 0o755)
                with self.assertRaises(MP.OutOfDomain, msg=uscita):
                    isolation.interpreter_pieces(finto)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    @unittest.skipUnless(os.name == "posix", "interpreter_pieces serves bwrap (Linux); the fake interpreter is a sh script")
    def test_pezzi_chiusi_stdlib_platstdlib_libpython(self):
        """Lista chiusa dei pezzi: eseguibile, stdlib, platstdlib (anche se diversa), libpython*.so* di LIBDIR; altro no."""
        d = os.path.realpath(tempfile.mkdtemp(prefix="finto_python_"))
        try:
            for x in ("bin", "lib/a", "lib/b", "lib/c"):
                os.makedirs(os.path.join(d, x))
            for n in ("libpython3.99.so.1.0", "libaltro.so", "README"):
                open(os.path.join(d, "lib/c", n), "w").close()
            finto = os.path.join(d, "bin", "python3")
            with open(finto, "w") as f:
                f.write("#!/bin/sh\necho '" + json.dumps([d, d + "/lib/a", d + "/lib/b", d + "/lib/c"]) + "'\n")
            os.chmod(finto, 0o755)
            self.assertEqual(set(isolation.interpreter_pieces(finto)),
                             {finto, d + "/lib/a", d + "/lib/b", d + "/lib/c/libpython3.99.so.1.0"})
        finally:
            shutil.rmtree(d, ignore_errors=True)

    @unittest.skipUnless(BWRAP, "bwrap assente")
    def test_pezzi_interprete_sola_lettura(self):
        """I pezzi montati dell'interprete (eseguibile, stdlib) non sono scrivibili dalla port."""
        pezzi = isolation.interpreter_pieces(os.path.realpath(sys.executable))
        cartelle = [x for x in pezzi if os.path.isdir(x)]
        if not cartelle:
            self.skipTest("interprete sotto /usr: nessun pezzo montato")
        target = os.path.join(cartelle[0], f"rigorous_levels_nemesis_prova_{os.getpid()}.txt")
        try:
            u = MP.run_port(request("test_hostile", truncation={"mode": "write", "path": target}))
            esiste = os.path.exists(target)
        finally:
            if os.path.exists(target):
                os.remove(target)
        self.assertIn("write: blocked", u.reason)
        self.assertFalse(esiste)

    @unittest.skipUnless(os.name == "posix", "pwd and user homes from the password database: POSIX only")
    def test_case_utente_anche_da_pwd(self):
        import pwd
        vecchio = os.environ.get("HOME")
        os.environ["HOME"] = tempfile.mkdtemp(prefix="home_diversa_")
        try:
            self.assertIn(os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir), isolation._user_homes())
        finally:
            shutil.rmtree(os.environ["HOME"], ignore_errors=True)
            if vecchio is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = vecchio


class TestProfonditaUscita(unittest.TestCase):
    """CI 11/11/2026: su CPython 3.14.10 json.loads accettava un oggetto annidato 100 000 volte (nessun RecursionError):
    il limite di annidamento è ora contato prima del parser, uguale su ogni versione di Python."""

    def _scrivi_e_leggi(self, testo):
        d = tempfile.mkdtemp(prefix="rigorous_levels_prof_")
        try:
            p = os.path.join(d, "u.json")
            with open(p, "w", encoding="utf-8") as f:
                f.write(testo)
            return MP.read_output(p)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_limite_esatto(self):
        L = MP.OUTPUT_MAX_DEPTH
        self.assertEqual(L, 32)                                              # il numero dichiarato in README e CHANGELOG
        for apri, chiudi in (("[", "]"), ('{"a":', "}")):
            doc, reason = self._scrivi_e_leggi(apri * L + "1" + chiudi * L)
            self.assertIsNotNone(doc, reason)                                   # check positivo: L levels passano
            doc, reason = self._scrivi_e_leggi(apri * (L + 1) + "1" + chiudi * (L + 1))
            self.assertIsNone(doc)
            self.assertIn("nested", reason)
            for n in (1000, 100000, 400000):                                    # i casi della CI, su ogni Python
                self.assertIsNone(self._scrivi_e_leggi(apri * n + "1" + chiudi * n)[0])

    def test_parentesi_nelle_stringhe_non_contano(self):
        L = MP.OUTPUT_MAX_DEPTH
        s = json.dumps({"reason": "[" * 1000 + '\\" {{{ \\\\', "x": ["]]]" * 50, "\"[\""]})
        self.assertEqual(MP._json_depth(s, L), 2)
        self.assertIsNotNone(self._scrivi_e_leggi(s)[0])

    def test_differenziale_con_profondita_vera(self):
        import random
        rnd = random.Random(20261111)

        def gen(d):
            if d == 0 or rnd.random() < 0.3:
                return rnd.choice([1, "a[{\\\"", None, 2.5, "}]"])
            if rnd.random() < 0.5:
                return [gen(d - 1) for _ in range(rnd.randint(0, 3))]
            return {f"k{i}[": gen(d - 1) for i in range(rnd.randint(0, 3))}

        def vera(o):
            if isinstance(o, list):
                return 1 + max((vera(x) for x in o), default=0)
            if isinstance(o, dict):
                return 1 + max((vera(x) for x in o.values()), default=0)
            return 0
        for _ in range(500):
            o = gen(rnd.randint(0, 45))
            s = json.dumps(o, indent=rnd.choice([None, 1]), ensure_ascii=rnd.random() < 0.5)
            self.assertEqual(min(MP._json_depth(s, 10 ** 9), 10 ** 9), vera(o))
            doc, reason = self._scrivi_e_leggi(s)
            self.assertEqual(bool(reason), vera(o) > MP.OUTPUT_MAX_DEPTH, reason)   # null è un doc valido: conta il reason

    def test_caso_peggiore_lineare(self):
        import time
        n = MP.OUTPUT_MAX_BYTES
        for testo in ('"\\' * (n // 2), '"' * n, "[" * n, "a" * n):
            t0 = time.perf_counter()
            doc, reason = self._scrivi_e_leggi(testo[:n])
            self.assertIsNone(doc)
            self.assertLess(time.perf_counter() - t0, 5.0, testo[:4])


def _engine_class(engine):
    name = "TestSandbox_" + engine.replace("-", "_")
    reason = f"{engine}: {ENGINES_WHY.get(engine, 'available')}"
    cls = type(name, (_SandboxTests, unittest.TestCase), {"ENGINE": engine, "__doc__": f"S1–S7 with the engine {engine}."})
    return unittest.skipUnless(engine in ENGINES_OK, reason)(cls)


for _e in ("podman", "docker", "bwrap", "sandbox-exec", "appcontainer", "wasm"):
    globals()["TestSandbox_" + _e.replace("-", "_")] = _engine_class(_e)


class TestFailClosedProbes(unittest.TestCase):
    """A degraded engine must FAIL the probe (and the suite), never pass or be skipped silently."""

    def test_engine_present_means_probe_passes(self):
        """If the executable is on PATH (and, for containers, the image is in the local store) the probe must pass:
        a probe that fails here is a defect of the engine code, not a reason to skip."""
        for e in ("bwrap", "podman", "docker"):
            if shutil.which(e) is None:
                continue
            if e != "bwrap":
                r = subprocess.run([e, "image", "inspect", isolation.default_image()], capture_output=True,
                                   env=isolation._client_env(), timeout=120)
                if r.returncode != 0:
                    continue
            if e == "bwrap" and not BWRAP:
                continue                                        # user namespaces denied: measured by the probe itself
            facts = isolation.probe(e)
            self.assertEqual(facts["engine"], e)
            self.assertIn(e, ENGINES_OK, ENGINES_WHY.get(e))

    def test_container_facts_closed(self):
        good = {"ifaces": ["lo"], "uid": 1000, "root_ro": True}
        isolation.check_container_facts("podman", good)              # positive control
        for bad in ({**good, "ifaces": ["lo", "eth0"]}, {**good, "ifaces": []}, {**good, "ifaces": None},
                    {**good, "uid": 0}, {**good, "uid": None}, {**good, "root_ro": False}, {**good, "root_ro": "yes"}, {}):
            with self.assertRaises(MP.SandboxMissing, msg=str(bad)):
                isolation.check_container_facts("podman", bad)

    def test_select_engine_with_every_probe_failing(self):
        probes = dict(isolation._PROBES)
        isolation._PROBES.clear()
        original, win = isolation.shutil.which, isolation._win
        isolation.shutil.which = lambda name: None
        isolation._win = _win_missing                 # appcontainer has no executable: its API made unavailable
        try:
            with self.assertRaises(MP.SandboxMissing) as cm:
                isolation.select_engine()
            for e in isolation.ENGINE_ORDER:
                self.assertIn(e, str(cm.exception))
        finally:
            isolation.shutil.which, isolation._win = original, win
            isolation._PROBES.update(probes)

    def test_wasm_writable_interpreter_folder_refused(self):
        d = tempfile.mkdtemp(prefix="pywasi_fake_")
        try:
            os.mkdir(os.path.join(d, "lib"))
            open(os.path.join(d, "python.wasm"), "wb").close()
            old = os.environ.get("RIGOROUS_LEVELS_PYTHON_WASM")
            os.environ["RIGOROUS_LEVELS_PYTHON_WASM"] = d
            try:
                if shutil.which("wasmtime") is None:
                    with self.assertRaises(MP.SandboxMissing):
                        isolation._wasm_parts()
                else:
                    with self.assertRaisesRegex(MP.SandboxMissing, "writable"):
                        isolation._wasm_parts()
            finally:
                if old is None:
                    os.environ.pop("RIGOROUS_LEVELS_PYTHON_WASM", None)
                else:
                    os.environ["RIGOROUS_LEVELS_PYTHON_WASM"] = old
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestEngineSelection(unittest.TestCase):
    def test_auto_picks_the_first_available_in_the_declared_order(self):
        if not ENGINES_OK:
            with self.assertRaises(MP.SandboxMissing):
                isolation.select_engine()
            return
        e, reasons = isolation.select_engine()
        self.assertEqual(e, ENGINES_OK[0])
        before = [x for x in isolation.ENGINE_ORDER if isolation.ENGINE_ORDER.index(x) < isolation.ENGINE_ORDER.index(e)]
        self.assertEqual(list(reasons), before)

    def test_unknown_engine_refused(self):
        with self.assertRaises(MP.OutOfDomain):
            MP.run_port(request("numpy_rotor"), engine="chroot")


class TestWasmChmodNoFollow20261120(unittest.TestCase):
    """0.3.0: _run_wasm made the work folder's files 0444 for the run and 0644 after it with os.chmod, which follows a
    symbolic link (os.walk lists a link to a file among the files): a link in the work folder pointing at a 0600 file
    of the user left that file 0644. The engine is replaced (probe and _run): every kind of entry, planted before the
    run or by the run itself, must leave what lies outside the work folder as it was. The modes expected are the ones
    read before the run (the umask decides the mode of request.json; on Windows os.chmod sets only the read-only flag:
    0600 reads 0666 there and a folder 0777): the victim and vdir unchanged, request.json 0444 during the run and its
    own mode again after it."""

    def _one(self, kind, when):
        from unittest import mock
        d = tempfile.mkdtemp()
        try:
            victim, vdir = os.path.join(d, "victim"), os.path.join(d, "vdir")
            with open(victim, "w") as f:
                f.write("x")
            os.mkdir(vdir)
            os.chmod(victim, 0o600)
            os.chmod(vdir, 0o700)
            work, outdir = os.path.join(d, "work"), os.path.join(d, "out")
            os.mkdir(work)
            os.mkdir(outdir)
            with open(os.path.join(work, "request.json"), "w") as f:
                f.write("{}")
            open(os.path.join(outdir, "output.json"), "wb").close()
            mode = lambda q: stat.S_IMODE(os.stat(q).st_mode)          # noqa: E731
            self.expected = (mode(victim), mode(vdir), 0o444, mode(os.path.join(work, "request.json")))

            def plant():
                p = os.path.join(work, "entry")
                if kind == "link_file":
                    os.symlink(victim, p)
                elif kind == "link_dir":
                    os.symlink(vdir, p)
                elif kind == "link_dangling":
                    os.symlink(os.path.join(d, "nothing"), p)
                elif kind == "link_inside":
                    os.symlink(os.path.join(work, "request.json"), p)
                elif kind == "fifo":
                    os.mkfifo(p)
                else:
                    with open(p, "w") as f:
                        f.write("y")
            modes_during = {}

            def fake_run(cmd, timeout, stderr_path, env):
                open(stderr_path, "wb").close()
                modes_during["request"] = stat.S_IMODE(os.stat(os.path.join(work, "request.json")).st_mode)
                if when == "during":
                    os.chmod(work, 0o755)
                    plant()
                    os.chmod(work, 0o555)
                return 0, False
            if when == "before":
                plant()
            facts = {"exe": "wasmtime", "folder": d, "version": [3, 12], "numpy": "-"}
            with mock.patch.object(isolation, "probe", return_value=facts), mock.patch.object(isolation, "_run", fake_run):
                isolation._run_wasm(work, os.path.join(outdir, "output.json"), 1, [], os.path.join(d, "stderr_copy.txt"))
            return (stat.S_IMODE(os.stat(victim).st_mode), stat.S_IMODE(os.stat(vdir).st_mode), modes_during["request"],
                    stat.S_IMODE(os.stat(os.path.join(work, "request.json")).st_mode))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_every_kind_of_entry(self):
        d = tempfile.mkdtemp()
        try:
            os.symlink(d, os.path.join(d, "l"))
            links = True
        except (OSError, NotImplementedError):                  # Windows without the right to make links
            links = False
        finally:
            shutil.rmtree(d, ignore_errors=True)
        kinds = ["regular"] + (["link_file", "link_dir", "link_dangling", "link_inside"] if links else []) \
            + (["fifo"] if hasattr(os, "mkfifo") else [])
        n = 0
        for kind in kinds:
            for when in ("before", "during"):
                with self.subTest(kind=kind, when=when):
                    self.assertEqual(self._one(kind, when), self.expected)
                n += 1
        self.assertEqual(n, 2 * len(kinds))
        if os.name == "posix":
            self.assertEqual(len(kinds), 6)                     # on POSIX no kind may drop out

    def test_name_swapped_after_lstat_is_not_followed(self):
        """the name is checked with lstat, then opened with O_NOFOLLOW | O_NONBLOCK and changed through the descriptor
        only if it is the same regular file: a link, a hard link to another file or a FIFO put there in between (and a
        descriptor that is not a regular file) is left alone, and nothing blocks"""
        if not (getattr(os, "O_NOFOLLOW", 0) and hasattr(os, "fchmod") and hasattr(os, "mkfifo")):
            self.skipTest("no O_NOFOLLOW / fchmod / mkfifo here: lstat + chmod")
        import threading
        from unittest import mock
        for swap in ("symlink", "hardlink", "fifo", "fstat_not_regular"):
            d = tempfile.mkdtemp()
            try:
                victim, p = os.path.join(d, "victim"), os.path.join(d, "f")
                for q in (victim, p):
                    with open(q, "w") as f:
                        f.write("x")
                os.chmod(victim, 0o600)
                os.chmod(p, 0o600)
                real_lstat, real_fstat = os.lstat, os.fstat

                def lstat_then_swap(path, *a, **k):
                    st = real_lstat(path, *a, **k)
                    if path == p and swap != "fstat_not_regular":
                        os.unlink(p)
                        {"symlink": lambda: os.symlink(victim, p), "hardlink": lambda: os.link(victim, p),
                         "fifo": lambda: os.mkfifo(p)}[swap]()
                    return st

                def fstat_fifo(fd):
                    st = real_fstat(fd)
                    return os.stat_result((stat.S_IFIFO | 0o600,) + tuple(st)[1:])
                done = []

                def call():
                    with mock.patch.object(isolation.os, "lstat", lstat_then_swap), \
                            mock.patch.object(isolation.os, "fstat", fstat_fifo if swap == "fstat_not_regular" else real_fstat):
                        isolation._chmod_regular_file(p, 0o644)
                    done.append(True)
                t = threading.Thread(target=call, daemon=True)
                t.start()
                t.join(10)
                with self.subTest(swap=swap):
                    self.assertEqual(done, [True], "blocked on the name swapped in")
                    self.assertEqual(stat.S_IMODE(real_lstat(victim).st_mode), 0o600)
                    if swap == "fstat_not_regular":
                        self.assertEqual(stat.S_IMODE(real_lstat(p).st_mode), 0o600)
            finally:
                if os.path.exists(p) and stat.S_ISFIFO(os.lstat(p).st_mode):
                    os.unlink(p)
                shutil.rmtree(d, ignore_errors=True)

    def test_opens_only_regular_files_never_following_and_changes_through_the_descriptor(self):
        """a name gone before the lstat is skipped; os.open is called only on regular files, always with O_NOFOLLOW;
        a link swapped in after the fstat is not what changes (the change goes through the descriptor)"""
        if not (getattr(os, "O_NOFOLLOW", 0) and hasattr(os, "fchmod") and hasattr(os, "mkfifo")):
            self.skipTest("no O_NOFOLLOW / fchmod / mkfifo here: lstat + chmod")
        from unittest import mock
        d = tempfile.mkdtemp()
        try:
            isolation._chmod_regular_file(os.path.join(d, "gone"), 0o644)        # no exception
            victim = os.path.join(d, "victim")
            with open(victim, "w") as f:
                f.write("x")
            os.chmod(victim, 0o600)
            names = {}
            for kind in ("regular", "link", "fifo"):
                q = os.path.join(d, kind)
                if kind == "regular":
                    with open(q, "w") as f:
                        f.write("y")
                elif kind == "link":
                    os.symlink(victim, q)
                else:
                    os.mkfifo(q)
                names[kind] = q
            opened, real_open = [], os.open

            def rec_open(path, flags, *a, **k):
                opened.append((path, flags))
                return real_open(path, flags, *a, **k)
            with mock.patch.object(isolation.os, "open", rec_open):
                for q in names.values():
                    isolation._chmod_regular_file(q, 0o640)
            self.assertEqual([x[0] for x in opened], [names["regular"]])
            self.assertTrue(all(fl & os.O_NOFOLLOW for _, fl in opened))
            self.assertEqual(stat.S_IMODE(os.stat(names["regular"]).st_mode), 0o640)
            # swap after the fstat: the regular file becomes a link to the victim before the change
            real_fstat, q = os.fstat, names["regular"]

            def fstat_then_swap(fd):
                st = real_fstat(fd)
                os.unlink(q)
                os.symlink(victim, q)
                return st
            with mock.patch.object(isolation.os, "fstat", fstat_then_swap):
                isolation._chmod_regular_file(q, 0o644)
            self.assertEqual(stat.S_IMODE(os.stat(victim).st_mode), 0o600)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestWasmHardLinkAndStderr20261120(unittest.TestCase):
    """Review of the change above (20/11/2026), the engine replaced in the same way. A HARD link in the work folder to a
    0600 file of the user is a regular file: the first version of _chmod_regular_file left that file 0644. And the
    folder the run can write (/out) holds stderr.txt, which _run_wasm copied with shutil.copy: a link there was
    followed (the user's file copied), and a missing file, a folder or a FIFO raised out of _run_wasm."""

    def _run(self, plant_work=None, plant_out=None, before=None):
        from unittest import mock
        from rigorous_levels import isolation
        d = tempfile.mkdtemp()
        try:
            victim = os.path.join(d, "victim")
            with open(victim, "w") as f:
                f.write("SECRET-OF-THE-USER\n")
            os.chmod(victim, 0o600)
            work, outdir = os.path.join(d, "work"), os.path.join(d, "out")
            os.mkdir(work)
            os.mkdir(outdir)
            with open(os.path.join(work, "request.json"), "w") as f:
                f.write("{}")
            open(os.path.join(outdir, "output.json"), "wb").close()
            self.victim0 = stat.S_IMODE(os.stat(victim).st_mode)           # 0o600 (Windows: 0o666, the flag only)
            self.request0 = stat.S_IMODE(os.stat(os.path.join(work, "request.json")).st_mode)   # the umask decides
            if before:
                before(work, victim)

            def fake_run(cmd, timeout, stderr_path, env):
                with open(stderr_path, "wb") as f:
                    f.write(b"true stderr\n")
                if plant_work:
                    os.chmod(work, 0o755)
                    plant_work(work, victim)
                    os.chmod(work, 0o555)
                if plant_out:
                    plant_out(outdir, victim)
                return 0, False
            copy = os.path.join(d, "stderr_copy.txt")
            facts = {"exe": "wasmtime", "folder": d, "version": [3, 12], "numpy": "-"}
            with mock.patch.object(isolation, "probe", return_value=facts), mock.patch.object(isolation, "_run", fake_run):
                isolation._run_wasm(work, os.path.join(outdir, "output.json"), 1, [], copy)
            with open(copy, "rb") as f:
                copied = f.read()
            return (stat.S_IMODE(os.stat(victim).st_mode), stat.S_IMODE(os.stat(os.path.join(work, "request.json")).st_mode), copied)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_control_and_hard_link_in_the_work_folder(self):
        self.assertEqual(self._run(), (self.victim0, self.request0, b"true stderr\n"))
        if not hasattr(os, "link"):
            self.skipTest("no os.link here")
        hard = lambda w, v: os.link(v, os.path.join(w, "hl"))        # noqa: E731
        for when in ("before", "during"):
            with self.subTest(when=when):
                r = self._run(before=hard) if when == "before" else self._run(plant_work=hard)
                self.assertEqual(r, (self.victim0, self.request0, b"true stderr\n"))

    def test_second_name_made_after_the_lstat(self):
        from unittest import mock
        from rigorous_levels import isolation
        if not (getattr(os, "O_NOFOLLOW", 0) and hasattr(os, "fchmod") and hasattr(os, "link")):
            self.skipTest("no O_NOFOLLOW / fchmod / link here")
        d = tempfile.mkdtemp()
        try:
            p, other = os.path.join(d, "f"), os.path.join(d, "second_name")
            with open(p, "w") as f:
                f.write("x")
            os.chmod(p, 0o600)
            real_lstat = os.lstat

            def lstat_then_second_name(path, *a, **k):       # one name at the lstat, two at the fstat
                st = real_lstat(path, *a, **k)
                if path == p and not os.path.exists(other):
                    os.link(p, other)
                return st
            with mock.patch.object(isolation.os, "lstat", lstat_then_second_name):
                isolation._chmod_regular_file(p, 0o644)
            self.assertEqual(stat.S_IMODE(real_lstat(p).st_mode), 0o600)
            os.unlink(other)
            isolation._chmod_regular_file(p, 0o640)             # control: with one name the mode changes
            self.assertEqual(stat.S_IMODE(real_lstat(p).st_mode), 0o640)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_stderr_of_the_run_is_read_only_as_a_regular_file_with_one_name(self):
        note = b"[rigorous-levels] the stderr file of the run was not read: "
        err = lambda o: os.path.join(o, "stderr.txt")               # noqa: E731

        def swap(make):
            def f(o, v):
                os.remove(err(o))
                make(o, v)
            return f
        not_regular, two_names = b"not a regular file\n", b"not a regular file with one name, or changed between the check and the open\n"
        cases = {"removed": (swap(lambda o, v: None), b"FileNotFoundError\n"), "folder": (swap(lambda o, v: os.mkdir(err(o))), not_regular)}
        d = tempfile.mkdtemp()
        try:
            os.symlink(d, os.path.join(d, "l"))
            cases["symlink"] = (swap(lambda o, v: os.symlink(v, err(o))), not_regular)
            cases["symlink_dangling"] = (swap(lambda o, v: os.symlink(os.path.join(o, "nothing"), err(o))), not_regular)
        except (OSError, NotImplementedError):                      # Windows without the right to make links
            pass
        finally:
            shutil.rmtree(d, ignore_errors=True)
        if hasattr(os, "link"):
            cases["hard_link"] = (swap(lambda o, v: os.link(v, err(o))), two_names)
        if hasattr(os, "mkfifo"):
            cases["fifo"] = (swap(lambda o, v: os.mkfifo(err(o))), not_regular)
        if os.name == "posix":
            self.assertEqual(len(cases), 6)                         # on POSIX no case may drop out
        import threading
        for name, (plant, why) in cases.items():
            got = []
            t = threading.Thread(target=lambda: got.append(self._run(plant_out=plant)), daemon=True)
            t.start()
            t.join(20)
            with self.subTest(case=name):
                self.assertEqual(len(got), 1, "blocked, or an exception left _run_wasm")
                mode, _, copied = got[0]
                self.assertEqual(mode, self.victim0)
                self.assertNotIn(b"SECRET", copied)
                self.assertEqual(copied, note + why)

    def test_where_o_nofollow_is_missing_and_a_name_swapped_after_the_lstat(self):
        """without O_NOFOLLOW (Windows) the lstat decides: a symbolic or hard link is not changed and not read; and the
        file opened must be the one the lstat saw, still a regular file"""
        from unittest import mock
        from rigorous_levels import isolation
        if not (hasattr(os, "symlink") and hasattr(os, "link") and os.name == "posix"):
            self.skipTest("links needed")
        note = b"[rigorous-levels] the stderr file of the run was not read: "
        d = tempfile.mkdtemp()
        try:
            victim, reg, hl, sl, dst = (os.path.join(d, n) for n in ("victim", "reg", "hl", "sl", "dst"))
            with open(victim, "w") as f:
                f.write("SECRET-OF-THE-USER\n")
            with open(reg, "w") as f:
                f.write("true stderr\n")
            os.chmod(victim, 0o600)
            os.chmod(reg, 0o600)
            os.link(victim, hl)
            os.symlink(victim, sl)
            real_lstat, real_fstat = os.lstat, os.fstat

            def read(src):
                if os.path.lexists(dst):
                    os.unlink(dst)                      # nothing left from the call before
                isolation._copy_run_stderr(src, dst)
                with open(dst, "rb") as f:
                    return f.read()
            opened, real_open = [], os.open

            def rec_open(path, flags, *a, **k):
                opened.append(flags)
                return real_open(path, flags, *a, **k)
            with mock.patch.object(isolation.os, "open", rec_open):
                self.assertEqual(read(reg), b"true stderr\n")
            self.assertEqual(len(opened), 2)                # the run's stderr file, then the copy (§6.7)
            self.assertTrue(opened[0] & os.O_NOFOLLOW and opened[0] & os.O_NONBLOCK, opened)
            self.assertTrue(opened[1] & os.O_NOFOLLOW and not opened[1] & os.O_TRUNC, opened)
            with mock.patch.object(isolation.os, "O_NOFOLLOW", 0):
                for q in (hl, sl, reg):
                    isolation._chmod_regular_file(q, 0o644)
                self.assertEqual(stat.S_IMODE(real_lstat(victim).st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(real_lstat(reg).st_mode), 0o644)     # control
                self.assertEqual(read(reg), b"true stderr\n")                      # control
                for q in (sl, hl):
                    got = read(q)
                    self.assertTrue(got.startswith(note) and b"SECRET" not in got, got)

                os.unlink(hl)                               # the victim has one name again

                def lstat_then_link(path, *a, **k):         # a regular file at the lstat, a link to the victim at the open
                    st = real_lstat(path, *a, **k)
                    if path == reg:
                        os.unlink(reg)
                        os.symlink(victim, reg)
                    return st
                with mock.patch.object(isolation.os, "lstat", lstat_then_link):
                    got = read(reg)
                self.assertTrue(got.startswith(note) and b"SECRET" not in got, got)
            os.unlink(reg)
            with open(reg, "w") as f:
                f.write("true stderr\n")

            reg_id = (real_lstat(reg).st_dev, real_lstat(reg).st_ino)

            def fstat_fifo(fd):                             # the same inode, no longer a regular file (the source only)
                st = real_fstat(fd)
                if (st.st_dev, st.st_ino) != reg_id:
                    return st
                return os.stat_result((stat.S_IFIFO | 0o600,) + tuple(st)[1:])
            with mock.patch.object(isolation.os, "fstat", fstat_fifo):
                got = read(reg)
            self.assertTrue(got.startswith(note), got)
            self.assertEqual(read(reg), b"true stderr\n")                          # control
        finally:
            shutil.rmtree(d, ignore_errors=True)


def isolation_status_time():
    """POSIX: st_ctime is the status-change time (on Windows the creation time)"""
    return os.name == "posix"


class TestWorkFolderClosed20261120(unittest.TestCase):
    """docs/PORT_CONTRACT.md §6.7 (rule of 2026-11-20): the work folder is read-only for the port, so after the run any
    entry the host did not put there, and any change to one it did, makes the outputs ERROR with a reason naming them.
    Up to 0.3.0 such entries were ignored and then removed by shutil.rmtree (measured: 23 of 23 cases OK, the output
    accepted). The engine is replaced (_run_engine): it writes a valid output, then plants or changes something in the
    work folder, as a run able to write into /work would."""

    HEAD = "work folder changed during the run (it is read-only for the port): "

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.victim = os.path.join(self.d, "victim")
        with open(self.victim, "wb") as f:                      # bytes: no \r\n on Windows
            f.write(b"SECRET-OF-THE-USER\n")
        os.chmod(self.victim, 0o600)
        self.victim_mode = stat.S_IMODE(os.stat(self.victim).st_mode)   # 0o600 (Windows: 0o666, the read-only flag only)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    @staticmethod
    def _req(port="numpy_rotor"):
        return MP.Request(port=port, model=ROTOR, levels=6, truncation={"ncut": 30}, unit="GHz", seconds=5, mem_mib=256,
                          site_packages=())

    def _go(self, plant, batch=0, timed_out=False, limit="", output=True):
        """run_port (or run_ports with `batch` requests) through the replaced engine; returns the outputs"""
        from unittest import mock
        from rigorous_levels import isolation
        works = []

        def engine(eng, work, out_path, seconds, mem_mib, site_packages, python, image):
            works.append(work)
            with open(os.path.join(work, "stderr.txt"), "wb") as f:      # what the host writes during the run
                f.write(b"stderr of the run\n")
            one = {"contract": MP.CONTRACT, "port": "numpy_rotor", "solver_version": "x", "levels": [1.0] * 6,
                   "unit": "GHz", "state": "OK", "reason": "", "seconds": 0.1}
            if output:
                with open(out_path, "w") as f:
                    json.dump([one] * batch if batch else one, f)
            plant(work)
            return (0, False, "replaced engine", limit) if not timed_out else (None, True, "replaced engine", limit)
        with mock.patch.object(isolation, "probe", return_value={}), mock.patch.object(isolation, "_run_engine", engine):
            if batch:
                outs = MP.run_ports([self._req()] * batch, engine="bwrap")
            else:
                outs = (MP.run_port(self._req(), engine="bwrap"),)
        self.assertEqual(len(works), 1)
        self.assertFalse(os.path.lexists(works[0]), "the work folder is removed after the run")
        return outs

    def _kinds(self):
        """(name in the reason, plant) for every kind of entry this platform can make"""
        v, vd = self.victim, self.d
        k = [("'new.txt': file the host did not put there", lambda w: open(os.path.join(w, "new.txt"), "w").close()),
             ("'.hidden': file", lambda w: open(os.path.join(w, ".hidden"), "w").close()),
             ("'dir': folder", lambda w: os.mkdir(os.path.join(w, "dir"))),
             ("'d2': folder", lambda w: (os.mkdir(os.path.join(w, "d2")), open(os.path.join(w, "d2", "f"), "w").close())),
             ("'output.json': missing", lambda w: os.unlink(os.path.join(w, "output.json"))),
             ("'request.json': size", lambda w: self._append(os.path.join(w, "request.json"))),
             ("'request.json': modification time changed", lambda w: os.utime(os.path.join(w, "request.json"), (1, 1))),
             ("'port_runner.py': inode changed", lambda w: self._replace(w, "port_runner.py")),
             ("'request.json': content changed", lambda w: self._same_size(w, "request.json")),
             ("the folder: modification time changed (an entry was created or removed)", self._create_remove),
             ("'stderr.txt': missing", lambda w: os.unlink(os.path.join(w, "stderr.txt"))),
             ("'été ☃': file", lambda w: open(os.path.join(w, "été ☃"), "w").close())]
        if os.name == "posix":
            k += [("'port_runner.py': mode 0o", self._other_mode),
                  ("the folder: mode 0o", lambda w: os.chmod(w, 0o777))]
            try:
                p = os.path.join(os.fsencode(self.d), b"probe\xff")
                open(p, "w").close()
                os.unlink(p)
                k.append(("b'bad\\xff\\xfe': file", lambda w: open(os.path.join(os.fsencode(w), b"bad\xff\xfe"), "w").close()))
            except OSError:                                          # a file system that refuses such names
                pass
        if hasattr(os, "symlink"):
            try:
                os.symlink(v, os.path.join(vd, "probe_link"))
                os.unlink(os.path.join(vd, "probe_link"))
                k += [("'link': symbolic link", lambda w: os.symlink(v, os.path.join(w, "link"))),
                      ("'dangling': symbolic link", lambda w: os.symlink(os.path.join(vd, "none"), os.path.join(w, "dangling"))),
                      ("'dlink': symbolic link", lambda w: os.symlink(vd, os.path.join(w, "dlink"))),
                      ("'stderr.txt': kind changed", lambda w: (os.unlink(os.path.join(w, "stderr.txt")),
                                                               os.symlink(v, os.path.join(w, "stderr.txt"))))]
            except (OSError, NotImplementedError):                   # Windows without the right to make links
                pass
        if hasattr(os, "link"):
            k += [("'hard': hard link (a file with 2 names)", lambda w: os.link(v, os.path.join(w, "hard"))),
                  ("'request.json': names 1 -> 2", lambda w: os.link(os.path.join(w, "request.json"),
                                                                     os.path.join(vd, "second_" + os.path.basename(w))))]
        if hasattr(os, "mkfifo"):
            k.append(("'fifo': FIFO", lambda w: os.mkfifo(os.path.join(w, "fifo"))))
        if hasattr(socket, "AF_UNIX") and os.name == "posix":
            k.append(("'sock': socket", self._socket))
        return k

    @staticmethod
    def _socket(w):
        s, here = socket.socket(socket.AF_UNIX), os.getcwd()
        os.chdir(w)                                              # AF_UNIX paths are short
        try:
            s.bind("sock")
        finally:
            os.chdir(here)
            s.close()

    @staticmethod
    def _other_mode(w):
        """a mode the host did not give port_runner.py (the umask decides that one: 0666 with umask 000)"""
        p = os.path.join(w, "port_runner.py")
        os.chmod(p, 0o640 if stat.S_IMODE(os.lstat(p).st_mode) != 0o640 else 0o600)

    @staticmethod
    def _append(p):
        with open(p, "a") as f:
            f.write(" ")

    @staticmethod
    def _create_remove(w):
        p = os.path.join(w, "tmp_entry")
        open(p, "w").close()
        os.unlink(p)

    @staticmethod
    def _replace(w, n):
        p = os.path.join(w, n)
        with open(p, "rb") as f:
            b = f.read()
        with open(p + ".new", "wb") as f:
            f.write(b)
        shutil.copymode(p, p + ".new")                           # the same mode: only the inode and the times differ
        os.replace(p + ".new", p)

    @staticmethod
    def _same_size(w, n):
        p = os.path.join(w, n)
        st = os.lstat(p)
        with open(p, "r+b") as f:
            b = f.read()
            f.seek(0)
            f.write(bytes([b[0] ^ 1]) + b[1:])
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))

    def test_control_nothing_changed(self):
        u, = self._go(lambda w: None)
        self.assertEqual((u.state, u.reason), ("OK", ""))

    def test_runner_copied_without_the_mode_of_the_installed_file(self):
        """port_runner.py is copied into the work folder with its content only (shutil.copyfile): its mode is the one
        the umask gives, as for request.json, not the mode of the installed file (0.3.1 before the CI of 2026-11-22:
        shutil.copy, so a package installed with umask 000 put a runner 0666 there and one installed 0755 an
        executable one)"""
        from unittest import mock
        src = os.path.join(self.d, "installed_runner.py")
        shutil.copyfile(MP.RUNNER, src)
        modes = {}

        def look(w):
            for n in ("port_runner.py", "request.json"):
                modes[n] = stat.S_IMODE(os.lstat(os.path.join(w, n)).st_mode)
            with open(os.path.join(w, "port_runner.py"), "rb") as f, open(MP.RUNNER, "rb") as g:
                modes["same content"] = f.read() == g.read()
        for installed in (0o755, 0o666, 0o600):
            with self.subTest(installed=oct(installed)):
                os.chmod(src, installed)
                with mock.patch.object(MP, "RUNNER", src):
                    u, = self._go(look)
                self.assertEqual((u.state, u.reason), ("OK", ""))
                self.assertTrue(modes["same content"])
                self.assertEqual(modes["port_runner.py"], modes["request.json"])

    def test_every_kind_of_entry_and_change_is_named(self):
        kinds = self._kinds()
        if os.name == "posix" and sys.platform.startswith("linux"):
            self.assertEqual(len(kinds), 23)                      # on Linux no kind may drop out
        for named, plant in kinds:
            with self.subTest(named=named):
                u, = self._go(plant)
                self.assertEqual(u.state, "ERROR", u)
                self.assertTrue(u.reason.startswith(self.HEAD), u.reason)
                self.assertIn(named, u.reason)
                self.assertEqual(u.levels, ())
        self.assertEqual(stat.S_IMODE(os.stat(self.victim).st_mode), self.victim_mode)
        with open(self.victim) as f:
            self.assertEqual(f.read(), "SECRET-OF-THE-USER\n")

    def test_batch_timeout_and_cap_precedence(self):
        plant = lambda w: open(os.path.join(w, "x"), "w").close()     # noqa: E731
        outs = self._go(plant, batch=3)
        self.assertEqual([o.state for o in outs], ["ERROR"] * 3)
        self.assertTrue(all(o.reason.startswith(self.HEAD + "'x': file") for o in outs), outs)
        u, = self._go(plant, timed_out=True)                      # before the timeout
        self.assertEqual(u.state, "ERROR")
        self.assertIn("'x': file", u.reason)
        u, = self._go(plant, limit="memory: over the cap (host watchdog)")
        self.assertEqual(u.state, "ERROR")
        self.assertTrue(u.reason.startswith(self.HEAD) and u.reason.endswith("; memory: over the cap (host watchdog)"))
        u, = self._go(lambda w: None, timed_out=True)             # control: the timeout alone
        self.assertEqual(u.state, "INVALID")

    def test_many_entries_first_twenty_named_and_the_others_counted(self):
        names = [f"e{i:03d}" for i in range(57)]

        def plant(w):
            for n in reversed(names):
                open(os.path.join(w, n), "w").close()
        u, = self._go(plant)
        self.assertEqual(u.state, "ERROR")
        for n in names[:20]:
            self.assertIn(f"'{n}': file", u.reason)
        for n in names[20:]:
            self.assertNotIn(f"'{n}'", u.reason)
        tail = "modification time changed (an entry was created or removed); and 37 more"
        # APFS (macOS) counts every entry of a folder in its number of names: 4 entries + 2 before the run, 57 more after
        self.assertTrue(u.reason.endswith("; the folder: " + tail)
                        or (sys.platform == "darwin" and u.reason.endswith("; the folder: names 6 -> 63, " + tail)),
                        u.reason[-120:])

    def test_named_and_counted_whatever_order_the_folder_lists(self):
        """the same 57 entries listed in ascending, descending and a shuffled order (file systems differ: btrfs lists
        in order of creation): the same reason each time"""
        import random
        from unittest import mock
        from rigorous_levels import isolation
        w = tempfile.mkdtemp(dir=self.d)
        open(os.path.join(w, "request.json"), "w").close()
        before = isolation.work_snapshot(w)
        names = [f"e{i:03d}".encode() for i in range(57)]
        for n in names:
            open(os.path.join(os.fsencode(w), n), "w").close()
        real = os.scandir
        shuffled = list(names)
        random.Random(7).shuffle(shuffled)
        reasons = set()
        for order in (sorted(names), sorted(names, reverse=True), shuffled):
            def listing(path, order=order):
                entries = {e.name: e for e in real(path)}
                ordered = [entries[n] for n in order] + [e for n, e in entries.items() if n not in order]

                class It:
                    def __enter__(self):
                        return iter(ordered)

                    def __exit__(self, *a):
                        return False
                return It()
            with mock.patch.object(isolation.os, "scandir", listing):
                reasons.add(isolation.work_changes(w, before))
        self.assertEqual(len(reasons), 1, reasons)
        r = reasons.pop()
        self.assertTrue(r.endswith("; and 37 more"), r[-80:])
        self.assertIn("'e019': file", r)
        self.assertNotIn("'e020'", r)

    def test_content_read_only_from_the_file_recorded(self):
        """the content is hashed only if the descriptor is the file lstat saw (device and inode)"""
        from rigorous_levels import isolation
        a, b = os.path.join(self.d, "a"), os.path.join(self.d, "b")
        for q in (a, b):
            with open(q, "w") as f:
                f.write("same\n")
        self.assertEqual(isolation._content_sha256(os.fsencode(a), os.lstat(a)),
                         isolation._content_sha256(os.fsencode(b), os.lstat(b)))           # control: same bytes
        self.assertEqual(isolation._content_sha256(os.fsencode(a), os.lstat(b)), "not the same regular file")

    def test_generative(self):
        """seeded random sets of 0-4 changes from the pool, names drawn from a closed alphabet (hidden, case, UTF-8,
        long): ERROR exactly when a change was made, and every change named while at most 20 differences exist"""
        import random
        rng = random.Random(20261120)
        pool = self._kinds()
        alphabet = ["a", "Z", ".", "_", "-", " ", "é", "☃", "0"]
        runs = errors = 0
        for _ in range(60):
            picks = rng.sample(pool, rng.randint(0, 4))
            fresh = ["".join(rng.choice(alphabet) for _ in range(rng.randint(1, 40))) for _ in range(rng.randint(0, 3))]
            fresh = [n for n in dict.fromkeys(fresh) if n not in (".", "..") and n.strip()
                     and n not in ("request.json", "port_runner.py", "output.json", "stderr.txt")
                     and not (os.name == "nt" and n[-1] in " .")]   # Windows drops a final space or period of a name

            def plant(w, picks=picks, fresh=fresh):
                for _, p in picks:
                    p(w)
                for n in fresh:
                    q = os.path.join(w, n)
                    if not os.path.lexists(q):
                        open(q, "w").close()
            u, = self._go(plant)
            runs += 1
            changed = bool(picks or fresh)
            self.assertEqual(u.state, "ERROR" if changed else "OK", (picks, fresh, u.reason))
            errors += u.state == "ERROR"
            for named, _ in picks:
                if "names 1 -> 2" in named and any("'request.json'" in n2 for n2, _ in picks if n2 != named):
                    continue                                       # another change to the same entry comes first
                self.assertIn(named.split(":")[0], u.reason)
            for n in fresh:
                self.assertIn(repr(n)[:77], u.reason)
            for f in os.listdir(self.d):                           # second names made outside: removed each time
                if f.startswith("second_"):
                    os.unlink(os.path.join(self.d, f))
        self.assertEqual(runs, 60)
        self.assertGreater(errors, 40)

    def test_changes_undone_are_seen_through_the_status_time(self):
        """POSIX: a change undone before the run ends still moves the status-change time (st_ctime), which a process
        cannot set back: an entry created and removed with the folder's time set back, content changed and set back
        with its time, a second name made and removed, the access time changed, an extended attribute (where the file
        system has them). On 439a6b5 all of them gave OK."""
        if not isolation_status_time():
            self.skipTest("no status-change time here (Windows: st_ctime is the creation time)")

        def folder_back(w):
            st = os.lstat(w)
            self._create_remove(w)
            os.utime(w, ns=(st.st_atime_ns, st.st_mtime_ns))

        def content_back(w):
            p = os.path.join(w, "port_runner.py")
            st = os.lstat(p)
            with open(p, "rb") as f:
                b = f.read()
            with open(p, "r+b") as f:
                f.write(b"#")
            with open(p, "r+b") as f:
                f.write(b[:1])
            os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))

        def second_name(w):
            q = os.path.join(self.d, "second")
            os.link(os.path.join(w, "request.json"), q)
            os.unlink(q)

        def access_time(w):
            p = os.path.join(w, "request.json")
            st = os.lstat(p)
            os.utime(p, ns=(st.st_atime_ns + 10 ** 9, st.st_mtime_ns))
        cases = [("the folder: status-change time changed", folder_back),
                 ("'port_runner.py': status-change time changed", content_back),
                 ("'request.json': status-change time changed", access_time)]
        if hasattr(os, "link"):
            cases.append(("'request.json': status-change time changed", second_name))
        if hasattr(os, "setxattr"):
            probe = os.path.join(self.d, "xattr_probe")
            open(probe, "w").close()
            try:
                os.setxattr(probe, "user.x", b"1")
                cases.append(("'request.json': status-change time changed",
                              lambda w: os.setxattr(os.path.join(w, "request.json"), "user.x", b"1")))
                cases.append(("the folder: status-change time changed", lambda w: os.setxattr(w, "user.x", b"1")))
            except OSError:                                       # a file system without user attributes
                pass
        for named, plant in cases:
            with self.subTest(named=named):
                u, = self._go(plant)
                self.assertEqual(u.state, "ERROR", u)
                self.assertIn(self.HEAD + named, u.reason)
        if sys.platform.startswith("linux"):
            self.assertGreaterEqual(len(cases), 4)
        u, = self._go(lambda w: None)                             # control
        self.assertEqual((u.state, u.reason), ("OK", ""))
        u, = self._go(lambda w: os.listdir(w))                    # control: reading changes no status time
        self.assertEqual(u.state, "OK")

    def test_change_right_after_the_record_is_seen(self):
        """work_snapshot returns only when the file system clock has passed what it recorded: a change made at once,
        in the same coarse tick, still moves the status-change time (100 runs, no pause)"""
        from rigorous_levels import isolation
        if not isolation_status_time():
            self.skipTest("no status-change time here")
        seen = 0
        for _ in range(100):
            w = tempfile.mkdtemp(dir=self.d)
            for n in ("request.json", "stderr.txt"):
                open(os.path.join(w, n), "w").close()
            before = isolation.work_snapshot(w)
            os.setxattr(w, "user.y", b"1") if hasattr(os, "setxattr") and self._xattr_ok(w) else os.chmod(w, 0o700)
            seen += isolation.work_changes(w, before) != ""
        self.assertEqual(seen, 100)

    @staticmethod
    def _xattr_ok(w):
        try:
            os.setxattr(w, "user.probe", b"1")
            os.removexattr(w, "user.probe")
            return True
        except OSError:
            return False

    def test_wasm_status_time(self):
        """wasm: the host changes the modes around the run, so the status-change times are recorded after that change
        and read again before the modes are set back"""
        from unittest import mock
        from rigorous_levels import isolation
        if not isolation_status_time():
            self.skipTest("no status-change time here")
        for change in (None, "content_back", "folder_back", "new_entry"):
            w, outdir = tempfile.mkdtemp(dir=self.d), tempfile.mkdtemp(dir=self.d)
            for n in ("request.json", isolation.RUNNER_NAME, "output.json"):
                with open(os.path.join(w, n), "w") as f:
                    f.write("x")
            open(os.path.join(outdir, "output.json"), "w").close()

            def fake_run(cmd, timeout, stderr_path, env, w=w, change=change):
                open(stderr_path, "wb").close()
                if change == "content_back":
                    p = os.path.join(w, "request.json")
                    st = os.lstat(p)
                    os.chmod(p, 0o644)
                    with open(p, "w") as f:
                        f.write("x")
                    os.chmod(p, 0o444)
                    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
                elif change == "new_entry":                       # a difference of its own and a status change
                    os.chmod(w, 0o755)
                    open(os.path.join(w, "new"), "w").close()
                    os.chmod(w, 0o555)
                elif change == "folder_back":
                    st = os.lstat(w)
                    os.chmod(w, 0o755)
                    self._create_remove(w)
                    os.chmod(w, 0o555)
                    os.utime(w, ns=(st.st_atime_ns, st.st_mtime_ns))
                return 0, False
            facts = {"exe": "wasmtime", "folder": self.d, "version": [3, 12], "numpy": "-"}
            with mock.patch.object(isolation, "probe", return_value=facts), mock.patch.object(isolation, "_run", fake_run):
                limit = isolation.run("wasm", w, os.path.join(outdir, "output.json"), 1, 1, [])[3]
            with self.subTest(change=change):
                self.assertLessEqual(limit.count(self.HEAD), 1)
                if change is None:
                    self.assertEqual(limit, "")
                elif change == "content_back":
                    self.assertEqual(limit, self.HEAD + "'request.json': " + isolation._STATUS_WORDS)
                elif change == "new_entry":
                    self.assertTrue(limit.startswith(self.HEAD + "'new': file the host did not put there"), limit)
                    self.assertNotIn(isolation._STATUS_WORDS, limit)
                else:
                    self.assertEqual(limit, self.HEAD + "the folder: " + isolation._STATUS_WORDS)

    def test_content_read_only_up_to_the_recorded_size(self):
        """a recorded file made larger is a difference and is not read (before: read to its end, 4 GiB sparse in 4 s)"""
        from unittest import mock
        from rigorous_levels import isolation
        w = tempfile.mkdtemp(dir=self.d)
        with open(os.path.join(w, "request.json"), "w") as f:
            f.write("{}")
        before = isolation.work_snapshot(w)
        with open(os.path.join(w, "request.json"), "r+b") as f:
            f.truncate(1 << 30)
        got, real = [], os.read

        def rd(fd, n):
            b = real(fd, n)
            got.append(len(b))
            return b
        with mock.patch.object(isolation.os, "read", rd):
            r = isolation.work_changes(w, before)
        self.assertIn("'request.json': size 2 -> 1073741824", r)
        self.assertLessEqual(sum(got), 3)                         # nothing beyond the recorded size (+1 to see the end)
        a = os.path.join(self.d, "grow")
        with open(a, "w") as f:
            f.write("abc")
        st = os.lstat(a)
        with open(a, "a") as f:
            f.write("d")                                          # grew after the lstat: not hashed
        self.assertTrue(isolation._content_sha256(os.fsencode(a), st).startswith("not read to the end"))

    def test_stderr_tail_read_only_from_the_file_checked(self):
        """the tail of <work>/stderr.txt in the reason of an output without levels: never through a link put there
        after the check (before: the last bytes of the user's file were in the reason)"""
        from unittest import mock
        from rigorous_levels import isolation
        if not (hasattr(os, "symlink") and os.name == "posix"):
            self.skipTest("links")
        real = isolation.work_changes

        def then_swap(work, before, *a, **k):
            r = real(work, before, *a, **k)
            p = os.path.join(work, "stderr.txt")
            os.unlink(p)
            os.symlink(self.victim, p)
            return r
        u, = self._go(lambda w: None)                             # control
        self.assertEqual(u.state, "OK")
        for batch in (0, 2):                                      # run_port and run_ports: "no output (…): <tail>"
            with mock.patch.object(isolation, "work_changes", then_swap):
                outs = self._go(lambda w: None, batch=batch, output=False)
            self.assertTrue(all(o.state == "INVALID" and o.reason.startswith("no output") for o in outs), outs)
            self.assertFalse(any("SECRET" in o.reason for o in outs), outs)
        outs = self._go(lambda w: None, batch=2, output=False)    # control: the true stderr is in the reason
        self.assertTrue(all("stderr of the run" in o.reason for o in outs), outs)
        p = os.path.join(self.d, "e")
        with open(p, "wb") as f:
            f.write(b"a" * 700 + b"END")
        self.assertEqual(isolation.read_stderr_tail(p), "a" * 597 + "END")
        os.symlink(self.victim, os.path.join(self.d, "l"))
        self.assertEqual(isolation.read_stderr_tail(os.path.join(self.d, "l")), "")
        with mock.patch.object(isolation.os, "O_NOFOLLOW", 0):
            self.assertEqual(isolation.read_stderr_tail(os.path.join(self.d, "l")), "")
        if hasattr(os, "link"):
            os.link(self.victim, os.path.join(self.d, "h"))
            self.assertEqual(isolation.read_stderr_tail(os.path.join(self.d, "h")), "")      # a second name
            os.unlink(os.path.join(self.d, "h"))
        real_lstat = os.lstat

        def lstat_of_other(path, *a, **k):                        # the lstat sees another file than the open
            return real_lstat(self.victim if path == p else path, *a, **k)
        with mock.patch.object(isolation.os, "lstat", lstat_of_other):
            self.assertEqual(isolation.read_stderr_tail(p), "")

    def test_no_status_time_the_folder_time_still_sees_create_and_remove(self):
        """where the status-change time is not recorded (Windows), the fixed modification time of the folder still
        shows an entry created and removed"""
        from unittest import mock
        from rigorous_levels import isolation
        w = tempfile.mkdtemp(dir=self.d)
        isolation.work_snapshot(w)
        self.assertEqual(os.lstat(w).st_mtime_ns, isolation.WORK_FOLDER_TIME_NS)    # the fixed time, whatever the tick
        with mock.patch.object(isolation, "_STATUS_TIME", False):
            u, = self._go(self._create_remove)
            self.assertEqual(u.state, "ERROR")
            self.assertIn("the folder: modification time changed (an entry was created or removed)", u.reason)
            u, = self._go(lambda w: None)                         # control
            self.assertEqual(u.state, "OK")

    def test_copy_of_stderr_destination_link_is_not_opened(self):
        """without O_NOFOLLOW a link at the destination is not even opened (a device it names could act on open), and
        a file swapped in between the lstat and the open is not written"""
        from unittest import mock
        from rigorous_levels import isolation
        if not (hasattr(os, "symlink") and os.name == "posix"):
            self.skipTest("links")
        src, dst = os.path.join(self.d, "src"), os.path.join(self.d, "dst")
        with open(src, "wb") as f:
            f.write(b"stderr of the run\n")
        os.symlink(self.victim, dst)
        opened, real_open = [], os.open

        def rec(path, flags, *a, **k):
            opened.append(path)
            return real_open(path, flags, *a, **k)
        with mock.patch.object(isolation.os, "O_NOFOLLOW", 0), mock.patch.object(isolation.os, "open", rec):
            isolation._copy_run_stderr(src, dst)
        self.assertNotIn(dst, opened)
        self.assertIn(src, opened)                                # control
        other = os.path.join(self.d, "other")
        open(other, "w").close()
        real_lstat = os.lstat

        def lstat_other(path, *a, **k):                           # the lstat sees a regular file, the open the link
            return real_lstat(other if path == dst else path, *a, **k)
        with mock.patch.object(isolation.os, "O_NOFOLLOW", 0), mock.patch.object(isolation.os, "lstat", lstat_other):
            isolation._copy_run_stderr(src, dst)
        with open(self.victim, "rb") as f:
            self.assertEqual(f.read(), b"SECRET-OF-THE-USER\n")

    def test_copy_of_stderr_without_o_nofollow(self):
        """where O_NOFOLLOW is missing (Windows) the lstat decides: a link at the destination is not written through
        (before: the file it named was overwritten)"""
        from unittest import mock
        from rigorous_levels import isolation
        if not (hasattr(os, "symlink") and os.name == "posix"):
            self.skipTest("links")
        src, dst = os.path.join(self.d, "src"), os.path.join(self.d, "dst")
        with open(src, "wb") as f:
            f.write(b"stderr of the run\n")
        os.symlink(self.victim, dst)
        with mock.patch.object(isolation.os, "O_NOFOLLOW", 0):
            isolation._copy_run_stderr(src, dst)
            os.unlink(dst)
            isolation._copy_run_stderr(src, dst)                  # control: nothing there, the copy is made
        with open(self.victim, "rb") as f:
            self.assertEqual(f.read(), b"SECRET-OF-THE-USER\n")
        with open(dst, "rb") as f:
            self.assertEqual(f.read(), b"stderr of the run\n")

    def test_folders_left_without_permissions_or_deep_are_removed(self):
        """the work folder is removed whatever the run left: modes 000, 0300, 0400, 0500 at the top or inside, 1 200
        and 5 000 folders one inside the other (3.11: RecursionError out of run_port before), 3 000 folders side by
        side; links inside are removed, never followed"""
        if os.name != "posix":
            self.skipTest("POSIX modes")
        vdir = os.path.join(self.d, "vdir")
        os.mkdir(vdir)
        with open(os.path.join(vdir, "keep"), "w") as f:
            f.write("k")
        os.chmod(vdir, 0o700)

        def deep(n):
            def plant(w):                                     # relative to a descriptor: paths get too long
                fd = os.open(w, os.O_RDONLY)
                try:
                    for _ in range(n):
                        os.mkdir("d", dir_fd=fd)
                        nfd = os.open("d", os.O_RDONLY, dir_fd=fd)
                        os.close(fd)
                        fd = nfd
                finally:
                    os.close(fd)
            return plant

        def sub(mode):
            def plant(w):
                s = os.path.join(w, "sub")
                os.mkdir(s)
                os.mkdir(os.path.join(s, "inner"))
                with open(os.path.join(s, "inner", "f"), "w") as f:
                    f.write("x")
                os.symlink(vdir, os.path.join(s, "inner", "to_user_dir"))
                os.chmod(os.path.join(s, "inner"), mode)
                os.chmod(s, mode)
            return plant

        def wide(w):
            for i in range(3000):
                os.mkdir(os.path.join(w, f"s{i}"))
        cases = [("top 000", lambda w: os.chmod(w, 0o000)), ("top 0300", lambda w: os.chmod(w, 0o300)),
                 ("top 0400", lambda w: os.chmod(w, 0o400)), ("top 0500", lambda w: os.chmod(w, 0o500)),
                 ("deep 1200", deep(1200)), ("deep 5000", deep(5000)), ("wide 3000", wide)]
        cases += [(f"inside {oct(m)}", sub(m)) for m in (0o000, 0o300, 0o400, 0o500)]

        def outlives(w):                                          # a writer still running after the run, for 0.15 s
            import threading

            def write():
                end = time.monotonic() + 0.15
                i = 0
                while time.monotonic() < end:
                    try:
                        open(os.path.join(w, f"late{i}"), "w").close()
                    except OSError:
                        return
                    i += 1
                    time.sleep(0.002)
            threading.Thread(target=write, daemon=True).start()
            time.sleep(0.01)
        cases.append(("writer outlives the run", outlives))
        from unittest import mock
        from rigorous_levels import isolation
        real_remove = isolation.remove_tree
        for name, plant in cases:
            with self.subTest(case=name):
                took = []

                def timed_plant(w, plant=plant):
                    t = time.monotonic()
                    plant(w)
                    took.append(("plant", time.monotonic() - t))

                def timed_remove(path):
                    t = time.monotonic()
                    real_remove(path)
                    took.append(("remove_tree", time.monotonic() - t))
                try:
                    with mock.patch.object(isolation, "remove_tree", timed_remove):
                        u, = self._go(timed_plant)                # _go asserts the work folder is gone
                except AssertionError as e:                       # the seconds of each step, to tell slow from stuck
                    raise AssertionError(f"{e} ({', '.join(f'{k} {v:.1f} s' for k, v in took)}; "
                                         f"REMOVE_SECONDS {isolation.REMOVE_SECONDS})") from None
                self.assertEqual(u.state, "ERROR")
        for name, plant in (("batch: deep 1200", deep(1200)), ("batch: top 000", lambda w: os.chmod(w, 0o000))):
            with self.subTest(case=name):
                outs = self._go(plant, batch=2)                   # run_ports removes it too
                self.assertEqual([o.state for o in outs], ["ERROR"] * 2)
        self.assertEqual(sorted(os.listdir(vdir)), ["keep"])
        self.assertEqual(stat.S_IMODE(os.stat(vdir).st_mode), 0o700)

    def _needs_fchmodat2(self):
        """skips where fchmodat2 is not called (not Linux x86-64 / arm64) or does not work (a kernel before 6.6, or a
        system call filter that refuses it): there the folders stay, which the tests below would report as failures"""
        from rigorous_levels import isolation
        if isolation._FCHMODAT2 is None:
            self.skipTest("fchmodat2: Linux x86-64 / arm64 only")
        try:
            isolation._fchmodat2_nofollow(self.d, None, stat.S_IMODE(os.stat(self.d).st_mode))
        except OSError as e:
            self.skipTest(f"fchmodat2 does not work here ({e.strerror}): Linux 6.6 and later")

    def test_removal_without_proc(self):
        """Linux without /proc: folders left 000 or 077 (the top and inside) get the owner's rwx through fchmodat2
        (Linux 6.6+) on an O_PATH descriptor and are removed; what takes the name after that descriptor was opened
        (a link to a folder of the user, a second name of a file of the user) is not changed; without fchmodat2
        either, the folder stays and nothing raises"""
        import errno
        from unittest import mock
        from rigorous_levels import isolation
        if not isolation._FD_REMOVAL:
            self.skipTest("no removal with descriptors here")
        self._needs_fchmodat2()
        real_isdir = os.path.isdir

        def no_proc(p):
            return False if str(p).startswith("/proc") else real_isdir(p)
        vdir = os.path.join(self.d, "vdir")
        os.mkdir(vdir)
        os.chmod(vdir, 0o500)
        os.chmod(self.victim, 0o640)

        def open_now():                                               # the descriptors of this process, where listed
            return sorted(os.listdir("/dev/fd")) if real_isdir("/dev/fd") else None
        open_before = open_now()
        for case in ("top", "inside", "inside 077"):
            top = tempfile.mkdtemp(dir=self.d)
            os.mkdir(os.path.join(top, "s"))
            open(os.path.join(top, "s", "f"), "w").close()
            os.chmod(os.path.join(top, "s"), 0o077 if case == "inside 077" else 0o000)
            if case == "top":
                os.chmod(top, 0o000)
            with self.subTest(case=case), mock.patch.object(isolation.os.path, "isdir", no_proc):
                try:
                    isolation.remove_tree(top)
                except Exception as e:                                # noqa: BLE001
                    self.fail(f"raised {e!r}")
                self.assertFalse(os.path.lexists(top))
        real_f2 = isolation._fchmodat2_nofollow
        for kind, left in (("link", 0o000), ("second name", 0o000), ("second name", 0o077)):
            top = tempfile.mkdtemp(dir=self.d)
            os.mkdir(os.path.join(top, "s"))
            os.chmod(os.path.join(top, "s"), left)
            calls = []

            def swap_then(name, dir_fd, mode):                        # the name becomes something of the user
                calls.append(name)
                os.rename(os.path.join(top, "s"), os.path.join(top, "s_moved"))
                if kind == "link":
                    os.symlink(vdir, os.path.join(top, "s"))
                else:
                    os.link(self.victim, os.path.join(top, "s"))
                return real_f2(name, dir_fd, mode)
            with self.subTest(kind=kind, left=left), mock.patch.object(isolation.os.path, "isdir", no_proc), \
                    mock.patch.object(isolation, "_fchmodat2_nofollow", swap_then), \
                    mock.patch.object(isolation, "REMOVE_PAUSES", ()):
                isolation.remove_tree(top)
                self.assertEqual(calls, [""])                         # on the descriptor, never by name
                self.assertEqual(stat.S_IMODE(os.stat(vdir).st_mode), 0o500)
                self.assertEqual(stat.S_IMODE(os.stat(self.victim).st_mode), 0o640)
                self.assertEqual(stat.S_IMODE(os.lstat(os.path.join(top, "s_moved")).st_mode), left | 0o700)
            isolation.remove_tree(top)
            self.assertFalse(os.path.lexists(top))
            self.assertEqual(os.stat(self.victim).st_nlink, 1)
        top = tempfile.mkdtemp(dir=self.d)
        os.mkdir(os.path.join(top, "s"))
        os.chmod(os.path.join(top, "s"), 0o000)
        with mock.patch.object(isolation.os.path, "isdir", no_proc), mock.patch.object(isolation, "_FCHMODAT2", None), \
                mock.patch.object(isolation, "REMOVE_PAUSES", ()):
            isolation.remove_tree(top)                                # no way at all: it stays, no exception
        self.assertEqual(stat.S_IMODE(os.lstat(os.path.join(top, "s")).st_mode), 0o000)
        import builtins
        real_import = builtins.__import__

        def no_ctypes(name, *a, **k):
            if name == "ctypes":
                raise ImportError("No module named '_ctypes'")
            return real_import(name, *a, **k)
        with mock.patch.object(isolation.os.path, "isdir", no_proc), mock.patch.object(builtins, "__import__", no_ctypes), \
                mock.patch.object(isolation, "REMOVE_PAUSES", ()):
            try:
                isolation.remove_tree(top)                            # no ctypes: it stays, no exception
            except Exception as e:                                    # noqa: BLE001
                self.fail(f"raised {e!r}")
            with self.assertRaises(OSError) as cm:
                isolation._fchmodat2_nofollow(top, None, 0o700)
            self.assertEqual(cm.exception.errno, errno.ENOSYS)
        self.assertEqual(stat.S_IMODE(os.lstat(os.path.join(top, "s")).st_mode), 0o000)
        self.assertEqual(open_now(), open_before)                     # no descriptor left open
        with mock.patch.object(isolation.os.path, "isdir", no_proc):
            isolation.remove_tree(top)                                # control
        self.assertFalse(os.path.lexists(top))

    def test_fchmodat2_only_where_its_number_was_read(self):
        """the system call number is used on Linux x86-64 and arm64 only: elsewhere a table can give that number to
        another system call (alpha: fchmodat2 is 562)"""
        from rigorous_levels import isolation
        number = isolation._fchmodat2_number
        self.assertEqual([number("linux", m) for m in ("x86_64", "aarch64")], [452, 452])
        for platform, machine in (("linux", "alpha"), ("linux", "riscv64"), ("linux", "ppc64le"), ("linux", "s390x"),
                                  ("linux", "armv7l"), ("linux", "i686"), ("linux", "mips64"), ("linux", ""),
                                  ("darwin", "x86_64"), ("darwin", "arm64"), ("win32", "AMD64"), ("win32", ""),
                                  ("freebsd14", "amd64"), ("android", "aarch64"), ("", "x86_64")):
            with self.subTest(platform=platform, machine=machine):
                self.assertIsNone(number(platform, machine))
        self.assertEqual(isolation._FCHMODAT2, number(sys.platform, os.uname().machine if hasattr(os, "uname") else ""))

    def test_owner_rwx_without_proc_exactly(self):
        """without /proc: a folder 000 gets 0700 (the owner's rwx, nothing for others), a file and a link are refused
        when the descriptor is opened, and fchmodat2 by name fails on a link with EOPNOTSUPP"""
        import errno
        from unittest import mock
        from rigorous_levels import isolation
        self._needs_fchmodat2()
        real_isdir = os.path.isdir
        no_proc = mock.patch.object(isolation.os.path, "isdir",
                                    lambda p: False if str(p).startswith("/proc") else real_isdir(p))
        d0, f, ln = os.path.join(self.d, "d0"), os.path.join(self.d, "f"), os.path.join(self.d, "ln")
        os.mkdir(d0)
        os.chmod(d0, 0o000)
        with open(f, "w") as fh:
            fh.write("x")
        os.chmod(f, 0o600)
        os.symlink(self.d, ln)
        before = stat.S_IMODE(os.stat(self.d).st_mode)
        with no_proc:
            isolation._owner_rwx_unopened(d0, None)
            for other in (f, ln):
                with self.assertRaises(OSError) as cm:
                    isolation._owner_rwx_unopened(other, None)
                self.assertEqual(cm.exception.errno, errno.ENOTDIR)
        self.assertEqual(stat.S_IMODE(os.lstat(d0).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.lstat(f).st_mode), 0o600)
        dfd, cwd = os.open(self.d, os.O_RDONLY), os.getcwd()
        try:
            os.chdir(self.d)
            for name, dir_fd in ((ln, None), ("ln", None), ("ln", dfd)):
                with self.assertRaises(OSError) as cm:
                    isolation._fchmodat2_nofollow(name, dir_fd, 0o777)
                self.assertEqual(cm.exception.errno, errno.EOPNOTSUPP)
        finally:
            os.chdir(cwd)
            os.close(dfd)
        self.assertEqual(stat.S_IMODE(os.stat(self.d).st_mode), before)

    def test_remove_tree_tries_again(self):
        """a first try that leaves the folder (a writer that outlived the run) is followed by the next ones"""
        from unittest import mock
        from rigorous_levels import isolation
        top = tempfile.mkdtemp(dir=self.d)
        open(os.path.join(top, "f"), "w").close()
        tries, real = [], (isolation._remove_tree_fd if isolation._FD_REMOVAL else None)

        def first_fails(path, end):
            tries.append(path)
            if len(tries) == 1:
                raise OSError("busy")
            if real:
                real(path, end)
            else:
                shutil.rmtree(path)
        name = "_remove_tree_fd" if isolation._FD_REMOVAL else None
        if name is None:
            self.skipTest("descriptor removal not used here")
        with mock.patch.object(isolation, name, first_fails):            # the pauses of the library
            isolation.remove_tree(top)
        self.assertEqual(len(tries), 2)
        self.assertFalse(os.path.lexists(top))

    def test_copy_of_stderr_second_name_made_after_the_lstat(self):
        """the destination had one name at the lstat and two at the open: not written"""
        from unittest import mock
        from rigorous_levels import isolation
        if not hasattr(os, "link"):
            self.skipTest("no os.link")
        src, dst = os.path.join(self.d, "src"), os.path.join(self.d, "dst")
        with open(src, "wb") as f:
            f.write(b"stderr of the run\n")
        with open(dst, "wb") as f:
            f.write(b"old\n")
        real_lstat = os.lstat

        def lstat_then_link(path, *a, **k):
            st = real_lstat(path, *a, **k)
            if path == dst and not os.path.lexists(dst + ".2"):
                os.link(dst, dst + ".2")
            return st
        with mock.patch.object(isolation.os, "lstat", lstat_then_link):
            isolation._copy_run_stderr(src, dst)
        with open(dst, "rb") as f:
            self.assertEqual(f.read(), b"old\n")
        os.unlink(dst + ".2")
        isolation._copy_run_stderr(src, dst)                      # control: one name again
        with open(dst, "rb") as f:
            self.assertEqual(f.read(), b"stderr of the run\n")

    def test_remove_tree_stops_if_the_parent_is_not_the_one_it_came_from(self):
        """going back up through "..": if the folder was moved meanwhile, nothing above it is removed"""
        from unittest import mock
        from rigorous_levels import isolation
        if not isolation._FD_REMOVAL:
            self.skipTest("descriptor removal not used here")
        top = tempfile.mkdtemp(dir=self.d)
        os.makedirs(os.path.join(top, "a", "b"))
        with open(os.path.join(top, "a", "f"), "w") as f:
            f.write("x")
        real_open, calls = os.open, []

        def open_dotdot(path, flags, *a, **k):
            if path == "..":
                calls.append(1)
                return real_open(self.d, flags)                  # another folder than the parent
            return real_open(path, flags, *a, **k)
        with mock.patch.object(isolation.os, "open", open_dotdot), mock.patch.object(isolation, "REMOVE_PAUSES", (0, 0)):
            isolation.remove_tree(top)
        self.assertEqual(len(calls), 3)                           # once per try, stopped each time
        self.assertTrue(os.path.isdir(os.path.join(top, "a")))   # stopped: "a" and the top stay
        self.assertTrue(os.path.isdir(self.d))
        isolation.remove_tree(top)                               # control
        self.assertFalse(os.path.lexists(top))

    def test_remove_tree_path_that_does_not_end_with_a_name(self):
        """a path ending with a separator, "." or "..": the system resolves a link there, so nothing is removed
        (measured before: with the top a link to a folder of the user and a final "/", that folder was emptied)"""
        from rigorous_levels import isolation
        if os.name != "posix":
            self.skipTest("POSIX links")
        vdir = os.path.join(self.d, "vdir")
        os.makedirs(os.path.join(vdir, "sub"))
        with open(os.path.join(vdir, "keep"), "w") as f:
            f.write("k")
        link = os.path.join(self.d, "top_link")
        os.symlink(vdir, link)
        real = tempfile.mkdtemp(dir=self.d)
        open(os.path.join(real, "f"), "w").close()
        for tail in (os.sep, os.sep + ".", os.sep + os.sep, os.sep + "sub" + os.sep + ".."):
            with self.subTest(tail=tail):
                isolation.remove_tree(link + tail)
                self.assertEqual(sorted(os.listdir(vdir)), ["keep", "sub"])
                isolation.remove_tree(real + tail.replace("sub", "."))
                self.assertEqual(os.listdir(real), ["f"])
        isolation.remove_tree(os.path.join(self.d, "nul\0name"))  # a path the system refuses: nothing raised
        isolation.remove_tree(link)                               # the link itself: never followed, it stays
        self.assertTrue(os.path.islink(link))
        self.assertEqual(sorted(os.listdir(vdir)), ["keep", "sub"])
        isolation.remove_tree(real)                               # control: the same folder by its name
        self.assertFalse(os.path.lexists(real))

    def test_remove_tree_top_folder_never_through_a_link(self):
        """the top folder left 000: on Linux its mode is changed through a descriptor, never by name (between an lstat
        and a chmod by name the name can become a link: measured before, the folder of the user it named got the rwx);
        on macOS, which has no O_PATH, by name without following a link (docs/PORT_CONTRACT.md §6.7): a link put there
        is not followed either"""
        from unittest import mock
        from rigorous_levels import isolation
        if not isolation._FD_REMOVAL:
            self.skipTest("descriptor removal not used here")
        vdir = os.path.join(self.d, "vdir")
        os.mkdir(vdir)
        os.chmod(vdir, 0o500)
        top = tempfile.mkdtemp(dir=self.d)
        os.chmod(top, 0o000)
        real_chmod, calls = os.chmod, []

        def chmod(path, mode, *a, **k):
            calls.append((path, k.get("follow_symlinks", True)))
            if len(calls) == 1:                                   # the name becomes a link right before the change
                os.rename(top, top + ".moved")
                os.symlink(vdir, top)
            return real_chmod(path, mode, *a, **k)
        with mock.patch.object(isolation.os, "chmod", chmod), mock.patch.object(isolation, "REMOVE_PAUSES", ()):
            isolation.remove_tree(top)
        self.assertEqual(len(calls), 1, calls)
        if hasattr(os, "O_PATH"):
            by_fd = str(calls[0][0]).startswith("/proc/self/fd/") or calls[0][1] is False
            self.assertTrue(calls[0][0] != top and by_fd, calls)
        else:
            self.assertEqual(calls, [(top, False)])               # by name, never following
        self.assertEqual(stat.S_IMODE(os.lstat(vdir).st_mode), 0o500)
        self.assertTrue(os.path.islink(top))                      # the link stays, the folder it names untouched
        os.chmod(vdir, 0o700)
        top2 = tempfile.mkdtemp(dir=self.d)                       # control: without the swap the 000 top is removed
        os.chmod(top2, 0o000)
        isolation.remove_tree(top2)
        self.assertFalse(os.path.lexists(top2))

    def test_remove_tree_ends_within_remove_seconds(self):
        """a process that keeps making folders one inside the other (measured before the cap: the removal followed
        it down for as long as it ran): the walk stops at REMOVE_SECONDS, never raises, the folder stays"""
        from unittest import mock
        from rigorous_levels import isolation
        if not isolation._FD_REMOVAL:
            self.skipTest("descriptor removal not used here")
        top = tempfile.mkdtemp(dir=self.d)
        os.makedirs(os.path.join(top, "a", "b"))
        with mock.patch.object(isolation, "REMOVE_SECONDS", -1.0):   # the time is already over: nothing is walked
            isolation.remove_tree(top)
        self.assertTrue(os.path.isdir(os.path.join(top, "a", "b")))
        self.assertGreaterEqual(isolation.REMOVE_SECONDS, 5 * sum(isolation.REMOVE_PAUSES))
        empty, sleeps = tempfile.mkdtemp(dir=self.d), []
        with mock.patch.object(isolation, "REMOVE_SECONDS", -1.0), \
                mock.patch.object(isolation.time, "sleep", sleeps.append):
            isolation.remove_tree(empty)                          # checked at each folder, also one without entries
        self.assertTrue(os.path.isdir(empty))
        self.assertEqual(sleeps, [0.0])                           # and no pause that would end after the time
        flat, ticks = tempfile.mkdtemp(dir=self.d), [0.0]
        for i in range(10):
            open(os.path.join(flat, f"f{i}"), "w").close()

        def clock():                                              # one second per reading
            ticks[0] += 1.0
            return ticks[0]
        with mock.patch.object(isolation.time, "monotonic", clock), \
                mock.patch.object(isolation, "REMOVE_SECONDS", 3.5), mock.patch.object(isolation.time, "sleep", lambda s: None):
            isolation.remove_tree(flat)                           # checked at each entry of one folder too
        self.assertEqual(len(os.listdir(flat)), 8)                # the first try stopped at its third entry
        dig = ("import os, sys, time\nend = time.monotonic() + 1.2\nwhile time.monotonic() < end:\n"
               "    try:\n        os.chdir(sys.argv[1])\n        while time.monotonic() < end:\n"
               "            os.mkdir('d')\n            os.chdir('d')\n    except OSError:\n        pass\n")
        p = subprocess.Popen([sys.executable, "-c", dig, top])   # a process of its own, digging for 1.2 s
        try:
            time.sleep(0.2)
            t0 = time.monotonic()
            with mock.patch.object(isolation, "REMOVE_SECONDS", 0.2):
                isolation.remove_tree(top)
            dt = time.monotonic() - t0
        finally:
            p.wait(30)
            with mock.patch.object(isolation, "REMOVE_SECONDS", 120.0):
                isolation.remove_tree(top)                        # the writer gone: removed (also for tearDown)
        self.assertLess(dt, 0.9)                                  # without the cap: as long as the writer digs
        self.assertFalse(os.path.lexists(top))

    def test_remove_tree_folder_without_permissions_swapped_for_a_link(self):
        """a folder left 000 inside: the owner's rwx is given through an O_PATH descriptor opened with O_NOFOLLOW (a
        link swapped in at that moment is not followed), and only the owner's bits are added"""
        from unittest import mock
        from rigorous_levels import isolation
        if not (isolation._FD_REMOVAL and hasattr(os, "O_PATH") and os.path.isdir("/proc/self/fd")):
            self.skipTest("no O_PATH descriptors here")
        vdir = os.path.join(self.d, "vdir")
        os.mkdir(vdir)
        os.chmod(vdir, 0o500)
        top = tempfile.mkdtemp(dir=self.d)
        os.mkdir(os.path.join(top, "p"))
        os.chmod(os.path.join(top, "p"), 0o000)
        real_open, done = os.open, []

        def swap_open(path, flags, *a, **k):
            if path == "p" and flags & os.O_PATH and not done:
                done.append(1)
                os.rename(os.path.join(top, "p"), os.path.join(top, "p.moved"))   # same parent: allowed for 000
                os.symlink(vdir, os.path.join(top, "p"))
            return real_open(path, flags, *a, **k)
        with mock.patch.object(isolation.os, "open", swap_open):
            isolation.remove_tree(top)
        self.assertEqual(done, [1])
        self.assertEqual(stat.S_IMODE(os.lstat(vdir).st_mode), 0o500)
        self.assertFalse(os.path.lexists(top))                    # the link removed as an entry at the next try
        os.chmod(vdir, 0o700)
        top = tempfile.mkdtemp(dir=self.d)                        # the modes given: the owner's rwx and nothing else
        os.makedirs(os.path.join(top, "q", "r"))
        os.mkdir(os.path.join(top, "z"))
        os.chmod(os.path.join(top, "q", "r"), 0o000)
        os.chmod(os.path.join(top, "q"), 0o500)
        os.chmod(os.path.join(top, "z"), 0o000)
        os.chmod(top, 0o000)
        real_chmod, real_fchmod, modes = os.chmod, os.fchmod, []

        def chmod(path, mode, *a, **k):
            modes.append(mode)
            return real_chmod(path, mode, *a, **k)

        def fchmod(fd, mode):
            modes.append(mode)
            return real_fchmod(fd, mode)
        with mock.patch.object(isolation.os, "chmod", chmod), mock.patch.object(isolation.os, "fchmod", fchmod):
            isolation.remove_tree(top)
        self.assertFalse(os.path.lexists(top))
        self.assertEqual(sorted(modes), [0o700, 0o700, 0o700, 0o700])

    def test_remove_tree_parent_on_another_device(self):
        """going back up: ".." must be the folder it came from by device AND inode (two file systems number their
        inodes on their own)"""
        from unittest import mock
        from rigorous_levels import isolation
        if not isolation._FD_REMOVAL:
            self.skipTest("descriptor removal not used here")
        top = tempfile.mkdtemp(dir=self.d)
        os.makedirs(os.path.join(top, "a", "b"))
        real_open, real_fstat, parents = os.open, os.fstat, set()

        def open_(path, flags, *a, **k):
            fd = real_open(path, flags, *a, **k)
            if path == "..":
                parents.add(fd)
            return fd

        def fstat(fd):
            st = real_fstat(fd)
            if fd in parents:                                     # the same inode number on another device
                parents.discard(fd)
                return os.stat_result((st.st_mode, st.st_ino, st.st_dev + 1) + tuple(st)[3:])
            return st
        with mock.patch.object(isolation.os, "open", open_), mock.patch.object(isolation.os, "fstat", fstat), \
                mock.patch.object(isolation, "REMOVE_PAUSES", ()):
            isolation.remove_tree(top)
        self.assertTrue(os.path.isdir(os.path.join(top, "a", "b")))   # stopped at the first step up
        isolation.remove_tree(top)
        self.assertFalse(os.path.lexists(top))

    def test_folder_unreadable_after_the_run(self):
        from unittest import mock
        from rigorous_levels import isolation
        w = tempfile.mkdtemp(dir=self.d)
        before = isolation.work_snapshot(w)
        with mock.patch.object(isolation.os, "scandir", side_effect=PermissionError("x")):
            self.assertEqual(isolation.work_changes(w, before), self.HEAD + "the folder could not be read again (PermissionError)")
        self.assertEqual(isolation.work_changes(w, before), "")

    def test_wasm_restores_the_recorded_modes(self):
        """the wasm engine makes the folder 0555 and the files 0444 for the run: after it they get back their recorded
        modes (0.3.0 and the change before: folder 0755, files 0644), so an unchanged run is not an ERROR; the copy of
        stderr.txt into the work folder is not made through a link put there"""
        from unittest import mock
        from rigorous_levels import isolation
        if os.name != "posix":
            self.skipTest("POSIX modes")
        for planted in (None, "symlink"):
            w, outdir = tempfile.mkdtemp(dir=self.d), tempfile.mkdtemp(dir=self.d)
            for n, mode in (("request.json", 0o600), (isolation.RUNNER_NAME, 0o640), ("output.json", 0o604)):
                open(os.path.join(w, n), "w").close()
                os.chmod(os.path.join(w, n), mode)
            open(os.path.join(outdir, "output.json"), "w").close()

            def fake_run(cmd, timeout, stderr_path, env, w=w, planted=planted):
                with open(stderr_path, "wb") as f:
                    f.write(b"wasm stderr\n")
                if planted:
                    os.chmod(w, 0o700)
                    os.unlink(os.path.join(w, "stderr.txt"))
                    os.symlink(self.victim, os.path.join(w, "stderr.txt"))
                return 0, False
            facts = {"exe": "wasmtime", "folder": self.d, "version": [3, 12], "numpy": "-"}
            with mock.patch.object(isolation, "probe", return_value=facts), mock.patch.object(isolation, "_run", fake_run):
                rc, timed_out, descr, limit = isolation.run("wasm", w, os.path.join(outdir, "output.json"), 1, 1, [])
            if planted:
                self.assertTrue(limit.startswith(self.HEAD + "'stderr.txt': kind changed"), limit)
                with open(self.victim) as f:
                    self.assertEqual(f.read(), "SECRET-OF-THE-USER\n")
            else:
                self.assertEqual(limit, "")
                self.assertEqual(stat.S_IMODE(os.lstat(w).st_mode), 0o700)
                self.assertEqual([stat.S_IMODE(os.lstat(os.path.join(w, n)).st_mode) for n in
                                  ("request.json", isolation.RUNNER_NAME, "output.json")], [0o600, 0o640, 0o604])
                with open(os.path.join(w, "stderr.txt"), "rb") as f:
                    self.assertEqual(f.read(), b"wasm stderr\n")

    def test_copy_of_stderr_into_the_work_folder(self):
        """the destination is written only as a regular file with one name, from its start, never through a link"""
        from rigorous_levels import isolation
        src, dst = os.path.join(self.d, "src"), os.path.join(self.d, "dst")
        with open(src, "wb") as f:
            f.write(b"short\n")
        with open(dst, "wb") as f:
            f.write(b"an older and longer content\n")
        isolation._copy_run_stderr(src, dst)
        with open(dst, "rb") as f:
            self.assertEqual(f.read(), b"short\n")                 # truncated through the descriptor
        bad = []
        if hasattr(os, "link"):
            bad.append(lambda: os.link(self.victim, dst))
        if hasattr(os, "symlink") and os.name == "posix":
            bad.append(lambda: os.symlink(self.victim, dst))
        if hasattr(os, "mkfifo"):
            bad.append(lambda: os.mkfifo(dst))
        for make in bad:
            os.unlink(dst)
            make()
            isolation._copy_run_stderr(src, dst)                  # no exception, nothing written
            with open(self.victim, "rb") as f:
                self.assertEqual(f.read(), b"SECRET-OF-THE-USER\n")
        os.unlink(dst)

    def test_wasm_sets_the_mode_back_only_on_the_recorded_file(self):
        """a file put in place of a recorded one during the run keeps its own mode (and the check names the change)"""
        from unittest import mock
        from rigorous_levels import isolation
        if os.name != "posix":
            self.skipTest("POSIX modes")
        w, outdir = tempfile.mkdtemp(dir=self.d), tempfile.mkdtemp(dir=self.d)
        for n in ("request.json", isolation.RUNNER_NAME, "output.json"):
            open(os.path.join(w, n), "w").close()
            os.chmod(os.path.join(w, n), 0o644)
        open(os.path.join(outdir, "output.json"), "w").close()
        other = os.path.join(self.d, "other")

        def fake_run(cmd, timeout, stderr_path, env):
            open(stderr_path, "wb").close()
            with open(other, "w") as f:
                f.write("{}")
            os.chmod(other, 0o600)
            os.chmod(w, 0o700)
            os.replace(other, os.path.join(w, "request.json"))
            os.chmod(w, 0o555)
            return 0, False
        facts = {"exe": "wasmtime", "folder": self.d, "version": [3, 12], "numpy": "-"}
        with mock.patch.object(isolation, "probe", return_value=facts), mock.patch.object(isolation, "_run", fake_run):
            limit = isolation.run("wasm", w, os.path.join(outdir, "output.json"), 1, 1, [])[3]
        self.assertTrue(limit.startswith(self.HEAD + "'request.json': mode 0o644 -> 0o600, inode changed"), limit)
        self.assertEqual(stat.S_IMODE(os.lstat(os.path.join(w, "request.json")).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.lstat(os.path.join(w, isolation.RUNNER_NAME)).st_mode), 0o644)   # control

    def test_real_engines_leave_the_folder_unchanged(self):
        """with every engine whose probe passes here, a run that changes nothing is not an ERROR of §6.7"""
        if not NUMPY_ENGINES and "wasm" not in ENGINES_OK:
            self.skipTest("no isolation engine on this machine: " + "; ".join(f"{k}: {v}" for k, v in ENGINES_WHY.items())[:300])
        for e in ENGINES_OK:
            with self.subTest(engine=e):
                u = MP.run_port(request("test_wrong" if e != "wasm" else "python_rotor"), engine=e)
                self.assertNotIn("work folder changed", u.reason)
                if e != "wasm":
                    self.assertEqual(u.state, "OK", u)


if __name__ == "__main__":
    unittest.main()
