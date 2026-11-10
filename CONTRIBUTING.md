# Contributing

Issues and pull requests are welcome. Security problems: see `SECURITY.md` (private report).

## Rules of this repository

1. **No number without a proof or a reason.** An interval marked GARANTITO must follow from `docs/PROOF.md`; where the
   proof does not apply, the code raises `FuoriDominio` with the reason instead of returning a number.
2. **Unknown input is refused with a named reason, and a test shows it.** The certificate reader refuses unknown,
   missing and repeated keys, NaN/Infinity, numbers that overflow, a BOM and wrong types at every level
   (`tests/test_integrazione_scq.py`, class `TestCertificato`, generative over every key and leaf).
3. **Tests first fail, then pass.** A fix comes with a test that fails on the old code. A new check comes with a
   positive control: an input it must refuse.
4. **Only measured sentences** in README, docstrings and commit messages. If a number is quoted, say how it was
   measured and on what date.
5. **The file list is closed.** `FILE_LIST.tsv` lists every file with its sha256; `python check_tree.py` fails on any
   file not listed, any import outside the standard library, the listed modules and a closed set of third-party
   packages (numpy, scipy, python-flint, mpmath, scqubits), and any secret found by gitleaks. A pull request that
   changes or adds a file updates the list with `python check_tree.py --update` and commits the new `FILE_LIST.tsv`.

## Running the checks

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements/ci.txt && pip install --no-deps .
cd tests && python -m unittest test_intervallo_garantito test_integrazione_scq test_livelli_grandi && cd ..
git add -A                      # check_tree.py lists files with git (tracked + untracked, .gitignore respected)
python check_tree.py --update   # needs gitleaks on PATH
python check_tree.py --positive-control
```

Install with `pip install .` (not `-e`) before running the tests, so they exercise the installed package.

## License of contributions

By contributing you agree that your contribution is licensed under the Apache License 2.0 (see `LICENSE`).
