# qraft-ra

Mathematically guaranteed eigenvalue intervals for the charge-basis rotor (transmon, cos 2φ qubits, any sum of
cosines up to cos 24φ), and a convergence warning for scqubits.

Noûs, AI agent under a revocable mandate from Roberto Locatelli.

## The problem, and for whom

Spectra of superconducting circuits are computed in a truncated charge basis. A fixed truncation (scqubits' `ncut`,
or `nmax` in a hand-written code) cannot notice when it is too small: the number comes out, wrong, with no warning.
scqubits leaves the convergence check to the user (documentation, "Bases, truncation, and convergence").

This package is for people who need to know how far a computed level can be trusted: when a value goes into a paper,
a fit, a design review or a regression test, or when a parameter sweep reaches regimes (large E_J/E_C, many
harmonics) where the usual truncation rule was never checked.

It gives three things:

1. **`intervallo_garantito.livelli_garantiti`**: the first k levels of
   H = 4E_C(n − n_g)² + Σ_m c_m cos(mφ) as intervals [low, high] that contain the exact eigenvalue of this H,
   with a proof that includes the truncation of the basis (`docs/PROOF.md`). When the proof does not apply, it
   raises `FuoriDominio` with the reason and returns no number.
2. **`rotore_spettro.spettro`**: float64 levels of the same H (sines allowed) whose basis grows until the low
   spectrum stops moving, checked by a second method; otherwise the state is `NON_CONVERGENTE`.
3. **`scqubits_adattatore.spettro_scqubits`**: scqubits' own transmon, called at `ncut` and at `2·ncut`; if the
   shift exceeds a threshold, the state is `NON_CONVERGENTE` (mode `raddoppio`), or `ncut` keeps doubling until it
   does not (mode `auto`).

Identifiers, states and error messages are in Italian (`Rotore`, `spettro`, `GARANTITO`, `FuoriDominio`, ...), as in
the code the package was extracted from.

## What is guaranteed, and under which conditions

For j < k, λ_j(H_N′) ≤ λ_j(H) ≤ λ_j(H_N): Rayleigh–Ritz above, a block decoupling of the quadratic form with a
proven bound on the truncated part below, eigenvalue counts by Sylvester's law of inertia in Arb ball arithmetic
(python-flint). The argument and its sources (Teschl; Barth, Martin, Wilkinson 1967; Johansson 2017) are in
`docs/PROOF.md`. The guarantee holds under three conditions:

1. E_C > 0 and distinct integer harmonics 1 ≤ m ≤ 24, cosines only (`Rotore` checks them; sines are refused).
2. H is the one of the exact float64 parameters (0.1 is 0.1000000000000000055…).
3. Arb/FLINT rounds correctly. This is assumed, not proven here, and there is no formal verification of this code:
   tests and mutation testing reduce the risk of a defect in the implementation, they do not remove it.

Within these conditions an interval marked `GARANTITO` has width ≤ the requested one (default 1e-12, in the unit of
E_C); `LARGO` means valid but wider than requested. Limits: k ≤ 20 levels, bases up to dimension 8001.

## What it does not do

- It does not say that H describes a device. The interval contains the value of the H you wrote, not of a chip.
- It is not faster than scqubits. A guaranteed point costs 0.16 s (median) to 3.8 s (6 levels); our float solver is
  about 11 times slower than scqubits in the device regime with one BLAS thread, about 40 times with 8 threads
  (measurements below). Fine for checking values, not for sweeps.
- It does not improve accuracy in the device regime: there scqubits and our solver agree within 2.3e-12 GHz.
- The convergence warning is an empirical check, not a proof: the shift on doubling is a lower bound of the true
  error, and misses and false alarms exist within ±1e-4 relative of the threshold (reported on 2026-11-08). Its
  default threshold is relative: see "Limits" before using it on device parameters.
- The scqubits adapter covers only the transmon (`scqubits.Transmon`); the kite and multi-harmonic rotors stay on
  our own solver.
- QRAFT-RA is an internal model of its author, not an external validator. Nothing here is an accredited or
  third-party certification: "guaranteed" means "follows from the proof in `docs/PROOF.md`", nothing more.

## Install and use

```sh
pip install .                  # numpy, scipy, python-flint
pip install ".[scqubits]"      # also the scqubits adapter
```

Python ≥ 3.10. Not on PyPI yet.

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

## Measurements

**Measured on 2026-11-10** on the author's machine (x86-64 Linux, 8 cores; Python 3.11.2, numpy 2.4.6, scipy 1.17.1,
python-flint 0.9.0, scqubits 4.3.1, mpmath 1.3.0) with `bench/readme_numbers.py --full`, which anyone can rerun (fixed
seeds, the same case generators as the author's benchmarks of 2026-11-08). Times depend on the machine and its load.

| What | Result |
|---|---|
| Guaranteed intervals, 400 cases (200 transmons −E_J cos φ and the same 200 as −E_J cos 2φ; E_C = 1, E_J/E_C = 10^U(−1, 6), 6 levels) | 400 of 400 `GARANTITO`; the 50-digit mpmath reference inside the interval in 2400 of 2400 levels; largest width 1.56e-13 GHz |
| Time per guaranteed point (6 levels) | mean 0.51 s, median 0.16 s, max 3.8 s |
| scqubits at ncut = 30 on the same 200 transmons (truth: scqubits at ncut = 300; wrong = error > 1e-6 × max(1, largest transition)) | wrong without a warning in 65 of 200 cases, all at E_J/E_C ≥ 7744 |
| Adapter, mode `raddoppio`, ncut = 30 | flags 65 of 65 wrong results, 0 false alarms on the 135 right ones |
| Adapter, mode `auto` | 0 of 200 wrong |
| Device regime, 200 transmons (E_C 0.05–1 GHz, E_J/E_C 1–1000): our solver against the adapter in mode `auto` | largest difference on E_j − E_0: 2.3e-12 GHz |
| Time per point, device regime, one BLAS thread (`OMP_NUM_THREADS=1`) | scqubits at ncut = 30: 0.29 ms; our float solver: 3.1 ms (about 11 times slower) |
| The same with the default 8 BLAS threads | scqubits 0.71 ms (adapter `auto` 1.25 ms); our solver 29.5 ms (about 40 times slower: thread overhead on small matrices) |

Test suite: see "Tests" below.

## Tests

`cd tests && python -m unittest test_intervallo_garantito test_scqubits_adattatore test_rotore_spettro
test_readme_example`, against the installed package (`pip install ".[scqubits,test]"`). Counts measured on 2026-11-10
are in the commit message that records them.

**Reported on 2026-11-08 and 2026-11-09** in the author's measurement logs (not in this repository, not re-run here):

- Out of sample, 2000 new transmon cases (other seed, ncut drawn among 15, 30, 60): the warning flagged 604 of 604
  wrong results with 0 false alarms on 1396; out of distribution, 4976 cases with E_C from 1e-3 to 1e2 GHz and
  E_J/E_C from 1e-3 to 1e7: no miss and no false alarm.
- A 24-harmonic transmon model fitted to the 6 devices of arXiv:2407.17407 (Table I): 12 levels, 6 of 6 `GARANTITO`,
  width at most 1.14e-13 GHz, 8.6–13.2 s per device.
- Guaranteed intervals exist up to E_J/E_C = 5e6 (k = 6); at 1e7 the counts stay uncertain at 1024 bits and the result
  is `FuoriDominio` with that reason.

## Limits

- **The 50-digit mpmath references are not independent of the truncation.** They diagonalize the same charge-basis
  matrix, only larger and in higher precision: they confirm the arithmetic, not the truncation bound. The truncation
  bound rests on the proof. An independent reference (Mathieu characteristic values by continued fractions,
  DLMF §28.6) is future work; the existing comparison with scipy's Mathieu functions (cos 2φ, n_g = 0) is only a
  1e-8 consistency check.
- The proof is the author's assembly of standard steps and has had no external review; prior art is in
  `docs/PROOF.md`.
- **The default threshold of the scqubits warning is relative, and too loose in the device regime.** It is
  1e-6 × max(1, largest transition), which for transmons with E_J/E_C 5–500 reaches 1.8e-5 GHz (18 kHz). Measured by
  the author on 2026-11-10 (200 transmons, E_J/E_C 5.5–492, truth = the guaranteed intervals, "wrong" = more than
  1e-6 GHz away; log not in this repository): with the default threshold 8 wrong results passed without a warning
  (4 of 63 at ncut = 10, 4 of 4 at ncut = 15); with `tol=1e-6` (GHz, absolute) all 67 were flagged with 0 false
  alarms. In the device regime pass an absolute `tol`, for example `spettro_scqubits(r, k, ncut, tol=1e-6)`. The
  same measurement found scqubits correct within 1 kHz on 200 of 200 cases at ncut = 30.
- Sines (for example the kite away from φ_ext = π) need a complex Hermitian count: not done, refused with a reason.
- Speed: see above.

## Provenance of releases

There is no release yet. Releases are planned to carry Sigstore build-provenance attestations from the release
workflow; until then, a copy can be checked only against this repository (`FILE_LIST.tsv` lists every file with its
sha256, `python check_tree.py` checks them).

## License

Apache License 2.0 (`LICENSE`, `NOTICE`). Copyright 2026 Roberto Locatelli.
