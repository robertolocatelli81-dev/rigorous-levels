# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Generative tests on EVERY public entry point (limit A of 0.3.0): random inputs from a closed grammar of attacks
(unknown keyword, wrong type, NaN/inf, bool where a number is expected, huge integers, unicode strings, negative
and zero sizes, nested containers, numpy scalars) must give exactly OutOfDomain / InputRejected / TypeError-free
behaviour: never another exception, never a silent acceptance of an unknown keyword, and a valid input in the
same family must still succeed (positive control of the generator). Seeded, so a failure is reproducible.
Every call carries a deadline so that a mutant that loops cannot stall the bench."""
import importlib.util
import inspect
import math
import random
import unittest
from fractions import Fraction

import numpy as np

from qraft_ra import multiport as MP
from qraft_ra import rotor_spectrum as RS

FLINT = importlib.util.find_spec("flint") is not None
if FLINT:
    from qraft_ra import duffing_vs_transmon as DT  # noqa: E402
    from qraft_ra import fluxonium as FX  # noqa: E402
    from qraft_ra import guaranteed_intervals as GI  # noqa: E402
    from qraft_ra import hyperfine_molecule as HM  # noqa: E402
    from qraft_ra import mathieu as MA  # noqa: E402
    from qraft_ra import spherical_rotor as SR  # noqa: E402

RND = random.Random(20261111)
BAD_NUMBERS = [float("nan"), float("inf"), -float("inf"), True, False, None, "1", "1.0", b"1", [1], (1,), {"x": 1},
               10 ** 400, -(10 ** 400), 1j, np.float64("nan"), np.bool_(True), np.array([1.0]), object(), "∞", "१"]
BAD_INTS = [0.5, 1.5, -1, 0, True, None, "3", np.float64(3.0), [3], float("nan"), -(10 ** 9), "３"]     # for a size ≥ 1
BAD_ANYINTS = [0.5, 1.5, True, None, "3", np.float64(3.0), [3], float("nan"), "３", 10 ** 400]            # for any integer
BAD_HARMONICS = [None, "x", 1, {0: 1.0}, {"1": 1.0}, {1: float("nan")}, {1: "x"}, {True: 1.0}, {1.5: 1.0}, {1: None},
                 {-1: 1.0}, {1: float("inf")}, {1: 10 ** 400}]
BAD_TRUNCATIONS = [None, [], "x", 1, {1: 2.0}, {True: 1.0}, {"k": float("nan")}, {"k": None}, {"k": [1]}, {0: 1.0},
                   {"k": True}, {"k": {}}, {"k": float("inf")}]
BAD_NONNEG = BAD_ANYINTS + [-1, -(10 ** 9)]
UNICODE = ["é", "ﬁ", "𝟙", "a\u0000b", "‮", "x" * 10000, "", " "]


def expected(exc_types):
    return tuple(exc_types)


class _Generative:
    """Subclasses define SPEC: (callable, good kwargs, {name: kind}) with kind in {"real", "int", "str", "dict", "any"}."""
    SPEC = ()
    ROUNDS = 40
    OK_EXC = ()

    def mutate(self, good, kinds):
        kw = dict(good)
        name = RND.choice(list(kinds))
        kind = kinds[name]
        if RND.random() < 0.15:                       # unknown keyword: must be refused (closed signature)
            kw["kw_" + RND.choice(UNICODE[:3]) + str(RND.randint(0, 9))] = 1
            return kw, "unknown keyword"
        if kind == "real":
            kw[name] = RND.choice(BAD_NUMBERS)
        elif kind == "int":
            kw[name] = RND.choice(BAD_INTS + BAD_NUMBERS)
        elif kind == "anyint":
            kw[name] = RND.choice(BAD_ANYINTS + [x for x in BAD_NUMBERS if not isinstance(x, int)])
        elif kind == "str":
            kw[name] = RND.choice(UNICODE + [1, None, [], b"x"])
        elif kind == "harm":
            kw[name] = RND.choice(BAD_HARMONICS)
        elif kind == "trunc":
            kw[name] = RND.choice(BAD_TRUNCATIONS)
        elif kind == "nonneg":
            kw[name] = RND.choice(BAD_NONNEG)
        elif kind == "model":                         # a closed-key model: an unknown key or a bad value is refused
            key = RND.choice([k for k in good[name] if k != "type"])
            kw[name] = RND.choice(BAD_TRUNCATIONS + [{**good[name], RND.choice(UNICODE): 1},
                                                     {k: v for k, v in list(good[name].items())[1:]},
                                                     {**good[name], key: RND.choice(BAD_NUMBERS)}])
        else:
            kw[name] = RND.choice(BAD_NUMBERS + UNICODE)
        return kw, f"{name} = {kw[name]!r}"[:120]

    def test_random_attacks_are_refused_with_the_declared_exceptions(self):
        for fn, good, kinds in self.SPEC:
            fn(**good)                                  # positive control: the good input works
            refused = 0
            for _ in range(self.ROUNDS):
                kw, what = self.mutate(good, kinds)
                try:
                    fn(**kw)
                except self.OK_EXC:
                    refused += 1
                except Exception as e:  # noqa: BLE001 — the point of the test
                    self.fail(f"{getattr(fn, '__name__', fn)}({what}): {type(e).__name__}: {e}")
                else:
                    # an attack that is accepted must be one the grammar tolerates: only numpy scalars of the right
                    # kind and bool-free, finite values; everything else is a silent acceptance = failure
                    self.fail(f"{getattr(fn, '__name__', fn)}({what}) accepted silently")
            self.assertGreater(refused, 0)


@unittest.skipUnless(FLINT, "python-flint absent")
class TestRotorFamily(_Generative, unittest.TestCase):
    OK_EXC = (RS.InputRejected, ValueError, TypeError)

    @property
    def SPEC(self):
        rot = dict(E_C=0.3, cosines={1: -15.0}, sines={}, n_g=0.25)
        return (
            (RS.Rotor, rot, {"E_C": "real", "cosines": "harm", "sines": "harm", "n_g": "real"}),
            (lambda **kw: RS.spectrum(RS.Rotor(0.3, {1: -15.0}), **kw), dict(k=3, tol=1e-8, nmax_limit=200),
             {"k": "int", "tol": "real", "nmax_limit": "int"}),
            (lambda **kw: GI.guaranteed_levels(RS.Rotor(0.3, {1: -15.0}), deadline=60, **kw), dict(k=3, width=1e-9),
             {"k": "int", "width": "real"}),
            (lambda **kw: DT.duffing_error(deadline=60, **kw), dict(E_C=0.3, E_J=15.0, n_g=0.0, k=4, variant="spectrum", width=1e-9),
             {"E_C": "real", "E_J": "real", "n_g": "real", "k": "int", "variant": "str", "width": "real"}),
        )


@unittest.skipUnless(FLINT, "python-flint absent")
class TestSphereMoleculeMathieuFluxonium(_Generative, unittest.TestCase):
    OK_EXC = (GI.OutOfDomain, TypeError)

    @property
    def SPEC(self):
        mol = dict(two_I1=1, two_I2=1, B=1.0e6, c4=100.0)
        return (
            (SR.SphericalRotor, dict(B=490.0, dE=1.0, M=0, Dc=0.0), {"B": "real", "dE": "real", "M": "anyint", "Dc": "real"}),
            (lambda **kw: SR.guaranteed_sphere_levels(SR.SphericalRotor(B=490.0, dE=1.0), deadline=60, **kw),
             dict(k=2, width=1e-9, L_limit=400), {"k": "int", "width": "real", "L_limit": "int"}),
            (HM.SigmaMolecule, mol, {"two_I1": "nonneg", "two_I2": "nonneg", "B": "real", "c4": "real"}),
            (lambda **kw: HM.guaranteed_molecule_levels(HM.SigmaMolecule(**mol), deadline=60, **kw),
             dict(two_MF=0, k=1, width=1e-9, L_limit=4), {"two_MF": "anyint", "k": "int", "width": "real", "L_limit": "int"}),
            (lambda **kw: HM.zeeman_hz(**kw), dict(g=1.0, B_gauss=100.0), {"g": "real", "B_gauss": "real"}),
            (lambda **kw: MA.mathieu_value(deadline=60, **kw), dict(kind="a", r=2, q=3.0, width=1e-10),
             {"kind": "str", "r": "int", "q": "real", "width": "real"}),
            (FX.Fluxonium, dict(E_C=0.5, E_J=4.0, E_L=0.5, flux=0.5), {"E_C": "real", "E_J": "real", "E_L": "real", "flux": "real"}),
            (lambda **kw: FX.guaranteed_fluxonium_levels(FX.Fluxonium(E_C=0.5, E_J=4.0, E_L=0.5), deadline=120, **kw),
             dict(k=2, width=1e-6, N_limit=60), {"k": "int", "width": "real", "N_limit": "int"}),
        )


class TestMultiportRequest(_Generative, unittest.TestCase):
    OK_EXC = (MP.OutOfDomain, TypeError)
    ROUNDS = 120

    @property
    def SPEC(self):
        model = {"type": "cos_rotor", "E_C": 0.3, "E_J": 15.0, "n_g": 0.25}
        return (
            (MP.Request, dict(port="numpy_rotor", model=model, levels=6, truncation={"ncut": 30}, unit="GHz", seconds=20, mem_mib=1024),
             {"port": "str", "model": "model", "levels": "int", "truncation": "trunc", "unit": "str", "seconds": "int", "mem_mib": "int"}),
        )

    def test_output_documents_generated(self):
        """validate_output on random JSON-like documents: (None, reason) or an Output, never an exception."""
        r = MP.Request("numpy_rotor", {"type": "cos_rotor", "E_C": 0.3, "E_J": 15.0, "n_g": 0.25}, 3, {"ncut": 30})
        good = {"contract": MP.CONTRACT, "port": "numpy_rotor", "solver_version": "x", "levels": [0.0] * 3,
                "unit": "GHz", "state": "OK", "reason": "", "seconds": 0.1}
        u, m = MP.validate_output(good, r)
        self.assertIsNotNone(u, m)
        for _ in range(300):
            d = dict(good)
            for _ in range(RND.randint(1, 3)):
                key = RND.choice(list(good) + UNICODE[:4])
                d[key] = RND.choice(BAD_NUMBERS + UNICODE + [[], {}, [1, 2], [0.0] * RND.randint(0, 6), "OK", "ERROR"])
            try:
                u, m = MP.validate_output(d, r)
            except Exception as e:  # noqa: BLE001
                self.fail(f"{d}: {type(e).__name__}: {e}")
            if u is not None:
                self.assertEqual(set(d), set(good))                 # only documents with exactly the closed keys pass
                self.assertIn(u.state, ("OK", "ERROR"))
                for x in u.levels:
                    self.assertTrue(math.isfinite(x))


class TestSignaturesAreClosed(unittest.TestCase):
    def test_no_var_keyword_in_public_api(self):
        """No public function accepts **kwargs: an unknown keyword is always a TypeError, never ignored."""
        mods = [MP, RS] + ([GI, SR, HM, MA, FX, DT] if FLINT else [])
        for mod in mods:
            for name, obj in vars(mod).items():
                if name.startswith("_") or not callable(obj) or getattr(obj, "__module__", None) != mod.__name__:
                    continue
                if isinstance(obj, type) and issubclass(obj, BaseException):
                    continue
                sig = inspect.signature(obj)
                kinds = {p.kind for p in sig.parameters.values()}
                self.assertNotIn(inspect.Parameter.VAR_KEYWORD, kinds, f"{mod.__name__}.{name}: accepts **kwargs")


if __name__ == "__main__":
    unittest.main()
