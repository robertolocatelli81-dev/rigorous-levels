# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra/isolation.py — the ISOLATION ENGINES of the multiport (docs/PORT_CONTRACT.md §6), one closed contract:

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

import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional, Tuple

from qraft_ra.guaranteed_intervals import OutOfDomain

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


def _run(cmd: List[str], timeout: float, stderr_path: str, env: Dict[str, str]) -> Tuple[Optional[int], bool]:
    """stdout discarded and stderr to a file: an unbounded stream never enters the memory of the trusted side."""
    try:
        with open(stderr_path, "wb") as ferr:
            p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=ferr, env=env,
                               timeout=timeout)
        return p.returncode, False
    except subprocess.TimeoutExpired:
        return None, True


# ── bwrap (Linux) ──────────────────────────────────────────────────────────────────────────────────────────────────
def _bwrap() -> str:
    b = shutil.which("bwrap")
    if b is None:
        raise SandboxMissing("bwrap (bubblewrap) not found: no execution of external code (fail-closed)")
    st = os.stat(os.path.realpath(b))
    if st.st_uid != 0 or st.st_mode & 0o022:          # a user-writable «bwrap» on PATH is not a sandbox
        raise SandboxMissing(f"bwrap {b!r} is not owned by root or is writable by others: no execution (fail-closed)")
    return b


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
    return exe


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
    open('/usr/qraft_probe', 'w').close(); root_ro = False
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
    work = tempfile.mkdtemp(prefix="qraft_probe_")
    try:
        with open(os.path.join(work, "probe.py"), "w", encoding="utf-8") as f:
            f.write(PROBE_CODE)
        out = os.path.join(work, "output.json")
        open(out, "wb").close()
        name = "qraft_probe_" + secrets.token_hex(6)
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
    name = "qraft_port_" + secrets.token_hex(6)
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
    return exe


def _sb_literal(p: str) -> str:
    return '"' + p.replace("\\", "\\\\").replace('"', '\\"') + '"'


def seatbelt_profile(python: str, readable: List[str], out_path: str, scratch: str) -> str:
    """Deny-default Seatbelt profile: read everything except the user's homes (then the declared pieces inside
    them), write only the output file and a scratch folder, no network, fork/exec of the interpreter only."""
    lines = ["(version 1)", "(deny default)", "(allow file-read-metadata)", "(allow file-read*)", "(allow sysctl-read)",
             "(allow process-fork)", "(allow signal (target self))",
             "(allow mach-lookup (global-name \"com.apple.system.opendirectoryd.libinfo\") "
             "(global-name \"com.apple.system.logger\") (global-name \"com.apple.system.notification_center\"))",
             f"(allow process-exec (literal {_sb_literal(os.path.realpath(python))}))",
             "(allow file-write-data (literal \"/dev/null\") (literal \"/dev/zero\"))"]
    for home in _user_homes():
        lines.append(f"(deny file-read* (subpath {_sb_literal(home)}))")
    for p in readable:                                   # later rules win: the declared pieces inside a home
        lines.append(f"(allow file-read* (subpath {_sb_literal(os.path.realpath(p))}))")
    lines.append(f"(allow file-write* (literal {_sb_literal(os.path.realpath(out_path))}))")
    lines.append(f"(allow file-write* (subpath {_sb_literal(os.path.realpath(scratch))}))")
    lines.append("(deny network*)")
    return "\n".join(lines) + "\n"


def _probe_sandbox_exec() -> Dict[str, object]:
    exe = _sandbox_exec()
    scratch = tempfile.mkdtemp(prefix="qraft_sb_")
    try:
        probe = os.path.join(scratch, "probe.py")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("import os, socket, sys, json\n"
                    "try:\n    socket.create_connection(('127.0.0.1', 9), timeout=1); net = 'open'\n"
                    "except OSError as e:\n    net = type(e).__name__\n"
                    "try:\n    open('/usr/qraft_probe', 'w').close(); root_ro = False\nexcept OSError:\n    root_ro = True\n"
                    "print(json.dumps({'net': net, 'root_ro': root_ro, 'home': os.path.isdir(sys.argv[1])}))\n")
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
    facts.update(engine="sandbox-exec", exe=exe)
    return facts


def _run_sandbox_exec(work: str, out_path: str, seconds: int, site_packages: List[str], python: str, stderr_path: str):
    exe = probe("sandbox-exec")["exe"]
    python = os.path.realpath(python or sys.executable)
    scratch = tempfile.mkdtemp(prefix="qraft_sb_")
    try:
        prof = seatbelt_profile(python, [sys.base_prefix, os.path.dirname(os.path.dirname(python)), work, *site_packages],
                                out_path, scratch)
        pf = os.path.join(scratch, "profile.sb")
        with open(pf, "w", encoding="utf-8") as f:
            f.write(prof)
        env = dict(SANDBOX_ENV, TMPDIR=scratch, QRAFT_OUTPUT_DIR=os.path.dirname(out_path))
        cmd = [exe, "-f", pf, python, "-I", "-S", "-B", os.path.join(work, RUNNER_NAME), work]
        rc, timed_out = _run(cmd, seconds + 5, stderr_path, env)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return rc, timed_out, "sandbox-exec deny-default profile: no network, read-only except output, homes hidden"


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
    hr = userenv.CreateAppContainerProfile(name, name, "qraft-ra multiport sandbox", None, 0, ctypes.byref(sid))
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


def _run_appcontainer_process(ctypes, wintypes, sid, cmdline: str, env: Dict[str, str], cwd: str, seconds: int,
                              mem_mib: int, stderr_path: str) -> Tuple[Optional[int], bool]:
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
    envblock = "".join(f"{k}={v}\0" for k, v in env.items()) + "\0"
    EXTENDED_STARTUPINFO_PRESENT, CREATE_SUSPENDED, CREATE_NO_WINDOW, CREATE_UNICODE_ENVIRONMENT = 0x80000, 0x4, 0x8000000, 0x400
    ok = k32.CreateProcessW(None, ctypes.create_unicode_buffer(cmdline), None, None, True,
                            EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT,
                            ctypes.create_unicode_buffer(envblock), cwd, ctypes.byref(si), ctypes.byref(pi))
    k32.CloseHandle(herr)
    k32.CloseHandle(hnul)
    if not ok:
        raise SandboxMissing(f"appcontainer: CreateProcessW failed ({ctypes.get_last_error()})")
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
    k32.ResumeThread(pi.hThread)
    WAIT_TIMEOUT = 0x102
    w = k32.WaitForSingleObject(pi.hProcess, int((seconds + 5) * 1000))
    timed_out = w == WAIT_TIMEOUT
    if timed_out:
        k32.TerminateJobObject(job, 1)
    code = wintypes.DWORD()
    k32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
    for h in (pi.hThread, pi.hProcess, job):
        k32.CloseHandle(h)
    return (None if timed_out else int(code.value)), timed_out


def _probe_appcontainer() -> Dict[str, object]:
    ctypes, wintypes = _win()
    sid, sid_str = _appcontainer_sid(ctypes, wintypes, "qraft-ra-multiport")
    scratch = tempfile.mkdtemp(prefix="qraft_ac_")
    try:
        for p in (sys.base_prefix, sys.prefix):
            _icacls(p, sid_str, "RX")
        _icacls(scratch, sid_str, "M")
        probe = os.path.join(scratch, "probe.py")
        home = _user_homes()[0]
        with open(probe, "w", encoding="utf-8") as f:
            f.write("import os, socket, sys, json\n"
                    "try:\n    socket.create_connection(('127.0.0.1', 9), timeout=1); net = 'open'\n"
                    "except OSError as e:\n    net = type(e).__name__\n"
                    "try:\n    open(os.path.join(os.environ['SYSTEMROOT'], 'qraft_probe'), 'w').close(); root_ro = False\n"
                    "except OSError:\n    root_ro = True\n"
                    "try:\n    os.listdir(sys.argv[1]); home = True\nexcept OSError:\n    home = False\n"
                    "open(sys.argv[2], 'w').write(json.dumps({'net': net, 'root_ro': root_ro, 'home': home}))\n")
        out = os.path.join(scratch, "out.json")
        env = {"SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"), "PATH": os.environ.get("SYSTEMROOT", r"C:\Windows"),
               "USERPROFILE": os.path.join(scratch, "nohome"), "HOME": os.path.join(scratch, "nohome"),
               "TEMP": scratch, "TMP": scratch, "PYTHONDONTWRITEBYTECODE": "1"}
        cmdline = subprocess.list2cmdline([sys.executable, "-I", "-S", "-B", probe, home, out])
        rc, timed_out = _run_appcontainer_process(ctypes, wintypes, sid, cmdline, env, scratch, 60, 1024,
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
    facts.update(engine="appcontainer", sid=sid_str)
    return facts


def _run_appcontainer(work: str, out_path: str, seconds: int, mem_mib: int, site_packages: List[str], python: str,
                      stderr_path: str):
    ctypes, wintypes = _win()
    facts = probe("appcontainer")
    sid, sid_str = _appcontainer_sid(ctypes, wintypes, "qraft-ra-multiport")
    python = os.path.realpath(python or sys.executable)
    for p in [os.path.dirname(os.path.dirname(python)), *site_packages, work]:
        _icacls(p, sid_str, "RX")
    _icacls(out_path, sid_str, "M")
    scratch = tempfile.mkdtemp(prefix="qraft_ac_")
    _icacls(scratch, sid_str, "M")
    try:
        env = {"SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"), "PATH": os.environ.get("SYSTEMROOT", r"C:\Windows"),
               "USERPROFILE": os.path.join(scratch, "nohome"), "HOME": os.path.join(scratch, "nohome"),
               "TEMP": scratch, "TMP": scratch, "PYTHONDONTWRITEBYTECODE": "1", "OMP_NUM_THREADS": "1",
               "OPENBLAS_NUM_THREADS": "1", "QRAFT_OUTPUT_DIR": os.path.dirname(out_path)}
        cmdline = subprocess.list2cmdline([python, "-I", "-S", "-B", os.path.join(work, RUNNER_NAME), work])
        rc, timed_out = _run_appcontainer_process(ctypes, wintypes, sid, cmdline, env, scratch, seconds, mem_mib, stderr_path)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return rc, timed_out, f"appcontainer {facts['sid']} + job object (memory, 16 processes, CPU time): no network, " \
                          f"reads only the granted folders, writes only the output file"


# ── WebAssembly (wasmtime + CPython for WASI) ─────────────────────────────────────────────────────────────────────
def _wasm_parts() -> Tuple[str, str]:
    """(wasmtime executable, folder with python.wasm and lib/) from PATH and QRAFT_PYTHON_WASM: never downloaded."""
    exe = shutil.which("wasmtime")
    if exe is None:
        raise SandboxMissing("wasmtime not found: no execution of external code (fail-closed)")
    folder = os.environ.get("QRAFT_PYTHON_WASM", "")
    if not folder or not os.path.isfile(os.path.join(folder, "python.wasm")) or not os.path.isdir(os.path.join(folder, "lib")):
        raise SandboxMissing("QRAFT_PYTHON_WASM must point to a folder with python.wasm and lib/ (a CPython WASI build)")
    folder = os.path.realpath(folder)
    # wasmtime pre-opens folders read-write (no read-only flag in wasmtime 50): the interpreter folder must be
    # non-writable by this user, so that the guest cannot alter the next run's interpreter (fail-closed otherwise)
    if any(os.access(p, os.W_OK) for p in (folder, os.path.join(folder, "lib"), os.path.join(folder, "python.wasm"))):
        raise SandboxMissing(f"QRAFT_PYTHON_WASM {folder!r} is writable by this user: make it read-only (chmod -R a-w)")
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
    scratch = tempfile.mkdtemp(prefix="qraft_wasm_")
    try:
        with open(os.path.join(scratch, "probe.py"), "w", encoding="utf-8") as f:
            f.write("import json, os, sys\n"
                    "try:\n    import socket; socket.create_connection(('127.0.0.1', 9), timeout=1); net = 'open'\n"
                    "except Exception as e:\n    net = type(e).__name__\n"
                    "try:\n    open('/lib/qraft_probe', 'w').close(); root_ro = False\nexcept OSError:\n    root_ro = True\n"
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


def _run_wasm(work: str, out_path: str, seconds: int, site_packages: List[str], stderr_path: str):
    facts = probe("wasm")
    # the output file must be writable: WASI pre-opens folders, so the work folder is pre-opened read-only and the
    # output file lives alone in a second, writable folder bound at /work/output.json's parent... WASI cannot bind a
    # single file: the runner writes <folder>/output.json, so a writable folder holding only that file is pre-opened
    outdir = os.path.dirname(out_path)
    # no site-packages under WASI (native wheels cannot load there; pre-opens are read-write): pure Python only.
    # The work folder is made non-writable for the run (pre-opens are read-write) and restored for the cleanup.
    for root, dirs, files in os.walk(work):
        for n in files:
            os.chmod(os.path.join(root, n), 0o444)
    os.chmod(work, 0o555)
    cmd = _wasm_cmd(facts["exe"], facts["folder"], [(work, "/work"), (outdir, "/out")],
                    seconds, {"HOME": "/nohome", "QRAFT_OUTPUT_DIR": "/out"})
    cmd += ["-I", "-S", "-B", "/work/" + RUNNER_NAME, "/work"]
    try:
        rc, timed_out = _run(cmd, seconds + 5, os.path.join(outdir, "stderr.txt"), {"PATH": os.environ.get("PATH", "")})
    finally:
        os.chmod(work, 0o755)
        for root, dirs, files in os.walk(work):
            for n in files:
                os.chmod(os.path.join(root, n), 0o644)
    shutil.copy(os.path.join(outdir, "stderr.txt"), stderr_path)
    return rc, timed_out, (f"wasmtime (WASI, no sockets, pre-opened folders only, max memory {WASM_MAX_MEMORY >> 20} MiB); "
                           f"CPython {facts['version'][0]}.{facts['version'][1]} for WASI: numpy {facts['numpy']}")


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
        python: Optional[str] = None, image: Optional[str] = None) -> Tuple[Optional[int], bool, str]:
    """Runs `<work>/port_runner.py <work>` inside `engine`. Returns (return code or None, timed_out, description)."""
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
        return _run_sandbox_exec(work, out_path, seconds, sp, python, stderr_path)
    if engine == "appcontainer":
        return _run_appcontainer(work, out_path, seconds, mem_mib, sp, python, stderr_path)
    if python is not None:
        raise OutOfDomain("python: only for the native engines (wasm runs CPython for WASI)")
    return _run_wasm(work, out_path, seconds, sp, stderr_path)
