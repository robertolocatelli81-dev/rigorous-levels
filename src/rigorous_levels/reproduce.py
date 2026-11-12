# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""rigorous_levels/reproduce.py — re-measure the numerical claims of README.md, offline, from a clean install:

    python -m rigorous_levels.reproduce             # the fast claims (target < 60 s): one line [PASS]/[FAIL] per claim with
                                             # the measured value and the published one; exit 0 iff every line is PASS
    python -m rigorous_levels.reproduce --full      # also the claims that take minutes (the 200-case benches of bench/)
    python -m rigorous_levels.reproduce --sabotage  # positive control: a solver is deliberately altered, at least one FAIL
    python -m rigorous_levels.reproduce --readme    # no computation: every published value must appear verbatim in README.md
                                             # (check_tree.py runs this: a number edited by hand fails the check)
    python -m rigorous_levels.reproduce --hash      # sha256 of a fixed set of guaranteed intervals (exact strings): the
                                             # determinism check across interpreters and platforms (CI prints it)

Each claim carries the README sentence fragment it reproduces (`published`), so that the README and this file cannot
drift apart silently. Claims whose other side is optional (scqubits, scipy nightly) are [SKIP] with the reason when
the dependency is absent; timings are [INFO] (machine-dependent, never PASS/FAIL)."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
import time
from fractions import Fraction
from typing import Callable, List, Optional, Tuple

README = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "README.md")

# (name, published strings that must appear in README.md, function returning (ok, measured text) or None to skip,
#  slow?)  — the functions import their dependencies lazily so that --readme and check_tree need nothing installed
CLAIMS: List[Tuple[str, Tuple[str, ...], Callable[[], Optional[Tuple[bool, str]]], bool]] = []


def claim(name, published, slow=False):
    def deco(fn):
        CLAIMS.append((name, tuple(published), fn, slow))
        return fn
    return deco


def _flint():
    return importlib.util.find_spec("flint") is not None


@claim("README example: f01 of the transmon E_C 0.2, E_J 10, n_g 0.3 = 3.788378597 (both ends at 9 decimals), GUARANTEED",
       ("GUARANTEED 3.788378597 3.788378597",))
def _example():
    if not _flint():
        return None
    from rigorous_levels import Rotor, guaranteed_levels
    iv = guaranteed_levels(Rotor.transmon(0.2, 10.0, n_g=0.3), 4)
    lo, hi = iv.transition(0, 1)
    s = f"{iv.state} {float(lo):.9f} {float(hi):.9f}"
    return s == "GUARANTEED 3.788378597 3.788378597", s


@claim("README example: scqubits at ncut 30 is NOT_CONVERGED at E_J/E_C = 2e4", ("NOT_CONVERGED",))
def _example_scq():
    if importlib.util.find_spec("scqubits") is None:
        return None
    from rigorous_levels import Rotor, scqubits_spectrum
    w = scqubits_spectrum(Rotor.transmon(1.0, 2e4), 6, 30, check="doubling")
    return w.state == "NOT_CONVERGED", w.state


@claim("Mathieu a_0(1) contains the tabulated value -0.45513860 (A&S 20.1) with width < 1e-12", ("a_0(1)",))
def _a01():
    if not _flint():
        return None
    from rigorous_levels import mathieu_a
    v = mathieu_a(0, 1.0)
    return abs(float(v.low) + 0.45513860) < 5e-9 and v.max_width < 1e-12, f"{v.strings} width {v.max_width:.1e}"


@claim("Mathieu a_11(299): interval [123.9949…], where scipy 1.17.1/1.18.1 give 232.195", ("[123.9949", "232.195"))
def _a11():
    if not _flint():
        return None
    from rigorous_levels import mathieu_a
    v = mathieu_a(11, 299.0)
    ok = v.strings[0].startswith("123.9949") and v.state == "GUARANTEED"
    try:
        from scipy.special import mathieu_a as sa
        import scipy
        s = float(sa(11, 299.0))
        return ok and (abs(s - 232.195) < 0.01 or tuple(int(x) for x in scipy.__version__.split(".")[:2]) >= (2, 0)), \
            f"ours {v.strings[0][:12]}; scipy {scipy.__version__} gives {s:.3f}"
    except ImportError:
        return ok, v.strings[0][:12]


@claim("Mathieu grid r ≤ 12, q = −400…400 step 0.5: 40 025 values, 40 025 GUARANTEED, 0 WIDE; scipy 1.17.1 and 1.18.1 wrong in 52, 2.0.0.dev in 0",
       ("40 025 `GUARANTEED`", "0 `WIDE`", "52 wrong", "0 in"), slow=True)
def _grid():
    if not _flint():
        return None
    import scipy
    from scipy.special import mathieu_a, mathieu_b
    from rigorous_levels import mathieu_value
    wide = wrong = total = 0
    for i in range(1601):
        q = -400.0 + 0.5 * i
        for r in range(13):
            for kind in ("a", "b"):
                if kind == "b" and r == 0:
                    continue
                v = mathieu_value(kind, r, q)
                total += 1
                wide += v.state != "GUARANTEED"
                s = float(mathieu_a(r, q) if kind == "a" else mathieu_b(r, q))
                tol = 1e-9 * max(1.0, abs(float(v.low)))
                wrong += not (float(v.low) - tol <= s <= float(v.high) + tol)
    ver = tuple(int(x) for x in scipy.__version__.split(".")[:2])
    expected = 0 if ver >= (2, 0) else 52
    return (total, wide, wrong) == (40025, 0, expected), f"{total} values, {wide} WIDE, scipy {scipy.__version__} wrong {wrong} (expected {expected})"


@claim("fluxonium Zhang 2021 (E_C 0.479, E_J 3.395, E_L 0.132, flux ½): f01 in [13.8815576, 13.8815586] MHz, N = 117",
       ("13.8815576", "13.8815586", "117"))
def _zhang():
    if not _flint():
        return None
    from rigorous_levels import Fluxonium, guaranteed_fluxonium_levels
    iv = guaranteed_fluxonium_levels(Fluxonium(E_C=0.479, E_J=3.395, E_L=0.132, flux=0.5), 3, 1e-9)
    lo, hi = (float(x) * 1e3 for x in iv.transition(0, 1))
    return iv.state == "GUARANTEED" and f"{lo:.7f}" == "13.8815576" and f"{hi:.7f}" == "13.8815586" and iv.N == 117, \
        f"{iv.state} [{lo:.7f}, {hi:.7f}] MHz, N = {iv.N}"


@claim("fluxonium Moskalenko 2022 A (0.567 / 2.052 / 0.835, flux ½): f01 685.731 MHz (measured 688.224), f12 1831.204 MHz (measured 1832)",
       ("685.73", "688.22", "1831.20", "1832"))
def _moskalenko():
    if not _flint():
        return None
    from rigorous_levels import Fluxonium, guaranteed_fluxonium_levels
    iv = guaranteed_fluxonium_levels(Fluxonium(E_C=0.567, E_J=2.052, E_L=0.835, flux=0.5), 3, 1e-9)
    f01 = float(sum(iv.transition(0, 1)) / 2) * 1e3
    f12 = float(sum(iv.transition(1, 2)) / 2) * 1e3
    return abs(f01 - 685.731) < 1e-3 and abs(f12 - 1831.204) < 1e-3, f"f01 {f01:.3f} MHz, f12 {f12:.3f} MHz"


@claim("parameter box E_C, E_J ± 1 % around (0.3, 15): GUARANTEED, rho = 0.15 GHz", ("rho = 0.15",))
def _box():
    if not _flint():
        return None
    from rigorous_levels import RotorBall, guaranteed_levels_over_box
    iv = guaranteed_levels_over_box(RotorBall.transmon((0.297, 0.303), (14.85, 15.15), n_g=0.25), 4)
    return iv.state == "GUARANTEED" and abs(iv.alpha - 0.15) < 1e-12, f"{iv.state} rho {iv.alpha}"


@claim("matrix element |<0|n|1>| of the transmon (0.3, 15, 0.25) = 1.08780085731 with width < 1e-13", ("1.08780085731",))
def _nmat():
    if not _flint():
        return None
    from rigorous_levels import Rotor, guaranteed_matrix_element
    e = guaranteed_matrix_element(Rotor.transmon(0.3, 15.0, n_g=0.25), 0, 1, "n")
    return f"{abs(e.value):.11f}" == "1.08780085731" and e.max_width < 1e-13, f"{abs(e.value):.11f} width {e.max_width:.1e}"


@claim("scqubits at ncut 30 wrong beyond 1e-6 GHz (absolute) in 70 of the 200 wide-range transmons (E_C = 1, E_J/E_C = 10^U(−1, 6), seed 7), all at E_J/E_C ≥ 5542, all 70 flagged by the adapter, 0 false alarms, 0 missed",
       ("70 of 200", "5542", "0 false alarms"), slow=True)
def _adapter():
    if importlib.util.find_spec("scqubits") is None or not _flint():
        return None
    import numpy as np
    from rigorous_levels import Rotor, scqubits_spectrum, guaranteed_levels
    rng = np.random.default_rng(7)
    for _ in range(200):                                   # the generator of bench/readme_numbers.py (wide range)
        rng.uniform(-1, 6)
        rng.integers(1, 5)
    cases = [(float(10 ** rng.uniform(-1, 6)), float(rng.uniform(0, 1))) for _ in range(200)]
    flagged = wrong = false_alarm = missed = 0
    smallest_wrong = None
    for ej, ng in cases:
        r = Rotor.transmon(1.0, ej, n_g=ng)
        a = scqubits_spectrum(r, 6, 30, check="doubling")
        iv = guaranteed_levels(r, 6, 1e-10)
        dist = max(max(float(iv.low[j]) - a.energies[j], a.energies[j] - float(iv.high[j]), 0.0) for j in range(6))
        is_wrong = dist > 1e-6
        is_flagged = a.state == "NOT_CONVERGED"
        wrong += is_wrong
        flagged += is_flagged
        false_alarm += is_flagged and not is_wrong
        missed += is_wrong and not is_flagged
        if is_wrong:
            smallest_wrong = ej if smallest_wrong is None else min(smallest_wrong, ej)
    return (wrong, missed, false_alarm) == (70, 0, 0) and smallest_wrong is not None and 5542 <= smallest_wrong < 5543, \
        f"wrong {wrong}, flagged {flagged}, missed {missed}, false alarms {false_alarm}, smallest wrong E_J/E_C {smallest_wrong:.0f}"


@claim("time per guaranteed transmon point (6 levels) and per Mathieu value: machine-dependent, reported only", ())
def _timing():
    if not _flint():
        return None
    from rigorous_levels import Rotor, guaranteed_levels, mathieu_a
    t = time.perf_counter()
    guaranteed_levels(Rotor.transmon(0.3, 15.0, n_g=0.25), 6)
    t1 = time.perf_counter() - t
    t = time.perf_counter()
    for _ in range(50):
        mathieu_a(5, 100.0)
    t2 = (time.perf_counter() - t) / 50
    return True, f"[INFO] transmon {t1 * 1e3:.0f} ms, Mathieu {t2 * 1e3:.2f} ms (README: 92 ms, 0.43 ms on the author's machine)"


def determinism_parts() -> List[Tuple[str, List[str]]]:
    """The exact decimal strings of a fixed set of enclosures, one entry per guaranteed module: transmon, sphere,
    Mathieu, fluxonium, parameter box, matrix element ⟨0|n|1⟩, then (added in 0.3.0 with the deterministic estimates)
    a rotor with cos φ and cos 2φ (band path), its ⟨0|cos φ|1⟩, and an RbCs hyperfine sector."""
    from rigorous_levels import (Fluxonium, Rotor, RotorBall, SigmaMolecule, SphericalRotor, guaranteed_fluxonium_levels,
                          guaranteed_levels, guaranteed_levels_over_box, guaranteed_matrix_element,
                          guaranteed_molecule_levels, guaranteed_sphere_levels, mathieu_a, zeeman_hz)
    out: List[Tuple[str, List[str]]] = []
    out.append(("transmon", [s for pair in guaranteed_levels(Rotor.transmon(0.3, 15.0, n_g=0.25), 6).strings for s in pair]))
    out.append(("sphere", [s for pair in guaranteed_sphere_levels(SphericalRotor(B=490.173994, dE=0.74, M=0), 3).strings
                           for s in pair]))
    v = mathieu_a(5, 100.0)
    out.append(("mathieu", [str(v.low), str(v.high)]))
    iv = guaranteed_fluxonium_levels(Fluxonium(E_C=0.567, E_J=2.052, E_L=0.835, flux=0.5), 3, 1e-9)
    out.append(("fluxonium", [str(x) for x in iv.low + iv.high]))
    b = guaranteed_levels_over_box(RotorBall.transmon((0.297, 0.303), (14.85, 15.15), n_g=0.25), 3)
    out.append(("box", [str(x) for x in b.low + b.high]))
    e = guaranteed_matrix_element(Rotor.transmon(0.3, 15.0, n_g=0.25), 0, 1, "n")
    out.append(("matrix element n", [str(e.low), str(e.high)]))
    r2 = Rotor(0.3, {1: -15.0, 2: 0.9}, n_g=0.25)
    out.append(("rotor cos 2phi", [s for pair in guaranteed_levels(r2, 4).strings for s in pair]))
    e2 = guaranteed_matrix_element(r2, 0, 1, "cos", 1)
    out.append(("matrix element cos", [str(e2.low), str(e2.high)]))
    m = SigmaMolecule(3, 7, B=490173994.0, D=213.0, c1=29.4, c2=196.8, c3=192.4, c4=19019.0, eQq1=-809290.0,
                      eQq2=59980.0, z_N=zeeman_hz(0.0062, 181.541), z1=zeeman_hz(1.8295, 181.541),
                      z2=zeeman_hz(0.7331, 181.541))
    h = guaranteed_molecule_levels(m, 12, 1, 1e-11, L_initial=3, L_limit=3)
    out.append(("hyperfine", [str(x) for x in h.low + h.high]))
    return out


def determinism_hash() -> str:
    """sha256 of the exact decimal strings of determinism_parts(), one per line, in order: identical on two machines
    iff every listed enclosure is identical bit for bit."""
    return hashlib.sha256("\n".join(s for _, ss in determinism_parts() for s in ss).encode()).hexdigest()


def readme_check() -> List[str]:
    """Every published string of every claim must appear in README.md; returns the missing ones."""
    with open(README, encoding="utf-8") as f:
        text = f.read()
    return [f"{name}: {s!r}" for name, published, _, _ in CLAIMS for s in published if s not in text]


def _console_safe() -> None:
    """A console that cannot encode a character (Windows cp1252 and "≤", CI 2026-11-12: UnicodeEncodeError ended the
    run) prints it as a backslash escape instead of stopping: no claim is lost, none is altered."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")


def main(argv) -> int:
    _console_safe()
    if argv == ["--readme"]:
        missing = readme_check()
        for m in missing:
            print("[FAIL] README does not contain", m)
        print(f"{'FAILED' if missing else 'OK'}: {len(CLAIMS)} claims, {len(missing)} missing in README.md")
        return 1 if missing else 0
    if argv == ["--hash"]:
        print(determinism_hash())
        return 0
    full = argv == ["--full"]
    sabotage = argv == ["--sabotage"]
    if argv and not (full or sabotage):
        print(__doc__)
        return 2
    if sabotage:
        import rigorous_levels.mathieu as M
        original = M.sector
        # the NEXT eigenvalue of the right sector (the scipy defect: another order): it changes every a_r and b_r,
        # so the fast set fails too (the old swap a_r -> b_r left r = 0 and every odd r unchanged: 0 FAIL, exit 1)
        M.sector = lambda kind, r: (lambda t: (t[0], t[1], t[2] + 1))(original(kind, r))
    failed = 0
    t0 = time.perf_counter()
    for name, published, fn, slow in CLAIMS:
        if slow and not full:
            print(f"[SLOW] {name} (run with --full)")
            continue
        t = time.perf_counter()
        try:
            res = fn()
        except Exception as e:  # noqa: BLE001 — a crash is a FAIL with its reason
            res = (False, f"{type(e).__name__}: {e}")
        dt = time.perf_counter() - t
        if res is None:
            print(f"[SKIP] {name} (dependency absent)")
            continue
        ok, text = res
        failed += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] {name} -> {text} ({dt:.1f} s)")
    print(f"{'FAILED' if failed else 'OK'}: {failed} of {len(CLAIMS)} claims failed, {time.perf_counter() - t0:.1f} s")
    if sabotage:
        print("(sabotage: the Mathieu solver returns the next order of the sector; at least one FAIL above is the positive control)")
        return 0 if failed else 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
