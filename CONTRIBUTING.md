# Contributing

Issues and pull requests are welcome. Security problems: see `SECURITY.md` (private report).

## Rules of this repository

1. **No number without a proof or a reason.** An interval marked GARANTITO must follow from `docs/PROOF.md`; where the
   proof does not apply, the code raises `FuoriDominio` with the reason instead of returning a number.
2. **Unknown input is refused with a named reason, and a test shows it.** `Rotore` refuses NaN, ±inf, booleans,
   strings and other non-numbers, non-integer or non-positive harmonics and E_C ≤ 0 (`tests/test_rotor_spectrum.py`,
   including 400 random inputs); `livelli_garantiti` refuses anything outside the domain of the proof with
   `FuoriDominio`; the adapter refuses any rotor that is not a transmon.
3. **Tests first fail, then pass.** A fix comes with a test that fails on the old code. A new check comes with a
   positive control: an input it must refuse.
4. **Only measured sentences** in README, docstrings and commit messages. If a number is quoted, say how it was
   measured and on what date.
5. **The file list is closed.** `FILE_LIST.tsv` lists every file with its sha256; `python check_tree.py` fails on any
   file not listed, any import outside the standard library, the listed modules and a closed set of third-party
   packages (numpy, scipy, python-flint, sympy, mpmath, scqubits and the optional port packages listed in
   `check_tree.py`), and any secret found by gitleaks. A pull request that
   changes or adds a file updates the list with `python check_tree.py --update` and commits the new `FILE_LIST.tsv`.

## Running the checks

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements/ci.txt && pip install --no-deps .
cd tests && python -B -m unittest test_guaranteed_intervals test_rotor_spectrum test_scqubits_adapter test_readme_example \
    test_spherical_rotor test_hyperfine_molecule test_inputs_review test_duffing_vs_transmon test_mathieu test_fluxonium \
    test_multiport test_port_centrex_tlf test_parameter_balls test_matrix_elements test_cos4phi_origin test_examples test_generative_inputs test_deprecated_aliases && cd ..
git add -A                      # check_tree.py lists files with git (tracked + untracked, .gitignore respected)
python check_tree.py --update   # needs gitleaks on PATH
python check_tree.py --positive-control
```

Install with `pip install .` (not `-e`) before running the tests, so they exercise the installed package.

## License of contributions

By contributing you agree that your contribution is licensed under the Apache License 2.0 (see `LICENSE`).
