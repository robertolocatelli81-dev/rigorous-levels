# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""Every script in examples/ runs as written (fresh interpreter, isolated mode, temporary HOME) and prints the
states it claims; the scqubits example is skipped without the extra."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
FLINT = importlib.util.find_spec("flint") is not None
SCQUBITS = importlib.util.find_spec("scqubits") is not None


def run(script):
    env = {"PATH": os.environ.get("PATH", ""), "HOME": tempfile.mkdtemp(prefix="home_example_"), "OMP_NUM_THREADS": "1"}
    for k in ("PYTHONUSERBASE", "SYSTEMROOT", "TEMP", "TMP"):
        if k in os.environ:
            env[k] = os.environ[k]
    if os.name == "nt":   # Windows has no password database: Path.home() needs USERPROFILE (qutip, imported by scqubits)
        env["USERPROFILE"] = tempfile.mkdtemp(prefix="rigorous_levels_home_")
    p = subprocess.run([sys.executable, "-I", "-B", str(EXAMPLES / script)], capture_output=True, text=True, timeout=900, env=env)
    return p.returncode, p.stdout, p.stderr


@unittest.skipUnless(FLINT, "python-flint absent")
class TestExamples(unittest.TestCase):
    def test_parameter_box(self):
        rc, out, err = run("parameter_box.py")
        self.assertEqual(rc, 0, err)
        self.assertIn("GUARANTEED rho = 0.15", out)
        self.assertIn("inside the box interval: True", out)

    def test_mathieu_and_fluxonium(self):
        rc, out, err = run("mathieu_and_fluxonium.py")
        self.assertEqual(rc, 0, err)
        self.assertIn("a_11(299): GUARANTEED ('123.99490539", out)
        self.assertIn("b_3(91): GUARANTEED ('-89.98305807", out)
        self.assertIn("fluxonium: GUARANTEED N = 117 f01 (MHz): ['13.8815576', '13.8815586']", out)

    @unittest.skipUnless(SCQUBITS, "scqubits absent")
    def test_from_scqubits(self):
        rc, out, err = run("from_scqubits.py")
        self.assertEqual(rc, 0, err)
        self.assertIn("Transmon ncut 30 -> INSIDE", out)
        self.assertIn("Transmon ncut 30 -> OUTSIDE | level 3 off by", out)
        self.assertIn("Fluxonium cutoff 110 -> INSIDE", out)

    def test_matrix_elements(self):
        rc, out, err = run("matrix_elements.py")
        self.assertEqual(rc, 0, err)
        self.assertIn("|<0|n|1>| in [1.08780085731", out)
        self.assertIn("<1|n|1> at n_g = 1/2 contains 1/2: True", out)

    def test_regression_assert(self):
        """The helper passes on the dense levels; on the sparse eigsh levels it raises from scipy 1.15.0 on (the
        exact zero is omitted) and passes before (measured: 1.14.1 right)."""
        import scipy
        rc, out, err = run("regression_assert.py")
        self.assertEqual(rc, 0, err)
        self.assertIn("dense eigvalsh: [0.  1.2 1.2 4.8] -> inside", out)
        major, minor = (int(x) for x in scipy.__version__.split(".")[:2])
        if (major, minor) >= (1, 15):
            self.assertIn("-> AssertionError: OUTSIDE", out)
        else:
            self.assertIn("-> inside", out.splitlines()[-1])

    def test_every_example_is_covered(self):
        scripts = sorted(p.name for p in EXAMPLES.glob("*.py"))
        self.assertEqual(scripts, ["from_scqubits.py", "mathieu_and_fluxonium.py", "matrix_elements.py", "parameter_box.py",
                                   "regression_assert.py"])


if __name__ == "__main__":
    unittest.main()
