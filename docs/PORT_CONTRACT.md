# Port contract "rigorous-levels-port/0.3" and the isolation engines

Specification of the multiport (`rigorous_levels.multiport`, runner `rigorous_levels.port_runner`). Written on 2026-11-11
(21:05 CET, system clock; §8 batches added 22:10 CET) before the code of 0.3.0; it supersedes the unpublished contracts
of the earlier private versions (0.1 of 0.2.0: same structure, Italian keys; 0.2: same as 0.3 without §8), which are no
longer accepted by the runner or the validator: a document carrying another contract string is INVALID with the
reason `contract '…' ≠ rigorous-levels-port/0.3`.

## 1. Request (host → port), file `request.json`

JSON object with EXACTLY these keys (an unknown or missing key is refused on the host, before anything runs):

| key | type | meaning |
|---|---|---|
| `contract` | string | `"rigorous-levels-port/0.3"` |
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
| `sigma_molecule` | `two_I1`, `two_I2`, `two_MF` (integers), `B`, `D`, `c1`, `c2`, `c3`, `c4`, `eQq1`, `eQq2`, `z_N`, `z1`, `z2`, `dE` (finite reals, Hz) | the H of `rigorous_levels.hyperfine_molecule`; the sign of c3 is the paper's one |
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

JSON object with EXACTLY these keys: `contract` (= `"rigorous-levels-port/0.3"`), `port` (= the one requested),
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
(CPU = seconds, address space = mem_mib, file size 64 MiB, 16 processes). Each rlimit is set on its own, never above
a lower hard limit already in force; a limit the platform refuses stops the run with the limit named, unless the
engine enforces that limit from the host and says so in `RIGOROUS_LEVELS_HOST_LIMITS` (closed list: cpu, memory, file_size,
processes; an unknown name is refused). Where an engine has no tmpfs or no address-space rlimit (sandbox-exec,
appcontainer) a HOST WATCHDOG samples the run every 20 ms and once more after the exit: one file over 64 MiB, or the
writable places over 256 MiB in all (the size of each tmpfs of bwrap), or (sandbox-exec) the resident memory of the
process group over `mem_mib`, kill the run, and the output is `ERROR` with the reason ending in "(host watchdog)":
what the port wrote is discarded. Sampled, not a hard cap: a port can write or allocate what fits in one interval
before it is killed (the resident peak after the exit, from wait4, is still checked); files unlinked while open are
not counted. The same positive controls S1–S7 are
required of every engine (tests `test_multiport.py`, parametrized over the engines available on the machine):

| control | what must happen inside, and the positive control outside |
|---|---|
| S1 network | a TCP connection to a listening socket of the host fails; outside the sandbox it succeeds |
| S2 writes and home | writes outside `/work/output.json` fail; the user's real home is not visible; outside they succeed |
| S3 time and memory | an endless loop ends with `INVALID: timeout`; allocating more than `mem_mib` gives `MemoryError` (sandbox-exec: `ERROR`, "memory: … over the mem_mib cap … (host watchdog)") |
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
listed in `RIGOROUS_LEVELS_TRUSTED_ENGINES` (relative, symlink or non-normalized entries vouch for nothing), never if group or
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
passes `--pids-limit 16` and `RIGOROUS_LEVELS_NPROC=cgroup`, and the runner does not set RLIMIT_NPROC there, because rootful
docker runs the port with the host uid in the host user namespace, where RLIMIT_NPROC counts every process and thread
of that user on the host (first CI run, 2026-11-12: "can't start new thread" on a GitHub Linux runner).

6.3 `sandbox-exec` (macOS): deny-default Seatbelt profile; `(allow file-read*)` then `(deny file-read* (subpath
<home>))` for each of the user's homes, then the declared pieces inside them (interpreter prefix, site-packages, work
folder) allowed again; `(allow file-write*)` only on the output file and a scratch folder; `(deny network*)`;
`process-exec` of the interpreter only; the output file allows `file-write-data` only (no unlink, no create: a link
cannot take its place). File metadata is readable everywhere (existence of a file in the home can be tested, its
content and the listing cannot). The probe checks network closed, root not writable, home not listable, and that the
memory watchdog reads this process (libproc `proc_pid_rusage`). The man page marks `sandbox-exec` DEPRECATED
(measured in CI on the runner: `man -w sandbox-exec`, a deny-default profile started). Limits: CPU, file size and
processes are the runner's rlimits; macOS refuses RLIMIT_AS ("current limit exceeds maximum limit", CI 2026-11-12),
so the memory cap is the host watchdog (`RIGOROUS_LEVELS_HOST_LIMITS=memory`: max of resident size and physical footprint of
the process group), and the scratch folder (on disk, not a tmpfs) is capped by the watchdog. The run is a new process
group, killed whole at the end. A child that leaves the group (`setsid`) is neither sampled nor killed by the watchdog:
measured on Linux with the same function (`run_watched`, 2026-11-12), such a child kept 311 MiB resident after the run
returned with no reason. On macOS a child needs `fork`, and the runner's RLIMIT_NPROC = 16 counts every process of the
user; whether a fork succeeds there is not measured.

6.4 `appcontainer` (Windows): AppContainer profile `rigorous-levels-multiport` (CreateAppContainerProfile, SID reused if it
exists); read-execute grants (`icacls … /grant *<SID>:(OI)(CI)RX`) on the interpreter prefix, the site-packages and
the work folder, modify on the output file and a scratch folder; the runner started with
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES and no capability (no internetClient: no network), assigned to a Job
Object with process-memory, active-process (16) and CPU-time limits, killed on timeout (TerminateJobObject).
The output file is granted `(R,W)` (no DELETE: with `M` the port removed it). Windows has no file-size rlimit and the
Job Object no disk limit: the host watchdog caps the scratch folder, the output file and the AppContainer's own
profile folder (`GetAppContainerFolderPath`, writable by the container and kept between runs: only its growth during
the run is counted). Windows checks the Job's CPU-time limit only periodically (CI 2026-11-12, Python 3.12: a 2 s
limit was not applied within 7 s), so the watchdog also reads the Job's user time (QueryInformationJobObject) and
stops the run over `seconds` ("cpu: … (host watchdog)"). Windows rewrites TEMP, TMP and LOCALAPPDATA of an
AppContainer process to `<LOCALAPPDATA>\Packages\rigorous-levels-multiport\AC[\Temp]` under the LOCALAPPDATA passed, which
here is inside the scratch folder and does not exist (measured in CI 2026-11-12): `tempfile.gettempdir()` then
falls back to the current folder, the scratch folder. The container cannot open the NUL device (CI 2026-11-12: `open('nul')` → PermissionError in
dill, imported by scqubits): the runner then points `os.devnull` at an empty file in the scratch folder
(`RIGOROUS_LEVELS_DEVNULL`), counted by the disk cap.
The environment is a closed list: SYSTEMROOT, WINDIR, SYSTEMDRIVE, COMSPEC, PATHEXT copied, PATH = SYSTEMROOT,
USERPROFILE, LOCALAPPDATA, APPDATA, HOME, TEMP, TMP inside the scratch folder, plus the runner's own variables.
The probe checks network closed, %SystemRoot% not writable, home not listable. The read-execute grants are not
removed after the run: they stay on those folders for the AppContainer SID `rigorous-levels-multiport`. Folders that are a
user's home, contain one, or are a root (any drive or share) are refused. The owner of the engine is not checked on Windows. Not
measured locally (CI job).

6.5 `wasm` (everywhere): `wasmtime run -W max-memory-size=1 GiB -W timeout=<s> --dir <python.wasm folder>::/
--dir <work>::/work --dir <output folder>::/out` with a CPython built for WASI (`RIGOROUS_LEVELS_PYTHON_WASM`, required
non-writable: wasmtime pre-opens read-write); no site-packages (native wheels cannot load; today no numpy exists
for WASI, so every solver port reports `ERROR: No module named 'numpy'`, declared), the work folder made
non-writable for the run, no sockets, no `/tmp`, no rlimits (the engine's own limits apply). Measured 2026-11-11:
wasmtime 50.0.1 + CPython 3.15.2 (brettcannon/cpython-wasi-build): S1, S2, S4, S5, the hostile controls and the
dirty-output checks pass; S3-memory, S6, S7 need numpy and are skipped with that reason.

6.6 What no engine claims: protection against kernel exploits, side channels, or a compromised engine binary; the
physics of the other solver.

6.7 The work folder after the run (0.3.1; rule written on 2026-11-20 before the code, for every engine; revised
on 2026-11-21 after the review of that code, before the new code, and again that day after the second review:
the removal). The work folder is read-only for the port, so after
the run it must hold exactly what the host put there. Before the run the host puts in it `request.json`
(`requests.json` for a batch, §8), `port_runner.py` (its content only, not the mode of the installed file: rule added on
2026-11-22; the files the host writes there take the mode the host process's umask gives), `output.json` (empty: the mount point of the engines that bind
the output file) and `stderr.txt` (empty: the file the host writes the run's standard error to), sets the folder's
modification time to a fixed value (86 400 s after the epoch), and records, with `lstat` (a link is never followed):
for the folder and for each entry the kind and permission bits (`st_mode`), device, inode, number of names, owner and
group; for each entry except `stderr.txt` also the size, the modification time and the SHA-256 of the content, read
through a descriptor opened with `O_NOFOLLOW | O_NONBLOCK` that must be the same regular file (device and inode); on
POSIX also the status-change time (`st_ctime_ns`) of the folder and of each entry except `stderr.txt`. A process
cannot set that time: a change made and undone, or made to something not recorded (an extended attribute, the
access time set with `utime`, a second name made and removed), still moves it; reading a file moves its access time
and not this one, so a port that only reads changes nothing here. So that a change made at once cannot fall in the same
tick of the file system clock, the record ends only when that clock has passed the recorded times (the host sets the
times of `stderr.txt` until its status-change time is later, for at most 0.1 s; with a coarser clock a change in that
tick is not seen through this time). After the run, before the host reads the port's output or `stderr.txt`, the
folder is read again in the same way, names as bytes. For `wasm`, whose engine itself makes the folder 0555 and the
files 0444 for the run and sets them back after it, the status-change times are recorded after the modes are set
for the run and read again before they are set back; the run's standard error is copied into `stderr.txt` before
the check (see below). Any difference makes every output of the run `ERROR`, the port's output discarded, with the
reason `work folder changed during the run (it is read-only for the port): ` followed by the differences: an entry
the host did not put there, with its kind (file, folder, symbolic link, hard link = a regular file with more than
one name, FIFO, socket, character or block device), hidden names and names that are not UTF-8 included; an entry
missing; an entry whose kind, mode, inode, number of names, owner, group, size, time or content changed; the
folder's mode, inode, number of names, owner, group or modification time changed; and, when nothing else differs
for that entry or the folder, `status-change time changed (changed during the run and set back, or an attribute not
recorded changed)`. Names are written as Python literals: a string literal for a UTF-8 name, a bytes literal
(`b'...'`, `\x` escapes) for any other, at most 80 characters; at most 20 differences (in the order of the names'
bytes) are named and the others counted. A folder that cannot be read again gives `ERROR` with that reason. The
content of a recorded file is read only if its size is still the recorded one, and never beyond it. This check comes
before the host caps, the timeout and the output (`run()` returns its reason as the `limit` of the run).

The host's own reads and writes in the folder after the run never go through a link: the copy of the `wasm` run's
standard error into `stderr.txt` and the last 600 bytes of `stderr.txt` read for the reason of an output without
levels use a regular file with one name only (`lstat`, then `O_NOFOLLOW`, then the same device and inode; where
`O_NOFOLLOW` is missing the `lstat` decides), the copy without `O_TRUNC`. The folder is then removed without
following links and without recursion, also when the run left it or a folder inside it without the owner's read,
write or search permission. POSIX with descriptors: each folder is opened relative to its parent with
`O_DIRECTORY | O_NOFOLLOW` and given the owner's rwx through that descriptor. A folder that cannot be opened is
given it first: on Linux through a descriptor, never by name, the top folder included (an
`O_PATH | O_DIRECTORY | O_NOFOLLOW` descriptor, changed through `/proc/self/fd`, or without `/proc`, rule added on
2026-11-21, with the `fchmodat2` system call and `AT_EMPTY_PATH` on that descriptor: Linux 6.6 and later, x86-64 and
arm64; with an older kernel without `/proc`, or without ctypes, such a folder stays); on macOS, where there is no
`O_PATH`, by name: `fchmodat` without following a link, after an `lstat` (a file put under that name in between
would take the mode, as measured on Linux with `fchmodat2` called by name; not measured on macOS). No step is more
than two levels below the top folder and `..` is never opened (rule of 2026-11-22, replacing a walk down and back up
through `..`): for each folder in the top, its entries that are not folders are removed, each of its folders is given
the owner's rwx and moved up into the top (`renameat` relative to the two descriptors, as
`.rigorous_levels_rm_<n>`, n counted from 0 in each try: if that name is in use the move fails, or replaces an empty
folder, and a later round moves the folder), and it is removed; this until the top holds no folder. Measured with the walk down, in CI
on macOS: 5 000 folders one inside the other, made by the test through descriptors in 43 s and 53 s, were not removed
within the 30 s below, while 1 200 were. Windows: `shutil.rmtree`. A path whose
last part is not a name (a final separator, `.` or `..`) is not removed: the system resolves a link there. The
removal is tried again after 0.05, 0.1 and 0.2 s if the folder is still there (a process that outlived the run and
still writes in it), and the whole removal stops 30 s after it began, checked at each folder and each entry; after
that the folder stays.

What it does not see: on Windows the status-change time does not exist (`st_ctime` is the creation time), so a
change undone before the run ends (content, size, mode, times set back with `utime`) is not seen there; the entries
inside a folder the host did not put there are not listed one by one (the folder is named); a process that outlived
the run and keeps writing longer than the removal tries can keep the folder in the temporary directory, and one
that keeps making folders one inside the other is followed until those 30 s end (measured without that cap: such
a process of 3 s and of 9 s kept the removal busy for 8.5 s and 19.5 s, and `run_port`, with the engine replaced,
returned 8.2 s after its start with the one of 3 s). Measured on
Linux (btrfs) with the engine replaced (`tests/test_multiport.py` `TestWorkFolderClosed20261120`) and with `bwrap`
for the runs that change nothing; on macOS, Windows and with the container engines it runs in CI, not measured on the
author's machine.

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
Deprecated aliases in Python (`rigorous_levels.multiporta`) translate the 0.2.0 Italian keyword arguments of the Python API,
not the JSON files: a 0.1 request file is refused.
