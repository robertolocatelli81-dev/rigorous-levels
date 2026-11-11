# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""NEMESIS 10/11/2026: ingressi che uscivano dal dominio con un'eccezione diversa da OutOfDomain/DeadlineExceeded o che
ignoravano la deadline (hyperfine_molecule e spherical_rotor). Ogni caso con un tetto di tempo."""
import importlib.util
import time
import unittest

FLINT = importlib.util.find_spec("flint") is not None
if FLINT:
    from qraft_ra import hyperfine_molecule as MI  # noqa: E402
    from qraft_ra import spherical_rotor as RS  # noqa: E402


@unittest.skipUnless(FLINT, "python-flint assente")
class TestIngressiNEMESIS(unittest.TestCase):
    def test_interi_oltre_il_float(self):
        for kw in ({"B": 10 ** 400}, {"B": 1.0, "c1": 10 ** 400}, {"B": 1.0, "dE": -(10 ** 400)}):
            with self.assertRaises(MI.OutOfDomain, msg=str(kw)[:40]):
                MI.SigmaMolecule(1, 1, **kw)
        with self.assertRaises(RS.OutOfDomain):
            RS.SphericalRotor(B=10 ** 400)

    def test_rapporto_dE_su_B_infinito(self):
        with self.assertRaises(MI.OutOfDomain):
            MI.guaranteed_molecule_levels(MI.SigmaMolecule(0, 0, B=1e-300, dE=1e300), 0, 1, deadline=5)
        with self.assertRaises(RS.OutOfDomain):
            RS.guaranteed_sphere_levels(RS.SphericalRotor(B=1e-300, dE=1e300), 1, deadline=5)

    def test_tetti_dichiarati(self):
        with self.assertRaises(MI.OutOfDomain):
            MI.SigmaMolecule(MI.TWO_I_MAX + 2, 0, B=1.0)
        m = MI.SigmaMolecule(1, 1, B=1.0)
        for kw in ({"L_limit": MI.L_LIMIT_MAX + 1}, {"prec": MI.PREC_MAX + 1}):
            with self.assertRaises(MI.OutOfDomain, msg=str(kw)):
                MI.guaranteed_molecule_levels(m, 0, 1, deadline=5, **kw)

    def test_scadenza_rispettata(self):
        for args, kw in (((MI.SigmaMolecule(40, 40, B=1.0, c4=0.1, c3=0.01, dE=0.5), 0, 4), {"deadline": 2}),
                         ((MI.SigmaMolecule(0, 0, B=1.0), 10 ** 9, 1), {"L_limit": MI.L_LIMIT_MAX, "deadline": 2})):
            t0 = time.time()
            try:
                MI.guaranteed_molecule_levels(*args, **kw)          # risultato valido o rifiuto: mai oltre la deadline
            except (MI.DeadlineExceeded, MI.OutOfDomain):
                pass
            self.assertLess(time.time() - t0, 15.0)


if __name__ == "__main__":
    unittest.main()
