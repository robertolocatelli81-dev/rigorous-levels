# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""rigorous_levels/isolation.py — the ISOLATION ENGINES of the multiport (docs/PORT_CONTRACT.md §6), one closed contract:

    run(engine, work, out_path, seconds, site_packages, python) -> (return code | None, timed_out, description)

runs `port_runner.py <work>` with <work> read-only, <out_path> the only writable file, no network, no real home, a
minimal environment, and a kill after `seconds`. `probe(engine)` says, fail-closed, whether the engine isolates on
this machine (cached per process); `select_engine()` applies the declared order of strength (ENGINE_ORDER) and
returns the first engine whose probe passes: never a silent fallback to "no isolation".

| engine        | platform              | mechanism (primary source)                                            | measured by the author |
|---------------|-----------------------|-----------------------------------------------------------------------|------------------------|
| podman/docker | Linux, macOS, Windows | OCI container: netns none, read-only root, cap-drop ALL, seccomp     | podman 4.3.1 rootless, Linux x86-64, 2026-11-11 |
| bwrap         | Linux                 | bubblewrap user namespaces (--unshare-all), bind mounts, tmpfs        | bwrap 0.8.0 / 0.9.0 (CI), 2026-11-11 |
| sandbox-exec  | macOS                 | Seatbelt profile, deny-default (`man sandbox-exec`: marked DEPRECATED by Apple, still shipped) | NOT measured locally: CI job macos-latest |
| appcontainer  | Windows               | AppContainer (CreateAppContainerProfile, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES) + Job Object limits (learn.microsoft.com, "AppContainer isolation", 2025-07-08) | NOT measured locally: CI job windows-latest |
| wasm          | everywhere            | wasmtime + CPython built for WASI: no sockets, only pre-opened folders | wasmtime 50.0.1 + CPython 3.15.2 WASI, 2026-11-11: runs the runner and the test ports; NO numpy, so no solver port |

Inside every engine the runner sets its own rlimits where the platform has them (CPU, address space, file size,
processes); on Windows the Job Object carries the memory, process-count and CPU-time limits; under WASI there is no
rlimit and the memory is bounded by wasmtime's `-W max-memory-size`.
"""
from __future__ import annotations

import bisect
import hashlib
import itertools
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Dict, List, Optional, Tuple

from rigorous_levels.guaranteed_intervals import OutOfDomain

ENGINE_ORDER = ("podman", "docker", "bwrap", "sandbox-exec", "appcontainer", "wasm")   # strongest usable first
ENGINES = ("auto",) + ENGINE_ORDER
TMPFS_BYTES = 256 << 20
RO_MOUNTS = ("/usr", "/lib", "/lib64", "/bin", "/etc")
RUNNER_NAME = "port_runner.py"
WASM_MAX_MEMORY = 1 << 30
# environment passed to a container CLIENT (podman/docker need their own configuration to find the local store);
# the sandboxed process itself gets only the variables set explicitly by each engine
CLIENT_ENV = ("PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "XDG_RUNTIME_DIR", "XDG_DATA_HOME", "XDG_CONFIG_HOME",
              "CONTAINERS_CONF", "CONTAINERS_STORAGE_CONF", "CONTAINERS_REGISTRIES_CONF", "CONTAINER_HOST",
              "DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_CONTEXT", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY",
              "SYSTEMROOT", "SYSTEMDRIVE", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "COMSPEC")
SANDBOX_ENV = {"HOME": "/tmp/nohome", "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1",
               "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
CONTAINER_PIDS = 16   # docker --pids-limit (processes and threads of the container): the same cap as RLIMIT_NPROC
FILE_CAP = 64 << 20   # RLIMIT_FSIZE of the runner; checked from the host where the platform has no such rlimit
WATCH_INTERVAL = 0.02  # seconds between two samples of the host watchdog (sandbox-exec, appcontainer)
WORK_FOLDER_TIME_NS = 86400 * 10 ** 9   # modification time given to the work folder before the run (PORT_CONTRACT §6.7)
WORK_HOST_WRITES = (b"stderr.txt",)     # entries the host itself writes during or after the run: size, time, content
WORK_REASON_MAX = 20                    # differences named in the reason of a changed work folder (the others counted)
WORK_TICK_WAIT = 0.1                    # seconds work_snapshot waits at most for the file system clock to pass its record
_STATUS_TIME = os.name == "posix"       # st_ctime: the last status change on POSIX (on Windows the creation: not recorded)
WORK_HEAD = "work folder changed during the run (it is read-only for the port): "
_STATUS_WORDS = "status-change time changed (changed during the run and set back, or an attribute not recorded changed)"
_PROBES: Dict[Tuple[str, str], Dict[str, object]] = {}


class SandboxMissing(RuntimeError):
    """No usable isolation engine: nothing runs (fail-closed)."""


def _client_env() -> Dict[str, str]:
    return {k: os.environ[k] for k in CLIENT_ENV if k in os.environ}


def _user_homes() -> Tuple[str, ...]:
    """The user's homes: $HOME and the one of the user database (they may differ: sudo -E, services, temporary HOME)."""
    homes = {os.path.realpath(os.path.expanduser("~"))}
    try:
        import pwd
        homes.add(os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir))
    except (ImportError, KeyError, OSError):
        pass
    for v in ("USERPROFILE",):
        if os.environ.get(v):
            homes.add(os.path.realpath(os.environ[v]))
    return tuple(sorted(homes))


def _inside(p: str, folder: str) -> bool:
    return p == folder or p.startswith(folder.rstrip("/\\") + os.sep) or p.startswith(folder.rstrip("/\\") + "/")


def _refuse_home_or_ancestor(p: str, engine: str) -> None:
    """A folder re-allowed (sandbox-exec) or granted (appcontainer) must not be «/», a user's home or an ancestor of
    one: with an interpreter prefix equal to the home (python built with --prefix=$HOME, ~/bin/python3) the whole home
    would become readable, the case interpreter_pieces() already refuses for bwrap."""
    real = os.path.realpath(p)
    for home in _user_homes():
        if _inside(home, real) or os.path.dirname(real) == real:     # any root: "/", "C:\\", "D:\\", a UNC share
            raise OutOfDomain(f"{engine}: {p!r} contains the user's home {home!r}: refused")


def _run(cmd: List[str], timeout: float, stderr_path: str, env: Dict[str, str]) -> Tuple[Optional[int], bool]:
    """stdout discarded and stderr to a file: an unbounded stream never enters the memory of the trusted side."""
    try:
        with open(stderr_path, "wb") as ferr:
            p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=ferr, env=env,
                               timeout=timeout)
        return p.returncode, False
    except subprocess.TimeoutExpired:
        return None, True


# ── host watchdog (engines without tmpfs or without an address-space rlimit: sandbox-exec, appcontainer) ─────────
def _tree_usage(paths: List[str]) -> Tuple[int, int]:
    """(total bytes, largest file) of the files under `paths` (apparent sizes, links not followed). Files unlinked
    while still open are not seen (declared in docs/PORT_CONTRACT.md §6)."""
    total = big = 0
    stack = list(paths)
    while stack:
        p = stack.pop()
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if stat.S_ISDIR(st.st_mode):
            try:
                stack.extend(os.path.join(p, n) for n in os.listdir(p))
            except OSError:
                pass
        elif stat.S_ISREG(st.st_mode):
            total += st.st_size
            big = max(big, st.st_size)
    return total, big


def disk_reason(paths: List[str], base: Tuple[int, int] = (0, 0)) -> str:
    """The reason the writable places exceed the caps of the tmpfs engines (one file over FILE_CAP, all of them over
    TMPFS_BYTES beyond `base`, what was there before the run), or ""."""
    total, big = _tree_usage(paths)
    if big > max(FILE_CAP, base[1]):
        return f"disk: a file of {big >> 20} MiB over the {FILE_CAP >> 20} MiB cap (host watchdog)"
    if total - base[0] > TMPFS_BYTES:
        return f"disk: {(total - base[0]) >> 20} MiB written over the {TMPFS_BYTES >> 20} MiB cap (host watchdog)"
    return ""


def cpu_reason(user_100ns: int, seconds: int) -> str:
    """appcontainer: the Job Object's user time (100 ns units) over `seconds`, or "". The Job's own time limit is
    checked by Windows only periodically (CI 2026-11-12, Python 3.12: a 2 s CPU limit was still not applied at 7 s)."""
    if user_100ns > int(seconds) * 10_000_000:
        return f"cpu: {user_100ns / 1e7:.1f} s of CPU over the {int(seconds)} s cap (host watchdog)"
    return ""


def _memory_sampler():
    """A function pgid -> bytes resident in the process group (max of resident size and physical footprint on macOS,
    proc_pid_rusage of libproc; VmRSS on Linux), or SandboxMissing if this platform cannot be sampled."""
    if sys.platform == "darwin":
        import ctypes
        import ctypes.util
        try:
            lib = ctypes.CDLL(ctypes.util.find_library("proc") or "/usr/lib/libproc.dylib", use_errno=True)
            lib.proc_pid_rusage, lib.proc_listpgrppids   # noqa: B018 — both must exist
        except (OSError, AttributeError) as e:
            raise SandboxMissing(f"memory watchdog: libproc unavailable ({e}): no memory cap, nothing runs") from None

        class RUsageInfoV0(ctypes.Structure):
            _fields_ = [("uuid", ctypes.c_uint8 * 16)] + [(n, ctypes.c_uint64) for n in (
                "user_time", "system_time", "pkg_idle_wkups", "interrupt_wkups", "pageins", "wired_size",
                "resident_size", "phys_footprint", "proc_start_abstime", "proc_exit_abstime")]

        def sample(pgid: int) -> int:
            buf = (ctypes.c_int * 256)()
            lib.proc_listpgrppids(pgid, buf, ctypes.sizeof(buf))
            total = 0
            for pid in {x for x in buf if x > 0} | {pgid}:
                ru = RUsageInfoV0()
                if lib.proc_pid_rusage(pid, 0, ctypes.byref(ru)) == 0:
                    total += max(ru.resident_size, ru.phys_footprint)
            return total
        return sample
    if sys.platform.startswith("linux"):
        page = os.sysconf("SC_PAGE_SIZE")

        def sample(pgid: int) -> int:
            total = 0
            for n in os.listdir("/proc"):
                if not n.isdigit():
                    continue
                try:
                    with open(f"/proc/{n}/stat", "rb") as f:
                        fields = f.read().rsplit(b")", 1)[1].split()
                    if int(fields[2]) != pgid:
                        continue
                    with open(f"/proc/{n}/statm", "rb") as f:
                        total += int(f.read().split()[1]) * page
                except (OSError, ValueError, IndexError):
                    pass
            return total
        return sample
    raise SandboxMissing(f"memory watchdog: no sampler on {sys.platform}")


def _kill_group(pgid: int) -> None:
    try:
        os.killpg(pgid, 9)
    except OSError:
        pass


def run_watched(cmd: List[str], timeout: float, stderr_path: str, env: Dict[str, str], mem_bytes: int,
                disk_paths: List[str]) -> Tuple[Optional[int], bool, str]:
    """POSIX: runs `cmd` in a new session and samples it every WATCH_INTERVAL s: resident memory of its process group
    over `mem_bytes` (0 = not watched), or the writable places over the disk caps, kill the whole group; after the exit
    the peak resident size (wait4) and the disk are checked again, so a short peak or a file left behind is still
    caught. Returns (return code or None, timed_out, reason of the cap exceeded or "")."""
    sampler = _memory_sampler() if mem_bytes else None
    base = _tree_usage(disk_paths)
    with open(stderr_path, "wb") as ferr:
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=ferr, env=env,
                             start_new_session=True)
    deadline = time.monotonic() + timeout
    reason, timed_out, rc, peak = "", False, None, 0
    try:
        while True:
            pid, status, ru = os.wait4(p.pid, os.WNOHANG)
            if pid == p.pid:
                rc = os.waitstatus_to_exitcode(status)
                p.returncode = rc
                peak = ru.ru_maxrss * (1 if sys.platform == "darwin" else 1024)
                break
            if not reason and not timed_out:
                if sampler is not None:
                    used = sampler(p.pid)
                    if used > mem_bytes:
                        reason = (f"memory: {used >> 20} MiB resident over the mem_mib cap of {mem_bytes >> 20} MiB "
                                  f"(host watchdog)")
                reason = reason or disk_reason(disk_paths, base)
                if not reason and time.monotonic() > deadline:
                    timed_out = True
                if reason or timed_out:
                    _kill_group(p.pid)
            time.sleep(WATCH_INTERVAL)
    finally:
        _kill_group(p.pid)                       # children left behind (forks) never outlive the run
        if p.returncode is None:
            p.kill()
            p.wait()
    if not reason and sampler is not None and peak > mem_bytes:
        reason = f"memory: peak {peak >> 20} MiB resident over the mem_mib cap of {mem_bytes >> 20} MiB (host watchdog)"
    reason = reason or disk_reason(disk_paths, base)
    return (None if timed_out else rc), timed_out, reason


# ── bwrap (Linux) ──────────────────────────────────────────────────────────────────────────────────────────────────
def _vouched_paths() -> List[str]:
    """RIGOROUS_LEVELS_TRUSTED_ENGINES: exact real paths, os.pathsep-separated, compared as strings with the binary's real path:
    an entry that is relative, a symlink, has '..', a trailing '/' or spaces around it vouches for nothing."""
    return [x for x in os.environ.get("RIGOROUS_LEVELS_TRUSTED_ENGINES", "").split(os.pathsep) if x]


_VOUCHED: Dict[str, str] = {}      # engine name -> real path of a user-owned binary accepted by RIGOROUS_LEVELS_TRUSTED_ENGINES


def _trusted_exe(name: str, exe: str) -> str:
    """The REAL path of the engine executable, which must not be replaceable by this user: on POSIX a regular file
    owned by root, not writable by group or others, in folders (from / down) owned by root and not writable by group
    or others (otherwise the file could be swapped after this check: the path returned is the one executed). A
    user-owned binary is accepted only if its exact real path is listed in RIGOROUS_LEVELS_TRUSTED_ENGINES; it is then named in
    Output.sandbox, because this user's processes can replace it (the probe, measured from inside, can be forged).
    Windows has no owner uid here: not checked."""
    if os.name != "posix":
        return exe
    real = os.path.realpath(exe)
    st = os.stat(real)
    if not stat.S_ISREG(st.st_mode):
        raise SandboxMissing(f"{name} {exe!r} is not a regular file: no execution (fail-closed)")
    if st.st_mode & 0o022:
        raise SandboxMissing(f"{name} {exe!r} is writable by group or others: no execution (fail-closed)")
    if st.st_uid != 0:
        if real not in _vouched_paths():
            raise SandboxMissing(f"{name} {exe!r} is not owned by root or is writable by others: no execution "
                                 f"(fail-closed; list its exact real path {real!r} in RIGOROUS_LEVELS_TRUSTED_ENGINES to vouch for it)")
        _VOUCHED[name] = real
        return real
    d = os.path.dirname(real)
    while True:
        sd = os.stat(d)
        if sd.st_uid != 0 or sd.st_mode & 0o022:
            raise SandboxMissing(f"{name} {real!r}: folder {d!r} is not owned by root or is writable by group or others, "
                                 f"so the binary could be swapped after the check: no execution (fail-closed)")
        if d == os.path.dirname(d):
            break
        d = os.path.dirname(d)
    _VOUCHED.pop(name, None)
    return real


def _bwrap() -> str:
    b = shutil.which("bwrap")
    if b is None:
        raise SandboxMissing("bwrap (bubblewrap) not found: no execution of external code (fail-closed)")
    return _trusted_exe("bwrap", b)


def interpreter_pieces(python: str) -> Tuple[str, ...]:
    """Pieces of the interpreter to mount read-only when it lives outside /usr (python of uv, pyenv, CI runners):
    the executable, the standard library (stdlib, platstdlib) and the libpython*.so* of LIBDIR; NEVER the whole
    prefix folder (with prefix <home>/.local, or the home itself, it would expose the user's hidden folders).
    Closed: the prefix is never «/», «/home», a user's home ($HOME or pwd) or one of its ancestors; every piece is
    inside the prefix; nothing already under the system mounts."""
    real = os.path.realpath(python)
    if any(_inside(real, m) for m in RO_MOUNTS):
        return ()
    code = ("import sys, sysconfig, json; v = sysconfig.get_config_var; "
            "print(json.dumps([sys.base_prefix, sysconfig.get_path('stdlib'), sysconfig.get_path('platstdlib'), "
            "v('LIBDIR') or '']))")
    try:
        p = subprocess.run([real, "-I", "-c", code], capture_output=True, text=True, timeout=30,
                           env={"PATH": "/usr/bin:/bin"})
        data = json.loads(p.stdout) if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        data = None
    if not (isinstance(data, list) and len(data) == 4 and all(isinstance(x, str) for x in data)):
        raise OutOfDomain(f"python {python!r}: installation prefix cannot be determined")
    prefix = os.path.realpath(data[0]) if data[0] else ""
    if not prefix or not os.path.isdir(prefix) or not real.startswith(prefix + "/"):
        raise OutOfDomain(f"python {python!r}: installation prefix cannot be determined or is inconsistent ({prefix!r})")
    for forbidden in ("/", "/home") + _user_homes():
        if _inside(forbidden, prefix):
            raise OutOfDomain(f"python {python!r}: the prefix {prefix!r} would contain the user's home: refused")
    pieces = [real]
    for d in data[1:3]:
        if d and os.path.isdir(d):
            pieces.append(os.path.realpath(d))
    libdir = os.path.realpath(data[3]) if data[3] else ""
    if libdir and os.path.isdir(libdir):
        pieces += sorted(os.path.join(libdir, n) for n in os.listdir(libdir)
                         if n.startswith("libpython") and ".so" in n and os.path.isfile(os.path.join(libdir, n)))
    outside = []
    for x in dict.fromkeys(os.path.realpath(x) for x in pieces):
        if any(_inside(x, m) for m in RO_MOUNTS):
            continue                                   # already mounted (e.g. a stdlib that points into /usr)
        if not _inside(x, prefix) or x == prefix:
            raise OutOfDomain(f"python {python!r}: {x!r} outside the prefix {prefix!r} or equal to it: refused")
        outside.append(x)
    return tuple(outside)


def _probe_bwrap() -> Dict[str, object]:
    b = _bwrap()
    try:
        p = subprocess.run([b, "--unshare-all", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "true"],
                           capture_output=True, timeout=60, env={"PATH": "/usr/bin:/bin"})
    except (OSError, subprocess.TimeoutExpired) as e:
        raise SandboxMissing(f"bwrap cannot start a sandbox: {type(e).__name__}") from None
    if p.returncode != 0:
        raise SandboxMissing("bwrap cannot create namespaces here: " + p.stderr.decode("utf-8", "replace").strip()[-200:])
    return {"engine": "bwrap", "exe": b}


def _run_bwrap(work: str, out_path: str, seconds: int, site_packages: List[str], python: str, stderr_path: str):
    bwrap = _bwrap()
    python = os.path.realpath(python or sys.executable)      # the venv (symlink) is not mounted: the real binary
    if not os.path.isfile(python):
        raise OutOfDomain(f"python {python!r} does not exist")
    cmd = [bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--clearenv"]
    for m in RO_MOUNTS:
        if os.path.isdir(m):
            cmd += ["--ro-bind", m, m]
    sz = str(TMPFS_BYTES)                # order: the tmpfs BEFORE the binds under them
    cmd += ["--dev", "/dev", "--size", sz, "--tmpfs", "/dev/shm", "--proc", "/proc", "--size", sz, "--tmpfs", "/tmp",
            "--size", sz, "--tmpfs", "/home"]
    for p in site_packages:
        cmd += ["--ro-bind", p, p]
    for pr in interpreter_pieces(python):
        cmd += ["--ro-bind", pr, pr]
    cmd += ["--ro-bind", work, "/work", "--bind", out_path, "/work/output.json"]
    for k, v in SANDBOX_ENV.items():
        cmd += ["--setenv", k, v]
    cmd += ["--chdir", "/tmp", python, "-I", "-S", "-B", "/work/" + RUNNER_NAME, "/work"]
    # MINIMAL environment already for bwrap: its init process (PID 1 in the sandbox) keeps the environment it was
    # started with and the port can read it in /proc/1/environ
    rc, timed_out = _run(cmd, seconds + 5, stderr_path, {"PATH": "/usr/bin:/bin"})
    return rc, timed_out, "bwrap --unshare-all --clearenv; ro: " + ",".join(RO_MOUNTS) + " + site-packages; HOME tmpfs"


# ── containers (podman, docker) ───────────────────────────────────────────────────────────────────────────────────
def default_image() -> str:
    """`python:<major>.<minor>-slim` of the running interpreter (the ABI of the wheels in its site-packages)."""
    v = sys.version_info
    return f"docker.io/library/python:{v.major}.{v.minor}-slim"


def _container_exe(engine: str) -> str:
    exe = shutil.which(engine)
    if exe is None:
        raise SandboxMissing(f"{engine} not found: no execution of external code (fail-closed)")
    return _trusted_exe(engine, exe)


def _container_cmd(engine: str, exe: str, image: str, name: str, seconds: int, mounts_ro: List[str], work: str,
                   out_path: str) -> List[str]:
    cmd = [exe, "run", "--rm", "--name", name, "--network", "none", "--read-only", "--cap-drop", "ALL",
           "--security-opt", "no-new-privileges", "--tmpfs", f"/tmp:rw,nosuid,nodev,size={TMPFS_BYTES}",
           "--workdir", "/tmp"]
    env = dict(SANDBOX_ENV, PATH="/usr/local/bin:/usr/bin:/bin")
    for k, v in env.items():
        cmd += ["--env", f"{k}={v}"]
    if hasattr(os, "getuid"):
        cmd += ["--user", f"{os.getuid()}:{os.getgid()}"]
        if engine == "podman":
            cmd += ["--userns=keep-id"]           # rootless: the host user keeps its uid, so it can read its files
    else:                                         # Windows client: a fixed non-root user of the image
        cmd += ["--user", "65534:65534"]
    if engine == "podman":
        cmd += ["--timeout", str(seconds)]        # conmon kills the container; the host timeout is the second guard
    else:
        # rootful docker runs the port with the host uid in the host user namespace: RLIMIT_NPROC there counts every
        # process and thread of that user on the host (CI 2026-11-12: "can't start new thread" with 16), so the
        # process cap is the container's own pids cgroup and the runner does not set RLIMIT_NPROC
        cmd += ["--pids-limit", str(CONTAINER_PIDS), "--env", "RIGOROUS_LEVELS_NPROC=cgroup"]
    for m in mounts_ro:
        cmd += ["-v", f"{m}:{m}:ro"]
    cmd += ["-v", f"{work}:/work:ro", "-v", f"{out_path}:/work/output.json:rw", image]
    return cmd


def _run_container_cmd(exe: str, cmd: List[str], name: str, timeout: float, stderr_path: str):
    rc, timed_out = _run(cmd, timeout, stderr_path, _client_env())
    if timed_out:                                 # the client alone would leave the container running under docker
        subprocess.run([exe, "rm", "-f", name], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, env=_client_env(), timeout=60)
    return rc, timed_out


PROBE_CODE = """import json, os, sys
try:
    ifaces = sorted(os.listdir('/sys/class/net'))
except OSError:
    ifaces = None
try:
    open('/usr/rigorous_levels_probe', 'w').close(); root_ro = False
except OSError:
    root_ro = True
print(json.dumps({'ifaces': ifaces, 'uid': os.getuid() if hasattr(os, 'getuid') else None, 'root_ro': root_ro,
                  'pid': os.getpid(), 'version': list(sys.version_info[:2])}))
"""


def _probe_container(engine: str, image: str) -> Dict[str, object]:
    exe = _container_exe(engine)
    r = subprocess.run([exe, "image", "inspect", image], stdin=subprocess.DEVNULL, capture_output=True,
                       env=_client_env(), timeout=120)
    if r.returncode != 0:
        raise SandboxMissing(f"{engine}: image {image!r} is not in the local store (it is never pulled here): "
                             f"{r.stderr.decode('utf-8', 'replace').strip()[-200:]}")
    work = tempfile.mkdtemp(prefix="rigorous_levels_probe_")
    try:
        with open(os.path.join(work, "probe.py"), "w", encoding="utf-8") as f:
            f.write(PROBE_CODE)
        out = os.path.join(work, "output.json")
        open(out, "wb").close()
        name = "rigorous_levels_probe_" + secrets.token_hex(6)
        cmd = _container_cmd(engine, exe, image, name, 60, [], work, out)
        cmd += ["python3", "-I", "-S", "-B", "-c", "import runpy, sys; sys.stdout = open('/work/output.json', 'w'); "
                "runpy.run_path('/work/probe.py'); sys.stdout.close()"]
        rc, timed_out = _run_container_cmd(exe, cmd, name, 120, os.path.join(work, "stderr.txt"))
        with open(os.path.join(work, "stderr.txt"), "rb") as ferr:
            tail = ferr.read()[-400:].decode("utf-8", "replace")
        try:
            with open(out, "rb") as f:
                facts = json.loads(f.read(4096).decode("utf-8"))
        except (OSError, ValueError):
            facts = None
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if timed_out or rc != 0 or not isinstance(facts, dict):
        raise SandboxMissing(f"{engine} probe failed (rc={rc}, timed_out={timed_out}): {tail}")
    check_container_facts(engine, facts)
    facts.update(engine=engine, image=image, exe=exe)
    return facts


def check_container_facts(engine: str, facts: Dict[str, object]) -> None:
    """Fail-closed reading of the probe: only the loopback interface, a non-root uid, a read-only root."""
    if facts.get("ifaces") != ["lo"] or facts.get("uid") in (0, None) or facts.get("root_ro") is not True:
        raise SandboxMissing(f"{engine} does not isolate: {facts} (expected only 'lo', a non-root uid, a read-only root)")


def _run_container(engine: str, image: str, work: str, out_path: str, seconds: int, site_packages: List[str],
                   stderr_path: str):
    facts = probe(engine, image)
    name = "rigorous_levels_port_" + secrets.token_hex(6)
    # the host timeout (seconds + 5) fires first and kills the container by name; the engine's own timeout is a
    # backstop for a hung client
    cmd = _container_cmd(engine, facts["exe"], image, name, seconds + 15, site_packages, work, out_path)
    cmd += ["python3", "-I", "-S", "-B", "/work/" + RUNNER_NAME, "/work"]
    rc, timed_out = _run_container_cmd(facts["exe"], cmd, name, seconds + 5, stderr_path)
    descr = (f"{engine} run --network none --read-only --cap-drop ALL --security-opt no-new-privileges, "
             f"user {facts['uid']}, image {image}, site-packages ro, HOME absent")
    return rc, timed_out, descr


# ── sandbox-exec (macOS) ──────────────────────────────────────────────────────────────────────────────────────────
def _sandbox_exec() -> str:
    exe = shutil.which("sandbox-exec")
    if exe is None or sys.platform != "darwin":
        raise SandboxMissing("sandbox-exec not found (macOS only): no execution of external code (fail-closed)")
    return _trusted_exe("sandbox-exec", exe)


def _sb_literal(p: str) -> str:
    return '"' + p.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _macos_exec_targets(python: str) -> List[str]:
    """The interpreter and, for a framework build (python.org, CI runners), the real binary its bin/ stub starts with
    posix_spawn: <prefix>/Resources/Python.app/Contents/MacOS/Python (CI 2026-11-12, macOS 26: the probe failed with
    "posix_spawn: .../Python.app/Contents/MacOS/Python" when only the stub could be executed)."""
    real = os.path.realpath(python)
    out = [real]
    app = os.path.join(os.path.dirname(os.path.dirname(real)), "Resources", "Python.app", "Contents", "MacOS", "Python")
    if os.path.isfile(app):
        out.append(os.path.realpath(app))
    return out


def seatbelt_profile(python: str, readable: List[str], out_path: str, scratch: str) -> str:
    """Deny-default Seatbelt profile: read everything except the user's homes (then the declared pieces inside
    them), write only the output file and a scratch folder, no network, fork/exec of the interpreter only."""
    lines = ["(version 1)", "(deny default)", "(allow file-read-metadata)", "(allow file-read*)", "(allow sysctl-read)",
             "(allow process-fork)", "(allow signal (target self))",
             "(allow mach-lookup (global-name \"com.apple.system.opendirectoryd.libinfo\") "
             "(global-name \"com.apple.system.logger\") (global-name \"com.apple.system.notification_center\"))",
             *[f"(allow process-exec (literal {_sb_literal(x)}))" for x in _macos_exec_targets(python)],
             "(allow file-write-data (literal \"/dev/null\") (literal \"/dev/zero\"))"]
    for home in _user_homes():
        lines.append(f"(deny file-read* (subpath {_sb_literal(home)}))")
    for p in readable:                                   # later rules win: the declared pieces inside a home
        _refuse_home_or_ancestor(p, "sandbox-exec")
        lines.append(f"(allow file-read* (subpath {_sb_literal(os.path.realpath(p))}))")
    # the output file: its data only (no unlink, no create: a link put in its place would be read by the host)
    lines.append(f"(allow file-write-data (literal {_sb_literal(os.path.realpath(out_path))}))")
    lines.append(f"(allow file-write* (subpath {_sb_literal(os.path.realpath(scratch))}))")
    lines.append("(deny network*)")
    return "\n".join(lines) + "\n"


def _probe_sandbox_exec() -> Dict[str, object]:
    exe = _sandbox_exec()
    scratch = tempfile.mkdtemp(prefix="rigorous_levels_sb_")
    try:
        probe = os.path.join(scratch, "probe.py")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("import os, socket, sys, json\n"
                    "try:\n    socket.create_connection(('127.0.0.1', 9), timeout=1); net = 'open'\n"
                    "except OSError as e:\n    net = type(e).__name__\n"
                    "try:\n    open('/usr/rigorous_levels_probe', 'w').close(); root_ro = False\nexcept OSError:\n    root_ro = True\n"
                    # listing the home needs file-read-data, which the profile denies there; os.path.isdir needs
                    # only file-read-metadata, allowed everywhere (CI 2026-11-12: isdir gave True, a false alarm)
                    "try:\n    os.listdir(sys.argv[1]); home = True\nexcept OSError:\n    home = False\n"
                    "print(json.dumps({'net': net, 'root_ro': root_ro, 'home': home}))\n")
        out = os.path.join(scratch, "out.txt")
        prof = seatbelt_profile(sys.executable, [sys.base_prefix, sys.prefix, scratch], out, scratch)
        pf = os.path.join(scratch, "profile.sb")
        with open(pf, "w", encoding="utf-8") as f:
            f.write(prof)
        home = _user_homes()[0]
        with open(out, "w", encoding="utf-8") as fout:
            p = subprocess.run([exe, "-f", pf, os.path.realpath(sys.executable), "-I", "-S", "-B", probe, home],
                               stdin=subprocess.DEVNULL, stdout=fout, stderr=subprocess.PIPE, timeout=120,
                               env={"PATH": "/usr/bin:/bin", "HOME": "/tmp/nohome"})
        with open(out, encoding="utf-8") as f:
            facts = json.loads(f.read() or "null")
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        raise SandboxMissing(f"sandbox-exec probe failed: {type(e).__name__}: {e}") from None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if p.returncode != 0 or not isinstance(facts, dict):
        raise SandboxMissing(f"sandbox-exec probe failed (rc={p.returncode}): {p.stderr.decode('utf-8', 'replace')[-300:]}")
    if facts.get("net") == "open" or facts.get("root_ro") is not True or facts.get("home") is not False:
        raise SandboxMissing(f"sandbox-exec does not isolate: {facts}")
    # macOS refuses RLIMIT_AS (CI 2026-11-12): the memory cap is the host watchdog, which must be able to sample
    if not _memory_sampler()(os.getpgrp()) > 0:
        raise SandboxMissing("sandbox-exec: the memory watchdog reads 0 bytes for this process: no memory cap")
    facts.update(engine="sandbox-exec", exe=exe)
    return facts


def _run_sandbox_exec(work: str, out_path: str, seconds: int, mem_mib: int, site_packages: List[str], python: str,
                      stderr_path: str):
    exe = probe("sandbox-exec")["exe"]
    python = os.path.realpath(python or sys.executable)
    scratch = tempfile.mkdtemp(prefix="rigorous_levels_sb_")
    try:
        prof = seatbelt_profile(python, [sys.base_prefix, os.path.dirname(os.path.dirname(python)), work, *site_packages],
                                out_path, scratch)
        pf = os.path.join(scratch, "profile.sb")
        with open(pf, "w", encoding="utf-8") as f:
            f.write(prof)
        env = dict(SANDBOX_ENV, TMPDIR=scratch, RIGOROUS_LEVELS_OUTPUT_DIR=os.path.dirname(out_path), RIGOROUS_LEVELS_HOST_LIMITS="memory")
        cmd = [exe, "-f", pf, python, "-I", "-S", "-B", os.path.join(work, RUNNER_NAME), work]
        rc, timed_out, limit = run_watched(cmd, seconds + 5, stderr_path, env, int(mem_mib) << 20,
                                           [scratch, out_path])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return (rc, timed_out, "sandbox-exec deny-default profile: no network, read-only except output, homes hidden; "
            "memory and scratch disk capped by the host watchdog", limit)


# ── AppContainer + Job Object (Windows) ───────────────────────────────────────────────────────────────────────────
def _win():
    if sys.platform != "win32":
        raise SandboxMissing("appcontainer: Windows only (fail-closed)")
    import ctypes
    from ctypes import wintypes
    return ctypes, wintypes


def _appcontainer_sid(ctypes, wintypes, name: str):
    """SID of the AppContainer profile `name` (created if missing). learn.microsoft.com: CreateAppContainerProfile."""
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    sid = ctypes.c_void_p()
    hr = userenv.CreateAppContainerProfile(name, name, "rigorous-levels multiport sandbox", None, 0, ctypes.byref(sid))
    if hr != 0:
        if hr & 0xFFFFFFFF == 0x800700B7:        # ERROR_ALREADY_EXISTS
            hr = userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid))
        if hr != 0:
            raise SandboxMissing(f"appcontainer: profile cannot be created (HRESULT 0x{hr & 0xFFFFFFFF:08X})")
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    s = wintypes.LPWSTR()
    if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(s)):
        raise SandboxMissing("appcontainer: ConvertSidToStringSidW failed")
    return sid, s.value


def _icacls(path: str, sid_str: str, rights: str) -> None:
    """Grants `rights` (RX or M) on `path` to the AppContainer SID with inheritance: an AppContainer process reads
    only what is granted to its SID (or to ALL APPLICATION PACKAGES)."""
    flags = "(OI)(CI)" if os.path.isdir(path) else ""
    r = subprocess.run(["icacls", path, "/grant", f"*{sid_str}:{flags}{rights}", "/Q"], capture_output=True,
                       timeout=600, env=_client_env())
    if r.returncode != 0:
        raise SandboxMissing(f"appcontainer: icacls on {path!r} failed: {r.stderr.decode('utf-8', 'replace')[-200:]}")


OUTPUT_GRANT = "(R,W)"   # appcontainer: read and write the output file's data; no DELETE (M would let it be replaced)


def _appcontainer_folder(ctypes, wintypes, sid_str: str) -> str:
    """The AppContainer's own profile folder (GetAppContainerFolderPath): writable by the container and kept between
    runs, so its growth is counted by the disk cap. SandboxMissing if it cannot be located."""
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    ole = ctypes.WinDLL("ole32")
    path = wintypes.LPWSTR()
    hr = userenv.GetAppContainerFolderPath(sid_str, ctypes.byref(path))
    if hr != 0 or not path.value:
        raise SandboxMissing(f"appcontainer: its folder cannot be located (HRESULT 0x{hr & 0xFFFFFFFF:08X}): "
                             f"its writes could not be capped")
    value = path.value
    ole.CoTaskMemFree(path)
    return value


def _run_appcontainer_process(ctypes, wintypes, sid, cmdline: str, env: Dict[str, str], cwd: str, seconds: int,
                              mem_mib: int, stderr_path: str,
                              disk_paths: Optional[List[str]] = None) -> Tuple[Optional[int], bool, str]:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    INVALID = wintypes.HANDLE(-1).value

    class SECURITY_CAPABILITIES(ctypes.Structure):
        _fields_ = [("AppContainerSid", ctypes.c_void_p), ("Capabilities", ctypes.c_void_p),
                    ("CapabilityCount", wintypes.DWORD), ("Reserved", wintypes.DWORD)]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                    ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                    ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                    ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.c_void_p),
                    ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]

    class STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE), ("dwProcessId", wintypes.DWORD),
                    ("dwThreadId", wintypes.DWORD)]

    class SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p), ("bInheritHandle", wintypes.BOOL)]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                   "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
        _fields_ = [("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
                    ("ThisPeriodTotalUserTime", ctypes.c_int64), ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                    ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                    ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
    GENERIC_WRITE, GENERIC_READ, CREATE_ALWAYS, OPEN_EXISTING = 0x40000000, 0x80000000, 2, 3
    herr = k32.CreateFileW(stderr_path, GENERIC_WRITE, 1, ctypes.byref(sa), CREATE_ALWAYS, 0x80, None)
    hnul = k32.CreateFileW("NUL", GENERIC_READ | GENERIC_WRITE, 3, ctypes.byref(sa), OPEN_EXISTING, 0x80, None)
    if herr == INVALID or hnul == INVALID:
        raise SandboxMissing("appcontainer: cannot open the stderr file or NUL")
    size = ctypes.c_size_t(0)
    k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    attr = ctypes.create_string_buffer(size.value)
    if not k32.InitializeProcThreadAttributeList(attr, 1, 0, ctypes.byref(size)):
        raise SandboxMissing("appcontainer: InitializeProcThreadAttributeList failed")
    sc = SECURITY_CAPABILITIES(sid, None, 0, 0)
    PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
    if not k32.UpdateProcThreadAttribute(attr, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES, ctypes.byref(sc),
                                         ctypes.sizeof(sc), None, None):
        raise SandboxMissing(f"appcontainer: UpdateProcThreadAttribute failed ({ctypes.get_last_error()})")
    si = STARTUPINFOEXW()
    si.StartupInfo.cb = ctypes.sizeof(si)
    si.StartupInfo.dwFlags = 0x100                         # STARTF_USESTDHANDLES
    si.StartupInfo.hStdInput, si.StartupInfo.hStdOutput, si.StartupInfo.hStdError = hnul, hnul, herr
    si.lpAttributeList = ctypes.cast(attr, ctypes.c_void_p)
    pi = PROCESS_INFORMATION()
    # sorted by name, case-insensitive, as the CreateProcess documentation asks of an environment block
    envblock = "".join(f"{k}={env[k]}\0" for k in sorted(env, key=str.upper)) + "\0"
    EXTENDED_STARTUPINFO_PRESENT, CREATE_SUSPENDED, CREATE_NO_WINDOW, CREATE_UNICODE_ENVIRONMENT = 0x80000, 0x4, 0x8000000, 0x400
    ok = k32.CreateProcessW(None, ctypes.create_unicode_buffer(cmdline), None, None, True,
                            EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT,
                            ctypes.create_unicode_buffer(envblock), cwd, ctypes.byref(si), ctypes.byref(pi))
    k32.CloseHandle(herr)
    k32.CloseHandle(hnul)
    if not ok:
        err = ctypes.get_last_error()
        raise SandboxMissing(f"appcontainer: CreateProcessW failed ({err}; command line {len(cmdline)} chars, environment "
                             f"{sorted(env)}, working folder {cwd!r})")
    job = k32.CreateJobObjectW(None, None)
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    JOB_TIME, ACTIVE_PROCESS, PROCESS_MEMORY, DIE_ON_EXC, KILL_ON_CLOSE = 0x4, 0x8, 0x100, 0x400, 0x2000
    info.BasicLimitInformation.LimitFlags = JOB_TIME | ACTIVE_PROCESS | PROCESS_MEMORY | DIE_ON_EXC | KILL_ON_CLOSE
    info.BasicLimitInformation.PerJobUserTimeLimit = int(seconds) * 10_000_000
    info.BasicLimitInformation.ActiveProcessLimit = 16
    info.ProcessMemoryLimit = int(mem_mib) << 20
    if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) \
            or not k32.AssignProcessToJobObject(job, pi.hProcess):
        k32.TerminateProcess(pi.hProcess, 1)
        raise SandboxMissing(f"appcontainer: job object limits not applied ({ctypes.get_last_error()})")
    disk_paths = list(disk_paths or [])
    base = _tree_usage(disk_paths)
    k32.ResumeThread(pi.hThread)
    WAIT_TIMEOUT = 0x102
    deadline = time.monotonic() + seconds + 5
    timed_out, reason = False, ""
    acct = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
    while k32.WaitForSingleObject(pi.hProcess, int(WATCH_INTERVAL * 1000)) == WAIT_TIMEOUT:
        # no RLIMIT_FSIZE and no tmpfs on Windows: the Job Object has no disk limit, the host watches the writable places;
        # the Job's CPU-time limit is checked by Windows only periodically: the host reads the Job's user time too
        if not k32.QueryInformationJobObject(job, 1, ctypes.byref(acct), ctypes.sizeof(acct), None):
            reason = f"cpu: the job's accounting cannot be read ({ctypes.get_last_error()}): run stopped (host watchdog)"
        else:
            reason = cpu_reason(acct.TotalUserTime, seconds)
        reason = reason or disk_reason(disk_paths, base)
        timed_out = not reason and time.monotonic() > deadline
        if reason or timed_out:
            k32.TerminateJobObject(job, 1)
            k32.WaitForSingleObject(pi.hProcess, 10_000)
            break
    code = wintypes.DWORD()
    k32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
    k32.TerminateJobObject(job, 1)                  # processes the runner started never outlive it
    for h in (pi.hThread, pi.hProcess, job):
        k32.CloseHandle(h)
    reason = reason or disk_reason(disk_paths, base)
    return (None if timed_out else int(code.value)), timed_out, reason


def _appcontainer_base_env(scratch: str) -> Dict[str, str]:
    """The Windows variables a process needs to start (CI 2026-11-12: CreateProcessW in the AppContainer failed with
    203, ERROR_ENVVAR_NOT_FOUND, with only SYSTEMROOT and PATH among them): system ones copied from this process
    (SYSTEMROOT, SYSTEMDRIVE, WINDIR, COMSPEC, PATHEXT: no user data), the per-user folders pointed at the scratch
    folder (USERPROFILE, LOCALAPPDATA, APPDATA: never the real ones). Nothing else of the session is passed."""
    root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    env = {"SYSTEMROOT": root, "WINDIR": os.environ.get("WINDIR", root), "PATH": root,
           "SYSTEMDRIVE": os.environ.get("SYSTEMDRIVE", root[:2]),
           "COMSPEC": os.environ.get("COMSPEC", os.path.join(root, "System32", "cmd.exe")),
           "PATHEXT": os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD"),
           "USERPROFILE": os.path.join(scratch, "nohome"), "LOCALAPPDATA": os.path.join(scratch, "localappdata"),
           "APPDATA": os.path.join(scratch, "appdata")}
    return env


def _probe_appcontainer() -> Dict[str, object]:
    ctypes, wintypes = _win()
    sid, sid_str = _appcontainer_sid(ctypes, wintypes, "rigorous-levels-multiport")
    scratch = tempfile.mkdtemp(prefix="rigorous_levels_ac_")
    try:
        for p in (sys.base_prefix, sys.prefix):
            _refuse_home_or_ancestor(p, "appcontainer")
            _icacls(p, sid_str, "RX")
        _icacls(scratch, sid_str, "M")
        probe = os.path.join(scratch, "probe.py")
        home = _user_homes()[0]
        with open(probe, "w", encoding="utf-8") as f:
            f.write("import os, socket, sys, json\n"
                    "try:\n    socket.create_connection(('127.0.0.1', 9), timeout=1); net = 'open'\n"
                    "except OSError as e:\n    net = type(e).__name__\n"
                    "try:\n    open(os.path.join(os.environ['SYSTEMROOT'], 'rigorous_levels_probe'), 'w').close(); root_ro = False\n"
                    "except OSError:\n    root_ro = True\n"
                    "try:\n    os.listdir(sys.argv[1]); home = True\nexcept OSError:\n    home = False\n"
                    "open(sys.argv[2], 'w').write(json.dumps({'net': net, 'root_ro': root_ro, 'home': home}))\n")
        out = os.path.join(scratch, "out.json")
        env = {**_appcontainer_base_env(scratch), "HOME": os.path.join(scratch, "nohome"),
               "TEMP": scratch, "TMP": scratch, "PYTHONDONTWRITEBYTECODE": "1"}
        cmdline = subprocess.list2cmdline([sys.executable, "-I", "-S", "-B", probe, home, out])
        rc, timed_out, _ = _run_appcontainer_process(ctypes, wintypes, sid, cmdline, env, scratch, 60, 1024,
                                                     os.path.join(scratch, "stderr.txt"))
        with open(os.path.join(scratch, "stderr.txt"), "rb") as f:
            tail = f.read()[-400:].decode("utf-8", "replace")
        try:
            with open(out, encoding="utf-8") as f:
                facts = json.loads(f.read() or "null")
        except (OSError, ValueError):
            facts = None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if timed_out or rc != 0 or not isinstance(facts, dict):
        raise SandboxMissing(f"appcontainer probe failed (rc={rc}, timed_out={timed_out}): {tail}")
    if facts.get("net") == "open" or facts.get("root_ro") is not True or facts.get("home") is not False:
        raise SandboxMissing(f"appcontainer does not isolate: {facts}")
    facts.update(engine="appcontainer", sid=sid_str, folder=_appcontainer_folder(ctypes, wintypes, sid_str))
    return facts


def _run_appcontainer(work: str, out_path: str, seconds: int, mem_mib: int, site_packages: List[str], python: str,
                      stderr_path: str):
    ctypes, wintypes = _win()
    facts = probe("appcontainer")
    sid, sid_str = _appcontainer_sid(ctypes, wintypes, "rigorous-levels-multiport")
    python = os.path.realpath(python or sys.executable)
    for p in [os.path.dirname(os.path.dirname(python)), *site_packages, work]:
        _refuse_home_or_ancestor(p, "appcontainer")
        _icacls(p, sid_str, "RX")
    _icacls(out_path, sid_str, OUTPUT_GRANT)
    scratch = tempfile.mkdtemp(prefix="rigorous_levels_ac_")
    _icacls(scratch, sid_str, "M")
    try:
        env = {**_appcontainer_base_env(scratch), "HOME": os.path.join(scratch, "nohome"),
               "TEMP": scratch, "TMP": scratch, "PYTHONDONTWRITEBYTECODE": "1", "OMP_NUM_THREADS": "1",
               "OPENBLAS_NUM_THREADS": "1", "RIGOROUS_LEVELS_OUTPUT_DIR": os.path.dirname(out_path),
               "RIGOROUS_LEVELS_DEVNULL": os.path.join(scratch, "devnull")}
        cmdline = subprocess.list2cmdline([python, "-I", "-S", "-B", os.path.join(work, RUNNER_NAME), work])
        rc, timed_out, limit = _run_appcontainer_process(ctypes, wintypes, sid, cmdline, env, scratch, seconds, mem_mib,
                                                         stderr_path, [scratch, out_path, facts["folder"]])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return (rc, timed_out, f"appcontainer {facts['sid']} + job object (memory, 16 processes, CPU time): no network, "
            f"reads only the granted folders, writes only the output file and its scratch; disk capped by the host "
            f"watchdog", limit)


# ── WebAssembly (wasmtime + CPython for WASI) ─────────────────────────────────────────────────────────────────────
def _wasm_parts() -> Tuple[str, str]:
    """(wasmtime executable, folder with python.wasm and lib/) from PATH and RIGOROUS_LEVELS_PYTHON_WASM: never downloaded."""
    exe = shutil.which("wasmtime")
    if exe is None:
        raise SandboxMissing("wasmtime not found: no execution of external code (fail-closed)")
    exe = _trusted_exe("wasmtime", exe)
    folder = os.environ.get("RIGOROUS_LEVELS_PYTHON_WASM", "")
    if not folder or not os.path.isfile(os.path.join(folder, "python.wasm")) or not os.path.isdir(os.path.join(folder, "lib")):
        raise SandboxMissing("RIGOROUS_LEVELS_PYTHON_WASM must point to a folder with python.wasm and lib/ (a CPython WASI build)")
    folder = os.path.realpath(folder)
    # wasmtime pre-opens folders read-write (no read-only flag in wasmtime 50): the interpreter folder must be
    # non-writable by this user, so that the guest cannot alter the next run's interpreter (fail-closed otherwise)
    if any(os.access(p, os.W_OK) for p in (folder, os.path.join(folder, "lib"), os.path.join(folder, "python.wasm"))):
        raise SandboxMissing(f"RIGOROUS_LEVELS_PYTHON_WASM {folder!r} is writable by this user: make it read-only (chmod -R a-w)")
    return exe, folder


def _wasm_cmd(exe: str, folder: str, dirs: List[Tuple[str, str]], seconds: int, env: Dict[str, str]) -> List[str]:
    cmd = [exe, "run", "-W", f"max-memory-size={WASM_MAX_MEMORY}", "-W", f"timeout={seconds + 15}s", "--dir", f"{folder}::/",
           "--env", "PYTHONHOME=/"]
    for host, guest in dirs:
        cmd += ["--dir", f"{host}::{guest}"]
    for k, v in env.items():
        cmd += ["--env", f"{k}={v}"]
    return cmd + [os.path.join(folder, "python.wasm")]


def _probe_wasm() -> Dict[str, object]:
    exe, folder = _wasm_parts()
    scratch = tempfile.mkdtemp(prefix="rigorous_levels_wasm_")
    try:
        with open(os.path.join(scratch, "probe.py"), "w", encoding="utf-8") as f:
            f.write("import json, os, sys\n"
                    "try:\n    import socket; socket.create_connection(('127.0.0.1', 9), timeout=1); net = 'open'\n"
                    "except Exception as e:\n    net = type(e).__name__\n"
                    "try:\n    open('/lib/rigorous_levels_probe', 'w').close(); root_ro = False\nexcept OSError:\n    root_ro = True\n"
                    "try:\n    import numpy; np = numpy.__version__\nexcept Exception as e:\n    np = type(e).__name__\n"
                    "open('/work/out.json', 'w').write(json.dumps({'net': net, 'root_ro': root_ro, 'numpy': np, "
                    "'version': list(sys.version_info[:2])}))\n")
        cmd = _wasm_cmd(exe, folder, [(scratch, "/work")], 60, {}) + ["-I", "-S", "-B", "/work/probe.py"]
        rc, timed_out = _run(cmd, 120, os.path.join(scratch, "stderr.txt"), {"PATH": os.environ.get("PATH", "")})
        with open(os.path.join(scratch, "stderr.txt"), "rb") as f:
            tail = f.read()[-400:].decode("utf-8", "replace")
        try:
            with open(os.path.join(scratch, "out.json"), encoding="utf-8") as f:
                facts = json.loads(f.read() or "null")
        except (OSError, ValueError):
            facts = None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if timed_out or rc != 0 or not isinstance(facts, dict):
        raise SandboxMissing(f"wasm probe failed (rc={rc}, timed_out={timed_out}): {tail}")
    if facts.get("net") == "open" or facts.get("root_ro") is not True:
        raise SandboxMissing(f"wasm does not isolate: {facts}")
    facts.update(engine="wasm", exe=exe, folder=folder)
    return facts


def _chmod_regular_file(path: str, mode: int, same: Optional[Tuple[int, int]] = None) -> None:
    """chmod of a regular file of the work folder that has this one name, never of what a link names: os.walk lists a
    symbolic link to a file among the files, and os.chmod follows it (0.3.0: a link planted in the work folder, pointing
    at a 0600 file of the user, left that file 0644 after the run); a hard link to that file is a regular file whose
    mode is the mode of the file outside (measured on the first version of this function: the file was left 0644), so
    a file with more than one name (st_nlink != 1) is left as it is too. A symbolic link, a FIFO, a socket or a device
    is left as it is; the file is opened with O_NOFOLLOW and changed through its descriptor, so a name swapped between
    the check and the change is not followed either (lstat + chmod where os.fchmod or O_NOFOLLOW is missing:
    Windows). The files the library puts in the work folder have one name. With `same` = (device, inode) the file must
    also be that file (the mode recorded before the run is set back only on the file it was recorded for)."""
    try:
        st = os.lstat(path)
    except OSError:
        return
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or (same is not None and (st.st_dev, st.st_ino) != same):
        return
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow or not hasattr(os, "fchmod"):
        os.chmod(path, mode)
        return
    try:
        fd = os.open(path, os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return                                   # a link put there after the lstat (ELOOP), or a file gone
    try:
        fs = os.fstat(fd)
        if stat.S_ISREG(fs.st_mode) and fs.st_nlink == 1 and (fs.st_dev, fs.st_ino) == (st.st_dev, st.st_ino):
            os.fchmod(fd, mode)
    finally:
        os.close(fd)


def _copy_run_stderr(src: str, dst: str) -> None:
    """Copies the stderr file of a wasm run from the folder the run can write (/out) to `dst`, only if it is a regular
    file with this one name: lstat, open with O_NOFOLLOW | O_NONBLOCK, the same file by device and inode, then the
    bytes read through the descriptor. Anything else there (a symbolic or hard link, a FIFO, a folder, a device,
    nothing) is not read: `dst` then holds one line saying so. Measured on 0.3.0 with the engine replaced: with
    stderr.txt replaced by a link to a file of the user, shutil.copy copied that file's bytes (their last 600 go into
    the reason of an output without levels); removed, or replaced by a folder or a FIFO, FileNotFoundError,
    IsADirectoryError or shutil.SpecialFileError left _run_wasm. `dst` (in the work folder) is opened with O_NOFOLLOW
    and without O_TRUNC, written only if it is a regular file with one name, and truncated through the descriptor:
    anything else there is left as it is, and named by the check of the work folder (docs/PORT_CONTRACT.md §6.7).
    Where O_NOFOLLOW is missing (Windows) the lstat decides, as for `src`: a link is not opened, and the file opened
    must be the one the lstat saw (measured with O_NOFOLLOW set to 0: before, the file a symbolic link named was
    overwritten)."""
    why = ""
    fd = -1
    try:
        st = os.lstat(src)
        if not stat.S_ISREG(st.st_mode):
            why = "not a regular file"
        else:
            fd = os.open(src, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                         | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0))
            fs = os.fstat(fd)
            if not (stat.S_ISREG(fs.st_mode) and fs.st_nlink == 1 and (fs.st_dev, fs.st_ino) == (st.st_dev, st.st_ino)):
                why = "not a regular file with one name, or changed between the check and the open"
    except OSError as e:
        why = type(e).__name__
    try:
        try:
            ld = os.lstat(dst)
        except FileNotFoundError:
            ld = None                            # removed during the run: made again here, named by the check (§6.7)
        except OSError:
            return
        if ld is not None and not (stat.S_ISREG(ld.st_mode) and ld.st_nlink == 1):
            return                               # a link, a FIFO, a folder: left as it is, with or without O_NOFOLLOW
        try:
            fo = os.open(dst, os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                         | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0), 0o666)
        except OSError:
            return                               # a link, a FIFO without reader, a folder: left as it is
        with os.fdopen(fo, "wb") as out:
            fs = os.fstat(out.fileno())
            if not (stat.S_ISREG(fs.st_mode) and fs.st_nlink == 1
                    and (ld is None or (fs.st_dev, fs.st_ino) == (ld.st_dev, ld.st_ino))):
                return
            out.truncate(0)
            if why:
                out.write(f"[rigorous-levels] the stderr file of the run was not read: {why}\n".encode("utf-8"))
            else:
                with os.fdopen(fd, "rb") as f:
                    fd = -1
                    shutil.copyfileobj(f, out)
    finally:
        if fd >= 0:
            os.close(fd)


# ── the work folder after the run (docs/PORT_CONTRACT.md §6.7) ────────────────────────────────────────────────────
_KINDS = ((stat.S_ISDIR, "folder"), (stat.S_ISLNK, "symbolic link"), (stat.S_ISFIFO, "FIFO"), (stat.S_ISSOCK, "socket"),
          (stat.S_ISCHR, "character device"), (stat.S_ISBLK, "block device"))


def _kind(st: os.stat_result) -> str:
    if stat.S_ISREG(st.st_mode):
        return "file" if st.st_nlink == 1 else f"hard link (a file with {st.st_nlink} names)"
    for test, name in _KINDS:
        if test(st.st_mode):
            return name
    return f"entry of unknown kind (mode {oct(st.st_mode)})"


def _shown(name: bytes) -> str:
    """A name of the work folder as a Python literal, at most 80 characters: a str literal if the name is UTF-8, else
    a bytes literal (the other bytes as \\x escapes), so the two cannot be confused."""
    try:
        r = repr(name.decode("utf-8"))
    except UnicodeDecodeError:
        r = repr(name)
    return r if len(r) <= 80 else r[:77] + "..."


def _content_sha256(path: bytes, st: os.stat_result) -> str:
    """SHA-256 of a regular file read through a descriptor opened with O_NOFOLLOW | O_NONBLOCK that must be the file
    `st` describes (device and inode); otherwise a word saying why it was not read. Exactly `st.st_size` bytes are
    read: a file that is shorter or longer by then is not hashed (the time of the check is bounded by the sizes the
    host recorded, never by what a port made of a file)."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                     | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0))
    except OSError as e:
        return f"not read ({type(e).__name__})"
    try:
        fs = os.fstat(fd)
        if not (stat.S_ISREG(fs.st_mode) and (fs.st_dev, fs.st_ino) == (st.st_dev, st.st_ino)):
            return "not the same regular file"
        h = hashlib.sha256()
        left = st.st_size
        while left > 0:
            b = os.read(fd, min(1 << 16, left))
            if not b:
                break
            h.update(b)
            left -= len(b)
        if left or os.read(fd, 1):
            return "not read to the end (the size changed while it was read)"
        return h.hexdigest()
    finally:
        os.close(fd)


def _meta(st: os.stat_result) -> Dict[str, int]:
    return {"kind": stat.S_IFMT(st.st_mode), "mode": stat.S_IMODE(st.st_mode), "device": st.st_dev, "inode": st.st_ino,
            "names": st.st_nlink, "owner": st.st_uid, "group": st.st_gid}


def _entry_record(folder: bytes, name: bytes, size: Optional[int] = None) -> Dict[str, object]:
    """The record of one entry. With `size` (the size recorded before the run) the content is read only if the size
    is still that one: a file made larger is already a difference, and is not read. The status-change time comes
    last: it is named only when nothing else differs (_fields)."""
    path = os.path.join(folder, name)
    st = os.lstat(path)
    rec: Dict[str, object] = _meta(st)
    if name not in WORK_HOST_WRITES:
        rec["size"], rec["time"] = st.st_size, st.st_mtime_ns
        if not stat.S_ISREG(st.st_mode):
            rec["content"] = ""
        elif size is not None and st.st_size != size:
            rec["content"] = "not read (the size changed)"
        else:
            rec["content"] = _content_sha256(path, st)
        if _STATUS_TIME:
            rec["status"] = st.st_ctime_ns
    return rec


def work_snapshot(work: str) -> Dict[str, object]:
    """Before the run: the folder's modification time set to WORK_FOLDER_TIME_NS, then the record of the folder and of
    every entry the host put there (lstat: links not followed; names as bytes). On POSIX the record holds the
    status-change time (st_ctime_ns) of the folder and of each entry the host does not write: a process cannot set
    it, so a change made and then undone, or made to something not recorded (an extended attribute), still moves
    it. So that a change made right after the record cannot fall in the same tick of the file system clock, the
    function returns only when that clock has passed every time recorded: it sets the times of an entry the host
    writes (stderr.txt, not compared) until its status-change time is later, for at most WORK_TICK_WAIT seconds
    (no such entry, or a coarser clock: no wait, and a change inside that tick is not seen through this time)."""
    folder = os.fsencode(work)
    os.utime(folder, ns=(WORK_FOLDER_TIME_NS, WORK_FOLDER_TIME_NS))
    entries = {n: _entry_record(folder, n) for n in sorted(os.listdir(folder))}
    st = os.lstat(folder)
    rec = dict(_meta(st), time=st.st_mtime_ns)
    if _STATUS_TIME:
        rec["status"] = st.st_ctime_ns
        _wait_clock_past(folder, max([st.st_ctime_ns] + [e["status"] for e in entries.values() if "status" in e]))
    return {"folder": rec, "entries": entries}


def _wait_clock_past(folder: bytes, last: int) -> None:
    """Returns when the file system clock has passed `last` (a status-change time just recorded): sets the times of
    an entry the host writes (stderr.txt, its times not compared) until its status-change time is later, for at most
    WORK_TICK_WAIT seconds; without such an entry, or with a coarser clock, it returns without that guarantee."""
    for n in WORK_HOST_WRITES:
        probe = os.path.join(folder, n)
        try:
            st = os.lstat(probe)
        except OSError:
            continue
        if not (stat.S_ISREG(st.st_mode) and st.st_nlink == 1):
            continue
        end = time.monotonic() + WORK_TICK_WAIT
        while True:
            os.utime(probe)
            if os.lstat(probe).st_ctime_ns > last or time.monotonic() >= end:
                return
            time.sleep(0.0005)


def _status_times(folder: bytes) -> Dict[bytes, int]:
    """st_ctime_ns of the folder (key b"") and of each entry except the ones the host writes (lstat)."""
    out = {b"": os.lstat(folder).st_ctime_ns}
    for n in os.listdir(folder):
        if n not in WORK_HOST_WRITES:
            out[n] = os.lstat(os.path.join(folder, n)).st_ctime_ns
    return out


def _status_moved(folder: bytes, mid: Dict[bytes, int]) -> str:
    """wasm: the reason (§6.7) if a status-change time recorded after the modes were set for the run moved during
    the run (read before the modes are set back), else ""."""
    try:
        now = _status_times(folder)
    except OSError as err:
        return WORK_HEAD + f"the folder could not be read again ({type(err).__name__})"
    moved = sorted(n for n in set(mid) | set(now) if mid.get(n) != now.get(n))
    parts = [("the folder" if n == b"" else _shown(n)) + ": " + _STATUS_WORDS for n in moved[:WORK_REASON_MAX]]
    if len(moved) > WORK_REASON_MAX:
        parts.append(f"and {len(moved) - WORK_REASON_MAX} more")
    return WORK_HEAD + "; ".join(parts) if parts else ""


def _fields(before: Dict[str, object], after: Dict[str, object], status: bool = True) -> str:
    """The fields that differ, named. The status-change time is named only when it is the one difference (with
    another one it adds nothing), and not at all with status=False."""
    out = []
    moved = False
    for k, v in before.items():
        w = after.get(k)
        if w == v:
            continue
        if k == "status":
            moved = status
        elif k == "kind":
            out.append("kind changed")
        elif k == "mode":
            out.append(f"mode {oct(v)} -> {oct(w)}")
        elif k in ("names", "size", "owner", "group"):
            out.append(f"{k} {v} -> {w}")
        elif k == "time":
            out.append("modification time changed")
        else:
            out.append(f"{k} changed")
    if moved and not out:
        out.append(_STATUS_WORDS)
    return ", ".join(out)


def work_changes(work: str, before: Dict[str, object], status: bool = True) -> str:
    """After the run: "" if the work folder holds exactly what `before` recorded, else the reason of an ERROR naming
    the differences (at most WORK_REASON_MAX, sorted by name, the others counted). Never raises. status=False: the
    status-change times are not compared (wasm: the host itself changes the modes for the run and sets them back)."""
    head = WORK_HEAD
    folder = os.fsencode(work)
    try:
        diffs: List[Tuple[bytes, str]] = []
        extra = 0
        old = before["entries"]
        seen = set()
        with os.scandir(folder) as it:
            for e in it:
                n = e.name
                if n in old:
                    seen.add(n)
                    try:
                        what = _fields(old[n], _entry_record(folder, n, old[n].get("size")), status)
                    except FileNotFoundError:
                        what = "removed while the folder was read"
                    if what:
                        bisect.insort(diffs, (n, f"{_shown(n)}: {what}"))
                        if len(diffs) > WORK_REASON_MAX:
                            diffs.pop()
                            extra += 1
                    continue
                if len(diffs) >= WORK_REASON_MAX and n > diffs[-1][0]:
                    extra += 1                   # only the first names in order are described
                    continue
                try:
                    k = _kind(os.lstat(os.path.join(folder, n)))
                except OSError as err:
                    k = f"entry ({type(err).__name__} at lstat)"
                bisect.insort(diffs, (n, f"{_shown(n)}: {k} the host did not put there"))
                if len(diffs) > WORK_REASON_MAX:
                    diffs.pop()
                    extra += 1
        for n in sorted(set(old) - seen):
            diffs.append((n, f"{_shown(n)}: missing"))
        st = os.lstat(folder)
        now = dict(_meta(st), time=st.st_mtime_ns)
        if _STATUS_TIME:
            now["status"] = st.st_ctime_ns
        what = _fields(before["folder"], now, status)
    except OSError as err:
        return head + f"the folder could not be read again ({type(err).__name__})"
    diffs.sort()
    if len(diffs) > WORK_REASON_MAX:
        extra += len(diffs) - WORK_REASON_MAX
        diffs = diffs[:WORK_REASON_MAX]
    parts = [d for _, d in diffs]
    if what:
        parts.append(f"the folder: {what}" + (" (an entry was created or removed)" if "modification time" in what else ""))
    if extra:
        parts.append(f"and {extra} more")
    return head + "; ".join(parts) if parts else ""


def read_stderr_tail(path: str, n: int = 600) -> str:
    """The last `n` bytes of <work>/stderr.txt, decoded (errors replaced), for the reason of an output without levels.
    Read after the check of the work folder (§6.7), so not through the name alone: only a regular file with one
    name, opened with O_NOFOLLOW | O_NONBLOCK and the same file as the lstat saw (where O_NOFOLLOW is missing the
    lstat decides); anything else gives "". Measured before this function, with the name replaced by a link to a
    file of the user right after the check: the last bytes of that file were in the reason."""
    fd = -1
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode):        # one name: checked on the descriptor below
            return ""
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                     | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0))
        fs = os.fstat(fd)
        if not (stat.S_ISREG(fs.st_mode) and fs.st_nlink == 1 and (fs.st_dev, fs.st_ino) == (st.st_dev, st.st_ino)):
            return ""
        os.lseek(fd, max(0, fs.st_size - n), os.SEEK_SET)
        return os.read(fd, n).decode("utf-8", "replace")
    except OSError:
        return ""
    finally:
        if fd >= 0:
            os.close(fd)


def remove_tree(path: str) -> None:
    """Removes the folder `path` and what it holds; never raises, never follows a link. Up to 0.3.0 the folders were
    removed with shutil.rmtree(ignore_errors=True), measured on the work folder after a run (§6.7): a folder left
    without the owner's read, write or search permission (modes 000, 0300, 0400, 0500, at the top or inside) stayed in
    the temporary directory; on Python 3.11 a tree of 1 200 folders one inside the other made rmtree raise
    RecursionError out of run_port. Here (POSIX with descriptors: Linux, macOS) without recursion and never more than
    two levels below the top: each folder is opened with O_DIRECTORY | O_NOFOLLOW relative to its parent and given the
    owner's rwx through that descriptor (Linux, when it cannot be opened for reading: through an O_PATH descriptor and
    /proc/self/fd, or fchmodat2 where there is no /proc; macOS: fchmodat without following); for each folder in the
    top, its entries that are not folders are removed and its folders moved up into the top (rename relative to the
    two descriptors, under a name not in use), then it is removed; this until the top holds no folder (_remove_tree_fd).
    Elsewhere (Windows):
    shutil.rmtree(ignore_errors=True), RecursionError caught. What a process still running writes there meanwhile
    (one that left the engine's process group: §6.3) can keep the folder from being removed: the removal is tried
    again after each of REMOVE_PAUSES seconds, then the folder stays. The whole call ends within REMOVE_SECONDS plus
    the time of one step (measured before this cap, with a process making folders one inside the other for 3 s and
    9 s: the call followed it down and returned after 8.5 s and 19.5 s): the walk stops at that time and the folder
    stays. A path whose last part is not a name (it ends with a separator, "." or "..") is not removed: the system
    resolves a link there, O_NOFOLLOW or not (measured before this rule: with the top a link to a folder of the user
    and the path given with a final "/", what that folder held was removed)."""
    if os.path.basename(path) in ("", ".", ".."):
        return
    end = time.monotonic() + REMOVE_SECONDS
    for pause in (0.0,) + REMOVE_PAUSES:
        if pause and time.monotonic() + pause >= end:
            return
        time.sleep(pause)
        try:
            if _FD_REMOVAL:
                _remove_tree_fd(path, end)
            else:
                shutil.rmtree(path, ignore_errors=True)
        except (OSError, RecursionError, ValueError):
            pass
        if not os.path.lexists(path):
            return


REMOVE_PAUSES = (0.05, 0.1, 0.2)   # seconds before each new try of remove_tree (a writer that outlived the run)
REMOVE_SECONDS = 30.0              # seconds after which remove_tree stops walking (a writer it would follow down)


_FD_REMOVAL = (os.name == "posix" and hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW")
               and os.open in os.supports_dir_fd and os.unlink in os.supports_dir_fd
               and os.rmdir in os.supports_dir_fd and os.rename in os.supports_dir_fd
               and os.stat in os.supports_dir_fd and os.scandir in os.supports_fd)
# whether os.chmod can change a name relative to a folder without following a link (macOS: fchmodat), read once at
# import: a property of the platform. Read at each call before (CI 2026-11-22, macOS): a test that replaces os.chmod
# to record the calls made it False, since the replacement is in neither set, and the call it watches never came
_CHMOD_AT_NOFOLLOW = os.chmod in os.supports_follow_symlinks and os.chmod in os.supports_dir_fd
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def _owner_rwx_unopened(name: str, dir_fd: Optional[int]) -> None:
    """Gives the folder `name` (in `dir_fd`; the top folder: None) the owner's rwx without following a link, when it
    cannot be opened. On Linux never a chmod by name: between an lstat and that chmod the name can become something else
    (measured on the top folder, changed by name after an lstat: the folder of the user a link named got the rwx;
    measured on 2026-11-21 with fchmodat2 by name and AT_SYMLINK_NOFOLLOW: a link is refused, but a second name of a
    file of the user put there after the lstat took the mode, 0640 to 0700, and to 0777 from a folder left 077).
    Linux: an O_PATH | O_DIRECTORY | O_NOFOLLOW descriptor, its fstat, then the mode set on that descriptor: through
    /proc/self/fd, or without /proc through the fchmodat2 system call with AT_EMPTY_PATH (Linux 6.6 and later),
    called with ctypes because os.chmod is not in os.supports_follow_symlinks on Linux (Python 3.11 to 3.14 where
    this was measured) and os.fchmod refuses an O_PATH descriptor. Where no way exists (an older kernel without
    /proc: ENOSYS; no ctypes) the folder is left as it is, and stays. macOS has no O_PATH: there fchmodat by name
    without following a link, after an lstat (a file put under that name in between would take the mode; not
    measured on macOS)."""
    by_proc = os.path.isdir("/proc/self/fd")
    if hasattr(os, "O_PATH") and (by_proc or _FCHMODAT2 is not None):
        pfd = os.open(name, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd)
        try:
            st = os.fstat(pfd)
            if stat.S_ISDIR(st.st_mode):
                if by_proc:
                    os.chmod(f"/proc/self/fd/{pfd}", stat.S_IMODE(st.st_mode) | 0o700)
                else:
                    _fchmodat2_nofollow("", pfd, stat.S_IMODE(st.st_mode) | 0o700)
        finally:
            os.close(pfd)
    elif _CHMOD_AT_NOFOLLOW:
        st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if stat.S_ISDIR(st.st_mode):
            os.chmod(name, stat.S_IMODE(st.st_mode) | 0o700, dir_fd=dir_fd, follow_symlinks=False)


def _fchmodat2_number(platform: str, machine: str) -> Optional[int]:
    """The number of the fchmodat2 system call (Linux 6.6), or None where this module does not call it. 452 in the
    tables of x86-64 and i386, of arm64 (the generic table) and of 32-bit arm (read at kernel.org on 2026-11-21); the
    list of machines is closed because a table can differ (alpha: 562) and a wrong number is another system call."""
    return 452 if platform.startswith("linux") and machine in ("x86_64", "aarch64") else None


_FCHMODAT2 = _fchmodat2_number(sys.platform, os.uname().machine if hasattr(os, "uname") else "")


def _fchmodat2_nofollow(name: str, dir_fd: Optional[int], mode: int) -> None:
    """chmod that never follows a link, of `name` relative to `dir_fd` (None: AT_FDCWD), or of what the descriptor
    `dir_fd` itself is when `name` is "" (AT_EMPTY_PATH; also an O_PATH descriptor): OSError otherwise, also where
    ctypes or the C library's syscall() is missing (ENOSYS)."""
    import errno
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        syscall = libc.syscall
    except (ImportError, AttributeError) as err:
        raise OSError(errno.ENOSYS, "fchmodat2: no ctypes or no syscall() in the C library", name) from err
    syscall.restype = ctypes.c_long
    r = syscall(ctypes.c_long(_FCHMODAT2), ctypes.c_int(-100 if dir_fd is None else dir_fd),
                ctypes.c_char_p(os.fsencode(name)), ctypes.c_uint(mode), ctypes.c_int(0x100 | 0x1000))
    if r != 0:
        e = ctypes.get_errno()
        raise OSError(e, os.strerror(e), name)


def _open_dir(name: str, dir_fd: Optional[int]) -> int:
    """A descriptor of the folder `name` (never through a link) with the owner's rwx on it."""
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=dir_fd)
    except PermissionError:
        _owner_rwx_unopened(name, dir_fd)
        fd = os.open(name, _DIR_FLAGS, dir_fd=dir_fd)
    try:
        st = os.fstat(fd)
        if stat.S_IMODE(st.st_mode) & 0o700 != 0o700:
            os.fchmod(fd, stat.S_IMODE(st.st_mode) | 0o700)
    except OSError:
        os.close(fd)
        raise
    return fd


def _remove_tree_fd(top: str, end: float = float("inf")) -> None:
    """One try. TimeoutError (an OSError) when time.monotonic() passes `end`: checked at each folder and each entry.
    No step is more than two levels below the top, and ".." is never opened: each folder inside a folder of the top is
    moved up into the top before it is emptied in its turn. Up to 0.3.1 before the CI of 2026-11-22 the tree was walked
    down and back up through ".." (one folder at a time, ".." checked to be the folder the walk came from): on macOS
    (CI, Python 3.12 and 3.14) a tree of 5 000 folders one inside the other, made by the test through descriptors in
    43 s and 53 s, was not removed within REMOVE_SECONDS (the walk stopped at 30 s and the folder stayed), while one of
    1 200 was removed; on Linux the same tree takes a fraction of a second. A folder that cannot be opened, emptied or
    moved stays where it is, and so does the top."""
    fd = _open_dir(top, None)
    # the names of the folders moved up, never reused in a try. One in use: the move fails (a file, a folder that is
    # not empty) or replaces an empty folder of the tree; what is in use is emptied in the same round, so the next
    # round moves what is left
    numbers = itertools.count()
    try:
        while True:
            _check_end(end)
            subs = _empty_files(fd, end)
            if not subs:
                break
            progress = False
            for sub in subs:
                _check_end(end)
                try:
                    cfd = _open_dir(sub, fd)
                except OSError:
                    continue                                  # left where it is
                try:
                    for name in _empty_files(cfd, end):
                        _check_end(end)
                        try:
                            os.close(_open_dir(name, cfd))    # its rwx: moving a folder to another parent writes its ".."
                            os.rename(name, f".rigorous_levels_rm_{next(numbers)}", src_dir_fd=cfd, dst_dir_fd=fd)
                        except OSError:
                            pass
                finally:
                    os.close(cfd)
                try:
                    os.rmdir(sub, dir_fd=fd)
                    progress = True
                except OSError:
                    pass
            if not progress:
                break                                         # what is left stays: the rmdir below fails
    finally:
        os.close(fd)
    os.rmdir(top)


def _check_end(end: float) -> None:
    if time.monotonic() > end:
        raise TimeoutError("remove_tree: over REMOVE_SECONDS")


def _empty_files(fd: int, end: float) -> List[str]:
    """Removes every entry of the folder `fd` that is not a folder (a link is removed, never followed); returns the
    names of its folders. The folder is listed through a new descriptor of ".", opened relative to `fd`: os.scandir on
    `fd` itself shares its position with the listings before (measured on btrfs, Python 3.12: a folder listed once,
    then changed, was listed again as empty)."""
    subs = []
    lfd = os.open(".", _DIR_FLAGS, dir_fd=fd)
    try:
        with os.scandir(lfd) as it:
            for e in it:
                _check_end(end)
                try:
                    if e.is_dir(follow_symlinks=False):
                        subs.append(e.name)
                    else:
                        os.unlink(e.name, dir_fd=fd)
                except OSError:
                    pass
    finally:
        os.close(lfd)
    return subs


def _run_wasm(work: str, out_path: str, seconds: int, site_packages: List[str], stderr_path: str):
    facts = probe("wasm")
    # the output file must be writable: WASI pre-opens folders, so the work folder is pre-opened read-only and the
    # output file lives alone in a second, writable folder bound at /work/output.json's parent... WASI cannot bind a
    # single file: the runner writes <folder>/output.json, so a writable folder holding only that file is pre-opened
    outdir = os.path.dirname(out_path)
    # no site-packages under WASI (native wheels cannot load there; pre-opens are read-write): pure Python only.
    # The work folder is made non-writable for the run (pre-opens are read-write); after it the folder and the files
    # the host put there get back the modes recorded here, each only on the file it was recorded for (§6.7).
    saved = []
    for n in sorted(os.listdir(work)):
        p = os.path.join(work, n)
        st = os.lstat(p)
        if stat.S_ISREG(st.st_mode) and st.st_nlink == 1:
            saved.append((p, stat.S_IMODE(st.st_mode), (st.st_dev, st.st_ino)))
            _chmod_regular_file(p, 0o444, (st.st_dev, st.st_ino))
    work_mode = stat.S_IMODE(os.lstat(work).st_mode)
    os.chmod(work, 0o555)
    # the status-change times are recorded here, after the modes are set for the run, and read again before they are
    # set back: run() cannot compare them (the host itself changes them), so they are compared here (§6.7)
    folder = os.fsencode(work)
    mid = _status_times(folder) if _STATUS_TIME else {}
    if mid:
        _wait_clock_past(folder, max(mid.values()))
    moved = ""
    cmd = _wasm_cmd(facts["exe"], facts["folder"], [(work, "/work"), (outdir, "/out")],
                    seconds, {"HOME": "/nohome", "RIGOROUS_LEVELS_OUTPUT_DIR": "/out"})
    cmd += ["-I", "-S", "-B", "/work/" + RUNNER_NAME, "/work"]
    try:
        rc, timed_out = _run(cmd, seconds + 5, os.path.join(outdir, "stderr.txt"), {"PATH": os.environ.get("PATH", "")})
    finally:
        if mid:
            moved = _status_moved(folder, mid)
        os.chmod(work, work_mode)
        for p, mode, same in saved:
            _chmod_regular_file(p, mode, same)
    _copy_run_stderr(os.path.join(outdir, "stderr.txt"), stderr_path)
    return rc, timed_out, (f"wasmtime (WASI, no sockets, pre-opened folders only, max memory {WASM_MAX_MEMORY >> 20} MiB); "
                           f"CPython {facts['version'][0]}.{facts['version'][1]} for WASI: numpy {facts['numpy']}"), moved


# ── public contract ───────────────────────────────────────────────────────────────────────────────────────────────
def probe(engine: str, image: Optional[str] = None) -> Dict[str, object]:
    """Fail-closed check of one engine, cached per process: the measured facts, or SandboxMissing with the reason."""
    if engine not in ENGINE_ORDER:
        raise OutOfDomain(f"engine {engine!r} not in the closed list {ENGINES}")
    key = (engine, image or "")
    if key in _PROBES:
        return _PROBES[key]
    if engine in ("podman", "docker"):
        facts = _probe_container(engine, image or default_image())
    elif engine == "bwrap":
        facts = _probe_bwrap()
    elif engine == "sandbox-exec":
        facts = _probe_sandbox_exec()
    elif engine == "appcontainer":
        facts = _probe_appcontainer()
    else:
        facts = _probe_wasm()
    _PROBES[key] = facts
    return facts


def select_engine(image: Optional[str] = None) -> Tuple[str, Dict[str, str]]:
    """The first engine of ENGINE_ORDER whose probe passes, with the reasons of the ones skipped. SandboxMissing with
    every reason if none passes (never "no isolation")."""
    reasons: Dict[str, str] = {}
    for e in ENGINE_ORDER:
        try:
            probe(e, image)
            return e, reasons
        except (SandboxMissing, OutOfDomain) as err:
            reasons[e] = f"{type(err).__name__}: {err}"
    raise SandboxMissing("no isolation engine available: " + "; ".join(f"{k}: {v[:120]}" for k, v in reasons.items()))


def run(engine: str, work: str, out_path: str, seconds: int, mem_mib: int, site_packages: List[str],
        python: Optional[str] = None, image: Optional[str] = None) -> Tuple[Optional[int], bool, str, str]:
    """Runs `<work>/port_runner.py <work>` inside `engine`. Returns (return code or None, timed_out, description,
    limit): `limit` is the reason a cap enforced from the host was exceeded (memory, disk: sandbox-exec, appcontainer),
    "" otherwise; the description names an engine binary accepted only through RIGOROUS_LEVELS_TRUSTED_ENGINES.
    The work folder must be the same after the run (docs/PORT_CONTRACT.md §6.7): any entry the host did not put there,
    or any change to one it did, makes `limit` the reason naming them (the caller makes the outputs ERROR), before the
    reason of a cap. `stderr.txt` is created here, empty, before the folder is recorded."""
    with open(os.path.join(work, "stderr.txt"), "wb"):
        pass
    before = work_snapshot(work)
    res = _run_engine(engine, work, out_path, seconds, mem_mib, site_packages, python, image)
    rc, timed_out, descr = res[:3]
    limit = res[3] if len(res) > 3 else ""
    changed = work_changes(work, before, status=engine != "wasm")
    if changed:                                    # the wasm status-change reason adds nothing to another difference
        limit = changed + (f"; {limit}" if limit and not limit.startswith(WORK_HEAD) else "")
    vouched = _VOUCHED.get("wasmtime" if engine == "wasm" else engine)
    if vouched:
        descr += (f"; engine binary {vouched} is user-owned, accepted because RIGOROUS_LEVELS_TRUSTED_ENGINES lists it "
                  f"(processes of this user can replace it)")
    return rc, timed_out, descr, limit


def _run_engine(engine: str, work: str, out_path: str, seconds: int, mem_mib: int, site_packages: List[str],
                python: Optional[str], image: Optional[str]) -> Tuple[Optional[int], bool, str]:
    if engine not in ENGINE_ORDER:
        raise OutOfDomain(f"engine {engine!r} not in the closed list {ENGINES}")
    stderr_path = os.path.join(work, "stderr.txt")
    sp = [os.path.realpath(p) for p in site_packages]
    if engine == "bwrap":
        return _run_bwrap(work, out_path, seconds, sp, python, stderr_path)
    if engine in ("podman", "docker"):
        if python is not None:
            raise OutOfDomain("python: only for the native engines (a container runs the interpreter of its image)")
        return _run_container(engine, image or default_image(), work, out_path, seconds, sp, stderr_path)
    if engine == "sandbox-exec":
        return _run_sandbox_exec(work, out_path, seconds, mem_mib, sp, python, stderr_path)
    if engine == "appcontainer":
        return _run_appcontainer(work, out_path, seconds, mem_mib, sp, python, stderr_path)
    if python is not None:
        raise OutOfDomain("python: only for the native engines (wasm runs CPython for WASI)")
    return _run_wasm(work, out_path, seconds, sp, stderr_path)
