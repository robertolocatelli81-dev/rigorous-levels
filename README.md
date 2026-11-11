# qraft-ra

Mathematically guaranteed eigenvalue intervals for the charge-basis rotor (transmon, cos 2φ, any sum of cosines up to
cos 24φ), for the spherical rotor in a field, for the ¹Σ molecule with hyperfine, Zeeman and Stark terms, for the
Mathieu characteristic values a_r(q), b_r(q) and for the fluxonium in the oscillator basis; a convergence warning for
scqubits with a declared threshold rule; a sandboxed multiport that runs other people's solvers inside one of six
isolation engines (Linux, macOS, Windows, WebAssembly) and tells, level by level, whether they fall inside the
intervals; and the guaranteed per-level error of the Duffing model against the transmon.

Noûs, AI agent under a revocable mandate from Roberto Locatelli.

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
3. **The multiport** (`multiport`, `port_runner`, `isolation`; contract "qraft-port/0.2" in `docs/PORT_CONTRACT.md`):
   an external solver runs inside an isolation engine chosen from a closed, ordered list — `podman`, `docker`,
   `bwrap` (Linux), `sandbox-exec` (macOS), `appcontainer` (Windows), `wasm` (wasmtime + CPython for WASI) — each
   with no network, a read-only file system, no real home, a minimal environment, time and memory limits and a
   fail-closed probe (an engine that is missing or does not isolate is never used silently). Its JSON output is
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
- It is not faster than the float tools: a guaranteed transmon point costs 0.16 s median; a Mathieu value 0.38 ms
  median (scipy: 3.6 µs); a fluxonium device 0.4–6.5 s (scqubits: milliseconds); the multiport costs seconds per run.
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
plus a CPython built for WASI in `QRAFT_PYTHON_WASM` (pure-Python ports only: no numpy exists for WASI). Not on PyPI.

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
from qraft_ra.mathieu import mathieu_a, mathieu_b
v = mathieu_a(11, 299.0)                         # scipy 1.18.1 returns 232.195 here; the interval is [123.9949…]
print(v.state, v.strings, v.K)

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
               {"ncut": 30}, site_packages=(<site-packages with scqubits>,))
u = MP.run_port(r, engine="auto")                # SandboxMissing if no engine isolates; u.sandbox names the engine
print(MP.compare(iv, "GHz", u, tolerance=1e-12).overall)      # INSIDE / INSIDE_TOLERANCE / OUTSIDE

# Duffing against transmon
from qraft_ra.duffing_vs_transmon import duffing_error
print(duffing_error(0.3, 15.0, 0.25, 6).delta_float()[3])     # interval of (E_3 - E_0) - E^D_3, GHz
```

## Against the existing tools, measured

Every row is a measurement of 2026-11-10/11 on this tree (details and dates in "Measurements" and in `CHANGELOG.md`);
"guarantee" means an interval proven to contain the exact eigenvalue of the written H, truncation included.

| quantity | this package | other tool | guarantee | correct against a known truth | time per point, ours / theirs (`bench/compare_tools.py`, 2026-11-11, Python 3.11.2) | fails when | script of the other columns |
|---|---|---|---|---|---|---|---|
| transmon levels (cos mφ, any n_g), 6 levels | `guaranteed_levels` | scqubits `Transmon` (ncut 30), qiskit-metal `Hcpb`, SQcircuit, pyEPR | yes (width ≤ 1.6e-13 GHz on 400 cases) / no | 50-digit mpmath inside in 2400 of 2400 levels; scqubits at ncut 30 wrong without a warning in 65 of 200 cases at E_J/E_C ≥ 7744, all flagged by the adapter | 92 ms / 0.27 ms (**scqubits 340× faster**; our float solver 2.4 ms) | E_J/E_C beyond ~1e6 (N > 4000: `OutOfDomain`) | `bench/readme_numbers.py` |
| transmon with E_C, E_J (and n_g) as intervals | `guaranteed_levels_over_box` | none gives a bound over a box | yes (point computations at the box corners and band edges + ρ) / — | 200 transmons × 5 inner points: 0 point intervals outside the box interval; a point 3 % outside the box detected in 187 of 200; box width 2.1× the observed spread (median; max 5.5×); n_g intervals checked against a fine sampling at E_J/E_C = 5 (tests) | 176 ms / — | an n_g interval longer than 1 is the whole band | `bench/parameter_balls.py` |
| matrix elements ⟨i|n|j⟩, ⟨i|cos φ|j⟩ | `guaranteed_matrix_element` | scqubits `matrixelement_table` (ncut 40) | yes (width median 2.7e-14, max 3.1e-12 on 1000 elements) / no | scqubits inside in 1000 of 1000 (200 transmons × 5 elements); exact symmetry values inside (tests) | 58 ms / ms | levels not separated at the width (no bound, `OutOfDomain`) | `bench/matrix_elements.py` |
| Mathieu a_r(q), b_r(q) | `mathieu_a/b` | scipy `mathieu_a/b` 1.17.1, 1.18.1 | yes (1e-12 relative, 40 019 of 40 025; 6 WIDE) / no | 52 scipy values of 40 025 wrong (another order), 0 in scipy 2.0.0.dev; all 52 confirmed by an independent reference | 0.33 ms / 2.3 µs (**scipy 150× faster**) | r > 200, non-finite q (refused) | `bench/mathieu_vs_scipy.py` |
| fluxonium levels | `guaranteed_fluxonium_levels` | scqubits `Fluxonium` (cutoff 110) | yes (5e-10 GHz) / no (cutoff chosen by the user) | scqubits cutoff 110 inside in 16 of 16 levels of 4 published devices; cutoff 6 outside | 0.39 s (light device) to 6.5 s / 10 ms (**scqubits 37× faster**) | N > 240 Fock states needed (`OutOfDomain`) | `bench/fluxonium_devices.py` |
| spherical rotor in a field | `guaranteed_sphere_levels` | numpy at a larger cut | yes / no | 177 of 177 cuts inside (author's repository, 2026-11-10); Blackmore et al. 2018: 130.3 Hz guaranteed vs 129 Hz | 0.36 ms / 0.10 ms (numpy 3.5× faster) | D_c with fewer than k levels in the model (refused) | `tests/test_spherical_rotor.py` |
| ¹Σ molecule, hyperfine + Zeeman + Stark | `guaranteed_molecule_levels` | diatomic-py 2.1.0, CeNTREX-TlF 0.4.0 | yes (7 mHz on RbCs) / no (`Nmax`, `Jmax` by hand) | Gregory et al. 2016: 16 of 16 transitions within 100 Hz of their model (author's repository, 2026-11-10); diatomic-py's code has the wrong sign of c₃ (issue #15); CeNTREX default `Jmax = J+2` errs 4.26 MHz at 10 kV/cm | 37 ms (L = 3, 1 level) to seconds per sector / ms | L > 64, 2I > 40 (refused); fields not along z (not modelled) | `tests/test_hyperfine_molecule.py` |
| convergence warning for scqubits | `scqubits_spectrum`, `guaranteed_from_scqubits` | scqubits alone | no (empirical, declared rule) / none; the second gives the guaranteed verdict | 0 results `OK` outside the threshold in 4280 runs | 2 scqubits calls / 1 | the border ±1e-4 of the threshold | `tests/test_scqubits_adapter.py`, `tests/test_parameter_balls.py` |
| running other people's solvers | multiport, 6 engines | — | fail-closed isolation, closed contract | S1–S7 controls pass for bwrap, podman and wasm (measured here); docker, sandbox-exec, appcontainer: CI only | seconds per run / — | an engine whose probe fails (`SandboxMissing`, no fallback) | `tests/test_multiport.py` |

Where the other tool is better it is written: scipy and scqubits are 37–340× faster on these inputs; they give no
bound. The timings are medians of 5 runs on the author's machine (`bench/compare_tools.py` prints the platform).

## Three public reports, reproducible with this package

Each one was found by comparing a public solver with the guaranteed intervals and reported by the author on
2026-11-11 (links are public; nothing else was sent):

1. **durham-qlm/diatomic-py #15** — https://github.com/durham-qlm/diatomic-py/issues/15. The code of
   `tensor_nuclear` (2.1.0) uses +√6 c₃ T²(C)·T²(I₁,I₂); the package's paper (eq. 5b), Aldegunde et al. 2008 and
   Gregory et al. 2016 use the opposite sign. With the paper's sign the 16 RbCs transitions of Gregory et al. 2016
   (Table I) are reproduced within 100 Hz of their model values f_the (intervals 7 mHz wide); with the code's sign 1 of
   16. In this package `tests/test_hyperfine_molecule.py::TestGregory2016` checks the stretched line M_F = +5 → +6 at
   181.541 G, and `TestCostruzioneContraDiatomicPy` compares the matrix elements (needs `pip install diatomic-py==2.1.0`).
2. **qiskit-community/qiskit-metal #1252** — https://github.com/qiskit-community/qiskit-metal/issues/1252.
   `mathieu_level(m, ng, Ej, Ec)` returns the energy of another level for some (m, Ej/Ec) at n_g = 0 and 1/2: the
   cause is `scipy.special.mathieu_a/mathieu_b` (fixed on scipy main by PR #25128, milestone 2.0.0). Two counts,
   two referents: (a) scipy releases, re-measured on this tree with `bench/mathieu_vs_scipy.py` (r ≤ 12,
   |q| ≤ 400, step 0.5): 52 wrong values of 40 025 in 1.17.1 and 1.18.1 (identical lists), 0 in
   2.0.0.dev0+git20261108; the finer grid of the issue (step 0.05, 400 000 values, 522 wrong, scipy 1.10.1 … 1.18.1)
   was measured on 2026-11-11 in the author's repository and is not re-run here; (b) qiskit-metal's `mathieu_level`,
   which inherits (a): the numbers in the issue are theirs to reproduce with the port `metal_mathieu`. Since 0.3.0
   `qraft_ra.mathieu` gives the guaranteed values directly.
3. **scqubits/scqubits #334** (comment) — https://github.com/scqubits/scqubits/issues/334#issuecomment-6796563509.
   The first scipy release whose sparse `eigsh` silently omits the zero eigenvalue is 1.15.0 (bisection 1.10.1,
   1.13.1, 1.14.1 right; 1.15.0, 1.15.3, 1.16.2, 1.17.1, 1.18.1 wrong; independent of the start vector).

Two more measurements with no report (the other side already documents or fixed them): CeNTREX-TlF's default
`Jmax = J + 2` errs by 4.26 MHz at 10 kV/cm with no warning; at 30 kV/cm their API is 3.9 GHz off but warns
("Ambiguous eigenstate assignment"); their AGENTS.md already tells users to raise Jmax. SQcircuit 1.0.0's single
transmon is inside the intervals within 3e-13 GHz once the junction's own capacitance (1e-20 F) is included.

## Measurements

**Measured on 2026-11-10** (charge-basis rotor, `bench/readme_numbers.py --full`, Python 3.11.2, numpy 2.4.6, scipy
1.17.1, python-flint 0.9.0, scqubits 4.3.1): 400 of 400 cases `GUARANTEED`, the 50-digit mpmath reference inside the
interval in 2400 of 2400 levels, largest width 1.56e-13 GHz; time per guaranteed point (6 levels) mean 0.51 s,
median 0.16 s; scqubits at ncut = 30 wrong without a warning in 65 of 200 cases at E_J/E_C ≥ 7744, all 65 flagged by
the adapter, 0 false alarms.

**Measured on 2026-11-11 on this tree** (`bench/mathieu_vs_scipy.py`, `bench/fluxonium_devices.py`, Python 3.11.2
unless stated):

| What | Result |
|---|---|
| Mathieu, r = 0…12, q = −400…400 step 0.5 | 40 025 values, 40 019 `GUARANTEED` (1e-12 relative), 6 `WIDE`; median 0.38 ms per value |
| scipy `mathieu_a/b` against those intervals | 1.17.1 (3.11.2) and 1.18.1 (3.12.15): 52 wrong, identical lists, 30 equal to another order ≤ 12, all 52 confirmed wrong by an independent tridiagonal reference (K = 400); 2.0.0.dev0+git20261108.c9073e6 (3.13.15): 0 wrong; scipy median 3.6 µs per value |
| fluxonium, 4 published parameter sets, 4 levels | all `GUARANTEED`, width 5e-10 GHz, N = 54…117, 0.4–6.5 s; scqubits 4.3.1 cutoff 110 inside 16 of 16 levels, cutoff 6 outside |
| fluxonium vs measured lines (one-mode H, parameters as printed) | Zhang et al. 2021: f01 13.88 MHz guaranteed vs 14 MHz measured; Moskalenko et al. 2022 qubit A: 685.73 vs 688.22 MHz (f01), 1831.20 vs 1832 MHz (f12); shifts reported, not judged |
| isolation engines, controls S1–S7 | bwrap 0.8.0, podman 4.3.1 (rootless, cgroups v1) and wasmtime 50.0.1 + CPython 3.15.2 WASI: all S1–S7 pass (the control ports are pure Python; under WASI only the numpy solver ports cannot run, there is no numpy for WASI); docker, sandbox-exec, appcontainer: not measured locally (CI jobs written) |
| matrix elements, 200 transmons of the device regime, ⟨0|n|1⟩, ⟨1|n|2⟩, ⟨0|n|2⟩, ⟨0|cos φ|1⟩, ⟨1|cos φ|2⟩ (`bench/matrix_elements.py`) | 1000 of 1000 enclosures contain the scqubits 4.3.1 value (ncut 40); 0 without a bound; width median 2.7e-14, max 3.1e-12; 0.058 s median per element |
| parameters as intervals, 200 transmons of the device regime, E_C and E_J ± 1 %, 6 levels, 5 inner points each (`bench/parameter_balls.py`) | 200 of 200 box intervals `GUARANTEED`; 0 of 1000 inner point intervals outside the box interval; a point with E_J 3 % above the box falls outside in 187 of 200 cases; box width / observed spread of the inner points: median 2.1, max 5.5; 0.11 s median per box |
| generative input tests (seeded, every public entry point) | found and fixed before this commit: OverflowError on integers beyond float64 in 4 entry points, `nmax_limit` not validated, uncapped `M`, `L_limit`, `N_limit`, `**kw` in `mathieu_a/b` |

**Measured on 2026-11-10/11** in the author's repository with the modules of 0.2.0 (logs there, not re-run here):
6 real transmons of arXiv:2407.17407: 26 of 26 `GUARANTEED`, width ≤ 1.1e-13 GHz; RbCs sphere 130.3 Hz guaranteed
for M = ±1 at 1.2 V/cm (Blackmore et al. 2018: 129 Hz); RbCs molecule 16 of 16 transitions of Gregory et al. 2016
within 100 Hz (max 94 Hz), intervals 7 mHz wide; TlF within 0.5 Hz of CeNTREX-TlF 0.4.0 at zero field and 173 V/cm;
adapter rule: 0 results `OK` outside the threshold, verdicts identical in GHz/MHz/Hz; Duffing |δ_3| ≥ 1 MHz in 200 of
200 transmons (median 34 MHz).

Mutation testing: 0.2.0 modules in the author's repository (rotor 8 of 8; sphere 16 of 16 + 14 of 14; molecule 24 of
24 + 21 of 21; adapter 18 of 18; multiport 23 of 24 + 1 equivalent; Duffing 22 of 24 + 2 equivalent). 0.3.0 modules:
see `CHANGELOG.md` (hand mutants on the new lines of mathieu, fluxonium, isolation and the input guards, run on a
green copy of this tree).

## Tests

`cd tests && python -B -m unittest test_guaranteed_intervals test_rotor_spectrum test_scqubits_adapter
test_readme_example test_spherical_rotor test_hyperfine_molecule test_inputs_review test_duffing_vs_transmon
test_multiport test_port_centrex_tlf test_mathieu test_fluxonium test_parameter_balls test_matrix_elements test_examples test_generative_inputs
test_deprecated_aliases`,
against the installed package. The sandbox tests run once per isolation engine whose probe passes
(`TestSandbox_<engine>`), and are skipped with the probe's reason otherwise. `test_port_centrex_tlf` runs only with
`QRAFT_BERSAGLI_VENV` pointing at a venv with centrex-tlf. `bench/matrix.sh VENV...` reproduces the CI matrix locally
(stack default / unlimited / 1 MiB, engines present, bwrap absent, bwrap failing; fresh HOME per run).
`tests/test_examples.py` runs every script of `examples/` in a fresh interpreter and checks what it prints.

CI: the workflow of 0.3.0 (`.github/workflows/ci.yml`: Linux x86-64 3.10–3.14 with three stack sizes and the
bwrap/podman/docker engines, Linux ARM64, macOS, Windows, free-threaded 3.14t) has not run yet: it runs when this
branch is pushed. The last green run of the published code is 43075004652 on commit 7beff99 (0.2.0, 2026-11-11,
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
  from the vendors' documentation and are measured only by the CI jobs (not yet run); the WebAssembly engine runs the
  pure-Python ports (reference, controls), not the numpy solvers (no numpy exists for WASI).
- Adapter: the float floor is a plausible bound (16× the nominal tolerance of LAPACK ?stebz), not a proof.
- Speed: see the table above.

## Provenance

There is no release yet. `FILE_LIST.tsv` lists every file with its sha256 and, for the modules derived from the
author's repository, the sha256 of the source file; `python check_tree.py` checks the list, the imports, a deny-list
and runs gitleaks.

## License

Apache License 2.0 (`LICENSE`, `NOTICE`). Copyright 2026 Roberto Locatelli.
