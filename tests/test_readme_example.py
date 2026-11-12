# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""The Python example of README.md runs as written and prints exactly the output shown below it."""
import contextlib
import importlib.util
import io
import re
import unittest
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"


@unittest.skipUnless(importlib.util.find_spec("scqubits"), "the example uses the scqubits extra")
class TestEsempioReadme(unittest.TestCase):
    def test_esempio(self):
        testo = README.read_text(encoding="utf-8")
        blocchi = re.findall(r"```python\n(.*?)```", testo, re.S)
        self.assertEqual(len(blocchi), 1)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            exec(compile(blocchi[0], "README.md", "exec"), {})
        attese = re.findall(r"```python\n.*?```\n\nOutput:\n\n```text\n(.*?)```", testo, re.S)
        self.assertEqual(len(attese), 1)
        self.assertEqual(out.getvalue(), attese[0])


class TestReproduceConsole(unittest.TestCase):
    """CI 2026-11-12, Windows: `python -m qraft_ra.reproduce` stopped with UnicodeEncodeError printing "≤" to a cp1252
    console. A console that cannot encode a character gets a backslash escape; the run ends normally."""

    def test_reproduce_on_a_cp1252_console(self):
        import os
        import subprocess
        import sys
        r = subprocess.run([sys.executable, "-B", "-m", "qraft_ra.reproduce"], capture_output=True, timeout=600,
                           env=dict(os.environ, PYTHONIOENCODING="cp1252"))
        self.assertEqual(r.returncode, 0, r.stderr.decode("cp1252", "replace")[-800:])
        self.assertIn(b"\\u2264", r.stdout)            # the character was there, escaped, not dropped
        self.assertNotIn(b"UnicodeEncodeError", r.stderr)


if __name__ == "__main__":
    unittest.main()
