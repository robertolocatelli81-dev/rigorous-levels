# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Test della porta centrex_tlf (qraft_ra/porte_runner.py) contro la molecola garantita (NEMESIS blocco B, 11/11/2026).
Richiede bwrap e il venv isolato con centrex-tlf 0.4.0 (QRAFT_BERSAGLI_VENV, default: cartella .venvs/qraft_bersagli nella casa dell'utente): altrimenti skip.
Mappa delle convenzioni (identità di operatori, non adattamento): c3_nostro = 5·c3_CeNTREX; Debye = 1e-21/c C·m (CODATA esatto)."""
import glob
import os
import pwd
import shutil
import unittest


from qraft_ra import molecola_iperfine_garantita as MI  # noqa: E402
from qraft_ra import multiporta as MP  # noqa: E402

# casa REALE dal database utenti: con HOME temporanea (obbligatoria nei banchi) expanduser("~") salterebbe i test in silenzio
VENV = os.environ.get("QRAFT_BERSAGLI_VENV", os.path.join(pwd.getpwuid(os.getuid()).pw_dir, ".venvs", "qraft_bersagli"))
PY = os.path.join(VENV, "bin", "python")
SP = tuple(p for p in glob.glob(os.path.join(VENV, "lib", "python3*", "site-packages"))
           if os.path.isdir(os.path.join(p, "centrex_tlf")))
PRONTO = shutil.which("bwrap") is not None and os.path.exists(PY) and len(SP) == 1 and os.environ.get("QRAFT_BERSAGLI_VENV") is not None

# XConstants di centrex-tlf 0.4.0
B0, D0 = 6689.8736e6 - 45.0843e6 / 2 + 0.0942e6 / 4, 5.84e3
C1, C2, C3_LORO, C4 = 126030.0, 17890.0, 700.0, -13300.0
MU_J, MU_TL, MU_F = 35.0, 1240.5, 2003.63
D_HZ_VCM = 4.2282 * (1e-21 / 299792458.0) * 100 / 6.62607015e-34


def nostra(E, Bg, c3):
    return MI.MolecolaSigma(1, 1, B=B0, D=D0, c1=C1, c2=C2, c3=c3, c4=C4, z_N=MU_J * Bg, z1=MU_TL / 0.5 * Bg,
                            z2=MU_F / 0.5 * Bg, dE=D_HZ_VCM * E)


def verdetto(E, Bg, due_MF, k, Jmax, c3=5 * C3_LORO):
    iv = MI.livelli_molecola_garantiti(nostra(E, Bg, c3), due_MF, k, scadenza=300, larghezza=1e-11)
    r = MP.Richiesta("centrex_tlf", {"tipo": "tlf_centrex", "E_Vcm": E, "B_G": Bg, "Jmax": Jmax, "due_MF": due_MF},
                     k, {}, unita="Hz", secondi=300, mem_mib=4096, site_packages=SP)
    u = MP.esegui_porta(r, python=PY)
    assert u.stato == "OK", u.motivo
    return MP.confronta(iv, "Hz", u, tolleranza=0.5).complessivo


def modello(**kw):
    m = {"tipo": "tlf_centrex", "E_Vcm": 0.0, "B_G": 1e-3, "Jmax": 3, "due_MF": 0}
    m.update(kw)
    return m


class TestIngressiTlf(unittest.TestCase):
    def test_settore_e_base_chiusi(self):
        for kw in ({"Jmax": -1}, {"Jmax": MP.JMAX_TLF + 1}, {"due_MF": 1}, {"due_MF": -3}, {"Jmax": 0, "due_MF": 4},
                   {"due_MF": 10 ** 6}, {"Jmax": 0, "due_MF": -4}, {"Jmax": 10 ** 9}):
            with self.assertRaises(MP.FuoriDominio, msg=kw):
                MP.Richiesta("centrex_tlf", modello(**kw), 2, {}, unita="Hz")
        for kw in ({"Jmax": 0, "due_MF": 2}, {"Jmax": 0, "due_MF": -2}, {"Jmax": MP.JMAX_TLF, "due_MF": 0}):
            MP.Richiesta("centrex_tlf", modello(**kw), 2, {}, unita="Hz")


@unittest.skipUnless(PRONTO, "bwrap o venv con centrex-tlf assenti")
class TestPortaCentrex(unittest.TestCase):
    def test_campo_nullo_mappa_c3_e_controllo_positivo(self):
        self.assertEqual(verdetto(0.0, 1e-3, 0, 14, 5), "DENTRO")            # J ≤ 3: la mappa non è una coincidenza di J = 1
        self.assertEqual(verdetto(0.0, 1e-3, 0, 6, 4, c3=-C3_LORO / 6 ** 0.5), "FUORI")   # mappa letterale −c3/√6: falsificata

    def test_stark_173_debye_esatto(self):
        self.assertEqual(verdetto(173.0, 1e-3, 2, 8, 6), "DENTRO")           # residuo 3,26 Hz sparito con il Debye esatto

    def test_zeeman_segno_e_j1(self):
        # 10 G lungo +z: livelli J = 0 e J = 1 del settore M_F = 1 (primi 4) coincidono; un segno opposto li sposterebbe di kHz
        self.assertEqual(verdetto(0.0, 10.0, 2, 4, 4), "DENTRO")
        self.assertEqual(verdetto(0.0, -10.0, 2, 4, 4), "DENTRO")
        iv = MI.livelli_molecola_garantiti(nostra(0.0, 10.0, 5 * C3_LORO), 2, 4, scadenza=300, larghezza=1e-11)
        r = MP.Richiesta("centrex_tlf", modello(B_G=-10.0, Jmax=4, due_MF=2), 4, {}, unita="Hz", secondi=300,
                         mem_mib=4096, site_packages=SP)
        self.assertEqual(MP.confronta(iv, "Hz", MP.esegui_porta(r, python=PY), tolleranza=0.5).complessivo, "FUORI")


if __name__ == "__main__":
    unittest.main()
