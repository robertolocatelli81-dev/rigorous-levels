# Why the intervals contain the true eigenvalues

This is the argument implemented in `qraft_ra.intervallo_garantito`. The assembly of the steps is the author's and has
had no external review; each step is standard and cited.

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
