# Threshold rule "scq-threshold/1.0" of the scqubits adapter

Identifier of the rule carried by `ScqubitsSpectrum.rule`. Written on 2026-11-11 as "soglia-scq/1.0" before the code
of 0.2.0 (author's notes); renamed in 0.3.0 with no change of content (same numbers, same decisions), so that the
public identifier is English. A different rule gets a different identifier, written here first.

Inputs: the levels E(ncut) and E(2·ncut) of `scqubits.Transmon` (k lowest), the declared unit u ∈ {GHz, MHz, Hz},
the optional user tolerance `tol` (in u), E_C, E_J, n_g, ncut.

1. error = max_j |E_j(ncut) − E_j(2·ncut)|  (a LOWER bound of the true truncation error at ncut: the charge bases are
   nested, so E_j(ncut) ≥ E_j(2·ncut) ≥ E_j).
2. floor = 32 · eps · (‖H(ncut)‖₂ + ‖H(2·ncut)‖₂) with eps = 2⁻⁵², ‖H(n)‖₂ ≤ 4E_C(n + |n_g|)² + E_J (Gershgorin on the
   symmetric tridiagonal), in u. 32 = 16 × the nominal tolerance of LAPACK ?stebz: a plausible bound, not a proof
   (measured on converged pairs: about 100 × above the observed noise).
3. physical = `tol` if given (origin "user"); else min(1e-6 GHz expressed in u, 1e-6 · (E_{k−1} − E_0) at 2·ncut)
   with origin "absolute" or "relative" (the smaller wins; with k = 1 "absolute").
4. threshold = max(floor, physical); `threshold_origin` names which term decided ("floor" if the floor wins).
5. state: NOT_CONVERGED if error > threshold; OK_FLOAT_FLOOR if error ≤ threshold and the origin is "floor";
   OK otherwise. The energies returned are those at ncut (check "doubling") or at the last doubling (check "auto",
   which doubles until the state is not NOT_CONVERGED or ncut > 1920).

Covariance: the verdict is the same in GHz, MHz and Hz (every term scales with u). Measured in 0.2.0 on 200 transmons
of the device regime × ncut 3…30: 0 results marked OK whose error was outside the threshold (2000 + 1200 runs), 0 on
1080 runs outside the regime (independent reviewer); verdicts identical in the three units (0 of 1000 differ).
