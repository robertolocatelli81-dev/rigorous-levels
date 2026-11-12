# Port contract "qraft-port/0.3" and the isolation engines

Specification of the multiport (`qraft_ra.multiport`, runner `qraft_ra.port_runner`). Written on 2026-11-11
(21:05 CET, system clock; §8 batches added 22:10 CET) before the code of 0.3.0; it supersedes the unpublished contract
"qraft-porta/0.1" of 0.2.0 (same structure, Italian keys) and "qraft-port/0.2" (same as 0.3 without §8), which are no
longer accepted by the runner or the validator: a document carrying another contract string is INVALID with the
reason `contract '…' ≠ qraft-port/0.3`.

## 1. Request (host → port), file `request.json`

JSON object with EXACTLY these keys (an unknown or missing key is refused on the host, before anything runs):

| key | type | meaning |
|---|---|---|
| `contract` | string | `"qraft-port/0.3"` |
| `port` | string | one of the closed list `PORTS` (§3) |
| `model` | object | `type` plus the keys of that type (§2); nothing else |
| `levels` | integer 1…10000 | number of levels requested |
| `truncation` | object | string keys, values int / finite float / string; for the ports of §3.2 the exact keys listed there, integers ≥ 1 |
| `unit` | string | `"GHz"`, `"MHz"` or `"Hz"` |
| `limits` | object | `{"seconds": 1…3600, "mem_mib": 16…65536}` (rlimits set by the runner inside the sandbox) |
| `site_packages` | list of strings | existing folders whose real path ends in `site-packages` or `dist-packages`, mounted read-only |

## 2. Models (closed)

| `type` | keys | notes |
|---|---|---|
| `cos_rotor` | `E_C`, `E_J`, `n_g` (finite reals) | H = 4E_C(n − n_g)² − E_J cos φ |
| `sigma_molecule` | `two_I1`, `two_I2`, `two_MF` (integers), `B`, `D`, `c1`, `c2`, `c3`, `c4`, `eQq1`, `eQq2`, `z_N`, `z1`, `z2`, `dE` (finite reals, Hz) | the H of `qraft_ra.hyperfine_molecule`; the sign of c3 is the paper's one |
| `tlf_centrex` | `E_Vcm`, `B_G` (finite reals), `Jmax` (0…20), `two_MF` (even, |M_F| ≤ Jmax + 1) | constants of centrex-tlf |

## 3. Ports (closed list)

3.1 Solvers: `numpy_rotor` (reference, `truncation.ncut`), `python_rotor` (the same tridiagonal in pure Python by
Sturm bisection, `truncation.ncut`: the reference that runs without numpy, e.g. under WASI), `scqubits_transmon` (`ncut`), `diatomic_py` (`N_max`),
`metal_hcpb` (`nlevels`), `metal_mathieu` (no truncation), `sqcircuit_transmon` (`ncut`), `pyepr_fock`
(`cos_trunc`, `fock_trunc`), `centrex_tlf` (no truncation: `Jmax` is in the model).

3.2 For `metal_hcpb`, `metal_mathieu`, `sqcircuit_transmon`, `pyepr_fock`, `centrex_tlf` the truncation keys are
EXACTLY the ones listed and the model type is fixed (`cos_rotor`, `cos_rotor`, `cos_rotor`, `cos_rotor`,
`tlf_centrex`). An exit code ≠ 0 with state `OK` makes the output INVALID.

3.3 Positive controls (never solvers; pure Python, so every engine including wasm runs them): `test_wrong`
(deliberately wrong levels), `test_network` (`tcp_port`),
`test_write` (`path`, `real_home`), `test_loop`, `test_memory` (`mib`), `test_dirty_output` (adds an unknown key),
`test_hostile` (`mode` ∈ environment, symlink, disk, write, fork, cpu, stdout, ok_then_crash, with their keys).

## 4. Output (port → host), file `output.json`

JSON object with EXACTLY these keys: `contract` (= `"qraft-port/0.3"`), `port` (= the one requested),
`solver_version` (string), `levels` (list; with state `OK` exactly `levels` finite real numbers, in `unit`), `unit`
(GHz/MHz/Hz), `state` (`"OK"` or `"ERROR"`), `reason` (string), `seconds` (finite number).
The host reads it as a regular file (no symlink, no FIFO), at most 1 MiB, strict JSON (no NaN/Infinity, no duplicate
key, nesting ≤ 32 levels counted before the parser). Anything else = state `INVALID` on the host with the reason.

## 5. Verdicts (closed list)

`compare(intervals, intervals_unit, output, tolerance=0)`: per level `INSIDE` (inside the guaranteed interval, exact
arithmetic), `INSIDE_TOLERANCE` (outside by at most the declared tolerance, with the distance), `OUTSIDE` (with the
distance); overall `OUTSIDE` if any level is, else `INSIDE_TOLERANCE` if any level is, else `INSIDE`;
`NOT_COMPARABLE` (with the reason) when the output is not `OK` or the number of levels differs.

## 6. Isolation engines (closed list `ENGINES`) and what each one guarantees

6.0 Automatic choice (`engine="auto"`, the default): the engines are tried in the declared order of strength
`ENGINE_ORDER = (podman, docker, bwrap, sandbox-exec, appcontainer, wasm)` and the first whose fail-closed probe
passes is used; the engine used is named in `Output.sandbox`; if none passes, `SandboxMissing` carries every reason.
The order: containers first (network namespace, read-only root, capabilities dropped, seccomp default profile of the
runtime, a separate user), then the native per-platform sandboxes (bwrap: user namespaces without seccomp;
sandbox-exec: deprecated by its own man page; appcontainer: file access by explicit grants), then WebAssembly last
only because its interpreter has no numpy today (it is the strongest isolation by construction: no system calls
besides the pre-opened folders). An explicit `engine=` never falls back to another one.

Every engine runs `python -I -S -B /work/port_runner.py /work` with `/work` read-only, `/work/output.json` the only
writable file, HOME pointing to a folder that does not exist, a minimal environment, and the runner's own rlimits
(CPU = seconds, address space = mem_mib, file size 64 MiB, 16 processes). The same positive controls S1–S7 are
required of every engine (tests `test_multiport.py`, parametrized over the engines available on the machine):

| control | what must happen inside, and the positive control outside |
|---|---|
| S1 network | a TCP connection to a listening socket of the host fails; outside the sandbox it succeeds |
| S2 writes and home | writes outside `/work/output.json` fail; the user's real home is not visible; outside they succeed |
| S3 time and memory | an endless loop ends with `INVALID: timeout`; allocating more than `mem_mib` gives `MemoryError` |
| S4 environment | no variable of the host session is visible, not even in `/proc/*/environ` |
| S5 fail-closed | engine missing, or not isolating, or (containers) image absent locally → `SandboxMissing`; no fallback |
| S6 dirty output | an unknown key, NaN, wrong length, non-JSON, symlinked or oversized output → `INVALID` with the reason |
| S7 wrong solver | `test_wrong` falls `OUTSIDE`; the reference solver falls `INSIDE` or `INSIDE_TOLERANCE` |

6.1 `bwrap` (Linux): `--unshare-all --die-with-parent --new-session --clearenv`; read-only binds of /usr, /lib,
/lib64, /bin, /etc, the declared site-packages and the pieces of an interpreter outside /usr (executable, stdlib,
libpython; never the prefix folder, never the user's home); tmpfs (256 MiB each) on /tmp, /home, /dev/shm; a
root-owned, non-writable `bwrap` binary is required (since the review of 0.3.0 the same rule holds on POSIX for
`podman`, `docker`, `sandbox-exec` and `wasmtime`: the probe is measured from inside the engine, so a binary the user
can replace could forge it; the binary is executed by its real path, and every folder above a root-owned binary must
be root-owned and not writable by group or others; a user-installed binary is accepted only if its exact real path is
listed in `QRAFT_TRUSTED_ENGINES` (relative, symlink or non-normalized entries vouch for nothing), never if group or
others can write it, and is then named in `Output.sandbox`). Not a VM: user namespaces, no seccomp.

6.2 `podman`, `docker` (Linux; macOS/Windows through their Linux container runtimes): `run --rm --network none
--read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev,size=256M` as a non-root
user (`--user uid:gid`, podman rootless adds `--userns=keep-id`), the declared site-packages and `/work` mounted
read-only, the image `python:<major>.<minor>-slim` of the interpreter whose site-packages are mounted (or the one
declared by the caller) taken ONLY from the local store: it is never pulled. Before the first run (per process and
image) a PROBE in the same image checks: only the `lo` interface, uid ≠ 0, root file system not writable; a probe
that fails or disagrees = `SandboxMissing`. Timeout: podman `--timeout` plus a host-side kill by container name
(docker: host-side kill only). NOT relied upon: `--memory`, `--cpus` (ignored with a warning on cgroups v1 rootless
podman, measured 2026-11-11 on podman 4.3.1): memory and CPU time are limited by the runner's rlimits inside the
container, as with bwrap. Processes: podman (its own user namespace) uses the runner's RLIMIT_NPROC of 16; docker
passes `--pids-limit 16` and `QRAFT_NPROC=cgroup`, and the runner does not set RLIMIT_NPROC there, because rootful
docker runs the port with the host uid in the host user namespace, where RLIMIT_NPROC counts every process and thread
of that user on the host (first CI run, 2026-11-12: "can't start new thread" on a GitHub Linux runner).

6.3 `sandbox-exec` (macOS): deny-default Seatbelt profile; `(allow file-read*)` then `(deny file-read* (subpath
<home>))` for each of the user's homes, then the declared pieces inside them (interpreter prefix, site-packages, work
folder) allowed again; `(allow file-write*)` only on the output file and a scratch folder; `(deny network*)`;
`process-exec` of the interpreter only. The probe checks network closed, root not writable, home not listable. The
man page marks `sandbox-exec` DEPRECATED (measured in CI on the runner: `man -w sandbox-exec`, a deny-default
profile started). Memory/CPU limits: the runner's rlimits (RLIMIT_AS effectiveness on macOS is measured by the S3
test in CI, not assumed).

6.4 `appcontainer` (Windows): AppContainer profile `qraft-ra-multiport` (CreateAppContainerProfile, SID reused if it
exists); read-execute grants (`icacls … /grant *<SID>:(OI)(CI)RX`) on the interpreter prefix, the site-packages and
the work folder, modify on the output file and a scratch folder; the runner started with
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES and no capability (no internetClient: no network), assigned to a Job
Object with process-memory, active-process (16) and CPU-time limits, killed on timeout (TerminateJobObject).
The environment is a closed list: SYSTEMROOT, WINDIR, SYSTEMDRIVE, COMSPEC, PATHEXT copied, PATH = SYSTEMROOT,
USERPROFILE, LOCALAPPDATA, APPDATA, HOME, TEMP, TMP inside the scratch folder, plus the runner's own variables.
The probe checks network closed, %SystemRoot% not writable, home not listable. The read-execute grants are not
removed after the run: they stay on those folders for the AppContainer SID `qraft-ra-multiport`. Folders that are a
user's home, contain one, or are a root (any drive or share) are refused. The owner of the engine is not checked on Windows. Not
measured locally (CI job).

6.5 `wasm` (everywhere): `wasmtime run -W max-memory-size=1 GiB -W timeout=<s> --dir <python.wasm folder>::/
--dir <work>::/work --dir <output folder>::/out` with a CPython built for WASI (`QRAFT_PYTHON_WASM`, required
non-writable: wasmtime pre-opens read-write); no site-packages (native wheels cannot load; today no numpy exists
for WASI, so every solver port reports `ERROR: No module named 'numpy'`, declared), the work folder made
non-writable for the run, no sockets, no `/tmp`, no rlimits (the engine's own limits apply). Measured 2026-11-11:
wasmtime 50.0.1 + CPython 3.15.2 (brettcannon/cpython-wasi-build): S1, S2, S4, S5, the hostile controls and the
dirty-output checks pass; S3-memory, S6, S7 need numpy and are skipped with that reason.

6.6 What no engine claims: protection against kernel exploits, side channels, or a compromised engine binary; the
physics of the other solver.

## 8. Batches (`run_ports`)

Several requests can share one sandbox process (the import of the solver, seconds per run, is paid once): the host
writes `requests.json` = a JSON list of request objects (§1, each complete, same `site_packages`), the runner answers
with `outputs.json` = a JSON list of output objects (§4) in the same order and of the same length (a shorter or
longer list, or a non-list, makes every output of the batch INVALID). The rlimits of the runner are the maxima of the
`limits` of the batch; the host timeout is the sum of the `seconds` plus 5. Each output is validated against its own
request (§4); the port of request i must be the port of output i. A batch of one request is equivalent to §1–§4
with `request.json`/`output.json`. Measured 2026-11-11 (`bench/multiport_batch.py`, bwrap): see README.

## 7. Versioning

A change of keys, states, ports' truncation keys or model keys requires a new contract string, written here first.
Deprecated aliases in Python (`qraft_ra.multiporta`) translate the 0.2.0 Italian keyword arguments of the Python API,
not the JSON files: a 0.1 request file is refused.
