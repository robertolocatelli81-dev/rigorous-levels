# Why the intervals contain the true eigenvalues

This is the argument implemented in `qraft_ra.guaranteed_intervals`. The assembly of the steps is the author's; it has
had no external human review (its adversarial reviews were automated, by an independent agent, reports in the author's
repository); each step is standard and cited.

## The operator

H = 4E_C(n − n_g)² + Σ_m c_m cos(mφ) on ℓ²(ℤ), in the charge basis, with cosines only and integer harmonics
1 ≤ m ≤ 24 (sines make the matrix complex: no interval, refused with a reason). Matrix elements: diagonal
d_n = 4E_C(n − n_g)²; off the diagonal, between n and n ± m, b_m = c_m/2. D is self-adjoint on its maximal domain and V
is bounded (‖V‖ ≤ Σ|c_m|), so H = D + V is self-adjoint, has compact resolvent (d_n → ∞), and the finite sequences are a
form core. The spectrum is discrete: λ_0 ≤ λ_1 ≤ …

Fix N ≥ |n_g|, I = {|n| ≤ N}, O = ℤ \ I.

## (a) Upper bound: Rayleigh–Ritz

Let H_N be the compression of H to I. Take ψ in the span of the first j+1 eigenvectors of H_N, extended by zeros.
Then ⟨ψ,Hψ⟩ = ⟨ψ,H_Nψ⟩ ≤ λ_j(H_N)‖ψ‖². By Theorem 4.12(i) of Teschl, for any λ > λ_j(H_N), H has at least j+1
eigenvalues < λ. Hence **λ_j(H) ≤ λ_j(H_N)**.

## (b) Lower bound, with the truncation closed

For each pair (i ∈ I, o ∈ O) with |i − o| = m and any α > 0: `2 b x_i x_o ≥ −|b| (α x_i² + x_o²/α)`, because
[[|b|α, b], [b, |b|/α]] is positive semidefinite (determinant 0, trace > 0). Summing over every pair that crosses the
border gives, as quadratic forms, **H ≥ B = H_N′ ⊕ H_O′**, where

- H_N′ is H_N with the diagonal of site i lowered by α·Σ|b| over its pairs that cross the border;
- H_O′ is H restricted to O, with the diagonal lowered by Σ|b|/α over its pairs that cross the border.

H − B is bounded and ≥ 0, so by Corollary 4.11 of Teschl (A ≥ B ⇒ E_n(A) ≥ E_n(B)) λ_j(H) ≥ λ_j(B).

On H_O′ use `|2 b x y| ≤ |b|(x² + y²)` (Gershgorin as a quadratic form). For each harmonic a site of O has at most two
partners and at most one of them is in I. Hence

`H_O′ ≥ L_out := 4E_C (N + 1 − |n_g|)² − Σ_m (|c_m|/2)(1 + max(1, 1/α))`,

where the first term is the minimum of d_n on O, because N ≥ |n_g|.

If L_out > λ_{k−1}(H_N′), the first k eigenvalues of B are those of H_N′, and for j < k:

**λ_j(H_N′) ≤ λ_j(H) ≤ λ_j(H_N).**

If the condition on L_out does not hold, no interval comes out: N grows, or the result is `FuoriDominio` with the
reason. α is chosen so that Σ(|c_m|/2)/α is about half the margin; α changes the width, never the validity.

## (c) Eigenvalues of the finite matrices, rigorously

Sylvester's law of inertia: if A − xI = L D Lᵀ (banded, no pivoting), the number of eigenvalues of A below x is the
number of D_i < 0. The factorization runs in Arb ball arithmetic (python-flint) at 128 bits, raised up to 1024 if
needed. If every pivot has a certain sign (the ball does not contain 0), the count is proven: the true pivots lie in
the balls and are all ≠ 0, so L D Lᵀ really exists. If a pivot has an uncertain sign, the point x moves or the
precision rises; a guessed count is never used. Bisection on these counts gives a ≤ λ_j ≤ b with exact (dyadic) a and
b. The float64 inputs (E_C, c_m, n_g) are exact numbers; d_n and b_m are computed exactly (Fraction) and converted to
Arb.

Output: [low_j, high_j] = [lower end for λ_j(H_N′), upper end for λ_j(H_N)], written as decimal strings rounded
OUTWARDS to 24 significant digits (float64 is not enough: at |E| ≈ 1e6 GHz one ulp is 1.2e-10). Transitions:
[low_j − high_0, high_j − low_0].

## Conditions

1. E_C > 0 and distinct integer harmonics m ≥ 1. `livelli_garantiti` accepts only a real `Rotore`, whose constructor
   checks them.
2. H is the one of the exact float64 parameters: 0.1 is 0.1000000000000000055…
3. Arb/FLINT rounds its balls correctly: a declared assumption, not proven here. No formal verification (Coq/Lean).

## Sources

- G. Teschl, *Mathematical Methods in Quantum Mechanics*, 2nd ed., AMS GSM 157 (2014). Online version
  https://www.mat.univie.ac.at/~gerald/ftp/book-schroe/schroe.pdf (sha256
  8dc8de0b58aa0a3fedfe594a345f9b5875322e5526ea581cb640a98d55b82818, downloaded 2026-11-08): Theorem 4.10 (min-max),
  Corollary 4.11, Theorem 4.12. The numbering of the printed AMS edition was not compared.
- Sylvester's law of inertia and LDLᵀ: Horn & Johnson, *Matrix Analysis*, 2nd ed., CUP 2013, §4.5.
- Bisection by eigenvalue counts: Barth, Martin, Wilkinson, Numer. Math. 9 (1967) 386–393, DOI 10.1007/BF02162154.
- Arb: F. Johansson, IEEE Trans. Computers 66(8) (2017) 1281–1292, DOI 10.1109/TC.2017.2690633.

## Prior art (search of 2026-11-08)

Rigorous intervals for eigenvalues of finite matrices exist (INTLAB `verifyeig`, FLINT `acb_mat_eig_*`, symveig,
arXiv:2606.16217); they cover rounding, not truncation. Proven bounds for the finite Hill equation exist since
Wagenführer, Numer. Math. 41 (1983) 255–279; verified enclosures with guaranteed index for Bloch eigenvalues
(Hoang–Plum–Wieners, ZAMP 60, 2009) and, for a Mathieu case at small q, with the basis truncation included (Liu,
arXiv:2607.04247, 2026). This repository applies known methods to the rotor in the charge basis, with any n_g and up to
24 harmonics. We did not find a tool for superconducting-qubit spectra that gives guaranteed intervals including
the truncation (searched: scqubits and CircuitQ, documentation and papers; SQcircuit, QuTiP and Qiskit Metal only by
web search, without reading their code). Not consulted (paywall): Volkmer 2004, Nagatou 2008, Shivakumar 1987,
Weinstein–Stenger 1972.

## The same argument on the sphere and for the molecule (0.2.0)

`rotore_sferico_garantito` (H = B N(N+1) − D_c [N(N+1)]² − dE cos θ, fixed M) and `molecola_iperfine_garantita`
(rotation, hyperfine, Zeeman and Stark terms, one M_F sector) use the three steps above with a different lattice:

- **Upper bound.** H_L is the compression of H to the states with N ≤ L: λ_j(H) ≤ λ_j(H_L) (Rayleigh–Ritz, Teschl
  Theorem 4.12(i)); the sector M_F is an invariant subspace when the fields are along z, so the argument is applied
  there.
- **Lower bound.** Only cos θ (ΔN = 1) and the rank-2 terms (quadrupoles and tensor spin–spin, ΔN = 2) couple the
  inner block A (N ≤ L) to the outer block C (N ≥ L + 1); the coupling V is a finite matrix built in Arb. For any
  η > 0, 2⟨x, Vy⟩ ≥ −η‖P_B x‖² − ‖V‖²‖y‖²/η with P_B the projector on the rows of A that V touches, so
  H ≥ (A − ηP_B) ⊕ (C − ‖V‖²/η) as forms, with ‖V‖₂ ≤ √(‖V‖₁‖V‖_∞). The outer block is bounded below by
  g(L+1) = B(L+1)(L+2) − D[(L+1)(L+2)]² − (block norms of the terms diagonal in N: Zeeman, spin–rotation, scalar
  spin–spin) − (K_T + K_Q) − dE, where K_T + K_Q bounds the norm of the rank-2 terms on the whole space (sum of the
  norms of the spin components, sup|C²_q| ≤ 1) and dE the Stark term (sup|C¹₀| ≤ 1): a compression does not increase
  a norm, so C ≥ (diagonal blocks) − ‖R‖ − ‖S‖. That g is increasing from L + 1 on is checked with exact increments in
  rational arithmetic (with D_c > 0 the model is defined on N ≤ N_fis, where the diagonal still grows; declared). If
  t = g(L+1) − ‖V‖²/η exceeds the upper bound of λ_j(H), then λ_j(H) ≥ λ_j(A − ηP_B) (Teschl Corollary 4.11).
- **Counts.** "How many eigenvalues below x" by LDLᵀ in Arb balls on the tridiagonal (sphere) or banded (molecule)
  matrix; an uncertain pivot raises the precision or moves the point, never counts.

Measured controls (2026-11-10/11, in the author's repository, not re-run here): the intervals contain the numpy
reference at a much larger truncation in every case tried (sphere: 177 of 177 cuts; molecule: 0 violations on 197
random and extreme cases by an independent reviewer, while the mutant with the wrong sign of η gives 50 violations);
RbCs with the constants of Gregory et al. 2016 reproduces their 16 hyperfine transitions within 100 Hz with intervals
7 mHz wide; TlF with the constants of CeNTREX-TlF 0.4.0 agrees with their code within 0.5 Hz at zero field and at
173 V/cm.

## Mathieu characteristic values (0.3.0)

`qraft_ra.mathieu`: a_r(q), b_r(q) are the eigenvalues of the four Jacobi matrices of the Fourier sectors (DLMF
28.4): d_k = (2k+ν)² on the diagonal, q off the diagonal, except (0,1) = √2·q for a_{2n} and d_0 = 1 ± q for
a_{2n+1} / b_{2n+1}; b_{2n+2} starts at k = 1. The three steps above apply on each sector with the cut K:

- Upper bound: λ_n(H) ≤ λ_n(H_K) (Rayleigh–Ritz).
- Lower bound: only the pair (K, K+1) with coupling q crosses the cut. For η > 0,
  2q x_K x_{K+1} ≥ −η x_K² − (q²/η) x_{K+1}², so H ≥ (H_K − η e_K e_Kᵀ) ⊕ H_O′ with, on the outer block (Gershgorin
  as a form, the first outer site has one outer neighbour and the others two, d_k increasing),
  H_O′ ≥ t = min(d_{K+1} − |q| − q²/η, d_{K+2} − 2|q|); η = |q| is used. If t > high_n, λ_n(H) ≥ λ_n(H_K − η e_K e_Kᵀ).
- Counts: the squares of the off-diagonal entries (q², 2q²) are exact rationals, so the tridiagonal LDLᵀ runs in Arb
  on exact data; uncertain pivots raise the precision or move the point.

Measured (2026-11-11, bench/mathieu_vs_scipy.py): r ≤ 12, q = −400…400 step 0.5, 40 025 values, 40 019
GUARANTEED at 1e-12 relative width (6 WIDE: valid, wider), median 0.38 ms; a_r(0) = b_r(0) = r² contained for
r ≤ 50; DLMF 28.2.3–4 symmetries; the sorted levels of the charge-basis rotor (E_C = 1, n_g = ν/2, 2q cos φ: a
different code path) meet the sector intervals in the order a_0 < b_2 < a_2 < … and b_1 < a_1 < b_3 < …;
scipy 1.17.1/1.18.1: 52 values outside, all confirmed wrong by an independent tridiagonal reference (K = 400).

## Fluxonium in the oscillator basis (0.3.0)

`qraft_ra.fluxonium`: H = H_0 + V with H_0 = ω(a†a + ½), ω = √(8E_LE_C), V = −E_J cos(φ − φ_ext), ‖V‖ ≤ E_J,
φ = φ_zpf(a + a†). V is dense in the Fock basis: cos(φ − φ_ext)_{mn} = cos(π(|m−n|/2 − 2·flux)) · g_{mn} with
g_{mn} = φ_zpf^{d} e^{−φ_zpf²/2} √(min!/max!) L_min^{(d)}(φ_zpf²), d = |m − n| (matrix elements of the displacement
operator D(iφ_zpf)); built in Arb from the exact rationals 2E_C/E_L and 8E_LE_C.

- Upper bound: λ_j(H) ≤ λ_j(PHP), P the projector on the first N Fock states.
- Lower bound: PH_0Q = 0. For every pair (i < N, o ≥ N), 2V_io x_i x_o ≥ −|V_io|(x_i² + x_o²); summing,
  H ≥ (PHP − diag r) ⊕ (QH_0Q + QVQ − diag c), r_i = Σ_{o≥N} |V_io|, c_o = Σ_{i<N} |V_io|. The outer block is
  ≥ t = ω(N+½) − E_J − max_o c_o. If t > high_j, λ_j(H) ≥ λ_j(PHP − diag r). The couplings with o < N + N2 are
  computed; for o ≥ N + N2 the bound |⟨i|D|o⟩| ≤ y^{d/2} √(o!/i!)/d! (DLMF 18.14.8, |L_n^{(α)}(x)| ≤ ((α+1)_n/n!) e^{x/2},
  y = φ_zpf²) has ratio ≤ ρ = √(y(N+N2+1))/(N2+1) between consecutive o; with ρ ≤ ½ the row tails are ≤ 2v(i, N+N2)
  and the column tails ≤ Σ_i v(i, N+N2). Why this is tight where the operator-norm route is not: ‖PVQ‖ stays O(E_J)
  for every N (cos φ couples neighbouring Fock states with O(1) amplitude), while r_i is O(E_J) only for i near N,
  where the low eigenvectors are negligible, so λ_j(PHP) − λ_j(PHP − diag r) shrinks super-exponentially with N.
- Counts: dense LDLᵀ in Arb (N ≤ 240).

Measured (2026-11-11, bench/fluxonium_devices.py, scqubits 4.3.1): four published parameter sets, 4 levels, width
5e-10 GHz, N = 54…117, 0.4–6.5 s; scqubits `Fluxonium(cutoff=110)` inside every interval, `cutoff=6` outside in at
least one level (negative control); with a vanishing E_J the levels are ω(j+½) (exact control).

## Parameters as intervals (0.3.0)

`qraft_ra.parameter_balls`: for the charge-basis rotor H(E_C, c) = 4E_C(n − n_g)² + Σ c_m cos(mφ) with E_C ∈ [E_C⁻, E_C⁺]
and c_m ∈ [c_m⁻, c_m⁺] (n_g exact):

- E_C ↦ λ_j is non-decreasing: H(E_C⁺) − H(E_C⁻) = 4(E_C⁺ − E_C⁻)(n − n_g)² ≥ 0 as a quadratic form on the common
  form domain, so λ_j(E_C⁻, c) ≤ λ_j(E_C, c) ≤ λ_j(E_C⁺, c) (Teschl, Corollary 4.11).
- c ↦ λ_j is Lipschitz: H(E_C, c) − H(E_C, c′) = Σ (c_m − c′_m) cos(mφ) is bounded with norm ≤ Σ|c_m − c′_m|, and a
  bounded self-adjoint perturbation B moves every min-max eigenvalue by at most ‖B‖ (Teschl, Theorem 4.10:
  λ_j(A + B) ≤ λ_j(A) + ‖B‖ and symmetrically), so |λ_j(E_C, c) − λ_j(E_C, c′)| ≤ Σ|c_m − c′_m|.

- n_g ↦ λ_j: with ψ(φ) ↦ e^{i n_g φ}ψ(φ), H(n_g) is unitarily the Floquet operator of Hill's equation
  −y″ + V(φ) y on the cell [0, 2π] with quasi-momentum 2π n_g: λ_j(n_g) is 1-periodic and even, and on [0, ½] every
  band function is monotone (Reed–Simon IV, Theorem XIII.89; Eastham, *The Spectral Theory of Periodic Differential
  Equations*, 1973, Theorem 2.3.1; for cos φ alone DLMF 28.12(i): the characteristic value a_ν(q) is monotone in ν on
  each band). Hence over n_g ∈ [a, b] the extremes of λ_j are at a, b and at the band edges 0 and ½ (mod 1) inside
  [a, b]: a finite set G of candidates, two guaranteed computations each.

With c⁰ the midpoint and ρ = Σ(c_m⁺ − c_m⁻)/2: min_{g∈G} low_j(E_C⁻, c⁰, g) − ρ ≤ λ_j(E_C, c, n_g) ≤
max_{g∈G} high_j(E_C⁺, c⁰, g) + ρ on the whole box. The bound is rigorous and in general not tight (the Lipschitz constant
is attained only by a level that follows the potential rigidly); the true spread of the levels can be much smaller.
Measured (2026-11-11, bench/parameter_balls.py): see README "Measurements".

## Matrix elements between eigenvectors (0.3.0)

`qraft_ra.matrix_elements`: the eigenvectors are not enclosed directly; the float eigenvectors ψ_j of H_N are
approximations whose distance from the true v_j is bounded.

- Residual, exact: r_j = (H − λ̃_j)ψ_j with λ̃_j the midpoint of the guaranteed enclosure of λ_j; ψ_j has finite
  support, so Hψ_j is a finite vector and ε_j = ‖r_j‖/‖ψ_j‖ is computed in rational arithmetic (square roots
  bounded by integer square roots).
- Gap: δ_j = min(λ̃_j − high_{j−1}, low_{j+1} − λ̃_j) from the guaranteed enclosures of the neighbours (k + 1 levels
  are enclosed; above level k the spectrum is ≥ low_{k}). If δ_j ≤ 0 the level is not separated: no bound.
- Spectral theorem: for ψ normalised, ‖(H − λ̃)ψ‖² = Σ_l |⟨v_l, ψ⟩|² (λ_l − λ̃)² ≥ δ² Σ_{l≠j} |⟨v_l, ψ⟩|², hence
  ‖(1 − P_j)ψ_j‖ ≤ ε_j/δ_j =: s_j (requires every eigenvalue other than λ_j to be at distance ≥ δ_j, which the
  enclosures give). With the sign of v_j fixed by ⟨v_j, ψ_j⟩ ≥ 0: ‖ψ_j − v_j‖² = s² + (1 − √(1 − s²))² ≤ s_j² + s_j⁴
  for s_j < 1, so ‖ψ_j − v_j‖ ≤ e_j := s_j(1 + s_j²).
- For a bounded X: ⟨v_i|X|v_j⟩ − ⟨ψ_i|X|ψ_j⟩ = ⟨v_i − ψ_i|X v_j⟩ + ⟨X ψ_i|v_j − ψ_j⟩, so the error is ≤ ‖X‖(e_i + e_j);
  ‖cos mφ‖ = ‖sin mφ‖ = 1. For X = n: the same identity with ‖n ψ_i‖ exact and
  ‖n v_j‖ ≤ ‖(n − n_g)v_j‖ + |n_g|, ‖(n − n_g)v_j‖² = ⟨v_j|(H − V)|v_j⟩/(4E_C) ≤ (high_j + Σ|c_m|)/(4E_C).
- ⟨ψ_i|X|ψ_j⟩ is exact: ⟨n′|cos mφ|n⟩ = ½(δ_{n′,n+m} + δ_{n′,n−m}), ⟨n′|sin mφ|n⟩ = (δ_{n′,n+m} − δ_{n′,n−m})/(2i); the
  normalisation ‖ψ_i‖‖ψ_j‖ is enclosed by integer square roots.

Measured (2026-11-11, bench/matrix_elements.py and tests): widths 1e-14 … 1e-13 on the device regime (residuals
≈ 1e-14, gaps of GHz); scqubits `matrixelement_table` (ncut 40) inside the enclosures; the exact symmetry values
(⟨j|n|j⟩ = ½ at n_g = ½, 0 at n_g = 0; ⟨0|cos φ|1⟩ = 0 at n_g = 0) inside; a vector of another rotor gives no bound
(OutOfDomain), a vector mixed with 1e-4 of its neighbour widens the enclosure to ≈ 1e-4 and keeps the truth inside.
