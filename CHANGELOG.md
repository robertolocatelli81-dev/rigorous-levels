# Changelog

All dates are from the author's system clock (Europe/Rome). Nothing here is published yet: no release, no PyPI.

## 0.2.0 — 2026-11-11 (local, unreleased)

Added (every module carries its proof or its measurement in the docstring; identifiers, states and the docstrings of the
new modules are in Italian, as in the source they were extracted from):

- `rotore_sferico_garantito`: guaranteed intervals for the spherical rotor in a field,
  H = B N(N+1) − D_c [N(N+1)]² − dE cos θ at fixed M (polar molecule, rigid rotor with centrifugal distortion). Same
  argument as the charge-basis rotor: Rayleigh–Ritz above, Young's inequality on the outer block below, Sylvester
  counts in Arb balls.
- `molecola_iperfine_garantita`: guaranteed intervals for a ¹Σ molecule with rotation, centrifugal distortion,
  nuclear spin–rotation (c₁, c₂), scalar (c₄) and tensor (c₃) spin–spin terms, nuclear quadrupoles, Zeeman and Stark
  terms (fields along z, one M_F sector at a time), with the truncation in N closed by the proof. The lower bound of the
  outer block is −(K_T + K_Q) − dE (norms of bounded operators, compression does not increase the norm). The matrix
  elements are built in Arb from exact square roots of rationals (3j symbols by sympy) and agree with diatomic-py 2.1.0
  element by element (relative 6.5e-16 on 23 830 elements) once the sign of the tensor term is mapped: diatomic-py's
  code uses +√6 c₃ T²(C)·T²(I₁,I₂), its paper (eq. 5b) and Aldegunde et al. 2008 the opposite sign; see "Reported".
- `scqubits_adattatore`: the convergence warning now follows the declared threshold rule "soglia-scq/1.0": declared
  unit (GHz/MHz/Hz, covariant), absolute 1e-6 GHz, relative 1e-6 of the span, a float floor
  32·eps·(‖H(ncut)‖₁ + ‖H(2ncut)‖₁) with the origin of the threshold reported (`assoluta`, `relativa`, `utente`,
  `pavimento`) and the state `OK_LIMITE_FLOAT` when the floor decides. Measured on 200 transmons of the device regime:
  0 results marked OK that were outside the threshold (2000 + 1200 runs), and 0 on 1080 runs outside that regime by
  an independent reviewer. The old relative rule (up to 18 kHz in the device regime) is removed. Optional engine
  `motore="sandbox"` runs scqubits through the multiport.
- `multiporta` and `porte_runner` (contract "qraft-porta/0.1", specification v0.2): an external solver runs in a
  bubblewrap sandbox (no network, separate PID/IPC namespaces, only /usr, /lib, /lib64, /bin, /etc, the declared
  site-packages and, for an interpreter outside /usr, its executable, standard library and libpython (never its whole
  prefix) mounted read-only, tmpfs HOME, 256 MiB tmpfs, rlimits, timeout, minimal environment also for bwrap
  itself), returns a JSON validated against a closed schema (unknown key, NaN, duplicate key, wrong length = not
  comparable, with the reason), and is compared level by level with the intervals in exact arithmetic, with a
  declared float tolerance. Ports: numpy reference, scqubits, diatomic-py, qiskit-metal `Hcpb` and `mathieu_level`
  (from their source files, mounted read-only), SQcircuit, pyEPR, CeNTREX-TlF, plus the test ports used as positive
  controls (network, file writes, loops, memory, malformed output). Without bubblewrap, or with a bubblewrap that is
  not root-owned, nothing runs (`SandboxAssente`): no silent fallback.
- `duffing_vs_transmon`: guaranteed per-level error of the Duffing model ω a†a + (α/2) a†a†aa against the full
  transmon, with ω and α taken from the guaranteed intervals of the first three levels ("spettro") or from Koch et al.
  2007 first order ("koch"). On 200 transmons of the device regime |δ_3| ≥ 1 MHz in 200 of 200 (median 34 MHz).

Fixed before publication (adversarial review of 2026-11-11):

- Multiport: an interpreter outside /usr had its whole installation prefix mounted read-only; with a prefix equal to
  `<home>/.local` (Python built with `--prefix=$HOME/.local`), or equal to the home itself when `$HOME` differs from
  the account's home, a port could read the user's hidden folders (measured: a fake keyring file read in 2 of 2 cases).
  Now only the executable, the standard library and libpython are mounted, and the home is taken from both `$HOME` and
  the user database. Tests: `TestPrefissoInterprete` (6 tests, they fail on the previous code). Mutation testing of the
  new lines on Python 3.11 and 3.12: 12 of 15 mutants killed, 3 equivalent (early return for /usr, a redundant
  coherence check, `-I` on the probe), checked by reasoning and on 305 inputs (0 differences; a non-equivalent control
  mutant differs on 8).
- `requirements/ci.txt`: numpy 2.5.4 and scipy 1.18.1 have no wheels for Python 3.10 and 3.11; those two jobs now pin
  numpy 2.2.6 / scipy 1.15.3 (3.10) and numpy 2.4.6 / scipy 1.17.1 (3.11).
- README: numbers of the qiskit-metal example, the CeNTREX-TlF warning at 30 kV/cm, what `TestGregory2016` checks, the
  scipy versions tested, the sandbox test count and the width default corrected; CONTRIBUTING test command; NOTICE;
  provenance hashes in `FILE_LIST.tsv`; license headers of the test files; references to the author's unpublished notes.

Changed:

- `pyproject.toml`: dependency on sympy (3j symbols); optional extra `porte` with the external solvers.
- CI: Python 3.10–3.14 (python-flint 0.9.0 wheels exist for 3.10–3.14); bubblewrap installed on the runner and
  unprivileged user namespaces allowed (Ubuntu 24.04 restricts them through AppArmor); the job fails if the sandbox
  cannot start, so in CI the sandbox tests run and are not skipped.
- Multiport: the nesting of `[` and `{` in a port's output is limited to 32 levels, counted in one linear pass
  before the JSON parser (`USCITA_MAX_PROFONDITA`). Before, the limit was the parser's RecursionError, which on
  Python 3.14 depends on the stack size: measured on 2026-11-11 with CPython 3.14.8, 10 000 levels accepted with an
  8 MiB stack, 100 000 levels accepted with 64 MiB or unlimited; the first CI run on 3.14.10 accepted 100 000.
- Tests: `test_scqubits_adattatore` and `test_porta_centrex_tlf` decide whether the sandbox is usable with the same probe
  as `test_multiporta` (bwrap started with `--unshare-all`), not with the presence of `bwrap` on PATH: on a runner where
  `bwrap` exists but cannot create namespaces the sandbox test raised an error instead of being skipped.
- `check_tree.py`: the closed list of allowed third-party imports includes sympy and the optional port packages.

Reported upstream (public, by the author, 2026-11-11; the package reproduces each one, see README):

- durham-qlm/diatomic-py #15: sign of the tensor spin–spin term in `tensor_nuclear` (2.1.0) differs from the paper.
- qiskit-community/qiskit-metal #1252: `mathieu_level` returns the value of another order for some (m, q)
  (root cause in `scipy.special.mathieu_a/b`, 522 wrong values on m ≤ 12, |q| ≤ 400 with scipy ≤ 1.18.1; fixed on
  scipy main by PR #25128, milestone 2.0.0).
- scqubits/scqubits #334 (comment): the first scipy release whose sparse `eigsh` omits the zero eigenvalue is 1.15.0
  (bisection 1.10.1 … 1.18.1, independent of the start vector).

Not in this release: the certificate module (removed in 0.1.0), guaranteed Mathieu characteristic values (planned),
fluxonium, matrix elements.

## 0.1.0 — 2026-11-10 (local, unreleased)

First extraction: `rotore_spettro`, `intervallo_garantito`, `scqubits_adattatore` (relative threshold), docs/PROOF.md,
check_tree.py, CI with gitleaks.
