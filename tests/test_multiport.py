# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Test di qraft_ra/multiport.py + qraft_ra/port_runner.py (10/11/2026). Specifica: note dell'autore (non pubblicate).
Controlli positivi S1-S7 della specifica: ognuno deve POTER fallire (il runner fuori sandbox fa ciò che dentro è bloccato)."""
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest


from qraft_ra import multiport as MP  # noqa: E402

FLINT = importlib.util.find_spec("flint") is not None


def _engines_available():
    """The engines whose fail-closed probe passes on this machine: the sandbox tests run once per engine and are
    SKIPPED with the probe's reason otherwise (bwrap needs user namespaces; containers need the local image;
    sandbox-exec needs macOS; appcontainer needs Windows; wasm needs wasmtime + QRAFT_PYTHON_WASM)."""
    from qraft_ra import isolation
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

# il venv qraft prende matplotlib (richiesto da scqubits) dal site user: entrambi dichiarati, in sola lettura
SITE = tuple(p for p in (sysconfig.get_path("purelib"), site.getusersitepackages()) if os.path.isdir(p))
ROTOR = {"type": "cos_rotor", "E_C": 0.3, "E_J": 15.0, "n_g": 0.25}


def request(port="numpy_rotor", **kw):
    base = dict(port=port, model=ROTOR, levels=6, truncation={"ncut": 30}, unit="GHz", seconds=20,
                mem_mib=1024, site_packages=SITE)
    base.update(kw)
    return MP.Request(**base)


def runner_direct(r, timeout=30):
    """Esegue il runner SENZA sandbox (solo nei test, come check positivo): ciò che qui riesce, dentro deve fallire."""
    work = tempfile.mkdtemp(prefix="qraft_port_direct_")
    try:
        with open(os.path.join(work, "request.json"), "w") as f:
            json.dump(r.json(), f)
        subprocess.run([sys.executable, "-I", "-B", str(MP.RUNNER), work], capture_output=True, text=True, timeout=timeout,
                       env={"PATH": os.environ.get("PATH", ""), "HOME": tempfile.mkdtemp(prefix="home_prova_")})
        with open(os.path.join(work, "output.json")) as f:
            return json.load(f)
    finally:
        shutil.rmtree(work, ignore_errors=True)


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
        """S5: the engine's executable missing on PATH → SandboxMissing, nothing runs (no fallback)."""
        from qraft_ra import isolation
        original, probes = isolation.shutil.which, dict(isolation._PROBES)
        isolation.shutil.which = lambda name: None
        isolation._PROBES.clear()
        try:
            with self.assertRaises(MP.SandboxMissing):
                self.run_port(request("numpy_rotor"))
        finally:
            isolation.shutil.which = original
            isolation._PROBES.update(probes)

    def test_s5_probe_that_does_not_isolate_fail_closed(self):
        """S5: a probe that reports an open network / writable root / visible home → SandboxMissing."""
        from qraft_ra import isolation
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
        from qraft_ra.guaranteed_intervals import guaranteed_levels
        from qraft_ra.rotor_spectrum import Rotor
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
        fuori = tempfile.mkdtemp(prefix="qraft_fuori_")
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
        self.assertFalse(os.path.exists(os.path.join(real_home, "qraft_port_test.txt")))
        shutil.rmtree(fuori, ignore_errors=True)

    def test_s3_tempo(self):
        u = self.run_port(request("test_loop", seconds=2))
        self.assertEqual(u.state, "INVALID", u)
        self.assertIn("timeout", u.reason)

    def test_s3_memoria(self):
        u = self.run_port(request("test_memory", truncation={"mib": 3000}, mem_mib=256))
        self.assertEqual(u.state, "ERROR", u)
        self.assertIn("MemoryError", u.reason)

    def test_s4_ambiente_pulito(self):
        """PYTHONPATH/HOME della sessione non arrivano: la port vede HOME = /tmp/nohome (inesistente)."""
        r = request("test_write", truncation={"path": "/tmp/fuori_work.txt", "real_home": os.path.expanduser("~")})
        os.environ["QRAFT_PROVA_AMBIENTE"] = "1"
        try:
            u = self.run_port(r)
        finally:
            os.environ.pop("QRAFT_PROVA_AMBIENTE", None)
        self.assertRegex(u.reason, r"blocked \S*nohome\S*qraft_port_test.txt")
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
        from qraft_ra.guaranteed_intervals import guaranteed_levels
        from qraft_ra.rotor_spectrum import Rotor
        iv = guaranteed_levels(Rotor(E_C=0.3, cosines=((1, -15.0),), n_g=0.25), 6, deadline=60)
        u = self.run_port(request("scqubits_transmon", mem_mib=4096, seconds=120))
        self.assertEqual(u.state, "OK", u)
        self.assertIn("scqubits", u.solver_version)
        self.assertIn(MP.compare(iv, "GHz", u, tolerance=1e-12).overall, ("INSIDE", "INSIDE_TOLERANCE"))
        if importlib.util.find_spec("diatomic") is None:
            self.skipTest("diatomic-py assente")
        from qraft_ra import hyperfine_molecule as MI
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
        r = request("test_hostile", truncation={"mode": "environment", "name": "QRAFT_NEMESIS_ESCA"})
        os.environ["QRAFT_NEMESIS_ESCA"] = "esca"
        try:
            u = self.run_port(r)
            diretto = subprocess.run([sys.executable, "-c", "import os,sys; print('QRAFT_NEMESIS_ESCA' in os.environ)"],
                                     capture_output=True, text=True).stdout.strip()
        finally:
            os.environ.pop("QRAFT_NEMESIS_ESCA", None)
        self.assertEqual(u.state, "ERROR", u)
        self.assertIn("seen in []", u.reason)
        self.assertEqual(diretto, "True")


    def test_uscita_non_sostituibile_e_disco_limitato(self):
        u = self.run_port(request("test_hostile", truncation={"mode": "symlink", "target": "/etc/hostname"}))
        self.assertEqual(u.state, "ERROR", u)
        self.assertIn("symlink blocked", u.reason)
        u = self.run_port(request("test_hostile", truncation={"mode": "disk", "where": "/work", "files": 2, "mib": 1}))
        self.assertRegex(u.reason, r"disk: 0 MiB then (OSError|PermissionError)")
        for where in ("/tmp", "/dev/shm", "/home"):           # tmpfs in RAM: tetto per ciascuno (RLIMIT_AS non li conta)
            u = self.run_port(request("test_hostile", truncation={"mode": "disk", "where": where, "files": 6, "mib": 60}))
            self.assertRegex(u.reason, r"then (OSError|PermissionError|FileNotFoundError)", where)   # WASI: no /tmp at all
            self.assertLessEqual(int(u.reason.split("disk: ")[1].split(" MiB")[0]), MP.TMPFS_BYTES >> 20, where)


    def test_stdout_illimitato_non_entra_in_memoria(self):
        import resource
        prima = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        u = self.run_port(request("test_hostile", truncation={"mode": "stdout", "mib": 300}))
        dopo = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        self.assertEqual(u.state, "ERROR", u)
        self.assertLess(dopo - prima, 100 * 1024, (prima, dopo))           # KiB: con capture_output cresce di ≥ 300 MiB


    def test_site_packages_sola_lettura_e_rlimit(self):
        """Il site-packages montato non è scrivibile (il engine «process» importa da lì); NPROC, FSIZE e CPU mordono."""
        # name usa-e-getta, NON .pth, e rimosso comunque: un mutante che rende scrivibile il bind scriverebbe nel venv VERO
        target = os.path.join(SITE[0], f"qraft_nemesis_prova_{os.getpid()}.txt")
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
        u = self.run_port(request("test_hostile", truncation={"mode": "disk", "where": "/tmp", "files": 1, "mib": 70}))
        if self.ENGINE == "wasm":                             # no rlimit and no writable scratch at all under WASI
            self.assertRegex(u.reason, r"disk: 0 MiB then FileNotFoundError")
        else:
            self.assertRegex(u.reason, r"disk: 64 MiB then (OSError|PermissionError)")
        u = self.run_port(request("test_hostile", truncation={"mode": "cpu"}, seconds=2))
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
        d = tempfile.mkdtemp(prefix="qraft_uscita_")
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
        from qraft_ra import isolation
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
        from qraft_ra import isolation
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
        from qraft_ra import isolation
        d, finto = self._fake("wasmtime")
        d, finto = os.path.realpath(d), os.path.realpath(finto)                   # macOS: /var -> /private/var
        vecchio = os.environ.pop("QRAFT_TRUSTED_ENGINES", None)
        try:
            with self.assertRaises(MP.SandboxMissing):                                   # not listed: refused
                isolation._trusted_exe("wasmtime", finto)
            os.environ["QRAFT_TRUSTED_ENGINES"] = os.path.join(d, "altro") + os.pathsep + d   # folder, not the file
            with self.assertRaises(MP.SandboxMissing):
                isolation._trusted_exe("wasmtime", finto)
            os.environ["QRAFT_TRUSTED_ENGINES"] = finto                                    # exact path: accepted
            self.assertEqual(isolation._trusted_exe("wasmtime", finto), finto)
            os.chmod(finto, 0o775)                                                         # group-writable: refused
            with self.assertRaises(MP.SandboxMissing) as cm:
                isolation._trusted_exe("wasmtime", finto)
            self.assertIn("writable by group or others", str(cm.exception))
        finally:
            os.environ.pop("QRAFT_TRUSTED_ENGINES", None)
            if vecchio is not None:
                os.environ["QRAFT_TRUSTED_ENGINES"] = vecchio
            shutil.rmtree(d, ignore_errors=True)

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "getuid") and os.getuid() != 0, "POSIX, non-root")
    def test_trusted_engines_entry_must_be_the_exact_real_path(self):
        from qraft_ra import isolation
        d, finto = self._fake("wasmtime")
        d, finto = os.path.realpath(d), os.path.realpath(finto)
        link = os.path.join(d, "collegamento")
        os.symlink(finto, link)
        vecchio, cwd = os.environ.pop("QRAFT_TRUSTED_ENGINES", None), os.getcwd()
        try:
            os.chdir(d)
            for voce in ("wasmtime", "./wasmtime", link, finto + "/", " " + finto, d + "/../" + os.path.basename(d) + "/wasmtime"):
                os.environ["QRAFT_TRUSTED_ENGINES"] = voce
                with self.assertRaises(MP.SandboxMissing, msg=repr(voce)):
                    isolation._trusted_exe("wasmtime", finto)
            os.environ["QRAFT_TRUSTED_ENGINES"] = finto
            self.assertEqual(isolation._trusted_exe("wasmtime", link), finto)     # the real path is what runs
            self.assertEqual(isolation._VOUCHED.get("wasmtime"), finto)
        finally:
            os.chdir(cwd)
            os.environ.pop("QRAFT_TRUSTED_ENGINES", None)
            isolation._VOUCHED.pop("wasmtime", None)
            if vecchio is not None:
                os.environ["QRAFT_TRUSTED_ENGINES"] = vecchio
            shutil.rmtree(d, ignore_errors=True)

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "getuid") and os.getuid() != 0, "POSIX, non-root")
    def test_root_engine_runs_by_its_real_path_and_folder_must_be_root_owned(self):
        from qraft_ra import isolation
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
        from qraft_ra import isolation
        with self.assertRaises(MP.SandboxMissing):
            isolation._trusted_exe("podman", "/usr/bin")              # a root-owned folder is not an engine
        isolation._VOUCHED["sh"] = "/x/sh"
        isolation._trusted_exe("sh", "/bin/sh")
        self.assertNotIn("sh", isolation._VOUCHED)

    def test_vouched_engine_named_in_the_description(self):
        from qraft_ra import isolation
        originale = isolation._run_engine
        try:
            isolation._run_engine = lambda *a, **k: (0, False, "wasmtime (WASI)")
            isolation._VOUCHED["wasmtime"] = "/x/wasmtime"
            self.assertIn("QRAFT_TRUSTED_ENGINES lists it", isolation.run("wasm", "w", "o", 1, 1, [])[2])
            isolation._VOUCHED.pop("wasmtime")
            self.assertEqual(isolation.run("wasm", "w", "o", 1, 1, [])[2], "wasmtime (WASI)")
        finally:
            isolation._run_engine = originale
            isolation._VOUCHED.pop("wasmtime", None)

    def test_any_root_refused_for_grants(self):
        from qraft_ra import isolation
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
        from qraft_ra import isolation
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


from qraft_ra import isolation  # noqa: E402


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
        target = os.path.join(cartelle[0], f"qraft_nemesis_prova_{os.getpid()}.txt")
        try:
            u = MP.run_port(request("test_hostile", truncation={"mode": "write", "path": target}))
            esiste = os.path.exists(target)
        finally:
            if os.path.exists(target):
                os.remove(target)
        self.assertIn("write: blocked", u.reason)
        self.assertFalse(esiste)

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
        d = tempfile.mkdtemp(prefix="qraft_prof_")
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
        original = isolation.shutil.which
        isolation.shutil.which = lambda name: None
        try:
            with self.assertRaises(MP.SandboxMissing) as cm:
                isolation.select_engine()
            for e in isolation.ENGINE_ORDER:
                self.assertIn(e, str(cm.exception))
        finally:
            isolation.shutil.which = original
            isolation._PROBES.update(probes)

    def test_wasm_writable_interpreter_folder_refused(self):
        d = tempfile.mkdtemp(prefix="pywasi_fake_")
        try:
            os.mkdir(os.path.join(d, "lib"))
            open(os.path.join(d, "python.wasm"), "wb").close()
            old = os.environ.get("QRAFT_PYTHON_WASM")
            os.environ["QRAFT_PYTHON_WASM"] = d
            try:
                if shutil.which("wasmtime") is None:
                    with self.assertRaises(MP.SandboxMissing):
                        isolation._wasm_parts()
                else:
                    with self.assertRaisesRegex(MP.SandboxMissing, "writable"):
                        isolation._wasm_parts()
            finally:
                if old is None:
                    os.environ.pop("QRAFT_PYTHON_WASM", None)
                else:
                    os.environ["QRAFT_PYTHON_WASM"] = old
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


if __name__ == "__main__":
    unittest.main()
