# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Test di qraft_ra/multiporta.py + qraft_ra/porte_runner.py (10/11/2026). Specifica: note dell'autore (non pubblicate).
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


from qraft_ra import multiporta as MP  # noqa: E402

FLINT = importlib.util.find_spec("flint") is not None
def _bwrap_funziona():
    """bwrap presente E capace di creare i namespace (su alcuni runner CI gli userns non privilegiati sono negati:
    allora i test della sandbox sono SALTATI con questo motivo, non passati)."""
    if shutil.which("bwrap") is None:
        return False
    try:
        return subprocess.run(["bwrap", "--unshare-all", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
                               "true"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


BWRAP = _bwrap_funziona()
import sysconfig  # noqa: E402

import site  # noqa: E402

# il venv qraft prende matplotlib (richiesto da scqubits) dal site utente: entrambi dichiarati, in sola lettura
SITE = tuple(p for p in (sysconfig.get_path("purelib"), site.getusersitepackages()) if os.path.isdir(p))
ROTORE = {"tipo": "rotore_cos", "E_C": 0.3, "E_J": 15.0, "n_g": 0.25}


def richiesta(porta="numpy_rotore", **kw):
    base = dict(porta=porta, modello=ROTORE, livelli=6, troncamento={"ncut": 30}, unita="GHz", secondi=20,
                mem_mib=1024, site_packages=SITE)
    base.update(kw)
    return MP.Richiesta(**base)


def runner_diretto(r, timeout=30):
    """Esegue il runner SENZA sandbox (solo nei test, come controllo positivo): ciò che qui riesce, dentro deve fallire."""
    work = tempfile.mkdtemp(prefix="qraft_porta_diretto_")
    try:
        with open(os.path.join(work, "richiesta.json"), "w") as f:
            json.dump(r.json(), f)
        subprocess.run([sys.executable, "-I", "-B", str(MP.RUNNER), work], capture_output=True, text=True, timeout=timeout,
                       env={"PATH": os.environ.get("PATH", ""), "HOME": tempfile.mkdtemp(prefix="home_prova_")})
        with open(os.path.join(work, "uscita.json")) as f:
            return json.load(f)
    finally:
        shutil.rmtree(work, ignore_errors=True)


class TestContrattoChiuso(unittest.TestCase):
    def test_richiesta_chiusa(self):
        for kw in (dict(porta="inesistente"), dict(modello={"tipo": "altro"}), dict(modello={**ROTORE, "extra": 1}),
                   dict(modello={"tipo": "rotore_cos", "E_C": 0.3}), dict(modello={**ROTORE, "E_J": "15"}),
                   dict(modello={**ROTORE, "E_J": float("nan")}), dict(livelli=0), dict(livelli=True),
                   dict(unita="eV"), dict(secondi=0), dict(mem_mib=1), dict(troncamento=[30]),
                   dict(troncamento={"ncut": float("inf")}), dict(troncamento={1: 2}), dict(site_packages=("/nonexistent",)),
                   dict(site_packages=["x"])):
            with self.assertRaises(MP.FuoriDominio, msg=str(kw)):
                richiesta(**kw)

    def test_uscita_chiusa_generativa(self):
        """S6: ogni deformazione dell'uscita valida è NON valida col motivo; mai un'eccezione diversa."""
        r = richiesta("numpy_rotore")
        buona = {"contratto": MP.CONTRATTO, "porta": "numpy_rotore", "versione_solutore": "x", "livelli": [0.0] * 6,
                 "unita": "GHz", "stato": "OK", "motivo": "", "secondi": 0.1}
        u, m = MP.valida_uscita(buona, r)
        self.assertIsNotNone(u, m)
        deformazioni = [dict(buona, extra=1), {k: v for k, v in buona.items() if k != "motivo"},
                        dict(buona, contratto="qraft-porta/0.2"), dict(buona, porta="prova_sbagliata"),
                        dict(buona, stato="BOH"), dict(buona, stato=1), dict(buona, unita="eV"),
                        dict(buona, livelli=[0.0] * 5), dict(buona, livelli=[0.0] * 7), dict(buona, livelli="0"),
                        dict(buona, livelli=[float("nan")] * 6), dict(buona, livelli=[True] * 6),
                        dict(buona, livelli=[0.0] * 5 + ["1"]), dict(buona, secondi="1"), dict(buona, secondi=float("inf")),
                        dict(buona, motivo=None), dict(buona, versione_solutore=3), [buona], "x", None, 3]
        for d in deformazioni:
            u, m = MP.valida_uscita(d, r)
            self.assertIsNone(u, d)
            self.assertTrue(m, d)

    def test_confronta_esatto(self):
        from fractions import Fraction as F
        iv = MP.Intervalli((F(1), F(2)), (F(1, 1) + F(1, 10 ** 9), F(2) + F(1, 10 ** 9)), (("1", "1"), ("2", "2")),
                           1e-9, "GARANTITO", 10, 128, 0.0, 0.0)
        u_ok = MP.Uscita("numpy_rotore", "v", (1000.0, 2000.0), "MHz", "OK", "", 0.0, "")
        self.assertEqual(MP.confronta(iv, "GHz", u_ok).complessivo, "DENTRO")
        u_fuori = MP.Uscita("numpy_rotore", "v", (1000.0, 2000.002), "MHz", "OK", "", 0.0, "")
        v = MP.confronta(iv, "GHz", u_fuori)
        self.assertEqual(v.complessivo, "FUORI")
        self.assertEqual(v.per_livello[1][0], "FUORI")
        self.assertIn("e-06 GHz", v.per_livello[1][1])
        u_err = MP.Uscita("numpy_rotore", "v", (), "GHz", "ERRORE", "boom", 0.0, "")
        self.assertEqual(MP.confronta(iv, "GHz", u_err).complessivo, "NON_CONFRONTABILE")
        with self.assertRaises(MP.FuoriDominio):
            MP.confronta(iv, "eV", u_ok)


@unittest.skipUnless(BWRAP, "bwrap assente")
class TestSandbox(unittest.TestCase):
    def test_s5_senza_bwrap_fail_closed(self):
        originale = MP.shutil.which
        MP.shutil.which = lambda nome: None
        try:
            with self.assertRaises(MP.SandboxAssente):
                MP.esegui_porta(richiesta("numpy_rotore"))
        finally:
            MP.shutil.which = originale

    def test_s7_solutore_giusto_e_sbagliato(self):
        if not FLINT:
            self.skipTest("python-flint assente")
        from qraft_ra.intervallo_garantito import livelli_garantiti
        from qraft_ra.rotore_spettro import Rotore
        iv = livelli_garantiti(Rotore(E_C=0.3, coseni=((1, -15.0),), n_g=0.25), 6, scadenza=60)
        u = MP.esegui_porta(richiesta("numpy_rotore"))
        self.assertEqual(u.stato, "OK", u)
        # eigvalsh float64: rumore ~1e-13 GHz (misurato), intervalli larghi ~1e-13: senza tolleranza è FUORI di 1e-14
        self.assertIn(MP.confronta(iv, "GHz", u).complessivo, ("DENTRO", "FUORI"))
        v0 = MP.confronta(iv, "GHz", u, tolleranza=1e-12)
        self.assertIn(v0.complessivo, ("DENTRO", "DENTRO_TOLLERANZA"), v0)
        self.assertTrue(all(float(d.split()[0]) <= 1e-12 for s, d in v0.per_livello if s != "DENTRO"), v0)
        u2 = MP.esegui_porta(richiesta("prova_sbagliata"))
        self.assertEqual(u2.stato, "OK", u2)
        v = MP.confronta(iv, "GHz", u2, tolleranza=1e-12)
        self.assertEqual(v.complessivo, "FUORI")
        with self.assertRaises(MP.FuoriDominio):
            MP.confronta(iv, "GHz", u2, tolleranza=-1.0)
        self.assertTrue(any(s == "FUORI" for s, _ in v.per_livello))
        # unità diverse: la stessa uscita in MHz resta DENTRO
        u3 = MP.Uscita(u.porta, u.versione_solutore, tuple(x * 1e3 for x in u.livelli), "MHz", "OK", "", 0.0, "")
        self.assertEqual(MP.confronta(iv, "GHz", u3, tolleranza=1e-12).complessivo, v0.complessivo)

    def test_s1_rete_bloccata(self):
        with socket.socket() as srv:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            porta_tcp = srv.getsockname()[1]
            r = richiesta("prova_rete", troncamento={"porta_tcp": porta_tcp})
            diretto = runner_diretto(r)                       # controllo positivo: fuori dalla sandbox la rete c'è
            self.assertEqual(diretto["stato"], "OK", diretto)
            self.assertIn("RAGGIUNTA", diretto["versione_solutore"])
            u = MP.esegui_porta(r)
        self.assertEqual(u.stato, "ERRORE", u)
        self.assertIn("rete bloccata", u.motivo)

    def test_s2_scrittura_e_home_bloccate(self):
        fuori = tempfile.mkdtemp(prefix="qraft_fuori_")
        bersaglio = os.path.join(fuori, "scritto_dal_solutore.txt")
        home_vera = os.path.expanduser("~")
        r = richiesta("prova_scrittura", troncamento={"percorso": bersaglio, "home_vera": home_vera})
        diretto = runner_diretto(r)                           # controllo positivo: fuori dalla sandbox scrive
        self.assertIn(f"SCRITTO {bersaglio}", diretto["motivo"])
        self.assertTrue(os.path.exists(bersaglio))
        os.remove(bersaglio)
        u = MP.esegui_porta(r)
        self.assertEqual(u.stato, "ERRORE")
        self.assertIn(f"bloccato {bersaglio}", u.motivo)
        self.assertIn("home_vera_visibile=False", u.motivo)
        self.assertFalse(os.path.exists(bersaglio))
        self.assertFalse(os.path.exists(os.path.join(home_vera, "qraft_porta_prova.txt")))
        shutil.rmtree(fuori, ignore_errors=True)

    def test_s3_tempo(self):
        u = MP.esegui_porta(richiesta("prova_loop", secondi=2))
        self.assertEqual(u.stato, "NON_VALIDA", u)
        self.assertIn("timeout", u.motivo)

    def test_s3_memoria(self):
        u = MP.esegui_porta(richiesta("prova_memoria", troncamento={"mib": 3000}, mem_mib=256))
        self.assertEqual(u.stato, "ERRORE", u)
        self.assertIn("MemoryError", u.motivo)

    def test_s4_ambiente_pulito(self):
        """PYTHONPATH/HOME della sessione non arrivano: la porta vede HOME = /tmp/casa_assente (inesistente)."""
        r = richiesta("prova_scrittura", troncamento={"percorso": "/tmp/fuori_work.txt", "home_vera": os.path.expanduser("~")})
        os.environ["QRAFT_PROVA_AMBIENTE"] = "1"
        try:
            u = MP.esegui_porta(r)
        finally:
            os.environ.pop("QRAFT_PROVA_AMBIENTE", None)
        self.assertIn("bloccato /tmp/casa_assente/qraft_porta_prova.txt", u.motivo)
        # --unshare-all: nuovo namespace PID (il runner ha pid ≤ 10; fuori dalla sandbox è il pid vero, grande)
        pid = int(u.motivo.split("pid=")[1].split(";")[0].strip())
        self.assertLessEqual(pid, 10, u.motivo)
        diretto = runner_diretto(r)
        self.assertGreater(int(diretto["motivo"].split("pid=")[1].split(";")[0].strip()), 10, diretto["motivo"])

    def test_s6_uscita_sporca(self):
        u = MP.esegui_porta(richiesta("prova_uscita_sporca"))
        self.assertEqual(u.stato, "NON_VALIDA", u)
        self.assertIn("chiave_ignota", u.motivo)

    def test_scqubits_e_diatomic(self):
        if importlib.util.find_spec("scqubits") is None or not FLINT:
            self.skipTest("scqubits o flint assenti")
        from qraft_ra.intervallo_garantito import livelli_garantiti
        from qraft_ra.rotore_spettro import Rotore
        iv = livelli_garantiti(Rotore(E_C=0.3, coseni=((1, -15.0),), n_g=0.25), 6, scadenza=60)
        u = MP.esegui_porta(richiesta("scqubits_transmon", mem_mib=4096, secondi=120))
        self.assertEqual(u.stato, "OK", u)
        self.assertIn("scqubits", u.versione_solutore)
        self.assertIn(MP.confronta(iv, "GHz", u, tolleranza=1e-12).complessivo, ("DENTRO", "DENTRO_TOLLERANZA"))
        if importlib.util.find_spec("diatomic") is None:
            self.skipTest("diatomic-py assente")
        from qraft_ra import molecola_iperfine_garantita as MI
        mol = dict(tipo="molecola_sigma", due_I1=3, due_I2=7, due_MF=12, B=490173.994e3, D=213.0, c1=29.4, c2=196.8,
                   c3=192.4, c4=19.019e3, eQq1=-809.29e3, eQq2=59.98e3, z_N=MI.zeeman_hz(0.0062, 181.541),
                   z1=MI.zeeman_hz(1.8295, 181.541), z2=MI.zeeman_hz(0.7331, 181.541), dE=0.0)
        m = MI.MolecolaSigma(**{k: v for k, v in mol.items() if k not in ("tipo", "due_MF")})
        iv6 = MI.livelli_molecola_garantiti(m, 12, 1, L_iniziale=3, L_limite=3, scadenza=120, larghezza=1e-11)
        u = MP.esegui_porta(richiesta("diatomic_py", modello=mol, livelli=1, troncamento={"N_max": 3}, unita="Hz", secondi=120, mem_mib=4096))
        self.assertEqual(u.stato, "OK", u)
        self.assertIn("c3 → −c3", u.versione_solutore)
        self.assertIn(MP.confronta(iv6, "Hz", u, tolleranza=1e-3).complessivo, ("DENTRO", "DENTRO_TOLLERANZA"), (iv6.stringhe, u))


class TestNemesis20261111(unittest.TestCase):
    """Rilievi NEMESIS 11/11/2026: ogni caso ha il suo controllo positivo (fuori dalla sandbox / codice vecchio)."""

    def test_leggi_uscita_json_stretto(self):
        d = tempfile.mkdtemp(prefix="qraft_uscita_")
        try:
            p = os.path.join(d, "u.json")
            buona = {"contratto": MP.CONTRATTO, "porta": "numpy_rotore", "versione_solutore": "x", "livelli": [0.0] * 6,
                     "unita": "GHz", "stato": "OK", "motivo": "", "secondi": 0.1}
            casi = ["[" * 200000 + "]" * 200000, '{"a":' * 100000 + "1" + "}" * 100000,
                    json.dumps(buona)[:-1] + ', "stato": "ERRORE"}', json.dumps(buona).replace("[0.0,", "[NaN,"),
                    json.dumps(dict(buona, motivo="x" * (MP.USCITA_MAX_BYTE + 1 - len(json.dumps(dict(buona, motivo="")))))),
                    "\xff"]                          # JSON valido di esattamente USCITA_MAX_BYTE + 1 byte
            for c in casi:
                with open(p, "w", encoding="latin-1") as f:
                    f.write(c)
                doc, motivo = MP.leggi_uscita(p)
                self.assertIsNone(doc, c[:40])
                self.assertTrue(motivo)
            with open(p, "w") as f:
                json.dump(buona, f)
            self.assertEqual(MP.leggi_uscita(p)[0], buona)              # controllo positivo: la valida passa
            os.symlink(p, os.path.join(d, "link"))
            self.assertIsNone(MP.leggi_uscita(os.path.join(d, "link"))[0])
            os.mkfifo(os.path.join(d, "fifo"))
            self.assertIsNone(MP.leggi_uscita(os.path.join(d, "fifo"))[0])
            os.mkdir(os.path.join(d, "cartella"))
            self.assertIsNone(MP.leggi_uscita(os.path.join(d, "cartella"))[0])
            self.assertIsNone(MP.leggi_uscita(os.path.join(d, "assente"))[0])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_valida_uscita_mai_eccezione(self):
        r = richiesta("numpy_rotore")
        buona = {"contratto": MP.CONTRATTO, "porta": "numpy_rotore", "versione_solutore": "x", "livelli": [0.0] * 6,
                 "unita": "GHz", "stato": "OK", "motivo": "", "secondi": 0.1}
        for d in (dict(buona, livelli=[10 ** 400] + [0.0] * 5), dict(buona, secondi=10 ** 400),
                  dict(buona, stato="ERRORE", livelli=["abc"]), dict(buona, stato="ERRORE", livelli=[[1]])):
            u, m = MP.valida_uscita(d, r)
            if d["stato"] == "OK":
                self.assertIsNone(u, m)
            else:
                self.assertEqual((u.stato, u.livelli), ("ERRORE", ()))

    def test_richiesta_tetti_e_tipi(self):
        for kw in (dict(secondi=2 ** 31), dict(secondi=MP.SECONDI_MAX + 1), dict(mem_mib=MP.MEM_MIB_MAX + 1),
                   dict(livelli=MP.LIVELLI_MAX + 1), dict(unita=[]), dict(modello={**ROTORE, "tipo": []}),
                   dict(modello={**ROTORE, "E_C": 10 ** 400}), dict(site_packages=(os.path.expanduser("~"),)),
                   dict(site_packages=("/",))):
            with self.assertRaises(MP.FuoriDominio, msg=str(kw)[:80]):
                richiesta(**kw)
        richiesta(secondi=MP.SECONDI_MAX, mem_mib=MP.MEM_MIB_MAX, livelli=6)     # controllo positivo: i tetti stessi passano

    def test_confronta_k_diversi_e_uscita_a_mano(self):
        from fractions import Fraction as F
        iv = MP.Intervalli((F(1),), (F(1) + F(1, 10 ** 9),), (("1", "1"),), 1e-9, "GARANTITO", 10, 128, 0.0, 0.0)
        u3 = MP.Uscita("numpy_rotore", "v", (1.0, 99.0, 1e9), "GHz", "OK", "", 0.0, "")
        self.assertEqual(MP.confronta(iv, "GHz", u3).complessivo, "NON_CONFRONTABILE")
        u1 = MP.Uscita("numpy_rotore", "v", (1.0,), "GHz", "OK", "", 0.0, "")
        self.assertEqual(MP.confronta(iv, "GHz", u1).complessivo, "DENTRO")          # controllo positivo
        for u in (MP.Uscita("numpy_rotore", "v", (float("nan"),), "GHz", "OK", "", 0.0, ""),
                  MP.Uscita("numpy_rotore", "v", (1.0,), "eV", "OK", "", 0.0, "")):
            with self.assertRaises(MP.FuoriDominio):
                MP.confronta(iv, "GHz", u)
        with self.assertRaises(MP.FuoriDominio):
            MP.confronta(iv, "GHz", u1, tolleranza=10 ** 400)

    @unittest.skipUnless(BWRAP, "bwrap assente")
    def test_ambiente_di_sessione_mai_visibile(self):
        """Nemmeno in /proc/1/environ (init di bwrap). Controllo positivo: fuori dalla sandbox la variabile si vede."""
        r = richiesta("prova_ostile", troncamento={"modo": "ambiente", "nome": "QRAFT_NEMESIS_ESCA"})
        os.environ["QRAFT_NEMESIS_ESCA"] = "esca"
        try:
            u = MP.esegui_porta(r)
            diretto = subprocess.run([sys.executable, "-c", "import os,sys; print('QRAFT_NEMESIS_ESCA' in os.environ)"],
                                     capture_output=True, text=True).stdout.strip()
        finally:
            os.environ.pop("QRAFT_NEMESIS_ESCA", None)
        self.assertEqual(u.stato, "ERRORE", u)
        self.assertIn("visto in []", u.motivo)
        self.assertEqual(diretto, "True")

    @unittest.skipUnless(BWRAP, "bwrap assente")
    def test_uscita_non_sostituibile_e_disco_limitato(self):
        u = MP.esegui_porta(richiesta("prova_ostile", troncamento={"modo": "symlink", "bersaglio": "/etc/hostname"}))
        self.assertEqual(u.stato, "ERRORE", u)
        self.assertIn("symlink bloccato", u.motivo)
        u = MP.esegui_porta(richiesta("prova_ostile", troncamento={"modo": "disco", "dove": "/tmp/work", "file": 2, "mib": 1}))
        self.assertIn("disco: 0 MiB poi OSError", u.motivo)
        for dove in ("/tmp", "/dev/shm", "/home"):           # tmpfs in RAM: tetto per ciascuno (RLIMIT_AS non li conta)
            u = MP.esegui_porta(richiesta("prova_ostile", troncamento={"modo": "disco", "dove": dove, "file": 6, "mib": 60}))
            self.assertIn("poi OSError", u.motivo, dove)
            self.assertLessEqual(int(u.motivo.split("disco: ")[1].split(" MiB")[0]), MP.TMPFS_BYTE >> 20, dove)

    @unittest.skipUnless(BWRAP, "bwrap assente")
    def test_stdout_illimitato_non_entra_in_memoria(self):
        import resource
        prima = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        u = MP.esegui_porta(richiesta("prova_ostile", troncamento={"modo": "stdout", "mib": 300}))
        dopo = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        self.assertEqual(u.stato, "ERRORE", u)
        self.assertLess(dopo - prima, 100 * 1024, (prima, dopo))           # KiB: con capture_output cresce di ≥ 300 MiB

    @unittest.skipUnless(BWRAP, "bwrap assente")
    def test_site_packages_sola_lettura_e_rlimit(self):
        """Il site-packages montato non è scrivibile (il motore «processo» importa da lì); NPROC, FSIZE e CPU mordono."""
        # nome usa-e-getta, NON .pth, e rimosso comunque: un mutante che rende scrivibile il bind scriverebbe nel venv VERO
        bersaglio = os.path.join(SITE[0], f"qraft_nemesis_prova_{os.getpid()}.txt")
        try:
            u = MP.esegui_porta(richiesta("prova_ostile", troncamento={"modo": "scrivi", "percorso": bersaglio}))
            esiste = os.path.exists(bersaglio)
        finally:
            if os.path.exists(bersaglio):
                os.remove(bersaglio)
        self.assertIn("scrivi: bloccato", u.motivo)
        self.assertFalse(esiste)
        u = MP.esegui_porta(richiesta("prova_ostile", troncamento={"modo": "fork"}))
        self.assertLessEqual(int(u.motivo.split("fork: ")[1]), 16, u.motivo)
        u = MP.esegui_porta(richiesta("prova_ostile", troncamento={"modo": "disco", "dove": "/tmp", "file": 1, "mib": 70}))
        self.assertIn("disco: 64 MiB poi OSError", u.motivo)
        u = MP.esegui_porta(richiesta("prova_ostile", troncamento={"modo": "cpu"}, secondi=2))
        self.assertEqual(u.stato, "NON_VALIDA", u)
        self.assertNotIn("timeout", u.motivo)                 # ucciso da RLIMIT_CPU, non dal timeout del chiamante

    def test_tolleranza_al_confine(self):
        from fractions import Fraction as F
        iv = MP.Intervalli((F(1),), (F(1),), (("1", "1"),), 0.0, "GARANTITO", 10, 128, 0.0, 0.0)
        u = MP.Uscita("numpy_rotore", "v", (1.5,), "GHz", "OK", "", 0.0, "")
        self.assertEqual(MP.confronta(iv, "GHz", u, tolleranza=0.5).complessivo, "DENTRO_TOLLERANZA")
        self.assertEqual(MP.confronta(iv, "GHz", u, tolleranza=0.25).complessivo, "FUORI")

    @unittest.skipUnless(BWRAP, "bwrap assente")
    def test_ok_poi_crash_non_valida(self):
        u = MP.esegui_porta(richiesta("prova_ostile", troncamento={"modo": "ok_poi_crash"}))
        self.assertEqual(u.stato, "NON_VALIDA", u)
        self.assertIn("codice di uscita", u.motivo)

    def test_bwrap_non_di_root_rifiutato(self):
        d = tempfile.mkdtemp(prefix="finto_bwrap_")
        finto = os.path.join(d, "bwrap")
        with open(finto, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(finto, 0o755)
        originale = MP.shutil.which
        MP.shutil.which = lambda nome: finto
        try:
            with self.assertRaises(MP.SandboxAssente):
                MP.esegui_porta(richiesta("numpy_rotore"))
        finally:
            MP.shutil.which = originale
            shutil.rmtree(d, ignore_errors=True)


class TestBersagliTroncamentoChiuso(unittest.TestCase):
    """NEMESIS 11/11: le porte dei bersagli accettavano chiavi ignote, 15.9 e "15" nel troncamento (int() nel runner)."""
    ROT = {"tipo": "rotore_cos", "E_C": 0.2, "E_J": 10.0, "n_g": 0.0}
    TLF = {"tipo": "tlf_centrex", "E_Vcm": 0.0, "B_G": 0.0, "Jmax": 1, "due_MF": 0}

    def test_troncamento_chiuso_per_porta(self):
        buoni = (("metal_hcpb", self.ROT, {"nlevels": 15}), ("metal_mathieu", self.ROT, {}),
                 ("sqcircuit_transmon", self.ROT, {"ncut": 30}), ("pyepr_fock", self.ROT, {"cos_trunc": 5, "fock_trunc": 10}),
                 ("centrex_tlf", self.TLF, {}))
        for porta, mod, tr in buoni:
            MP.Richiesta(porta, dict(mod), 4, dict(tr))
            for cattivo in ({**tr, "chiave_ignota": 1}, {k: v + 0.5 for k, v in tr.items()},
                            {k: str(v) for k, v in tr.items()}, {k: True for k in tr}, {k: 0 for k in tr},
                            {k: -3 for k in tr}, {k: v for k, v in list(tr.items())[1:]}):
                if cattivo == tr:
                    continue
                with self.assertRaises(MP.FuoriDominio, msg=(porta, cattivo)):
                    MP.Richiesta(porta, dict(mod), 4, cattivo)

    def test_modello_obbligato_e_jmax(self):
        with self.assertRaises(MP.FuoriDominio):
            MP.Richiesta("metal_hcpb", dict(self.TLF), 4, {"nlevels": 15})
        with self.assertRaises(MP.FuoriDominio):
            MP.Richiesta("centrex_tlf", dict(self.ROT), 4, {})
        with self.assertRaises(MP.FuoriDominio):
            MP.Richiesta("centrex_tlf", {**self.TLF, "Jmax": -1}, 4, {})


class TestPrefissoInterprete(unittest.TestCase):
    """NEMESIS 11/11 (pubblicazione 0.2.0): un python con sys.base_prefix = <casa>/.local (o = la casa, con HOME diversa) faceva
    montare l'intera cartella: la porta leggeva <casa>/.local/share/keyrings. Si montano solo eseguibile, stdlib e libpython."""

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
            if not any(stdlib_reale.startswith(m + "/") for m in MP.MONTAGGI_RO):
                with self.assertRaises(MP.FuoriDominio):     # stdlib (symlink) fuori dal prefisso: rifiuto, nessun montaggio
                    MP._prefisso_interprete(exe)
                return
            pezzi = MP._prefisso_interprete(exe)             # stdlib già sotto /usr: deve montare solo l'eseguibile
            segreto = os.path.realpath(os.path.join(prefisso, "share", "keyrings"))
            self.assertIn(os.path.realpath(exe), pezzi)
            for x in pezzi:                                   # nessun montaggio contiene la cartella del segreto
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
            with self.assertRaisesRegex(MP.FuoriDominio, "casa dell'utente"):
                MP._prefisso_interprete(exe)
        finally:
            if vecchio is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = vecchio
            shutil.rmtree(casa, ignore_errors=True)

    def test_sonda_malformata_rifiutata(self):
        """La sonda dell'interprete è un JSON di 4 stringhe: altro (lunghezza, tipo, non JSON) = FuoriDominio, mai crash."""
        d = tempfile.mkdtemp(prefix="finto_python_")
        try:
            os.makedirs(os.path.join(d, "bin"))
            finto = os.path.join(d, "bin", "python3")
            for uscita in (json.dumps([d]), json.dumps([d, d, d, 4]), "non json", json.dumps({"a": d}), json.dumps([d, d, d, ""])):
                with open(finto, "w") as f:
                    f.write("#!/bin/sh\necho '" + uscita + "'\n")
                os.chmod(finto, 0o755)
                with self.assertRaises(MP.FuoriDominio, msg=uscita):
                    MP._prefisso_interprete(finto)
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
            self.assertEqual(set(MP._prefisso_interprete(finto)),
                             {finto, d + "/lib/a", d + "/lib/b", d + "/lib/c/libpython3.99.so.1.0"})
        finally:
            shutil.rmtree(d, ignore_errors=True)

    @unittest.skipUnless(BWRAP, "bwrap assente")
    def test_pezzi_interprete_sola_lettura(self):
        """I pezzi montati dell'interprete (eseguibile, stdlib) non sono scrivibili dalla porta."""
        pezzi = MP._prefisso_interprete(os.path.realpath(sys.executable))
        cartelle = [x for x in pezzi if os.path.isdir(x)]
        if not cartelle:
            self.skipTest("interprete sotto /usr: nessun pezzo montato")
        bersaglio = os.path.join(cartelle[0], f"qraft_nemesis_prova_{os.getpid()}.txt")
        try:
            u = MP.esegui_porta(richiesta("prova_ostile", troncamento={"modo": "scrivi", "percorso": bersaglio}))
            esiste = os.path.exists(bersaglio)
        finally:
            if os.path.exists(bersaglio):
                os.remove(bersaglio)
        self.assertIn("scrivi: bloccato", u.motivo)
        self.assertFalse(esiste)

    def test_case_utente_anche_da_pwd(self):
        import pwd
        vecchio = os.environ.get("HOME")
        os.environ["HOME"] = tempfile.mkdtemp(prefix="home_diversa_")
        try:
            self.assertIn(os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir), MP._case_utente())
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
            return MP.leggi_uscita(p)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_limite_esatto(self):
        L = MP.USCITA_MAX_PROFONDITA
        self.assertEqual(L, 32)                                              # il numero dichiarato in README e CHANGELOG
        for apri, chiudi in (("[", "]"), ('{"a":', "}")):
            doc, motivo = self._scrivi_e_leggi(apri * L + "1" + chiudi * L)
            self.assertIsNotNone(doc, motivo)                                   # controllo positivo: L livelli passano
            doc, motivo = self._scrivi_e_leggi(apri * (L + 1) + "1" + chiudi * (L + 1))
            self.assertIsNone(doc)
            self.assertIn("annidata", motivo)
            for n in (1000, 100000, 400000):                                    # i casi della CI, su ogni Python
                self.assertIsNone(self._scrivi_e_leggi(apri * n + "1" + chiudi * n)[0])

    def test_parentesi_nelle_stringhe_non_contano(self):
        L = MP.USCITA_MAX_PROFONDITA
        s = json.dumps({"motivo": "[" * 1000 + '\\" {{{ \\\\', "x": ["]]]" * 50, "\"[\""]})
        self.assertEqual(MP._profondita_json(s, L), 2)
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
            self.assertEqual(min(MP._profondita_json(s, 10 ** 9), 10 ** 9), vera(o))
            doc, motivo = self._scrivi_e_leggi(s)
            self.assertEqual(bool(motivo), vera(o) > MP.USCITA_MAX_PROFONDITA, motivo)   # null è un doc valido: conta il motivo

    def test_caso_peggiore_lineare(self):
        import time
        n = MP.USCITA_MAX_BYTE
        for testo in ('"\\' * (n // 2), '"' * n, "[" * n, "a" * n):
            t0 = time.perf_counter()
            doc, motivo = self._scrivi_e_leggi(testo[:n])
            self.assertIsNone(doc)
            self.assertLess(time.perf_counter() - t0, 5.0, testo[:4])


if __name__ == "__main__":
    unittest.main()
