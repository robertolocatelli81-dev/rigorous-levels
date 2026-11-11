# qraft-ra

Mathematically guaranteed eigenvalue intervals for the charge-basis rotor (transmon, cos 2φ, any sum of cosines up to
cos 24φ), for the spherical rotor in a field and for the ¹Σ molecule with hyperfine, Zeeman and Stark terms; a
convergence warning for scqubits with a declared threshold rule; a sandboxed multiport that runs other people's
solvers and tells, level by level, whether they fall inside the intervals; and the guaranteed per-level error of the
Duffing model against the transmon.

Noûs, AI agent under a revocable mandate from Roberto Locatelli.

## The problem, and for whom

Spectra of superconducting circuits and of polar molecules are computed in a truncated basis (charge states `ncut`,
rotational states `Nmax`/`Jmax`, Fock states). A fixed truncation cannot notice when it is too small: the number comes
out, wrong, with no warning. scqubits, diatomic-py, CeNTREX-TlF, qiskit-metal's `Hcpb`, SQcircuit and pyEPR all leave
the truncation to the user. This package is for people who need to know how far a computed level can be trusted:
when a value goes into a paper, a fit, a design review or a regression test.

It gives, in `src/qraft_ra`:

1. **Guaranteed intervals** (`intervallo_garantito`, `rotore_sferico_garantito`, `molecola_iperfine_garantita`):
   the first k levels as intervals [low, high] that contain the exact eigenvalue of the written H, with a proof that
   includes the truncation of the basis (`docs/PROOF.md`). When the proof does not apply, `FuoriDominio` with the reason
   and no number.
2. **A float solver with a declared error** (`rotore_spettro`) and **the scqubits convergence warning**
   (`scqubits_adattatore`): scqubits' transmon at `ncut` and `2·ncut`; the threshold rule "soglia-scq/1.0" (declared
   unit, absolute 1e-6 GHz, relative 1e-6, float floor) reports which of its three parts decided (`soglia_origine`).
3. **The multiport** (`multiporta`, `porte_runner`): an external solver runs inside a bubblewrap sandbox (no network,
   read-only system, tmpfs HOME, rlimits, minimal environment), its JSON output is validated against a closed schema,
   and each level is compared with the intervals in exact arithmetic: `DENTRO`, `DENTRO_TOLLERANZA` (within a float
   tolerance you declare), `FUORI` (with the distance) or `NON_CONFRONTABILE` (with the reason). Without bubblewrap
   nothing runs: no silent fallback. Ports: scqubits, diatomic-py, qiskit-metal (`Hcpb`, `mathieu_level`), SQcircuit,
   pyEPR, CeNTREX-TlF.
4. **Duffing against transmon** (`duffing_vs_transmon`): the guaranteed interval of (E_j − E_0) − E^D_j for each
   level, with ω and α taken from the first three guaranteed levels or from Koch et al. 2007 first order.

Identifiers, states and error messages are in Italian (`Rotore`, `spettro`, `GARANTITO`, `FuoriDominio`, ...), as in
the code the package was extracted from; the docstrings of the modules added in 0.2.0 are in Italian too (translation
pending).

## What is guaranteed, and under which conditions

For j < k, λ_j(H_N′) ≤ λ_j(H) ≤ λ_j(H_N): Rayleigh–Ritz above, a block decoupling of the quadratic form with a proven
bound on the truncated part below (Young's inequality on the coupling, Gershgorin or operator norms on the outer
block), eigenvalue counts by Sylvester's law of inertia in Arb ball arithmetic (python-flint). The argument and its
sources (Teschl; Barth, Martin, Wilkinson 1967; Johansson 2017) are in `docs/PROOF.md`. The guarantee holds under
three conditions:

1. The inputs are in the declared domain (each constructor checks them; anything else is `FuoriDominio` with the
   reason: unknown input is never accepted silently).
2. H is the one of the exact float64 parameters (0.1 is 0.1000000000000000055…).
3. Arb/FLINT rounds correctly, and sympy's 3j symbols are exact. This is assumed, not proven here, and there is no
   formal verification of this code: tests and mutation testing reduce the risk of a defect, they do not remove it.

Within these conditions an interval marked `GARANTITO` has width ≤ the requested one (default 1e-12: absolute, in the
unit of E_C, for the charge-basis rotor; relative to max(|E_j|, B) for the sphere and the molecule);
`LARGO` means valid but wider than requested (the molecule keeps trying larger truncations while the width halves).

## What it does not do

- It does not say that H describes a device or a molecule. The interval contains the value of the H you wrote.
- The multiport does not judge the physics of the other solver: it says inside/outside our intervals, with the reason.
  bubblewrap is a user-namespace sandbox, not a virtual machine (no seccomp, no `--disable-userns`); the environment
  passed to bwrap itself is minimal (a reviewer found the session environment readable in `/proc/1/environ` before
  0.2.0: fixed and tested).
- The convergence warning is an empirical check, not a proof: the shift on doubling is a lower bound of the true
  error. With the rule "soglia-scq/1.0" no result marked `OK` was outside its own threshold in 2000 + 1200 runs in the
  device regime and 1080 runs outside it (independent reviewer); the float floor (factor 32) is about 100 times above
  the measured noise on converged pairs, declared.
- It is not faster than scqubits (a guaranteed point costs 0.16 s median to a few seconds; a molecule sector up to
  ~500 states costs seconds per count); the multiport costs ~3.6 s per run (import of scqubits inside bwrap).
- QRAFT-RA is an internal model of its author, not an external validator. Nothing here is an accredited or
  third-party certification: "guaranteed" means "follows from the proof in `docs/PROOF.md`", nothing more.

## Install and use

```sh
pip install .                  # numpy, scipy, python-flint, sympy
pip install ".[scqubits]"      # also the scqubits adapter
pip install ".[porte]"         # scqubits, diatomic-py, SQcircuit, pyEPR-quantum, centrex-tlf (ports of the multiport)
```

Python 3.10–3.14 (python-flint 0.9.0 has wheels for these). bubblewrap (`bwrap`) is needed only by the multiport.
Not on PyPI.

```python
from qraft_ra.intervallo_garantito import livelli_garantiti
from qraft_ra.rotore_spettro import Rotore, spettro
from qraft_ra.scqubits_adattatore import spettro_scqubits

r = Rotore.transmon(0.2, 10.0, n_g=0.3)          # E_C, E_J in GHz: U = -E_J cos(phi)
iv = livelli_garantiti(r, 4)                     # 4 levels, width <= 1e-12 GHz
lo, hi = iv.transizione(0, 1)                    # f01 as an exact interval (Fractions)
print(iv.stato, f"{float(lo):.9f}", f"{float(hi):.9f}")

s = spettro(r, 4)                                # float64 levels with a declared error
print(s.stato, float(lo) - s.errore <= s.energie[1] - s.energie[0] <= float(hi) + s.errore)

w = spettro_scqubits(Rotore.transmon(1.0, 2e4), 6, 30, controllo="raddoppio")
print(w.stato)                                   # ncut = 30 is too small at E_J/E_C = 2e4
```

Output:

```text
GARANTITO 3.788378597 3.788378597
OK True
NON_CONVERGENTE
```

More (shown as text, each one is exercised by the tests):

```text
# spherical rotor: RbCs, B = 490.173994 MHz, d·E at 1.2 V/cm, M = ±1
from qraft_ra.rotore_sferico_garantito import RotoreSferico, livelli_sfera_garantiti, transizione
iv0 = livelli_sfera_garantiti(RotoreSferico(B=490.173994, dE=1.225 * 0.503412 * 1.2, M=0), 2)
iv1 = livelli_sfera_garantiti(RotoreSferico(B=490.173994, dE=1.225 * 0.503412 * 1.2, M=1), 1)
print(transizione(iv0, 0, iv1, 0))               # N = 0 -> N = 1, M = 1, in MHz, as exact Fractions

# molecule: RbCs with the constants of Gregory et al. 2016, sector M_F = +6, level N = 1
from qraft_ra.molecola_iperfine_garantita import MolecolaSigma, livelli_molecola_garantiti, zeeman_hz
m = MolecolaSigma(3, 7, B=490173.994e3, D=213.0, c1=29.4, c2=196.8, c3=192.4, c4=19.019e3,
                  eQq1=-809.29e3, eQq2=59.98e3, z_N=zeeman_hz(0.0062, 181.541),
                  z1=zeeman_hz(1.8295, 181.541), z2=zeeman_hz(0.7331, 181.541))     # Hz
iv6 = livelli_molecola_garantiti(m, 12, 1, larghezza=1e-11)       # 2M_F = 12

# multiport: scqubits in a sandbox, compared with the intervals
from qraft_ra import multiporta as MP
r = MP.Richiesta("scqubits_transmon", {"tipo": "rotore_cos", "E_C": 0.3, "E_J": 15.0, "n_g": 0.25}, 6,
                 {"ncut": 30}, site_packages=(<site-packages with scqubits>,))
u = MP.esegui_porta(r)                           # SandboxAssente without bwrap
print(MP.confronta(iv, "GHz", u, tolleranza=1e-12).complessivo)   # DENTRO / DENTRO_TOLLERANZA / FUORI

# Duffing against transmon
from qraft_ra.duffing_vs_transmon import errore_duffing
print(errore_duffing(0.3, 15.0, 0.25, 6).delta_float()[3])        # interval of (E_3 - E_0) - E^D_3, GHz
```

## Three public reports, reproducible with this package

Each one was found by comparing a public solver with the guaranteed intervals and reported by the author on
2026-11-11 (links are public; nothing else was sent):

1. **durham-qlm/diatomic-py #15** — https://github.com/durham-qlm/diatomic-py/issues/15. The code of
   `tensor_nuclear` (2.1.0) uses +√6 c₃ T²(C)·T²(I₁,I₂); the package's paper (eq. 5b), Aldegunde et al. 2008 and
   Gregory et al. 2016 use the opposite sign. With the paper's sign the 16 RbCs transitions of Gregory et al. 2016
   (Table I) are reproduced within 100 Hz of their model values f_the (intervals 7 mHz wide); with the code's sign 1 of
   16 (the 16-line script is in the issue). In this package `tests/test_molecola_iperfine_garantita.py::TestGregory2016`
   checks the stretched line M_F = +5 → +6 at 181.541 G (within 100 Hz with the paper's sign, about 800 Hz off with the
   code's), and `TestCostruzioneContraDiatomicPy` compares the matrix elements (needs `pip install diatomic-py==2.1.0`).
2. **qiskit-community/qiskit-metal #1252** — https://github.com/qiskit-community/qiskit-metal/issues/1252.
   `mathieu_level(m, ng, Ej, Ec)` returns the energy of another level for some (m, Ej/Ec) at n_g = 0 and 1/2: the
   cause is `scipy.special.mathieu_a/mathieu_b` (522 wrong values on m ≤ 12, |q| ≤ 400, identical with scipy 1.10.1, 1.14.1, 1.15.0 and
   1.18.1, the releases tested; fixed on scipy main by PR #25128, milestone 2.0.0). Reproduce with the port `metal_mathieu` (mount their
   `transmon_CPB_analytic.py` and `transmon_charge_basis.py` in a folder named `site-packages/`): case E_C = 0.16792,
   E_J = 7.01912 GHz, n_g = 0.5, m = 5 → 2.524025 GHz (the value of m = 3), while the guaranteed interval of
   level 5 is [6.277480…]; `Hcpb(nlevels=15)` on the author's 50 transmons is inside the intervals except 7 of 50 at
   E_J/E_C ≥ 285 (≤ 2.9 kHz).
3. **scqubits/scqubits #334** (comment) — https://github.com/scqubits/scqubits/issues/334#issuecomment-6796563509.
   The first scipy release whose sparse `eigsh` silently omits the zero eigenvalue is 1.15.0 (bisection 1.10.1,
   1.13.1, 1.14.1 right; 1.15.0, 1.15.3, 1.16.2, 1.17.1, 1.18.1 wrong; independent of the start vector). This is a
   scipy sparse defect, not a truncation one: scqubits' dense transmon (`eigvalsh_tridiagonal`) is unaffected, and
   the port `scqubits_transmon` falls inside the intervals (0 of 200 outside at ncut = 30 in the device regime).

Two more measurements with no report (the other side already documents or fixed them): CeNTREX-TlF's default
`Jmax = J + 2` errs by 4.26 MHz at 10 kV/cm with no warning; at 30 kV/cm the result of their API is 3.9 GHz off but
comes with their warning "Ambiguous eigenstate assignment" (the truncation alone accounts for 1.1 GHz there); their
AGENTS.md already tells users to raise Jmax at tens of kV/cm; SQcircuit 1.0.0's single transmon is inside the intervals within 3e-13 GHz once the junction's
own capacitance (1e-20 F) is included (issue #5 there expected the first-order anharmonicity −E_C, the exact one at
E_J/E_C = 26.3 and n_g = 0.3, the values of the issue's code, is −0.466 GHz).

## Measurements

**Measured on 2026-11-10** (charge-basis rotor, `bench/readme_numbers.py --full`, Python 3.11.2, numpy 2.4.6, scipy
1.17.1, python-flint 0.9.0, scqubits 4.3.1): 400 of 400 cases `GARANTITO`, the 50-digit mpmath reference inside the
interval in 2400 of 2400 levels, largest width 1.56e-13 GHz; time per guaranteed point (6 levels) mean 0.51 s, median
0.16 s; scqubits at ncut = 30 wrong without a warning in 65 of 200 cases at E_J/E_C ≥ 7744, all 65 flagged by the
adapter, 0 false alarms.

**Measured on 2026-11-10/11** in the author's repository with the modules of 0.2.0 (logs there, not re-run here):

| What | Result |
|---|---|
| 6 real transmons of arXiv:2407.17407 (up to 12 levels, up to cos 8φ) | 26 of 26 `GARANTITO`, width ≤ 1.1e-13 GHz; the authors' levels need ncut 10–20 to stay within 1 kHz |
| Spherical rotor, RbCs (Blackmore et al. 2018: 129 Hz at ~1.2 V/cm, estimated field) | 130.3 Hz guaranteed for M = ±1 at 1.2 V/cm |
| Molecule, RbCs, 16 transitions of Gregory et al. 2016 with their constants | 16 of 16 within 100 Hz of their model (max 94 Hz), intervals 7 mHz wide, 70 transitions in ~2.5 s |
| Molecule, TlF, CeNTREX-TlF 0.4.0 | levels within 0.5 Hz at zero field and at 173 V/cm (with c₃_ours = 5·c₃_theirs: an operator identity); Zeeman μ_J/J convention of theirs not covered for J ≥ 2 |
| Adapter rule "soglia-scq/1.0", 200 transmons × ncut 3…30 | 0 results `OK` outside the threshold; verdicts identical in GHz/MHz/Hz (0 of 1000 differ) |
| Multiport sandbox, positive controls | network reached outside / blocked inside; file written outside / blocked inside; loop → timeout; 3 GiB → MemoryError; unknown key → `NON_VALIDA`; without bwrap → `SandboxAssente` |
| Duffing against transmon, 200 transmons (E_J/E_C 5–500) | |δ_3| ≥ 1 MHz in 200 of 200 (median 34 MHz, 90th percentile 1.18 GHz); δ_3 = 0 near E_J/E_C ≈ 30.56 at n_g = 0, so this is a property of the sample, not of the regime |

Mutation testing (author's benches in the author's repository, not re-run on this tree; copies with a green control,
PYTHONDONTWRITEBYTECODE=1): charge-basis rotor
8 of 8; sphere 16 of 16 (+ 14 of 14 by the reviewer); molecule 24 of 24 (+ 21 of 21); adapter 18 of 18; multiport
23 of 24 (+ 1 equivalent, declared; 2 of the reviewer's alive: `--new-session`, `--die-with-parent`, untested; the
mount of an interpreter outside /usr is covered by a separate bench of 2026-11-11, see CHANGELOG);
Duffing 22 of 24 (+ 2 equivalent).

## Tests

`cd tests && python -B -m unittest test_intervallo_garantito test_rotore_spettro test_scqubits_adattatore
test_readme_example test_rotore_sferico_garantito test_molecola_iperfine_garantita test_ingressi_nemesis_qraft
test_duffing_vs_transmon test_multiporta test_porta_centrex_tlf`, against the installed package. The sandbox tests
need `bwrap`; they are skipped with that reason when it is missing or cannot create namespaces. `test_porta_centrex_tlf`
runs only with `QRAFT_BERSAGLI_VENV` pointing at a venv with centrex-tlf. Results from clean venvs: see the table kept in
this section (measured, see CHANGELOG for dates).

Measured on 2026-11-11 from this tree, each Python in a fresh venv (`pip install --no-deps .` after the dependencies),
run from `tests/` with the command above, `bwrap` 0.8.0 present:

| Python | numpy, scipy, python-flint | scqubits | Result |
|---|---|---|---|
| 3.11.2 | 2.4.6, 1.17.1, 0.9.0 | 4.3.1 | 157 tests, OK, 6 skipped (3 `test_porta_centrex_tlf` without `QRAFT_BERSAGLI_VENV`, 2 diatomic-py absent, 1 interpreter under /usr: no interpreter piece to mount) |
| 3.12.15 | 2.5.4, 1.18.1, 0.9.0 | absent | 157 tests, OK, 15 skipped (the first 5 above + 10 of the scqubits adapter and README example) |
| 3.13.15 | 2.5.4, 1.18.1, 0.9.0 | 4.3.1 | 157 tests, OK, 5 skipped |
| 3.14.8 | 2.5.4, 1.18.1, 0.9.0 | absent | 157 tests, OK, 15 skipped |
| 3.11.2 with `QRAFT_BERSAGLI_VENV` (venv with centrex-tlf 0.4.0) | | | `test_porta_centrex_tlf`: 4 tests, OK |

Python 3.10 was not available on the author's machine: the CI matrix includes it, not yet run. With `bwrap` removed
from PATH, Python 3.11.2 gives 157 tests, OK, 20 skipped: 16 with the reason "bwrap assente" (15 of the 31 tests of
`test_multiporta`, 1 of `test_scqubits_adattatore`), plus the 3 of `test_porta_centrex_tlf` and 1 of diatomic-py.

## Limits

- The 50-digit mpmath references of the charge-basis rotor are not independent of the truncation: they confirm the
  arithmetic, not the truncation bound, which rests on the proof. Guaranteed Mathieu characteristic values as an
  independent reference are planned, not done.
- The proof is the author's assembly of standard steps, reviewed adversarially by an independent AI agent (its
  reports are in the author's repository), not by a human mathematician.
- Molecule: fields along z only; no AC polarizability; the CeNTREX-TlF Zeeman convention μ_J/J is not covered for
  J ≥ 2 (declared); quadrupole with I < 1 is refused, not zeroed.
- Multiport: user-namespace sandbox, not a VM; /etc is mounted read-only (what any user process reads); an interpreter
  outside /usr (uv, pyenv, CI) is mounted read-only piece by piece (executable, standard library, libpython), never its
  whole prefix, and a prefix that is or contains the user's home is refused; the test ports
  `prova_*` are controls, not solvers.
- Adapter: the float floor is a plausible bound (16× the nominal tolerance of LAPACK ?stebz), not a proof.
- Speed: see above.

## Provenance

There is no release yet. `FILE_LIST.tsv` lists every file with its sha256 and, for the modules derived from the
author's repository, the sha256 of the source file; `python check_tree.py` checks the list, the imports, a deny-list
and runs gitleaks.

## License

Apache License 2.0 (`LICENSE`, `NOTICE`). Copyright 2026 Roberto Locatelli.
