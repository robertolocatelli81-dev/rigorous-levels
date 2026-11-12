# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""The Italian names of 0.2.0 still work through the deprecated modules and emit exactly DeprecationWarning (so a
migration is measurable with -W error::DeprecationWarning), while the English API emits none."""
import importlib.util
import unittest
import warnings

FLINT = importlib.util.find_spec("flint") is not None


class TestAliases(unittest.TestCase):
    def _reload(self, mod):
        """Re-runs the body of a deprecated module (it may already be imported): the import-time warning must fire."""
        name = mod.__name__.split(".")[-1]
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            mod = importlib.reload(mod)
        self.assertTrue(any(issubclass(x.category, DeprecationWarning) and name in str(x.message) for x in w), name)
        return mod

    def test_rotor_and_spectrum(self):
        from rigorous_levels import rotore_spettro
        RS = self._reload(rotore_spettro)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            r = RS.Rotore(E_C=0.3, coseni={1: -15.0}, n_g=0.25)
            s = RS.spettro(r, 3, doppio_metodo=True)
            self.assertEqual(s.stato, RS.OK)
            self.assertEqual(r.coseni, ((1, -15.0),))
            self.assertEqual(len(s.energie), 3)
            self.assertIsInstance(r, RS.Rotor)
            r2 = RS.Rotore.transmon(0.3, 15.0, n_g=0.25)
            self.assertEqual(r2.cosines, r.cosines)
        self.assertTrue(all(issubclass(x.category, DeprecationWarning) for x in w))
        self.assertGreaterEqual(len(w), 5)

    @unittest.skipUnless(FLINT, "python-flint absent")
    def test_intervals_sphere_molecule_duffing(self):
        from rigorous_levels import intervallo_garantito, molecola_iperfine_garantita, rotore_sferico_garantito, rotore_spettro
        IG = self._reload(intervallo_garantito)
        RS = self._reload(rotore_spettro)
        SR = self._reload(rotore_sferico_garantito)
        MI = self._reload(molecola_iperfine_garantita)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            iv = IG.livelli_garantiti(RS.Rotore.transmon(0.3, 15.0, n_g=0.25), 3, larghezza=1e-9, scadenza=60)
            self.assertEqual(iv.stato, IG.GARANTITO)
            self.assertEqual(iv.stato, "GUARANTEED")              # the English state value, documented
            lo, hi = iv.transizione(0, 1)
            self.assertLess(lo, hi)
            self.assertEqual(iv.bassi, iv.low)
            self.assertTrue(iv.contiene(0, iv.low[0]))
            sv = SR.livelli_sfera_garantiti(SR.RotoreSferico(B=490.0, dE=1.0, M=0), 2, larghezza=1e-9, scadenza=60)
            self.assertEqual(sv.stato, "GUARANTEED")
            self.assertEqual(len(SR.transizione(sv, 0, sv, 1)), 2)
            m = MI.MolecolaSigma(1, 1, B=1e6, c4=100.0)
            self.assertEqual(m.due_I1, 1)
            mv = MI.livelli_molecola_garantiti(m, due_MF=0, k=1, larghezza=1e-9, L_limite=4, scadenza=60)
            self.assertIn(mv.stato, ("GUARANTEED", "WIDE"))
            self.assertEqual(MI.dimensione_settore(m, due_MF=0, L=1), MI.sector_dimension(m, 0, 1))
        self.assertTrue(all(issubclass(x.category, DeprecationWarning) for x in w), [x.category for x in w])

    def test_multiport_and_adapter_names(self):
        from rigorous_levels import multiporta, scqubits_adattatore
        MP = self._reload(multiporta)
        SA = self._reload(scqubits_adattatore)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            r = MP.Richiesta(porta="numpy_rotor", modello={"type": "cos_rotor", "E_C": 0.3, "E_J": 15.0, "n_g": 0.25},
                             livelli=3, troncamento={"ncut": 30}, unita="GHz", secondi=10)
            self.assertEqual(r.livelli, 3)
            self.assertEqual(r.port, "numpy_rotor")
            u = MP.Uscita("numpy_rotor", "v", (1.0, 2.0, 3.0), "GHz", "OK", "", 0.0, "")
            self.assertEqual(u.stato, "OK")
            self.assertEqual(MP.CONTRATTO, "rigorous-levels-port/0.3")
            self.assertEqual(SA.REGOLA, "scq-threshold/1.0")
            self.assertEqual(SA.NON_CONVERGENTE, "NOT_CONVERGED")
            self.assertEqual(SA.disponibile()["present"], SA.available()["present"])
        self.assertTrue(all(issubclass(x.category, DeprecationWarning) for x in w))

    def test_english_api_is_warning_free(self):
        from rigorous_levels import multiport, rotor_spectrum
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            r = rotor_spectrum.Rotor.transmon(0.3, 15.0, n_g=0.25)
            s = rotor_spectrum.spectrum(r, 3)
            self.assertEqual(s.state, "OK")
            multiport.Request("numpy_rotor", {"type": "cos_rotor", "E_C": 0.3, "E_J": 15.0, "n_g": 0.25}, 3, {"ncut": 30})


if __name__ == "__main__":
    unittest.main()
