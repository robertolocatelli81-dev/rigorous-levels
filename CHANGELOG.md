# Changelog

All dates are from the author's system clock (Europe/Rome). Nothing here is published yet: no release, no PyPI.

## 0.3.0 — 2026-11-11 (local, unreleased; branch dev-0.3 from 7beff99)

Four limits of 0.2.0 were named by the author on 2026-11-11 and are closed or narrowed here (measurements in
README "Measurements" and in the author's report; every number re-measured on this tree, dates and versions stated).

### A. Tests that did not see what the CI saw

0.2.0 shipped two defects found only by GitHub's CI (user namespaces denied by AppArmor; a nesting limit left to
RecursionError, which depends on the stack size on Python 3.14). The class is closed, not the two cases:

- `bench/matrix.sh`: the whole suite against the installed package on every venv given, with the stack at its
  default, unlimited and 1 MiB, with the isolation engines present, with `bwrap` absent from PATH and with a fake
  `bwrap` that fails; every run in a fresh temporary HOME; one summary line per run plus the list of skips with
  reasons.
- CI: Linux x86-64 (3.10–3.14, stack default/unlimited/1 MiB, bwrap + podman + docker engines, each one's S1 test
  required to run), Linux ARM64 (3.12, 3.14; bwrap + docker), macOS (3.12, 3.14; everything that is not a sandbox
  plus the `sandbox-exec` engine, state of that tool measured on the runner), Windows (3.12, 3.14; everything that is
  not a sandbox plus the `appcontainer` engine), free-threaded 3.14t (pure-math modules, dependencies installed only
  from wheels). The jobs run when the branch is pushed: not yet.
- `tests/test_generative_inputs.py`: seeded random attacks on every public entry point (unknown keyword, wrong type,
  NaN/inf, bool, integers beyond float64, unicode, nested containers, numpy scalars) must give exactly the declared
  refusal; a valid input of the same family must pass (positive control); no public function accepts `**kwargs`.
  Defects it found in this tree before the fix (all fixed): `Rotor`, `spectrum`, `guaranteed_levels`,
  `mathieu_value` crashed with OverflowError on an integer beyond float64 instead of refusing it; `spectrum`
  accepted a non-integer `nmax_limit`; `SphericalRotor` accepted any |M| and `guaranteed_sphere_levels` any
  `L_limit`; `guaranteed_levels` accepted any `N_limit`; `mathieu_a/b` took `**kw`. Caps are now declared constants
  (`N_LIMIT`, `L_LIMIT`, `K_LIMIT`, `N_LIMIT` of the fluxonium, `NMAX_LIMIT`).
- Audit of the dependence on interpreter limits (recursion, float conversion of big ints, locale, dict order,
  encoding): no recursion in the parsers (the JSON depth is counted linearly), every float conversion of an input
  goes through a guard, `json.dumps` with `sort_keys` where a canonical form is needed, every file opened with an
  explicit encoding; `resource`, `socket`, `os.fork`, `os.kill` are optional in the runner (Windows, WASI).

### B. English API

Modules, classes, functions, keyword arguments, fields, states and error messages are English. Old → new:
`intervallo_garantito` → `guaranteed_intervals` (`livelli_garantiti` → `guaranteed_levels`, `Intervalli` →
`Intervals` with `low/high/strings/max_width/state/seconds`, `GARANTITO/LARGO` → `GUARANTEED/WIDE`,
`FuoriDominio/ArbAssente/TempoScaduto` → `OutOfDomain/ArbMissing/DeadlineExceeded`); `rotore_spettro` →
`rotor_spectrum` (`Rotore` → `Rotor` with `cosines/sines`, `spettro` → `spectrum`, `Spettro` → `Spectrum` with
`energies/error/floor/state`, `NON_CONVERGENTE` → `NOT_CONVERGED`, `IngressoRifiutato` → `InputRejected`);
`scqubits_adattatore` → `scqubits_adapter` (`spettro_scqubits` → `scqubits_spectrum` with `check=` in
`none/doubling/auto`, `unit=`, `engine=` in `process/sandbox`, states `UNCHECKED`, `OK_FLOAT_FLOOR`, origins
`absolute/relative/user/floor`, rule id `scq-threshold/1.0`); `rotore_sferico_garantito` → `spherical_rotor`
(`RotoreSferico` → `SphericalRotor`, `livelli_sfera_garantiti` → `guaranteed_sphere_levels`, `N_fis` → `N_phys`);
`molecola_iperfine_garantita` → `hyperfine_molecule` (`MolecolaSigma` → `SigmaMolecule` with `two_I1/two_I2`,
`livelli_molecola_garantiti` → `guaranteed_molecule_levels` with `two_MF`, `dimensione_settore` →
`sector_dimension`); `multiporta` → `multiport` (`Richiesta/Uscita/Verdetto` → `Request/Output/Verdict`,
`esegui_porta/confronta/valida_uscita/leggi_uscita` → `run_port/compare/validate_output/read_output`, verdicts
`INSIDE/INSIDE_TOLERANCE/OUTSIDE/NOT_COMPARABLE`, output states `OK/ERROR/INVALID`); `porte_runner` → `port_runner`;
`duffing_vs_transmon` (`errore_duffing` → `duffing_error`, variants `spectrum/koch`, `ErroreDuffing` → `DuffingError`).
The Italian modules remain as deprecated aliases (`qraft_ra._compat`): importing them or using any old name emits a
DeprecationWarning that names the replacement; keyword arguments are translated; the fields of the results have
Italian read-only aliases; `tests/test_deprecated_aliases.py` measures that the old names work and that the
English API is warning-free under `-W error::DeprecationWarning`.
Formats on disk changed with a new version declared first: the port contract is "qraft-port/0.2" (then
"qraft-port/0.3" with the batches of §8, the one accepted by 0.3.0)
(`docs/PORT_CONTRACT.md`, English keys, port names `numpy_rotor`, `test_*`, model types `cos_rotor`,
`sigma_molecule`; "qraft-porta/0.1" is refused); the threshold rule is "scq-threshold/1.0"
(`docs/THRESHOLD_RULE.md`, same content as "soglia-scq/1.0").
Not translated: test method names and test docstrings (prose, not API), kept from 0.2.0.

### C. Isolation beyond Linux (`qraft_ra.isolation`, the same contract for every engine)

- Engines, closed list with a declared order of strength (`ENGINE_ORDER`, docs/PORT_CONTRACT.md §6.0): `podman`,
  `docker` (OCI container: `--network none --read-only --cap-drop ALL --security-opt no-new-privileges`, non-root
  user, tmpfs /tmp, site-packages and work folder read-only, image taken only from the local store, kill on timeout
  from the host), `bwrap` (as in 0.2.0), `sandbox-exec` (macOS, deny-default Seatbelt profile: no network, reads
  everything except the user's homes, writes only the output file), `appcontainer` (Windows: AppContainer process
  through `CreateAppContainerProfile` / `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES`, read grants to the
  interpreter and site-packages for the container SID, Job Object limits on memory, process count and CPU time),
  `wasm` (wasmtime + a CPython built for WASI: no sockets, only pre-opened folders, interpreter folder required
  read-only, `-W max-memory-size`, `-W timeout`).
- `run_port(request, engine="auto")` picks the first engine of the order whose fail-closed PROBE passes (engine
  executable present; containers: image present locally and, inside, only the `lo` interface, uid ≠ 0, read-only
  root; sandbox-exec/appcontainer/wasm: network closed, root not writable, home not visible); the engine used is
  named in `Output.sandbox`. Nothing degrades silently: no engine → `SandboxMissing` with every reason.
- Tests: the S1–S7 controls run once per engine available (`TestSandbox_<engine>` classes), skipped with the
  probe's reason otherwise; CI requires the S1 test of the expected engines to have run.
- Measured locally (Linux x86-64, 2026-11-11): bwrap 0.8.0 and podman 4.3.1 rootless pass S1–S7 (podman on cgroups
  v1 ignores `--memory`/`--pids-limit` with a warning: not relied upon, the runner's rlimits apply); wasmtime 50.0.1
  + CPython 3.15.2 WASI passes the controls that do not need numpy and has NO numpy, so no solver port can run there
  (declared; `test_s3_memoria`, `s6`, `s7`, scqubits tests skipped with that reason). NOT measured locally:
  docker, sandbox-exec, appcontainer, ARM64 (CI jobs written; they run after the push).
- Runner: `resource`, `socket`, `os.fork`, `os.kill` optional; `QRAFT_OUTPUT_DIR` for engines that cannot bind a
  single file into a read-only folder; `ok_then_crash` ends with `os._exit(137)` when SIGKILL is ignored (PID 1).

### D. Wider field with guaranteed intervals

- `parameter_balls`: E_C and the cosine coefficients as intervals (`RotorBall`, `guaranteed_levels_over_box`): the
  level over the whole box from two guaranteed computations (E_C ↦ λ_j non-decreasing; coefficients ↦ λ_j Lipschitz
  with constant Σ|Δc_m|, Weyl), docs/PROOF.md. Measured 2026-11-11 (`bench/parameter_balls.py`): 200 transmons of
  the device regime with E_C, E_J ± 1 %, 6 levels, 5 inner points each: 0 of 1000 inner point intervals outside the
  box interval; a point with E_J 3 % above the box detected outside in 187 of 200; box width 2.1× the observed
  spread (median; max 5.5×: the Lipschitz bound is rigorous, not tight); 0.11 s per box. n_g as an interval: see below.
- `scqubits_adapter.guaranteed_from_scqubits`: from a `scqubits.Transmon` or `Fluxonium` object, the guaranteed
  intervals of its H and the verdict (`INSIDE` / `INSIDE_TOLERANCE` / `OUTSIDE` per level, tolerance 32·eps·‖H‖) on
  its own `eigenvals()` at its own cutoff; closed list of classes, read by name and attributes.
- The public API is exposed at the package level (`from qraft_ra import Rotor, guaranteed_levels, ...`, `__all__`).
- `examples/` (five scripts run by `tests/test_examples.py` in a fresh interpreter), `CITATION.cff`,
  `bench/compare_tools.py` (time per point against scqubits, scipy, numpy: the other tools are 37–340× faster on
  the inputs of the README table).

- `mathieu`: Mathieu characteristic values a_r(q), b_r(q) (r ≤ 200, any finite q, negative and large included) as
  guaranteed intervals on the four Fourier sectors (Jacobi matrices with (0,1) = √2·q, d_0 = 1 ± q), same proof as
  the rotor (Rayleigh–Ritz above, per-pair Young plus Gershgorin on the outer block below, Sylvester counts in Arb).
  Measured 2026-11-11: r = 0…12, q = −400…400 step 0.5 (40 025 values), median 0.38 ms per value, 40 019
  GUARANTEED at 1e-12 relative and 6 WIDE (valid, wider); scipy 1.17.1 and 1.18.1 give 52 values outside the
  intervals (identical lists; 30 of them equal another order ≤ 12; all 52 confirmed wrong by an independent
  tridiagonal reference at K = 400, which agrees with the intervals in 52 of 52); scipy 2.0.0.dev0+git20261108
  gives 0. scipy is about 100× faster (3.6 µs median) and gives no guarantee.
- `fluxonium`: H = 4E_C n² + (E_L/2)φ² − E_J cos(φ − 2π·flux) in the oscillator basis with the truncation closed by
  a per-site lower bound (Young on every coupling pair, DLMF 18.14.8 tails on the Laguerre couplings) and dense LDLᵀ
  counts in Arb. Measured 2026-11-11 against scqubits 4.3.1 `Fluxonium`: cutoff 110 inside the intervals in every
  level of 4 published parameter sets at flux ½ (`bench/fluxonium_devices.py`) and of 2 of them at flux 0, ¼, ½
  (`tests/test_fluxonium.py`), cutoff 6 outside in at least one (negative control); width
  5e-10 GHz, 0.4–6.5 s per device (N = 54…117). Published devices (parameters as printed, one-mode model): Zhang et
  al. 2021 f01 = 13.8816 MHz guaranteed vs 14 MHz measured; Moskalenko et al. 2022 qubit A f01 = 685.731 MHz vs
  688.224, f12 = 1831.204 MHz vs 1832 (shifts reported, not judged: two-mode fit, printed rounding).
- `matrix_elements`: guaranteed enclosures of ⟨v_i|n|v_j⟩, ⟨v_i|cos mφ|v_j⟩, ⟨v_i|sin mφ|v_j⟩ for the charge-basis
  rotor: the float eigenvectors of H_N are approximations whose distance from the true eigenvectors is bounded by
  the exact residual against the FULL operator over the gap given by the guaranteed enclosures of the neighbouring
  levels (spectral theorem), with ‖n v_j‖ bounded through ⟨(n − n_g)²⟩ ≤ (λ_j + ‖V‖)/4E_C (docs/PROOF.md). Measured
  2026-11-11 (`bench/matrix_elements.py`, `tests/test_matrix_elements.py`): see README "Measurements".
- `parameter_balls`: n_g as an interval too (band functions of Hill's equation monotone on [0, ½]: the extremes
  are at the ends and at the band edges 0, ½ inside the interval; Reed–Simon XIII.89, Eastham 1973 Thm 2.3.1,
  DLMF 28.12(i)); checked against a fine sampling of n_g at E_J/E_C = 5 and a point outside (tests).
- Multiport: `python_rotor` (the reference tridiagonal in pure Python, Sturm bisection) and pure-Python control
  ports, so that every engine, WebAssembly included, runs the full S1–S7 (measured: 16 of 17 tests of
  `TestSandbox_wasm` run, the only skip is the scqubits/diatomic-py solver test); `python_rotor` agrees with
  numpy's `eigvalsh` within 1e-11 GHz.
- `python -m qraft_ra.reproduce`: re-measures the numerical claims of the README offline (one [PASS]/[FAIL] line per
  claim with the measured and the published value; fast set 22 s, `--full` adds the 40 025-value Mathieu grid and the
  200 wide-range transmons, 108 s); `--sabotage` makes the Mathieu solver return the next order of the sector as a positive control (at least one
  FAIL; the first version swapped a_r with b_r, which left r = 0 and every odd r unchanged: 0 FAIL in the fast set);
  `--readme` checks that every published value appears verbatim in README.md and is run by `check_tree.py` (a number
  edited by hand fails the tree check: positive control included); `--hash` prints the sha256 of a fixed set of
  exact enclosures: identical on Python 3.11 (numpy 2.4.6, scipy 1.17.1), 3.12, 3.13 and 3.14 (numpy 2.5.4, scipy
  1.18.1) on Linux x86-64 (c3ae60dd…); the CI jobs print it on every platform.
- Benches inside the tree for every row of the README tables: `bench/readme_numbers.py`, `mathieu_vs_scipy.py` (also
  the fine grid of qiskit-metal #1252), `gregory2016.py` (the 16 RbCs lines), `real_transmons.py` (the 6 transmons of
  arXiv:2407.17407), `duffing_adapter_sphere.py`,
  `fluxonium_devices.py`, `parameter_balls.py`, `matrix_elements.py`, `check_200.py`, `multiport_batch.py`,
  `compare_tools.py`. Re-measured here with the absolute criterion (error > 1e-6 GHz): scqubits at ncut 30 wrong in 70
  of the 200 wide-range transmons (smallest E_J/E_C 5542), all 70 flagged by the adapter, 0 false alarms, 0 missed
  (the 65 at ≥ 7744 of the README of 0.2.0 use the relative criterion of `readme_numbers.py`: both stated).
- `check(scqubits_obj, tolerance=…)` (= `guaranteed_from_scqubits`) and `assert_inside(levels, intervals, tolerance)`
  for other people's regression tests (`examples/regression_assert.py`: fails on scipy's sparse `eigsh` from 1.15.0
  on, which omits the exact zero eigenvalue of 4E_C n², and passes on the dense solver).
- `tests/test_cos4phi_origin.py`: H = h2·n² + c2·cos 4φ of the author's earlier work with a fixed cut Nb = 40: inside
  for three parameter sets, OFF by 1.4e-11 for (h2, c2) = (0.25, 60) (first cut inside between 41 and 60); Nb = 2
  outside for all (positive control).
- Multiport batches (`run_ports`, contract "qraft-port/0.3" §8): 100 requests in one sandbox process: 0.012 s
  (numpy_rotor) and 0.023 s (python_rotor) per case against 1.0–1.1 s per single run (podman), outputs equal to the
  single runs; `site_packages_of("scqubits")` finds the folder to mount (no placeholder in the examples).
- Tests are discoverable (`python -m unittest discover -s tests`); CITATION.cff; examples/ run by the tests.
- Not done: nothing of A–D is deferred. The deprecated Italian aliases stay (cost: one module and one test).

### Other

- `guaranteed_intervals.Intervals.contains(j, value)` (was `valore`); `rotor_spectrum.spectrum` checks that its
  first argument is a `Rotor`.
- `check_tree.py`: unchanged rules; `FILE_LIST.tsv` lists the new files.

### Fixed before release (adversarial review of 0.3.0, 2026-11-12)

Each code fix has a test that fails on the tree before it and passes after it, except the Windows branch of the
root refusal (its test runs in the Windows CI job only); the `--sabotage` change is run by the Linux CI job
(`python -m qraft_ra.reproduce --sabotage`); the CI and text items have no test.

- Isolation: a user-owned `podman` placed first on PATH was chosen by `engine="auto"` and ran the port on the host
  (network reached) while the result named a container: the probe is measured from inside the engine, so a binary
  the user can replace can forge it. Every engine binary on POSIX must now be owned by root and not writable by
  group or others, as `bwrap` already had to be; a user-installed binary is used only if its exact real path is
  listed in `QRAFT_TRUSTED_ENGINES`. `sandbox-exec` and `appcontainer` refuse a readable or granted folder that is a
  user's home, contains one, or is a root (any drive or share). Not covered (declared in README and docs/PORT_CONTRACT.md): a container
  runtime set in the user's own podman/docker configuration, the binary owner on Windows, the AppContainer grants
  that stay on the folders after the run.
- Isolation, second pass: a `QRAFT_TRUSTED_ENGINES` entry vouches only if it is an absolute real path (a relative
  entry was resolved from the current folder); the engine is executed by its real path (a symlink on PATH retargeted
  after the cached probe ran an unlisted binary on the host, network reached, `Output.sandbox` naming wasm); a
  root-owned binary in a folder that is not root-owned or is writable by group or others is refused (a hard link
  with `fs.protected_hardlinks = 0`); a vouched binary is named in `Output.sandbox`.
- Fluxonium: E_C = 1e17 or 2^63 made the oscillator basis grow without a cap (host out of memory); refused when
  √(2E_C/E_L) exceeds `N_LIMIT`.
- Parameter boxes: an n_g beyond 2^53 made the candidate loop endless; the candidates are now computed in exact
  arithmetic. The Lipschitz radius used the exact half-width around a float midpoint that can be rounded (one end
  uncovered by up to 8.9e-16 in 49 914 of 100 000 random boxes; no value was observed outside, the computation
  margins were larger): the radius is now the larger exact distance from the float midpoint to either end.
- Extreme inputs (1e308, 5e-324, q ≥ 1e155) in `guaranteed_levels`, `mathieu_a/b`, `Fluxonium` raised
  OverflowError; they are now refused with `OutOfDomain` and the reason. `assert_inside` with 10**400 now fails with
  its AssertionError and the reason instead of OverflowError; with a unit that is not a string ([1], {}) it refuses
  with `OutOfDomain` instead of TypeError.
- `reproduce --sabotage` gave 0 FAIL in the fast set (swapping a_r with b_r leaves r = 0 and every odd r unchanged);
  it now makes the Mathieu solver return the next order of the sector: 2 FAIL.
- CI: the `unittest discover` step could not fail (`> /dev/null && echo OK`); it now exits with the suite's status.
- Text: the port contract is "qraft-port/0.3" (README and the `multiport` docstring said 0.2); the number of example
  scripts (five) and the fluxonium sets and flux points were corrected.

### Fixed after the first CI run on macOS, Windows and ARM (2026-11-12)

The first run of the branch on GitHub (run 43152525407): 11 of 16 jobs green; Linux ARM64 and free-threaded 3.14t
green; 5 red. Product defects, each with a test that fails on the tree before it:

- `read_output` followed a symlink `output.json` on Windows, where `O_NOFOLLOW` does not exist: the link (and a
  reparse point) is now refused from `lstat`, and the opened file must be the one `lstat` saw.
- docker: the runner's RLIMIT_NPROC of 16 counted every process of the host user (rootful docker, host user
  namespace): "can't start new thread" in the scqubits port on Linux 3.10. docker now caps the container with
  `--pids-limit 16` (the same cap of 16, now counted only inside the container) and the runner leaves RLIMIT_NPROC
  to podman and bwrap.
- Deadlines and elapsed times use `time.perf_counter()`: on Windows with Python 3.12 a deadline of 1e-9 s did not
  raise DeadlineExceeded in `mathieu_a` and `guaranteed_sphere_levels` with the clocks used before (`time.time`,
  `time.monotonic`), whose resolution there is coarse; Windows with Python 3.14 passed.

- macOS (python.org framework build, macOS 26): the interpreter in bin/ is a stub that starts
  `Resources/Python.app/Contents/MacOS/Python` with posix_spawn, which the Seatbelt profile did not allow: the
  sandbox-exec probe failed. That binary is now allowed too (only when it exists next to the interpreter).
- Windows: CreateProcessW in the AppContainer failed with error 203 (ERROR_ENVVAR_NOT_FOUND) on the GitHub runner;
  the environment block is now sorted by name, the error names the variables passed (names only), and the block
  carries the system variables a process needs (SYSTEMDRIVE, WINDIR, COMSPEC, PATHEXT) and LOCALAPPDATA/APPDATA
  pointed at the scratch folder. Sorting alone did not fix it (CI run 43156458790); with the system variables the
  error 203 is gone and the AppContainer probe passes (CI run 43157816967).
- macOS: the sandbox-exec probe asked `os.path.isdir(home)`, which needs only file metadata, allowed everywhere by
  the profile: a false "does not isolate". It now tries to list the home (file-read-data, denied there).
- CI: the check that each engine's S1 test ran matched only the test name format of Python 3.11+; on 3.10 it failed
  although the test had passed. It now matches both formats and still refuses a skipped test.

After run 43157816967 (12 of 16 jobs green; macOS and Windows red in the S1–S7 tests of their engine):

- macOS refuses RLIMIT_AS ("ValueError: current limit exceeds maximum limit"), and the runner set all its rlimits in
  one block: every sandbox-exec run, and the runner outside the sandbox, ended in that error. Each rlimit is now set
  on its own, never above a lower hard limit already in force; a refused limit stops the run with the limit named
  unless the engine enforces it from the host (`QRAFT_HOST_LIMITS`, closed list). sandbox-exec enforces memory from
  the host: a watchdog samples the resident memory of the process group every 20 ms (libproc) and checks the peak
  after the exit (wait4); over `mem_mib` the run is killed and the output is ERROR "memory: … (host watchdog)".
- sandbox-exec and appcontainer have no tmpfs, and Windows has no file-size rlimit: the same watchdog caps one file at
  64 MiB and the writable places at 256 MiB in all, the limits of the other engines (sampled, declared in
  docs/PORT_CONTRACT.md §6); the whole process group (macOS) or job (Windows) is killed at the end of a run.
- Windows: the output file was granted `M`, which includes DELETE: the port removed it and `run_port` raised
  FileNotFoundError. The grant is now `(R,W)`, and a missing output file is INVALID "no output", never an exception.
  sandbox-exec allowed `file-write*` on the output file (unlink and create too): now `file-write-data` only.
- Windows: the AppContainer cannot open the NUL device (scqubits → dill: "Permission denied: 'nul'"); the runner points
  `os.devnull` at an empty file in the scratch folder, only when NUL cannot be opened.
- The `test_write` port reported the real home "visible" from `os.path.isdir`, which Seatbelt allows everywhere
  (metadata); it now lists the folder, as the probe does.

Test fixes for these platforms: the runner outside the sandbox (positive controls) gets the Windows system variables
(WinError 10106 without SYSTEMROOT) and `QRAFT_HOST_LIMITS=memory`; the engine-missing controls make appcontainer
missing through its Windows API, as it has no executable; the peak-memory check of the stdout test reads
PeakWorkingSetSize on Windows and bytes (not KiB) on macOS; the disk controls use the runner's `$WORK` and `$TMP` on
the engines that run on host paths.

Measured by the CI (2026-11-12): macOS refuses RLIMIT_AS, RLIMIT_DATA and RLIMIT_RSS alike ("current limit exceeds
maximum limit"; RLIMIT_FSIZE, RLIMIT_CPU and RLIMIT_NPROC are accepted): the host watchdog is the only memory cap
there. With these fixes both macOS jobs are green and every sandbox-exec S1–S7 test runs (run 43161023860; the
scqubits test is skipped there, scqubits is not installed on macOS). Inside the AppContainer `open('nul')` fails in
`rb`, `wb` and `r+b` (PermissionError), the AppContainer folder is found, and TEMP/TMP/LOCALAPPDATA are rewritten
by Windows to folders that do not exist (run 43163743554). Then, from run 43163743554:

- Windows, Python 3.12: the 2 s CPU control ended at the 7 s wall-clock timeout: Windows checks the Job's CPU-time
  limit only periodically. The host watchdog now reads the Job's user time and stops the run over `seconds`.
- Windows: `python -m qraft_ra.reproduce` stopped with UnicodeEncodeError printing "≤" to the cp1252 console; a
  character the console cannot encode is now printed as a backslash escape.

Earlier, after run 43162320603 (Windows: `$TMP` gave FileNotFoundError inside the AppContainer), the test ports'
`$TMP` placeholder follows `tempfile.gettempdir()` (where a solver's temporary files go) and the disk error names the
folder; the Seatbelt-profile test built POSIX paths that `realpath` changes on Windows (a test defect).

Result: run 43165166338 on commit d93eda1, 16 of 16 jobs green; every S1–S7 test of sandbox-exec (macOS 3.12, 3.14)
and appcontainer (Windows 3.12, 3.14) ran and passed (one skip each for a solver not installed there). The CI also
showed that the determinism hash differs between machines (README, "Determinism"); not investigated in this entry.

Test and CI fixes: tests that need `pwd`, a `sh` fake interpreter or `SIGALRM` are POSIX-only or use a thread with a
time limit; the examples get a fresh `USERPROFILE` on Windows (qutip needs a home); scqubits 4.3.1 is not installed
on macOS, where it requires scipy ≤ 1.13.1 (its scqubits tests are skipped there with the reason).

### Determinism of the published ends (2026-11-12)

Defect, measured on 2026-11-12 (commit f9867d8, Python 3.11.2–3.14.8, Linux x86-64 with AVX2): `reproduce --hash`
gave c3ae60dd… with `OPENBLAS_CORETYPE` Haswell or unset, adfa1368… with Prescott and b99bed48… with Nehalem; in CI
the Linux x86-64 runners alternated between two values and ARM64, macOS and Windows each gave another. Cause: the
float estimates that choose where the exact counts are taken came from numpy/scipy (`eigvalsh`, `eig_banded`,
`eigvalsh_tridiagonal`), whose last bits depend on the BLAS/LAPACK kernel, and the ends of the published intervals
are built from those points (fluxonium, sphere, molecule and Mathieu centre the trial interval on the estimate; the
matrix elements use the float eigenvectors). The intervals were correct on every machine, but not the same. A seeded
probe of 309 inputs over all the guaranteed modules (`gen.py` in the author's report) gave different strings under
Prescott in 29 of them on the code before (8 of 8 fluxonium, 6 of 6 molecule, 15 of 15 matrix elements); the rotor,
sphere and Mathieu cases of the probe happened to agree.

- New `qraft_ra._deterministic`: eigenvalue estimates by bisection on the Sturm count (tridiagonal), Householder then
  the same bisection (dense), bisection on the LDLᵀ inertia (band), and eigenvectors by inverse iteration with banded
  partial pivoting from a fixed start vector (sign fixed by the largest entry), using only Python float operations
  whose result IEEE 754 fixes (+ − × ÷, `math.sqrt`, `math.fsum`, `ldexp`/`frexp`, `float()` of an int or a Fraction)
  in a fixed order. No BLAS/LAPACK, no libm transcendental, no builtin `sum()` of floats (changed in Python 3.12).
- Every guaranteed module uses it: `guaranteed_intervals` (estimates and the first-order filter of the basis growth),
  `spherical_rotor`, `hyperfine_molecule`, `mathieu`, `fluxonium`, `matrix_elements`. The other float decisions use
  the same operations: the initial cut of the rotor and the fluxonium (`** 0.25` → two `math.sqrt`), `sum` of floats
  → `math.fsum`; `Fluxonium.phi_zpf` is now √√(2E_C/E_L) by `math.sqrt` (the last bit may differ from before).
- The bisection runs to adjacent floats: as a side effect the Mathieu grid r ≤ 12, |q| ≤ 400 step 0.5 has 0 WIDE
  values of 40 025 (6 before).
- `reproduce --hash` covers three more enclosures (a rotor with cos φ and cos 2φ, its ⟨0|cos φ|1⟩, an RbCs hyperfine
  sector); `reproduce.determinism_parts()` returns them by name.
- `tests/test_determinism.py`: the strings of every hash entry (python-flint 0.9.0; another version is skipped with
  the reason), the fluxonium ends spelled out, the same guaranteed intervals in fresh interpreters under
  `OPENBLAS_CORETYPE` unset, Prescott and Nehalem (where numpy runs on run-time-dispatched OpenBLAS on x86-64;
  skipped elsewhere with the reason), no numpy/scipy eigen-solver called by any guaranteed entry point, the
  estimators against numpy on seeded matrices, the zero-pivot and eigenvector-sign conventions, the overflow refusal,
  φ_zpf and the fluxonium cuts (9 tests). On the code before, the cross-kernel test and the fluxonium test fail by
  assertion (6 more by ImportError of the new names, 1 passes); with numpy's `eigvalsh` put back into the fluxonium
  module (positive control) 4 of 9 fail, under `OPENBLAS_CORETYPE` unset and Prescott alike.
- Mutation testing of the new and changed lines (36 hand mutants, test file of the mutated module first, on a green
  tree): 31 killed. Alive: 3 equivalent, declared — `q <= 0` for the first Sturm pivot (a zero pivot is already
  replaced by −pivmin), a stop tolerance 1e6× larger (still ≈ 1e-302·‖A‖), the scaling exponent + 1 (scaling by a
  power of two commutes with IEEE rounding without under/overflow); and 2 on an overflow re-check that was dead code
  (`math.ldexp` already raises OverflowError), now removed. The first round left 8 alive; the tests for the
  zero-pivot convention, the eigenvector sign, φ_zpf and the fluxonium cut were added and killed 4 of them.
- The CI runs `test_determinism` in every job and the free-threaded job prints the hash too. Run 43177561844 on
  22a5b37: 16 of 16 jobs green, all 16 print `4d7d61cd…` (Linux x86-64, ARM64, macOS, Windows, 3.14t); the
  cross-kernel test ran on the 13 x86-64 jobs and was skipped with its reason on ARM64 and macOS.
- Measured after the change (2026-11-12): the same hash on Python 3.11.2, 3.12.15, 3.13.15, 3.14.8 × `OPENBLAS_CORETYPE`
  unset/Haswell/Prescott/Nehalem (16 of 16 runs); the probe of 309 inputs identical under the three kernels and on
  Python 3.12 and 3.14. Times (README): a Mathieu value 0.38 → 0.50 ms median, the real-transmon bench 5.6 → 8.7 s
  (the cos 8φ fits use the band bisection), the sphere 0.36 → 0.51 ms; the other benches changed by −9 % to +11 %.

Also: `bench/readme_numbers.py` stopped with AssertionError on the state OK_FLOAT_FLOOR (added in 0.3.0) and counted
it as a flag; it now accepts it as an OK state. The watchdog test of the multiport expected the exact size the host
watchdog samples during a 6 MiB write ("6 MiB"); under load it saw 5 MiB: the test now accepts 4–6 MiB.

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
  cannot start, so in CI no test is skipped for lack of the sandbox (the CeNTREX and diatomic-py port tests are
  skipped because those packages are not installed there).
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
