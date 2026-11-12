# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Test della port centrex_tlf (rigorous_levels/port_runner.py) contro la molecola garantita (NEMESIS blocco B, 11/11/2026).
Richiede bwrap e il venv isolato con centrex-tlf 0.4.0 (RIGOROUS_LEVELS_TARGETS_VENV, default: cartella .venvs/rigorous_levels_targets nella casa dell'user): altrimenti skip.
Mappa delle convenzioni (identità di operatori, non adattamento): c3_nostro = 5·c3_CeNTREX; Debye = 1e-21/c C·m (CODATA esatto)."""
import glob
import os
import pwd
import shutil
import subprocess
import unittest


from rigorous_levels import hyperfine_molecule as MI  # noqa: E402
from rigorous_levels import multiport as MP  # noqa: E402


def _bwrap_funziona():
    """bwrap presente E capace di creare i namespace (stessa sonda di test_multiporta: su runner con userns non
    privilegiati negati bwrap esiste ma fallisce, e i test della sandbox vanno SALTATI con questo reason)."""
    if shutil.which("bwrap") is None:
        return False
    try:
        return subprocess.run(["bwrap", "--unshare-all", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
                               "true"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# casa REALE dal database utenti: con HOME temporanea (obbligatoria nei banchi) expanduser("~") salterebbe i test in silenzio
VENV = os.environ.get("RIGOROUS_LEVELS_TARGETS_VENV", os.path.join(pwd.getpwuid(os.getuid()).pw_dir, ".venvs", "rigorous_levels_targets"))
PY = os.path.join(VENV, "bin", "python")
SP = tuple(p for p in glob.glob(os.path.join(VENV, "lib", "python3*", "site-packages"))
           if os.path.isdir(os.path.join(p, "centrex_tlf")))
PRONTO = _bwrap_funziona() and os.path.exists(PY) and len(SP) == 1 and os.environ.get("RIGOROUS_LEVELS_TARGETS_VENV") is not None

# XConstants di centrex-tlf 0.4.0
B0, D0 = 6689.8736e6 - 45.0843e6 / 2 + 0.0942e6 / 4, 5.84e3
C1, C2, C3_LORO, C4 = 126030.0, 17890.0, 700.0, -13300.0
MU_J, MU_TL, MU_F = 35.0, 1240.5, 2003.63
D_HZ_VCM = 4.2282 * (1e-21 / 299792458.0) * 100 / 6.62607015e-34


def nostra(E, Bg, c3):
    return MI.SigmaMolecule(1, 1, B=B0, D=D0, c1=C1, c2=C2, c3=c3, c4=C4, z_N=MU_J * Bg, z1=MU_TL / 0.5 * Bg,
                            z2=MU_F / 0.5 * Bg, dE=D_HZ_VCM * E)


def verdetto(E, Bg, two_MF, k, Jmax, c3=5 * C3_LORO):
    iv = MI.guaranteed_molecule_levels(nostra(E, Bg, c3), two_MF, k, deadline=300, width=1e-11)
    r = MP.Request("centrex_tlf", {"type": "tlf_centrex", "E_Vcm": E, "B_G": Bg, "Jmax": Jmax, "two_MF": two_MF},
                     k, {}, unit="Hz", seconds=300, mem_mib=4096, site_packages=SP)
    u = MP.run_port(r, python=PY)
    assert u.state == "OK", u.reason
    return MP.compare(iv, "Hz", u, tolerance=0.5).overall


def model(**kw):
    m = {"type": "tlf_centrex", "E_Vcm": 0.0, "B_G": 1e-3, "Jmax": 3, "two_MF": 0}
    m.update(kw)
    return m


class TestIngressiTlf(unittest.TestCase):
    def test_settore_e_base_chiusi(self):
        for kw in ({"Jmax": -1}, {"Jmax": MP.JMAX_TLF + 1}, {"two_MF": 1}, {"two_MF": -3}, {"Jmax": 0, "two_MF": 4},
                   {"two_MF": 10 ** 6}, {"Jmax": 0, "two_MF": -4}, {"Jmax": 10 ** 9}):
            with self.assertRaises(MP.OutOfDomain, msg=kw):
                MP.Request("centrex_tlf", model(**kw), 2, {}, unit="Hz")
        for kw in ({"Jmax": 0, "two_MF": 2}, {"Jmax": 0, "two_MF": -2}, {"Jmax": MP.JMAX_TLF, "two_MF": 0}):
            MP.Request("centrex_tlf", model(**kw), 2, {}, unit="Hz")


@unittest.skipUnless(PRONTO, "bwrap o venv con centrex-tlf assenti")
class TestPortaCentrex(unittest.TestCase):
    def test_campo_nullo_mappa_c3_e_controllo_positivo(self):
        self.assertEqual(verdetto(0.0, 1e-3, 0, 14, 5), "INSIDE")            # J ≤ 3: la mappa non è una coincidenza di J = 1
        self.assertEqual(verdetto(0.0, 1e-3, 0, 6, 4, c3=-C3_LORO / 6 ** 0.5), "OUTSIDE")   # mappa letterale −c3/√6: falsificata

    def test_stark_173_debye_esatto(self):
        self.assertEqual(verdetto(173.0, 1e-3, 2, 8, 6), "INSIDE")           # residuo 3,26 Hz sparito con il Debye esatto

    def test_zeeman_segno_e_j1(self):
        # 10 G lungo +z: levels J = 0 e J = 1 del settore M_F = 1 (primi 4) coincidono; un segno opposto li sposterebbe di kHz
        self.assertEqual(verdetto(0.0, 10.0, 2, 4, 4), "INSIDE")
        self.assertEqual(verdetto(0.0, -10.0, 2, 4, 4), "INSIDE")
        iv = MI.guaranteed_molecule_levels(nostra(0.0, 10.0, 5 * C3_LORO), 2, 4, deadline=300, width=1e-11)
        r = MP.Request("centrex_tlf", model(B_G=-10.0, Jmax=4, two_MF=2), 4, {}, unit="Hz", seconds=300,
                         mem_mib=4096, site_packages=SP)
        self.assertEqual(MP.compare(iv, "Hz", MP.run_port(r, python=PY), tolerance=0.5).overall, "OUTSIDE")


if __name__ == "__main__":
    unittest.main()
