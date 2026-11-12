# qraft-ra

Mathematically guaranteed eigenvalue intervals, truncation included: for j < k, **λ_j(H_N′) ≤ λ_j(H) ≤ λ_j(H_N)**
(Rayleigh–Ritz above, a proven lower bound of the truncated block below, eigenvalue counts in Arb ball arithmetic;
`docs/PROOF.md`), for the charge-basis rotor (transmon, cos 2φ, any sum of cosines up to cos 24φ), the spherical rotor
in a field, the ¹Σ molecule with hyperfine, Zeeman and Stark terms, the Mathieu characteristic values a_r(q), b_r(q),
the fluxonium in the oscillator basis, parameters given as intervals, and matrix elements between eigenvectors; a
convergence warning for scqubits with a declared threshold rule, a one-line check of a scqubits object, a sandboxed
multiport that runs other people's solvers inside one of six isolation engines (Linux, macOS, Windows, WebAssembly)
and tells, level by level, whether they fall inside the intervals, and the guaranteed per-level error of the Duffing
model against the transmon. The numbers below are re-measured by `python -m qraft_ra.reproduce` and by the scripts in
`bench/`, each row of the tables naming its script.

Noûs, AI agent under a revocable mandate from Roberto Locatelli.

## Three public reports, reproducible with this package

Each one was found by comparing a public solver with the guaranteed intervals and reported by the author on
2026-11-11 (links are public; nothing else was sent):

1. **durham-qlm/diatomic-py #15** — https://github.com/durham-qlm/diatomic-py/issues/15. The code of
   `tensor_nuclear` (2.1.0) uses +√6 c₃ T²(C)·T²(I₁,I₂); the package's paper (eq. 5b), Aldegunde et al. 2008 and
   Gregory et al. 2016 use the opposite sign. With the paper's sign the 16 RbCs transitions of Gregory et al. 2016
   (Table I) are reproduced within 100 Hz of their model values f_the (intervals 7 mHz wide); with the code's sign 1 of
   16. In this package `bench/gregory2016.py` re-computes the 16 lines (re-measured here on 2026-11-11: 16 of 16
   centres within 100 Hz of their f_the, largest 93.8 Hz, every interval ≤ 7.4 mHz wide, 1.6 s), `tests/test_hyperfine_molecule.py::TestGregory2016`
   checks the stretched line M_F = +5 → +6 at 181.541 G, and `TestCostruzioneContraDiatomicPy` compares the matrix
   elements (needs `pip install diatomic-py==2.1.0`).
2. **qiskit-community/qiskit-metal #1252** — https://github.com/qiskit-community/qiskit-metal/issues/1252.
   `mathieu_level(m, ng, Ej, Ec)` returns the energy of another level for some (m, Ej/Ec) at n_g = 0 and 1/2: the
   cause is `scipy.special.mathieu_a/mathieu_b` (fixed on scipy main by PR #25128, milestone 2.0.0). Two counts,
   two referents: (a) scipy releases, re-measured on this tree with `bench/mathieu_vs_scipy.py` (r ≤ 12,
   |q| ≤ 400, step 0.5): 52 wrong values of 40 025 in 1.17.1 and 1.18.1 (identical lists), 0 in
   2.0.0.dev0+git20261108; on the fine grid of the issue (step 0.05, `bench/mathieu_vs_scipy.py intervals OUT 0.05`,
   re-measured here on 2026-11-12): 400 025 values, all GUARANTEED (0 WIDE; 74 on 2026-11-11, before the
   deterministic estimates), 522 wrong in 1.17.1 and in 1.18.1 (identical lists, 326 of them equal to another order
   ≤ 12; the same list as on 2026-11-11), 0 in 2.0.0.dev0+git20261108 (measured on 2026-11-11 against the intervals of
   then: no scipy nightly here on 2026-11-12; the ends moved since by at most 1.3e-12 relative, below the 1e-9
   tolerance of the comparison), 0.56 ms median per value; (b) qiskit-metal's `mathieu_level`,
   which inherits (a): the numbers in the issue are theirs to reproduce with the port `metal_mathieu`. Since 0.3.0
   `qraft_ra.mathieu` gives the guaranteed values directly.
3. **scqubits/scqubits #334** (comment) — https://github.com/scqubits/scqubits/issues/334#issuecomment-6796563509.
   The first scipy release whose sparse `eigsh` silently omits the zero eigenvalue is 1.15.0 (bisection 1.10.1,
   1.13.1, 1.14.1 right; 1.15.0, 1.15.3, 1.16.2, 1.17.1, 1.18.1 wrong; independent of the start vector).

Two more measurements with no report (the other side already documents or fixed them): CeNTREX-TlF's default
`Jmax = J + 2` errs by 4.26 MHz at 10 kV/cm with no warning; at 30 kV/cm their API is 3.9 GHz off but warns
("Ambiguous eigenstate assignment"); their AGENTS.md already tells users to raise Jmax. SQcircuit 1.0.0's single
transmon is inside the intervals within 3e-13 GHz once the junction's own capacitance (1e-20 F) is included.

## The problem, and for whom

Spectra of superconducting circuits and of polar molecules are computed in a truncated basis (charge states `ncut`,
rotational states `Nmax`/`Jmax`, Fock states `cutoff`). A fixed truncation cannot notice when it is too small: the
number comes out, wrong, with no warning. scqubits, diatomic-py, CeNTREX-TlF, qiskit-metal's `Hcpb`, SQcircuit and
pyEPR all leave the truncation to the user; scipy's `mathieu_a/mathieu_b` return, for some orders and parameters,
the value of another order. This package is for people who need to know how far a computed level can be trusted:
when a value goes into a paper, a fit, a design review or a regression test.

It gives, in `src/qraft_ra` (English API since 0.3.0, exposed at the package level: `from qraft_ra import Rotor,
guaranteed_levels, ...`; the Italian names of 0.2.0 are deprecated aliases that warn):

1. **Guaranteed intervals** (`guaranteed_levels`, `guaranteed_sphere_levels`, `guaranteed_molecule_levels`,
   `mathieu_a/mathieu_b`, `guaranteed_fluxonium_levels`): the first k levels as intervals [low, high] that contain
   the exact eigenvalue of the written H, with a proof that includes the truncation of the basis (`docs/PROOF.md`).
   When the proof does not apply, `OutOfDomain` with the reason and no number. **Parameters with an uncertainty**
   (`RotorBall`, `guaranteed_levels_over_box`): E_C and the cosine coefficients as intervals, the level guaranteed
   over the whole box with two computations (monotonicity in E_C, Weyl's inequality in the coefficients).
   **From the object you already have** (`guaranteed_from_scqubits`): a `scqubits.Transmon` or `Fluxonium` gives the
   guaranteed intervals of its H and the verdict on its own levels at its own cutoff, in one line.
   **Matrix elements** (`guaranteed_matrix_element`): ⟨v_i|n|v_j⟩, ⟨v_i|cos mφ|v_j⟩, ⟨v_i|sin mφ|v_j⟩ between the
   eigenvectors, with the eigenvector error bounded by the exact residual over the gap of the guaranteed levels.
2. **A float solver with a declared error** (`rotor_spectrum.spectrum`) and **the scqubits convergence warning**
   (`scqubits_adapter.scqubits_spectrum`): scqubits' transmon at `ncut` and `2·ncut`; the threshold rule
   "scq-threshold/1.0" (`docs/THRESHOLD_RULE.md`: declared unit, absolute 1e-6 GHz, relative 1e-6, float floor)
   reports which of its three parts decided (`threshold_origin`).
3. **The multiport** (`multiport`, `port_runner`, `isolation`; contract "qraft-port/0.3" in `docs/PORT_CONTRACT.md`):
   an external solver runs inside an isolation engine chosen from a closed, ordered list — `podman`, `docker`,
   `bwrap` (Linux), `sandbox-exec` (macOS), `appcontainer` (Windows), `wasm` (wasmtime + CPython for WASI) — each
   with no network, a read-only file system, no real home, a minimal environment, time and memory limits and a
   fail-closed probe (an engine that is missing or does not isolate is never used silently; on Linux and macOS every
   engine binary must be owned by root and not writable by others, because the probe is measured from inside the
   engine and a binary the user can replace could forge it; the binary is run by its real path, and every folder above
   a root-owned binary must be root-owned and not writable by group or others; a user-installed binary only if its
   exact real path is listed in `QRAFT_TRUSTED_ENGINES`, and then `Output.sandbox` names it, because processes of
   this user can replace it). Not covered by that check: a container runtime set in the user's own podman or docker
   configuration, the owner of the engine binary on Windows, and the AppContainer read grants (`icacls`) on the
   interpreter and site-packages folders, which stay on those folders after the run. Its JSON output is
   validated against a closed schema and each level is compared with the intervals in exact arithmetic: `INSIDE`,
   `INSIDE_TOLERANCE` (within a float tolerance you declare), `OUTSIDE` (with the distance) or `NOT_COMPARABLE`
   (with the reason). Ports: scqubits, diatomic-py, qiskit-metal (`Hcpb`, `mathieu_level`), SQcircuit, pyEPR,
   CeNTREX-TlF.
4. **Duffing against transmon** (`duffing_vs_transmon.duffing_error`): the guaranteed interval of
   (E_j − E_0) − E^D_j for each level, with ω and α taken from the first three guaranteed levels or from Koch et al.
   2007 first order.

## What is guaranteed, and under which conditions

For j < k, λ_j(H_N′) ≤ λ_j(H) ≤ λ_j(H_N): Rayleigh–Ritz above, a block decoupling of the quadratic form with a proven
bound on the truncated part below (Young's inequality on the coupling, Gershgorin or operator norms on the outer
block; for the fluxonium a per-site bound with explicit Laguerre tails), eigenvalue counts by Sylvester's law of
inertia in Arb ball arithmetic (python-flint). The argument and its sources (Teschl; Barth, Martin, Wilkinson 1967;
Johansson 2017; DLMF 18.14.8, 28.2, 28.4) are in `docs/PROOF.md`. The guarantee holds under three conditions:

1. The inputs are in the declared domain (each constructor checks them; anything else is `OutOfDomain` or
   `InputRejected` with the reason: unknown input is never accepted silently; every size has a declared cap).
2. H is the one of the exact float64 parameters (0.1 is 0.1000000000000000055…).
3. Arb/FLINT rounds correctly, and sympy's 3j symbols are exact. This is assumed, not proven here, and there is no
   formal verification of this code: tests and mutation testing reduce the risk of a defect, they do not remove it.

Within these conditions an interval marked `GUARANTEED` has width ≤ the requested one (default 1e-12: absolute, in
the unit of E_C, for the charge-basis rotor; relative to max(|E_j|, B) for the sphere and the molecule; relative to
max(|a|, 1) for Mathieu; absolute 1e-10 GHz for the fluxonium); `WIDE` means valid but wider than requested.

## What it does not do

- It does not say that H describes a device or a molecule. The interval contains the value of the H you wrote.
- The multiport does not judge the physics of the other solver: it says inside/outside our intervals, with the reason.
  No engine is a virtual machine; what each one blocks and what it does not is in `docs/PORT_CONTRACT.md` §6.
- The convergence warning is an empirical check, not a proof: the shift on doubling is a lower bound of the true
  error. With the rule "scq-threshold/1.0" no result marked `OK` was outside its own threshold in 2000 + 1200 runs in
  the device regime and 1080 runs outside it (independent reviewer, 0.2.0); the float floor (factor 32) is about 100
  times above the measured noise on converged pairs, declared.
- It is not faster than the float tools: a guaranteed transmon point costs 0.25 s median on the wide-range set; a
  Mathieu value 0.50 ms median (scipy: 3.3 µs); a fluxonium device 0.34–6.0 s (scqubits: milliseconds); the multiport costs seconds per run.
- QRAFT-RA is an internal model of its author, not an external validator. Nothing here is an accredited or
  third-party certification: "guaranteed" means "follows from the proof in `docs/PROOF.md`", nothing more.

## Install and use

```sh
pip install .                  # numpy, scipy, python-flint, sympy
pip install ".[scqubits]"      # also the scqubits adapter
pip install ".[porte]"         # scqubits, diatomic-py, SQcircuit, pyEPR-quantum, centrex-tlf (ports of the multiport)
```

Python 3.10–3.14 (python-flint 0.9.0 has wheels for these). The multiport needs one isolation engine: bubblewrap
(`bwrap`) or podman/docker with the image `python:<major>.<minor>-slim` of your interpreter already in the local
store (it is never pulled), or `sandbox-exec` (macOS), or nothing beyond Windows itself (AppContainer), or `wasmtime`
plus a CPython built for WASI in `QRAFT_PYTHON_WASM` (pure-Python ports only: no numpy exists for WASI). On POSIX
every engine binary must be owned by root and not writable by group or others; a binary you installed yourself (for
example wasmtime unpacked in your home) is used only if you list its exact real path in `QRAFT_TRUSTED_ENGINES` (an
entry that is relative, a symlink or not normalized vouches for nothing), and `Output.sandbox` then names it.
Not on PyPI.

```python
from qraft_ra import Rotor, guaranteed_levels, scqubits_spectrum, spectrum

r = Rotor.transmon(0.2, 10.0, n_g=0.3)           # E_C, E_J in GHz: U = -E_J cos(phi)
iv = guaranteed_levels(r, 4)                     # 4 levels, width <= 1e-12 GHz
lo, hi = iv.transition(0, 1)                     # f01 as an exact interval (Fractions)
print(iv.state, f"{float(lo):.9f}", f"{float(hi):.9f}")

s = spectrum(r, 4)                               # float64 levels with a declared error
print(s.state, float(lo) - s.error <= s.energies[1] - s.energies[0] <= float(hi) + s.error)

w = scqubits_spectrum(Rotor.transmon(1.0, 2e4), 6, 30, check="doubling")
print(w.state)                                   # ncut = 30 is too small at E_J/E_C = 2e4
```

Output:

```text
GUARANTEED 3.788378597 3.788378597
OK True
NOT_CONVERGED
```

More (shown as text, each one is exercised by the tests; runnable scripts in `examples/`, run by `tests/test_examples.py`):

```text
# from the scqubits object you already have: its guaranteed intervals and the verdict on its own cutoff
from qraft_ra import guaranteed_from_scqubits
c = guaranteed_from_scqubits(scqubits.Transmon(EJ=15.0, EC=0.3, ng=0.25, ncut=30), 4)
print(c.verdict.overall, c.intervals.transition(0, 1))                  # INSIDE; OUTSIDE at E_J/E_C = 2e4, ncut 30

# parameters with an uncertainty: E_C and E_J ± 1 %, levels guaranteed over the whole box
from qraft_ra import RotorBall, guaranteed_levels_over_box
iv = guaranteed_levels_over_box(RotorBall.transmon((0.297, 0.303), (14.85, 15.15), n_g=0.25), 4)
print(iv.state, iv.alpha)                                                # GUARANTEED, rho = 0.15 GHz

# Mathieu characteristic values, any real q (negative and large included), guaranteed order
from qraft_ra import mathieu_a, mathieu_b
v = mathieu_a(11, 299.0)                         # scipy 1.18.1 returns 232.195 here; the interval is [123.9949…]
print(v.state, v.strings, v.K)                   # a_0(1) = -0.45513860 (A&S Table 20.1) is inside its interval

# matrix elements between eigenvectors: |<0|n|1>| = 1.08780085731 with a width of 1.7e-14
from qraft_ra import guaranteed_matrix_element
e = guaranteed_matrix_element(Rotor.transmon(0.3, 15.0, n_g=0.25), 0, 1, "n")
print(e.low, e.high, e.max_width)

# fluxonium at half flux, parameters of Zhang et al. 2021 (PRX 11, 011010)
from qraft_ra.fluxonium import Fluxonium, guaranteed_fluxonium_levels
iv = guaranteed_fluxonium_levels(Fluxonium(E_C=0.479, E_J=3.395, E_L=0.132, flux=0.5), 4, 1e-9)
print(iv.state, [float(x) * 1e3 for x in iv.transition(0, 1)])   # f01 in MHz: [13.8815576, 13.8815586]

# spherical rotor: RbCs, B = 490.173994 MHz, d·E at 1.2 V/cm, M = ±1
from qraft_ra.spherical_rotor import SphericalRotor, guaranteed_sphere_levels, transition
iv0 = guaranteed_sphere_levels(SphericalRotor(B=490.173994, dE=1.225 * 0.503412 * 1.2, M=0), 2)
iv1 = guaranteed_sphere_levels(SphericalRotor(B=490.173994, dE=1.225 * 0.503412 * 1.2, M=1), 1)
print(transition(iv0, 0, iv1, 0))                # N = 0 -> N = 1, M = 1, in MHz, as exact Fractions

# molecule: RbCs with the constants of Gregory et al. 2016, sector M_F = +6, level N = 1
from qraft_ra.hyperfine_molecule import SigmaMolecule, guaranteed_molecule_levels, zeeman_hz
m = SigmaMolecule(3, 7, B=490173.994e3, D=213.0, c1=29.4, c2=196.8, c3=192.4, c4=19.019e3,
                  eQq1=-809.29e3, eQq2=59.98e3, z_N=zeeman_hz(0.0062, 181.541),
                  z1=zeeman_hz(1.8295, 181.541), z2=zeeman_hz(0.7331, 181.541))     # Hz
iv6 = guaranteed_molecule_levels(m, 12, 1, width=1e-11)       # 2M_F = 12

# multiport: scqubits in the strongest isolation engine available, compared with the intervals
from qraft_ra import multiport as MP
r = MP.Request("scqubits_transmon", {"type": "cos_rotor", "E_C": 0.3, "E_J": 15.0, "n_g": 0.25}, 6,
               {"ncut": 30}, site_packages=MP.site_packages_of("scqubits"))
u = MP.run_port(r, engine="auto")                # SandboxMissing if no engine isolates; u.sandbox names the engine
print(MP.compare(iv, "GHz", u, tolerance=1e-12).overall)      # INSIDE / INSIDE_TOLERANCE / OUTSIDE
outs = MP.run_ports([r] * 100)                   # a batch: one sandbox process, 0.012 s per case (measured)

# Duffing against transmon
from qraft_ra.duffing_vs_transmon import duffing_error
print(duffing_error(0.3, 15.0, 0.25, 6).delta_float()[3])     # interval of (E_3 - E_0) - E^D_3, GHz
```

## Against the existing tools, measured

Every row is a measurement of 2026-11-10/11 on this tree (details and dates in "Measurements" and in `CHANGELOG.md`);
"guarantee" means an interval proven to contain the exact eigenvalue of the written H, truncation included.

| quantity | this package | other tool | guarantee | correct against a known truth | time per point, ours / theirs (`bench/compare_tools.py`, 2026-11-11, Python 3.11.2) | fails when | script of the other columns |
|---|---|---|---|---|---|---|---|
| transmon levels (cos mφ, any n_g), 6 levels | `guaranteed_levels` | scqubits `Transmon` (ncut 30), qiskit-metal `Hcpb`, SQcircuit, pyEPR | yes (width ≤ 1.6e-13 GHz on 400 cases) / no | 50-digit mpmath inside in 2400 of 2400 levels; scqubits at ncut 30 wrong without a warning in 70 of 200 wide-range cases (error > 1e-6 GHz; 65 with the relative criterion of `bench/readme_numbers.py`), all flagged by the adapter, 0 false alarms | 92 ms / 0.27 ms (**scqubits 340× faster**; our float solver 2.2 ms) | E_J/E_C beyond ~1e6 (N > 4000: `OutOfDomain`) | `bench/readme_numbers.py` |
| transmon with E_C, E_J (and n_g) as intervals | `guaranteed_levels_over_box` | none gives a bound over a box | yes (point computations at the box corners and band edges + ρ) / — | 200 transmons × 5 inner points: 0 point intervals outside the box interval; a point 3 % outside the box detected in 187 of 200; box width 2.1× the observed spread (median; max 5.5×); n_g intervals checked against a fine sampling at E_J/E_C = 5 (tests) | 182 ms / — | an n_g interval longer than 1 is the whole band | `bench/parameter_balls.py` |
| matrix elements ⟨i|n|j⟩, ⟨i|cos φ|j⟩ | `guaranteed_matrix_element` | scqubits `matrixelement_table` (ncut 40) | yes (width median 2.7e-14, max 3.1e-12 on 1000 elements) / no | scqubits inside in 1000 of 1000 (200 transmons × 5 elements); exact symmetry values inside (tests) | 54 ms / ms | levels not separated at the width (no bound, `OutOfDomain`) | `bench/matrix_elements.py` |
| Mathieu a_r(q), b_r(q) | `mathieu_a/b` | scipy `mathieu_a/b` 1.17.1, 1.18.1 | yes (1e-12 relative, 40 025 of 40 025; 0 WIDE) / no | 52 scipy values of 40 025 wrong (another order), 0 in scipy 2.0.0.dev; all 52 confirmed by an independent reference | 0.43 ms / 2.1 µs (**scipy 200× faster**) | r > 200, non-finite q (refused) | `bench/mathieu_vs_scipy.py` |
| fluxonium levels | `guaranteed_fluxonium_levels` | scqubits `Fluxonium` (cutoff 110) | yes (5e-10 GHz) / no (cutoff chosen by the user) | scqubits cutoff 110 inside in 16 of 16 levels of 4 published devices; cutoff 6 outside | 0.35 s (light device) to 6.0 s / 8.3 ms (**scqubits 42× faster**) | N > 240 Fock states needed (`OutOfDomain`) | `bench/fluxonium_devices.py` |
| spherical rotor in a field | `guaranteed_sphere_levels` | numpy at a larger cut | yes / no | 60 random (B, dE, M): numpy at a cut 40 larger inside in 240 of 240 levels; Blackmore et al. 2018: 130.3 Hz guaranteed vs 129 Hz | 0.51 ms / 0.09 ms (numpy 5.6× faster) | D_c with fewer than k levels in the model (refused) | `bench/duffing_adapter_sphere.py`, `tests/test_spherical_rotor.py` |
| ¹Σ molecule, hyperfine + Zeeman + Stark | `guaranteed_molecule_levels` | diatomic-py 2.1.0, CeNTREX-TlF 0.4.0 | yes (7 mHz on RbCs) / no (`Nmax`, `Jmax` by hand) | Gregory et al. 2016: 16 of 16 transitions within 100 Hz of their model (`bench/gregory2016.py`); diatomic-py's code has the wrong sign of c₃ (issue #15); CeNTREX default `Jmax = J+2` errs 4.26 MHz at 10 kV/cm (measured 2026-11-11 in the author's repository with their package; the port `centrex_tlf` reproduces their levels here) | 35 ms (L = 3, 1 level) to seconds per sector / ms | L > 64, 2I > 40 (refused); fields not along z (not modelled) | `bench/gregory2016.py`, `tests/test_hyperfine_molecule.py`, `tests/test_port_centrex_tlf.py` |
| convergence warning for scqubits; `check(scqubits_obj)` | `scqubits_spectrum`, `check` (= `guaranteed_from_scqubits`) | scqubits alone | no (empirical, declared rule) / none; `check` gives the guaranteed verdict | rule: 0 results `OK` outside the threshold in 4280 runs; `check` at ncut 30 on the 200 wide-range transmons: 70 OUTSIDE beyond 1e-6 GHz = exactly the 70 the rule flags (0 flagged by one and not the other), 76 outside the float floor; device regime 0 of 200 | 2 scqubits calls / 1 (0.06–0.10 s) | the border ±1e-4 of the threshold | `bench/check_200.py`, `tests/test_parameter_balls.py` |
| running other people's solvers | multiport, 6 engines, batches | — | fail-closed isolation, closed contract | S1–S7 controls pass for bwrap, podman and wasm (measured here); docker, sandbox-exec, appcontainer: in CI (run 43165166338) | 1.0–1.1 s per single run; 0.012–0.023 s per case in a batch of 100 (podman; `bench/multiport_batch.py`) | an engine whose probe fails (`SandboxMissing`, no fallback) | `tests/test_multiport.py`, `bench/multiport_batch.py` |

Where the other tool is better it is written: scipy and scqubits are 37–340× faster on these inputs; they give no
bound. The timings are medians of 5 runs on the author's machine (`bench/compare_tools.py` prints the platform).

## Measurements

**Measured on 2026-11-12** (charge-basis rotor, `bench/readme_numbers.py --full`, Python 3.11.2, numpy 2.4.6, scipy
1.17.1, python-flint 0.9.0, scqubits 4.3.1, one BLAS thread): 400 of 400 cases `GUARANTEED`, the 50-digit mpmath
reference inside the interval in 2400 of 2400 levels, largest width 1.56e-13 GHz; time per guaranteed point (6
levels) mean 0.60 s, median 0.25 s (2026-11-10, in the author's repository: 0.51 s and 0.16 s; on 40 cases of the
same generator the code before the deterministic estimates took 15.5 s, this code 16.6 s); scqubits at ncut = 30
wrong without a warning in 65 of 200 cases at E_J/E_C ≥ 7744 with the criterion of that bench (error > 1e-6 ×
max(1, largest transition)), all 65 flagged by the adapter, 5 more flagged that this criterion counts as right (their
absolute errors are 4.2e-6 … 1.3e-4 GHz: wrong by the absolute criterion below). Re-measured on
2026-11-11 and 2026-11-12 with the absolute criterion (error > 1e-6 GHz, `bench/check_200.py`, `python -m qraft_ra.reproduce --full`):
wrong in 70 of 200 at E_J/E_C ≥ 5542, all 70 flagged, 0 false alarms, 0 missed; with the float floor as criterion
(32·eps·‖H‖) 76 of 200 are outside the intervals; in the device regime (E_J/E_C ≤ 1000) 0 of 200 at either criterion.

**Measured on 2026-11-11 on this tree, re-measured on 2026-11-12 after the deterministic estimates** (rows of
`bench/mathieu_vs_scipy.py`, `bench/fluxonium_devices.py`, `bench/matrix_elements.py`, `bench/parameter_balls.py`;
Python 3.11.2 unless stated, one BLAS thread):

| What | Result |
|---|---|
| Mathieu, r = 0…12, q = −400…400 step 0.5 | 40 025 values, 40 025 `GUARANTEED` (1e-12 relative), 0 `WIDE`; median 0.50 ms per value |
| scipy `mathieu_a/b` against those intervals | 1.17.1 (3.11.2) and 1.18.1 (3.12.15): 52 wrong, identical lists, 30 equal to another order ≤ 12, all 52 confirmed wrong by an independent tridiagonal reference (K = 400); 2.0.0.dev0+git20261108.c9073e6 (3.13.15): 0 wrong; scipy median 3.3 µs per value (1.17.1, 1.18.1 re-measured on 2026-11-12; 2.0.0.dev on 2026-11-11) |
| fluxonium, 4 published parameter sets, 4 levels | all `GUARANTEED`, width 5e-10 GHz, N = 54…117, 0.34–6.0 s; scqubits 4.3.1 cutoff 110 inside 16 of 16 levels, cutoff 6 outside |
| fluxonium vs measured lines (one-mode H, parameters as printed) | Zhang et al. 2021: f01 13.88 MHz guaranteed vs 14 MHz measured; Moskalenko et al. 2022 qubit A: 685.73 vs 688.22 MHz (f01), 1831.20 vs 1832 MHz (f12); shifts reported, not judged |
| isolation engines, controls S1–S7 | bwrap 0.8.0, podman 4.3.1 (rootless, cgroups v1) and wasmtime 50.0.1 + CPython 3.15.2 WASI (a user-installed wasmtime, listed in `QRAFT_TRUSTED_ENGINES`): all S1–S7 pass (the control ports are pure Python; under WASI only the numpy solver ports cannot run, there is no numpy for WASI); docker, sandbox-exec, appcontainer: not measured locally; in CI run 43165166338 (2026-11-12) every S1–S7 test of docker (Linux x86-64 and ARM64), sandbox-exec (macOS, Python 3.12 and 3.14; the scqubits test skipped, scqubits is not installed there) and appcontainer (Windows, Python 3.12 and 3.14; its diatomic-py half skipped, not installed) passes |
| matrix elements, 200 transmons of the device regime, ⟨0|n|1⟩, ⟨1|n|2⟩, ⟨0|n|2⟩, ⟨0|cos φ|1⟩, ⟨1|cos φ|2⟩ (`bench/matrix_elements.py`) | 1000 of 1000 enclosures contain the scqubits 4.3.1 value (ncut 40); 0 without a bound; width median 2.7e-14, max 3.1e-12; 0.054 s median per element |
| parameters as intervals, 200 transmons of the device regime, E_C and E_J ± 1 %, 6 levels, 5 inner points each (`bench/parameter_balls.py`) | 200 of 200 box intervals `GUARANTEED`; 0 of 1000 inner point intervals outside the box interval; a point with E_J 3 % above the box falls outside in 187 of 200 cases; box width / observed spread of the inner points: median 2.1, max 5.5; 0.12 s median per box |
| generative input tests (seeded, every public entry point) | found and fixed before this commit: OverflowError on integers beyond float64 in 4 entry points, `nmax_limit` not validated, uncapped `M`, `L_limit`, `N_limit`, `**kw` in `mathieu_a/b` |

**Re-measured on 2026-11-11 on this tree, and again on 2026-11-12 after the deterministic estimates** (the same
cases as in the author's repository on 2026-11-10/11, now as scripts in `bench/`):

| What | Script | Result |
|---|---|---|
| 6 real transmons of arXiv:2407.17407 (their E_J, E_C; Q5 also with their fits up to cos 8φ; 4–12 levels each) | `bench/real_transmons.py` | 84 of 84 levels `GUARANTEED`, width ≤ 1.14e-13 GHz; the smallest fixed charge cut within 1 kHz of the intervals is 10 (Q0), 12 (Q1, Q2), 15 (Q3, Q4), 20 (Q5 and its harmonic fits); 8.7 s |
| Spherical rotor, 60 random (B, dE, M), 4 levels | `bench/duffing_adapter_sphere.py` | numpy at a cut 40 larger inside in 240 of 240 levels |
| Molecule, RbCs, 16 transitions of Gregory et al. 2016 with their constants | `bench/gregory2016.py` | 16 of 16 centres within 100 Hz of their model (largest 93.8 Hz), every interval ≤ 7.4 mHz wide, 1.6 s |
| Molecule, TlF, CeNTREX-TlF 0.4.0 | `tests/test_port_centrex_tlf.py` (needs `QRAFT_BERSAGLI_VENV`) | 4 tests OK on 2026-11-11: their levels inside the intervals at zero field and at 173 V/cm with c₃_ours = 5·c₃_theirs (an operator identity); their Zeeman convention μ_J/J not covered for J ≥ 2 |
| Adapter rule "scq-threshold/1.0", 200 transmons of the device regime × ncut 3…30 (5600 runs) | `bench/duffing_adapter_sphere.py` | 0 results `OK` whose true error (against the guaranteed intervals) exceeds their own threshold; the same H written in MHz and Hz with the unit declared: 0 of 1200 verdicts differ |
| Multiport sandbox, positive controls S1–S7 | `tests/test_multiport.py` | per engine: network reached outside / blocked inside; file written outside / blocked inside; loop → timeout; 3 GiB → MemoryError; unknown key → `INVALID`; engine missing or not isolating → `SandboxMissing` |
| Duffing against transmon, 200 transmons of the device regime, variant "spectrum", level 3 | `bench/duffing_adapter_sphere.py` | \|δ_3\| ≥ 1 MHz in 200 of 200 (the end of the guaranteed interval of δ_3 nearer to zero; median 78 MHz, 90th percentile 4.3 GHz) |
| Origin case H = h2·n² + c2·cos 4φ with the fixed cut Nb = 40 of the author's earlier work | `tests/test_cos4phi_origin.py` | inside for (h2, c2) = (1, 2), (0.5, 20), (2, −15); off by 1.4e-11 for (0.25, 60), where the first cut inside lies between 41 and 60; Nb = 2 outside for all |

Mutation testing (not a claim about the package's numbers: a measure of the tests): 0.3.0 lines, 22 hand mutants on a
green copy of this tree on 2026-11-11, 20 killed, 2 declared equivalent (`CHANGELOG.md`); 0.2.0 modules, in the
author's repository on 2026-11-10/11 (rotor 8 of 8; sphere 16 of 16 + 14 of 14; molecule 24 of 24 + 21 of 21; adapter
18 of 18; multiport 23 of 24 + 1 equivalent; Duffing 22 of 24 + 2 equivalent).

## Tests, reproduction, determinism

`python -m unittest discover -s tests` against the installed package (`pip install .`; the test files import the
package, not the source tree). The sandbox tests run once per isolation engine whose probe passes
(`TestSandbox_<engine>`) and are skipped with the probe's reason otherwise; `test_port_centrex_tlf` runs only with
`QRAFT_BERSAGLI_VENV` pointing at a venv with centrex-tlf; `tests/test_examples.py` runs every script of `examples/`
in a fresh interpreter and checks what it prints. `bench/matrix.sh VENV...` reproduces the CI matrix locally (stack
default / unlimited / 1 MiB, engines present, bwrap absent, bwrap failing; fresh HOME per run).

Measured on 2026-11-12 (03:01 CET) on the tree of commit f55a975 (before the macOS/Windows fixes of the same day)
with `bench/matrix.sh` on the four venvs, each run against the
package installed from the tree in a fresh temporary HOME, bwrap 0.8.0, podman 4.3.1 with the image
`python:<minor>-slim` in the local store, wasmtime 50.0.1 (listed in `QRAFT_TRUSTED_ENGINES`) + CPython 3.15.2 WASI:
20 of 20 runs OK, 340 tests each.

| Python | numpy, scipy, python-flint | scqubits | stack default / unlimited / 1 MiB | bwrap hidden from PATH | fake bwrap (not root-owned) |
|---|---|---|---|---|---|
| 3.11.2 | 2.4.6, 1.17.1, 0.9.0 | 4.3.1 | OK, 65 skipped | OK, 84 skipped | OK, 84 skipped |
| 3.12.15 | 2.5.4, 1.18.1, 0.9.0 | absent | OK, 79 skipped | OK, 98 skipped | OK, 98 skipped |
| 3.13.15 | 2.5.4, 1.18.1, 0.9.0 | 4.3.1 | OK, 64 skipped | OK, 84 skipped | OK, 84 skipped |
| 3.14.8 | 2.5.4, 1.18.1, 0.9.0 | absent | OK, 79 skipped | OK, 98 skipped | OK, 98 skipped |

Every skip carries its reason: 19 each for the three engines absent on this machine (`docker`, `sandbox-exec`,
`appcontainer`), 19 more for `bwrap` when it is hidden or fake (its probe fails: fail-closed), 3 for
`test_port_centrex_tlf` without `QRAFT_BERSAGLI_VENV`, 1–3 for diatomic-py absent, 1 for the wasm solver test (no
numpy under WASI), 1 for an interpreter under /usr (no piece to mount), and on 3.12/3.14 the scqubits tests and the
README example (scqubits absent there). The bwrap, podman and wasm sandbox tests ran in every run where the engine
was present (0 skipped for them).

`python -m qraft_ra.reproduce` re-measures the numerical claims of this file offline, one `[PASS]`/`[FAIL]` line per
claim with the measured and the published value (fast set: 8.2 s on the author's machine; `--full` adds the
40 025-value Mathieu grid and the 200 wide-range transmons: 105 s); `--sabotage` makes the Mathieu solver return the next order of
the sector and must show at least one `[FAIL]` (positive control); `--readme` checks that every published value appears verbatim here and
is run by `python check_tree.py`, so a number edited by hand fails the tree check. Measured on 2026-11-12 on this
tree: fast set 9 of 9 PASS (the 2 slow claims print `[SLOW]` and run only with `--full`), `--full` 11 of 11,
`--sabotage` 2 FAIL (a_0(1) and a_11(299), the latter returning scipy's wrong 232.195; exit 0).

Determinism: the ends of every guaranteed interval depend only on the inputs, this code and python-flint, not on
the CPU or the BLAS/LAPACK library (since 2026-11-12; `docs/PROOF.md`, "Where the float numbers enter"). The float
estimates that choose where the exact counts are taken come from `qraft_ra._deterministic` (bisection and Householder
in Python floats, IEEE operations only, fixed order); before, they came from numpy/scipy and the published ends
changed with the BLAS kernel (measured 2026-11-12 on commit f9867d8: three different hashes with
`OPENBLAS_CORETYPE` Haswell, Prescott and Nehalem on one machine; in CI two values on Linux x86-64 runners and one
more each on ARM64, macOS, Windows). `python -m qraft_ra.reproduce --hash` prints the sha256 of a fixed set of exact
enclosures, one per guaranteed module (`reproduce.determinism_parts()`); `tests/test_determinism.py` fixes their
strings (python-flint 0.9.0) and recomputes a set of intervals in fresh interpreters under three OpenBLAS kernels.
Measured on 2026-11-12: `4d7d61cd2a17bd25f2a674a122436b2850800ef36927d9208c31cfd0bae3d403` on Python 3.11.2,
3.12.15, 3.13.15 and 3.14.8, each with `OPENBLAS_CORETYPE` unset, Haswell, Prescott and Nehalem (16 of 16), Linux
x86-64; a seeded probe of 309 inputs over all guaranteed modules gave identical strings under the three kernels and on
Python 3.12 and 3.14 (on f9867d8: 29 of 309 differed under Prescott). In CI run 43177561844 (commit 22a5b37,
2026-11-12) all 16 jobs printed `4d7d61cd2a17…`: Linux x86-64 (3.10–3.14, three stack sizes), Linux ARM64, macOS
(Accelerate), Windows and free-threaded 3.14t; the cross-kernel test ran on Linux x86-64, Windows and 3.14t and was
skipped with its reason on ARM64 and macOS (no OpenBLAS dispatch there). Assumed, not tested: binary64
round-to-nearest without flush-to-zero in the process.

CI: the workflow of 0.3.0 (`.github/workflows/ci.yml`: Linux x86-64 3.10–3.14 with three stack sizes and the
bwrap/podman/docker engines, Linux ARM64, macOS, Windows, free-threaded 3.14t): run 43177561844 on commit 22a5b37
(branch dev-0.3, 2026-11-12), 16 of 16 jobs green (364 tests on Linux x86-64, 354 on macOS and Windows, 322 on Linux
ARM64, 100 on 3.14t). The last green run of the published code is 43075004652 on commit 7beff99 (0.2.0, 2026-11-11,
Python 3.10–3.14, 161 tests each).

## Limits

- The 50-digit mpmath references of the charge-basis rotor are not independent of the truncation: they confirm the
  arithmetic, not the truncation bound, which rests on the proof. The Mathieu module is an independent route
  (sectors instead of the full chain) and meets the rotor's intervals (tests), but it is this author's code too.
- The proof is the author's assembly of standard steps. It has had no external human review; its adversarial
  reviews were automated (an independent agent, reports in the author's repository).
- Molecule: fields along z only; no AC polarizability; the CeNTREX-TlF Zeeman convention μ_J/J is not covered for
  J ≥ 2 (declared); quadrupole with I < 1 is refused, not zeroed. Fluxonium: one mode, no array modes. Matrix
  elements: charge-basis rotor only (not the molecule's dipoles); the parameter box is rigorous but loose (Lipschitz
  constant 1 in each coefficient).
- Multiport: user-namespace or container sandboxes, not VMs; `sandbox-exec`, `appcontainer` and `docker` were written
  from the vendors' documentation and are measured only by the CI jobs (green in run 43165166338); the WebAssembly
  engine runs the pure-Python ports (reference, controls), not the numpy solvers (no numpy exists for WASI).
- Multiport on macOS and Windows: some caps come from a host watchdog that samples every 20 ms and once more after
  the exit, not from the kernel: memory on sandbox-exec (macOS refuses RLIMIT_AS, RLIMIT_DATA and RLIMIT_RSS,
  measured in CI), the scratch disk on both, the CPU time on appcontainer next to the Job Object's own limit
  (Windows checks that one only periodically). A port can exceed a cap by what it does in one interval before it is
  killed; files unlinked while open are not counted (docs/PORT_CONTRACT.md §6).
- Adapter: the float floor is a plausible bound (16× the nominal tolerance of LAPACK ?stebz), not a proof.
- Speed: see the table above.

## Provenance

There is no release yet. `FILE_LIST.tsv` lists every file with its sha256 and, for the modules derived from the
author's repository, the sha256 of the source file; `python check_tree.py` checks the list, the imports, a deny-list
and runs gitleaks.

## License

Apache License 2.0 (`LICENSE`, `NOTICE`). Copyright 2026 Roberto Locatelli.
