"""NEMESIS 10/11/2026: ingressi che uscivano dal dominio con un'eccezione diversa da FuoriDominio/TempoScaduto o che
ignoravano la scadenza (molecola_iperfine_garantita e rotore_sferico_garantito). Ogni caso con un tetto di tempo."""
import importlib.util
import sys
import time
import unittest
from pathlib import Path

FLINT = importlib.util.find_spec("flint") is not None
if FLINT:
    from qraft_ra import molecola_iperfine_garantita as MI  # noqa: E402
    from qraft_ra import rotore_sferico_garantito as RS  # noqa: E402


@unittest.skipUnless(FLINT, "python-flint assente")
class TestIngressiNEMESIS(unittest.TestCase):
    def test_interi_oltre_il_float(self):
        for kw in ({"B": 10 ** 400}, {"B": 1.0, "c1": 10 ** 400}, {"B": 1.0, "dE": -(10 ** 400)}):
            with self.assertRaises(MI.FuoriDominio, msg=str(kw)[:40]):
                MI.MolecolaSigma(1, 1, **kw)
        with self.assertRaises(RS.FuoriDominio):
            RS.RotoreSferico(B=10 ** 400)

    def test_rapporto_dE_su_B_infinito(self):
        with self.assertRaises(MI.FuoriDominio):
            MI.livelli_molecola_garantiti(MI.MolecolaSigma(0, 0, B=1e-300, dE=1e300), 0, 1, scadenza=5)
        with self.assertRaises(RS.FuoriDominio):
            RS.livelli_sfera_garantiti(RS.RotoreSferico(B=1e-300, dE=1e300), 1, scadenza=5)

    def test_tetti_dichiarati(self):
        with self.assertRaises(MI.FuoriDominio):
            MI.MolecolaSigma(MI.DUE_I_MAX + 2, 0, B=1.0)
        m = MI.MolecolaSigma(1, 1, B=1.0)
        for kw in ({"L_limite": MI.L_LIMITE_MAX + 1}, {"prec": MI.PREC_MAX + 1}):
            with self.assertRaises(MI.FuoriDominio, msg=str(kw)):
                MI.livelli_molecola_garantiti(m, 0, 1, scadenza=5, **kw)

    def test_scadenza_rispettata(self):
        for args, kw in (((MI.MolecolaSigma(40, 40, B=1.0, c4=0.1, c3=0.01, dE=0.5), 0, 4), {"scadenza": 2}),
                         ((MI.MolecolaSigma(0, 0, B=1.0), 10 ** 9, 1), {"L_limite": MI.L_LIMITE_MAX, "scadenza": 2})):
            t0 = time.time()
            try:
                MI.livelli_molecola_garantiti(*args, **kw)          # risultato valido o rifiuto: mai oltre la scadenza
            except (MI.TempoScaduto, MI.FuoriDominio):
                pass
            self.assertLess(time.time() - t0, 15.0)


if __name__ == "__main__":
    unittest.main()
