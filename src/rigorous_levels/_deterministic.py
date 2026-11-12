# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""rigorous_levels._deterministic — float estimates of eigenvalues and eigenvectors that are the same on every machine.

The guaranteed modules use float estimates only to choose where the exact (Arb) counts are taken, but the ends of a
published interval are built from those points: an estimate that changes with the CPU or the BLAS/LAPACK kernel
changes the published interval (measured 2026-11-12: numpy.linalg.eigvalsh gave different last bits under
OPENBLAS_CORETYPE=Haswell, Prescott and Nehalem, and so did the fluxonium intervals). The functions here use only
Python float operations whose result IEEE 754 fixes bit for bit (+, −, ×, ÷, comparisons, math.sqrt, math.fsum,
float() of an int or a Fraction), each in a fixed order: no BLAS/LAPACK, no libm transcendental, no builtin sum() of
floats (its algorithm changed in Python 3.12). On binary64 hardware with round-to-nearest (every 64-bit platform
CPython supports) the results depend only on the inputs and this code.

  - tridiagonal: bisection on the Sturm count (the LDLᵀ pivot recurrence, LAPACK dlaebz convention for tiny pivots);
  - dense symmetric: Householder reduction to tridiagonal, then the same bisection;
  - banded symmetric: bisection on the LDLᵀ inertia of the band (no pivoting: an estimate, the exact counts decide);
  - eigenvectors of a band matrix: inverse iteration with banded LU and partial pivoting, from a fixed start vector.

Accuracy is that of a backward-stable method for the tridiagonal and dense paths (a few eps·‖A‖); for the band path
the LDLᵀ without pivoting is not backward stable in general. None of these numbers enters a proof: they only choose
points, and every point is then checked by an exact count."""
from __future__ import annotations

import math
from operator import mul
from typing import Callable, Dict, List, Optional, Sequence

EPS = 2.220446049250313e-16
SAFMIN = 2.2250738585072014e-308
MAX_BISECTIONS = 2200          # enough to reach adjacent floats from any finite bracket


def _scale_exponent(values) -> int:
    """e with max|v| / 2^e in [0.5, 1) (0 if all zero); scaling by 2^−e is exact for normal floats and keeps every
    square below the overflow threshold."""
    m = 0.0
    for v in values:
        if not math.isfinite(v):                    # NaN too: max() would skip it in silence
            raise OverflowError("an entry of the matrix is not finite")
        if abs(v) > m:
            m = abs(v)
    if m == 0.0:
        return 0
    return math.frexp(m)[1]


def _fsum_dot(a: Sequence[float], b: Sequence[float]) -> float:
    return math.fsum(map(mul, a, b))


def _checked(count: Callable[[float], int], check: Optional[Callable[[], None]]) -> Callable[[float], int]:
    """count with the caller's deadline check before each evaluation (the check raises; it changes no number)."""
    if check is None:
        return count

    def c(x: float) -> int:
        check()
        return count(x)
    return c


def _bisect_lowest(count: Callable[[float], int], k: int, lo: float, hi: float, atol: float,
                   first: int = 0) -> List[float]:
    """λ_first … λ_{k−1} from count(x) = #{eigenvalues < x}, given lo ≤ λ_0 and λ_{k−1} < hi. Every count narrows the
    brackets of all the eigenvalues still to compute; each bracket stops at width ≤ atol + 2·eps·max(|a|, |b|) or
    when the midpoint is no longer strictly inside (adjacent floats)."""
    L = [lo] * k
    U = [hi] * k
    out: List[float] = []
    for j in range(first, k):
        a = L[j]
        b = U[j]
        if a > b:
            a = b
        for _ in range(MAX_BISECTIONS):
            if b - a <= atol + 2.0 * EPS * max(abs(a), abs(b)):
                break
            m = a * 0.5 + b * 0.5
            if not a < m < b:
                break
            c = count(m)
            for t in range(j, k):
                if t < c:
                    if m < U[t]:
                        U[t] = m
                elif m > L[t]:
                    L[t] = m
            if c > j:
                b = m
            else:
                a = m
        out.append(a * 0.5 + b * 0.5)
    return out


def sturm_count(d: Sequence[float], e2: Sequence[float], x: float, pivmin: float) -> int:
    """#{eigenvalues < x} of the symmetric tridiagonal with diagonal d and squared off-diagonal e2 (float)."""
    q = d[0] - x
    if abs(q) <= pivmin:
        q = -pivmin
    c = 1 if q < 0 else 0
    for i in range(1, len(d)):
        q = d[i] - x - e2[i - 1] / q
        if abs(q) <= pivmin:
            q = -pivmin
        if q < 0:
            c += 1
    return c


def _pivmin(e2: Sequence[float]) -> float:
    m = 1.0
    for v in e2:
        if v > m:
            m = v
    return SAFMIN * m


def tridiagonal_lowest(d: Sequence[float], e2: Sequence[float], k: int, first: int = 0,
                       check: Optional[Callable[[], None]] = None) -> List[float]:
    """λ_first … λ_{k−1} (the lowest first) of the symmetric tridiagonal (d, squared off-diagonal e2), bisection on
    the Sturm count."""
    d = [float(x) for x in d]
    e2 = [float(x) for x in e2]
    n = len(d)
    if not 1 <= k <= n:
        raise ValueError("k out of range")
    ex = max(_scale_exponent(d), (_scale_exponent(e2) + 1) // 2)
    if ex != 0:                                     # exact power-of-two scaling, undone exactly at the end
        d = [math.ldexp(x, -ex) for x in d]
        e2 = [math.ldexp(x, -2 * ex) for x in e2]
    e = [math.sqrt(x) for x in e2]
    lo, hi = math.inf, -math.inf
    for i in range(n):
        r = (e[i - 1] if i > 0 else 0.0) + (e[i] if i < n - 1 else 0.0)
        if d[i] - r < lo:
            lo = d[i] - r
        if d[i] + r > hi:
            hi = d[i] + r
    scale = max(abs(lo), abs(hi))
    atol = SAFMIN * max(scale, 1.0)               # bisect to adjacent floats (relative accuracy where the matrix allows it)
    pad = atol + 2.0 * EPS * scale * n
    pivmin = _pivmin(e2)
    out = _bisect_lowest(_checked(lambda x: sturm_count(d, e2, x, pivmin), check), k, lo - pad, hi + pad, atol, first)
    return [math.ldexp(x, ex) for x in out]                # ldexp raises OverflowError beyond float64


def householder_tridiagonal(A: Sequence[Sequence[float]]):
    """(d, e2): diagonal and squared off-diagonal of Qᵀ A Q tridiagonal (A symmetric, dense, float). Householder
    reflections H = I − v vᵀ·2/‖v‖² column by column; each column is scaled by its largest |entry| first. e2 holds
    squares: OverflowError if an off-diagonal entry is beyond √(float max) ≈ 1.3e154 (dense_lowest never unscales them)."""
    d, e2, ex = _householder_scaled(A)
    if ex != 0:
        d = [math.ldexp(x, ex) for x in d]
        e2 = [math.ldexp(x, 2 * ex) for x in e2]
    return d, e2


def _householder_scaled(A: Sequence[Sequence[float]], check: Optional[Callable[[], None]] = None):
    """(d, e2, ex): the tridiagonal of A·2^−ex (exact power-of-two scaling, entries of A·2^−ex below 1)."""
    n = len(A)
    S = [[float(x) for x in row] for row in A]
    ex = _scale_exponent(x for row in S for x in row)
    if ex != 0:                                     # exact power-of-two scaling, undone exactly at the end
        S = [[math.ldexp(x, -ex) for x in row] for row in S]
    d = [0.0] * n
    e2 = [0.0] * max(n - 1, 0)
    for k in range(n - 2):
        if check is not None:
            check()
        x = [S[i][k] for i in range(k + 1, n)]
        s = 0.0
        for t in x:
            if abs(t) > s:
                s = abs(t)
        d[k] = S[k][k]
        if s == 0.0:
            e2[k] = 0.0
            continue
        xs = [t / s for t in x]
        alpha = math.sqrt(math.fsum(t * t for t in xs))
        if xs[0] > 0:
            alpha = -alpha
        v = list(xs)
        v[0] = v[0] - alpha                     # v = x/s − α e₁, |v₀| ≥ |x₀/s|: no cancellation
        vv = math.fsum(t * t for t in v)
        beta = alpha * s
        e2[k] = beta * beta
        if vv == 0.0:
            continue
        tau = 2.0 / vv
        m = n - k - 1
        rows = [S[k + 1 + i][k + 1:] for i in range(m)]
        p = [tau * _fsum_dot(rows[i], v) for i in range(m)]          # p = τ B v
        K = tau * 0.5 * _fsum_dot(v, p)                                # K = τ vᵀp / 2
        q = [p[i] - K * v[i] for i in range(m)]                       # B' = B − v qᵀ − q vᵀ
        for i in range(m):
            vi, qi = v[i], q[i]
            row = [b - vi * qj - qi * vj for b, vj, qj in zip(rows[i], v, q)]
            S[k + 1 + i][k + 1:] = row
    if n >= 2:
        d[n - 2] = S[n - 2][n - 2]
        e2[n - 2] = S[n - 1][n - 2] * S[n - 1][n - 2]
    d[n - 1] = S[n - 1][n - 1]
    return d, e2, ex


def dense_lowest(A: Sequence[Sequence[float]], k: int, check: Optional[Callable[[], None]] = None) -> List[float]:
    """The k lowest eigenvalues of the dense symmetric float matrix A (Householder, then Sturm bisection), computed
    on A·2^−ex and scaled back exactly: the squared off-diagonal never leaves the scaled range (entries up to the
    float max; before 2026-11-12 (NEMESIS) e2 was unscaled first and overflowed beyond ≈ 1.3e154)."""
    d, e2, ex = _householder_scaled(A, check)
    return [math.ldexp(x, ex) for x in tridiagonal_lowest(d, e2, k, check=check)]    # ldexp raises OverflowError beyond float64


def band_count(diag: Sequence[float], bands: Dict[int, Sequence[float]], w: int, x: float, pivmin: float) -> int:
    """#{negative pivots} of LDLᵀ of A − xI, A symmetric with diag and bands[m][i] = A[i, i+m] (1 ≤ m ≤ w)."""
    n = len(diag)
    D: List[float] = []
    L: List[List[float]] = []          # L[i][t] = l_{i, i−w+t} for t < w
    c = 0
    for i in range(n):
        Li = [0.0] * w
        for j in range(max(0, i - w), i):
            band = bands.get(i - j)
            s = band[j] if band is not None else 0.0
            Lj = L[j]
            for t in range(max(0, i - w), j):
                lit = Li[t - i + w]
                if lit != 0.0:
                    ljt = Lj[t - j + w]
                    if ljt != 0.0:
                        s = s - lit * ljt * D[t]
            Li[j - i + w] = s / D[j]
        dd = diag[i] - x
        for t in range(max(0, i - w), i):
            lit = Li[t - i + w]
            if lit != 0.0:
                dd = dd - lit * lit * D[t]
        if abs(dd) <= pivmin:
            dd = -pivmin
        if dd < 0:
            c += 1
        D.append(dd)
        L.append(Li)
    return c


def band_lowest(diag: Sequence[float], bands: Dict[int, Sequence[float]], k: int,
                check: Optional[Callable[[], None]] = None) -> List[float]:
    """The k lowest eigenvalues of the symmetric band matrix (diag, bands[m][i] = A[i, i+m]); tridiagonal bands go to
    the Sturm path."""
    diag = [float(x) for x in diag]
    bands = {m: [float(x) for x in b] for m, b in bands.items() if any(x != 0 for x in b)}
    w = max(bands, default=0)
    n = len(diag)
    ex = max([_scale_exponent(diag)] + [_scale_exponent(b) for b in bands.values()])
    if ex != 0:                                     # exact power-of-two scaling, undone exactly at the end
        diag = [math.ldexp(x, -ex) for x in diag]
        bands = {m: [math.ldexp(x, -ex) for x in b] for m, b in bands.items()}
        return [math.ldexp(x, ex) for x in band_lowest(diag, bands, k, check)]    # ldexp raises OverflowError beyond float64
    if w <= 1:
        b1 = bands.get(1, [0.0] * (n - 1))
        return tridiagonal_lowest(diag, [x * x for x in b1], k, check=check)
    lo, hi = math.inf, -math.inf
    for i in range(n):
        r = 0.0
        for m, b in bands.items():
            if i + m < n:
                r += abs(b[i])
            if i - m >= 0:
                r += abs(b[i - m])
        if diag[i] - r < lo:
            lo = diag[i] - r
        if diag[i] + r > hi:
            hi = diag[i] + r
    scale = max(abs(lo), abs(hi))
    atol = SAFMIN * max(scale, 1.0)               # bisect to adjacent floats (relative accuracy where the matrix allows it)
    pad = atol + 2.0 * EPS * scale * n
    big = 1.0
    for b in bands.values():
        for v in b:
            if v * v > big:
                big = v * v
    pivmin = SAFMIN * big
    return _bisect_lowest(_checked(lambda x: band_count(diag, bands, w, x, pivmin), check), k, lo - pad, hi + pad, atol)


def _start_vector(n: int) -> List[float]:
    """Fixed start vector with components of both signs and no symmetry (integer LCG, exact conversions)."""
    s = 12345
    out = []
    for _ in range(n):
        s = (1103515245 * s + 12345) % 2147483648
        out.append((s - 1073741824) / 1073741824.0 + (0.5 if s & 1 else -0.5))
    return out


def band_eigenvector(diag: Sequence[float], bands: Dict[int, Sequence[float]], lam: float, iterations: int = 3,
                     check: Optional[Callable[[], None]] = None) -> List[float]:
    """Unit eigenvector estimate for the eigenvalue estimate `lam`: inverse iteration with (A − lam·I) factored by
    banded Gaussian elimination with partial pivoting (the right-hand side follows the same row operations), from a
    fixed start vector; sign fixed so that the entry of largest |value| is > 0 (on a tie, the first such index:
    the antisymmetric levels of a symmetric rotor have exact ties, so this rule fixes published signs)."""
    diag = [float(x) for x in diag]
    n = len(diag)
    bands = {m: [float(x) for x in b] for m, b in bands.items() if m >= 1 and any(x != 0 for x in b)}
    w = max(bands, default=0)
    rows: List[Dict[int, float]] = []
    norm = 0.0
    for i in range(n):
        r = {i: diag[i] - lam}
        for m, b in bands.items():
            if i + m < n and b[i] != 0.0:
                r[i + m] = b[i]
            if i - m >= 0 and b[i - m] != 0.0:
                r[i - m] = b[i - m]
        a = math.fsum(abs(v) for v in r.values())
        if a > norm:
            norm = a
        rows.append(r)
    tiny = EPS * norm if norm > 0 else SAFMIN
    steps = []                                   # (pivot row chosen, [(row, multiplier)])
    for c in range(n):
        if check is not None and c % 256 == 0:
            check()
        best, bi = -1.0, c
        for i in range(c, min(n, c + w + 1)):
            v = abs(rows[i].get(c, 0.0))
            if v > best:
                best, bi = v, i
        if bi != c:
            rows[c], rows[bi] = rows[bi], rows[c]
        pr = rows[c]
        piv = pr.get(c, 0.0)
        if abs(piv) < tiny:
            piv = tiny if piv >= 0 else -tiny
            pr[c] = piv
        cols = sorted(col for col in pr if col > c)
        mults = []
        for i in range(c + 1, min(n, c + w + 1)):
            ri = rows[i]
            a = ri.pop(c, 0.0)
            if a == 0.0:
                continue
            l = a / piv
            mults.append((i, l))
            for col in cols:
                ri[col] = ri.get(col, 0.0) - l * pr[col]
        steps.append((bi, mults))
    U = [sorted((col, v) for col, v in rows[c].items() if col > c) for c in range(n)]
    x = _start_vector(n)
    for _ in range(iterations):
        y = list(x)
        for c, (bi, mults) in enumerate(steps):
            if bi != c:
                y[c], y[bi] = y[bi], y[c]
            yc = y[c]
            for i, l in mults:
                y[i] = y[i] - l * yc
        z = [0.0] * n
        for c in range(n - 1, -1, -1):
            s = y[c]
            for col, v in U[c]:
                s = s - v * z[col]
            z[c] = s / rows[c][c]
        s = 0.0
        for v in z:
            if abs(v) > s:
                s = abs(v)
        if s == 0.0 or not math.isfinite(s):
            break
        x = [v / s for v in z]
    nrm = math.sqrt(math.fsum(v * v for v in x))
    x = [v / nrm for v in x]
    big, bi = -1.0, 0
    for i, v in enumerate(x):
        if abs(v) > big:
            big, bi = abs(v), i
    if x[bi] < 0:
        x = [-v for v in x]
    return x
