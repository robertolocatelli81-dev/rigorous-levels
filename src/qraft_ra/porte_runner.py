# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra/porte_runner.py — runner delle PORTE della multiporta: gira DENTRO la sandbox (bwrap), mai nel processo di
QRAFT-RA. Legge /tmp/work/richiesta.json, esegue la porta (lista chiusa), scrive /tmp/work/uscita.json.
Specifica: note dell'autore (non pubblicate) (contratto "qraft-porta/0.1").
Le porte `prova_*` esistono SOLO per i controlli positivi della sandbox (rete, scrittura, tempo, memoria, uscita sporca,
solutore sbagliato). Nessuna di esse è un solutore.
Questo file non importa nulla di QRAFT-RA: è autonomo (numpy e i solutori arrivano dal site-packages dichiarato)."""
import json
import math
import os
import resource
import socket
import sys
import time
import traceback

CONTRATTO = "qraft-porta/0.1"
H_PLANCK = 6.62607015e-34


def _rlimit(secondi: int, mem_mib: int) -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (secondi, secondi))
    resource.setrlimit(resource.RLIMIT_AS, (mem_mib * 1024 * 1024, mem_mib * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024, 64 * 1024 * 1024))
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (16, 16))
    except (ValueError, OSError):
        pass


def _rotore_numpy(modello: dict, k: int, ncut: int):
    import numpy as np
    EC, EJ, ng = modello["E_C"], modello["E_J"], modello["n_g"]
    n = np.arange(-ncut, ncut + 1)
    H = np.diag(4.0 * EC * (n - ng) ** 2) - 0.5 * EJ * (np.eye(2 * ncut + 1, k=1) + np.eye(2 * ncut + 1, k=-1))
    return [float(x) for x in np.linalg.eigvalsh(H)[:k]]


def porta_numpy_rotore(r):
    return _rotore_numpy(r["modello"], r["livelli"], int(r["troncamento"]["ncut"])), "numpy"


def porta_prova_sbagliata(r):
    """Solutore volutamente sbagliato: troncamento ncut = 3 e livelli spostati di +1e-3."""
    return [x + 1e-3 for x in _rotore_numpy(r["modello"], r["livelli"], 3)], "numpy ncut 3 + 1e-3"


def porta_scqubits_transmon(r):
    import scqubits
    m = r["modello"]
    t = scqubits.Transmon(EJ=m["E_J"], EC=m["E_C"], ng=m["n_g"], ncut=int(r["troncamento"]["ncut"]))
    return [float(x) for x in t.eigenvals(evals_count=r["livelli"])], f"scqubits {scqubits.__version__}"


def porta_diatomic_py(r):
    """Molecola ¹Σ via diatomic-py 2.1.0 nel settore M_F richiesto. Mappa c3 → −c3: il codice diatomic-py usa
    +√6 c3 T²(C)·T²(I1,I2), il suo articolo (eq. 5b), Aldegunde 2008 e Gregory 2016 il segno opposto
    (note dell'autore (non pubblicate)): la porta lo dichiara nel campo versione_solutore."""
    import numpy as np
    from diatomic import operators as op
    from diatomic.systems import SingletSigmaMolecule
    import importlib.metadata
    m = r["modello"]
    h = H_PLANCK
    mol = SingletSigmaMolecule(Ii=(m["due_I1"] / 2, m["due_I2"] / 2), Nmax=int(r["troncamento"]["N_max"]),
                               Brot=m["B"] * h, Drot=m["D"] * h, Ci=(m["c1"] * h, m["c2"] * h), C4=m["c4"] * h,
                               C3=-m["c3"] * h, Qi=(m["eQq1"] * h, m["eQq2"] * h), d0=1.0, MuN=1.0, Mui=(1.0, 1.0))
    if m["due_I1"] % 2 == 0:
        mol.Ii = (m["due_I1"] // 2, mol.Ii[1])
    if m["due_I2"] % 2 == 0:
        mol.Ii = (mol.Ii[0], m["due_I2"] // 2)
    H = op.hyperfine_ham(mol) / h
    N_vec, I1_vec, I2_vec = op.generate_vecs(mol.Nmax, mol.Ii[0], mol.Ii[1])
    H = H - (m["z_N"] * N_vec[2] + m["z1"] * I1_vec[2] + m["z2"] * I2_vec[2])
    if m["dE"] != 0.0:
        H = H - m["dE"] * op.expanded_unit_dipole_operator(mol, 0)
    H = np.asarray(H).real
    basi = list(op.uncoupled_basis_iter(mol.Nmax, mol.Ii[0], mol.Ii[1]))
    ii = [i for i, (N, MN, M1, M2) in enumerate(basi) if int(round(2 * (float(MN) + float(M1) + float(M2)))) == m["due_MF"]]
    ev = np.linalg.eigvalsh(H[np.ix_(ii, ii)])[:r["livelli"]]
    return [float(x) for x in ev], f"diatomic-py {importlib.metadata.version('diatomic-py')} (c3 → −c3)"


def porta_prova_rete(r):
    """Tenta una connessione TCP alla porta indicata su 127.0.0.1: fuori dalla sandbox riesce, dentro deve fallire."""
    try:
        with socket.create_connection(("127.0.0.1", int(r["troncamento"]["porta_tcp"])), timeout=2):
            pass
        return _rotore_numpy(r["modello"], r["livelli"], 30), "rete RAGGIUNTA"
    except OSError as e:
        raise RuntimeError(f"rete bloccata: {type(e).__name__}: {e}")


def porta_prova_scrittura(r):
    """Tenta di scrivere nella HOME e nel percorso dato, e di vedere la casa vera dell'utente: riporta cosa è riuscito."""
    esiti = []
    for p in (os.path.join(os.environ.get("HOME", "/nonexistent"), "qraft_porta_prova.txt"), r["troncamento"]["percorso"]):
        try:
            with open(p, "w") as f:
                f.write("prova")
            esiti.append(f"SCRITTO {p}")
        except OSError as e:
            esiti.append(f"bloccato {p}: {type(e).__name__}")
    esiti.append("home_vera_visibile=" + str(os.path.isdir(r["troncamento"]["home_vera"])))
    esiti.append(f"pid={os.getpid()}")                       # nuovo namespace PID: pid piccolo (bwrap è 1)
    raise RuntimeError("; ".join(esiti))


def porta_prova_loop(r):
    while True:
        time.sleep(0.01)


def porta_prova_memoria(r):
    import numpy as np
    a = np.ones(int(r["troncamento"]["mib"]) * 1024 * 1024 // 8)
    return [float(a.sum())], "memoria ALLOCATA"


def porta_prova_ostile(r):
    """Controlli positivi NEMESIS 11/11 (modo in troncamento.modo): legge l'ambiente di tutti i processi visibili,
    sostituisce uscita.json con un symlink, riempie il disco, scrive OK e poi si uccide."""
    t = r["troncamento"]
    modo = t["modo"]
    if modo == "ambiente":
        nome = t["nome"].encode()
        visti = []
        for pid in [x for x in os.listdir("/proc") if x.isdigit()]:
            try:
                with open(f"/proc/{pid}/environ", "rb") as f:
                    if any(v.split(b"=")[0] == nome for v in f.read().split(b"\0")):
                        visti.append(pid)
            except OSError:
                pass
        if nome.decode() in os.environ:
            visti.append("os.environ")
        raise RuntimeError(f"ambiente: {t['nome']} visto in {visti}")
    if modo == "symlink":
        try:
            os.unlink(os.path.join(sys.argv[1], "uscita.json"))
            os.symlink(t["bersaglio"], os.path.join(sys.argv[1], "uscita.json"))
            esito = "symlink FATTO"
        except OSError as e:
            esito = f"symlink bloccato: {type(e).__name__}"
        raise RuntimeError(esito)
    if modo == "disco":
        scritti = 0
        for i in range(int(t["file"])):
            try:
                with open(os.path.join(t["dove"], f"f{i}"), "wb") as f:
                    for _ in range(int(t["mib"])):
                        f.write(b"\0" * 1048576)
                        scritti += 1
            except OSError as e:
                raise RuntimeError(f"disco: {scritti} MiB poi {type(e).__name__}")
        raise RuntimeError(f"disco: {scritti} MiB scritti")
    if modo == "scrivi":
        try:
            with open(t["percorso"], "w") as f:
                f.write("x")
            raise RuntimeError(f"scrivi: SCRITTO {t['percorso']}")
        except OSError as e:
            raise RuntimeError(f"scrivi: bloccato {type(e).__name__}")
    if modo == "fork":
        n = 0
        try:
            for _ in range(64):
                if os.fork() == 0:
                    time.sleep(3)
                    os._exit(0)
                n += 1
        except OSError:
            pass
        raise RuntimeError(f"fork: {n}")
    if modo == "cpu":
        while True:
            pass
    if modo == "stdout":
        blocco = "x" * 1048576
        for _ in range(int(t["mib"])):
            sys.stdout.write(blocco)
        sys.stdout.flush()
        raise RuntimeError("stdout scritto")
    if modo == "ok_poi_crash":
        with open(os.path.join(sys.argv[1], "uscita.json"), "w") as f:
            json.dump({"contratto": CONTRATTO, "porta": r["porta"], "versione_solutore": "x", "livelli": [0.0] * r["livelli"],
                       "unita": r["unita"], "stato": "OK", "motivo": "", "secondi": 0.0}, f)
        os.kill(os.getpid(), 9)
    raise RuntimeError(f"modo {modo!r} ignoto")


def porta_prova_uscita_sporca(r):
    out = _rotore_numpy(r["modello"], r["livelli"], 30)
    return out, "sporca", {"chiave_ignota": 1}


# ── porte dei bersagli (11/11/2026, note dell'autore (non pubblicate)) ──────────────────────────────────
def porta_metal_hcpb(r):
    """qiskit-metal Hcpb (transmon_charge_basis.py, letto dal repo, montato in sola lettura): eigh_tridiagonal su
    4E_C(n−n_g)² − (E_J/2)(|n⟩⟨n+1| + h.c.), n ∈ [−nlevels, nlevels+1]."""
    import transmon_charge_basis as tcb
    m = r["modello"]
    h = tcb.Hcpb(nlevels=int(r["troncamento"]["nlevels"]), Ej=m["E_J"], Ec=m["E_C"], ng=m["n_g"])
    return [float(x) for x in h.evals[:r["livelli"]]], "qiskit-metal Hcpb (transmon_charge_basis.py, repo HEAD 11/11/2026)"


def porta_metal_mathieu(r):
    """qiskit-metal transmon_CPB_analytic.mathieu_level(m, n_g, E_J, E_C): valori caratteristici di Mathieu (scipy)."""
    import transmon_CPB_analytic as tca
    m = r["modello"]
    out = [float(tca.mathieu_level(j, m["n_g"], m["E_J"], m["E_C"])) for j in range(r["livelli"])]
    return out, "qiskit-metal mathieu_level (transmon_CPB_analytic.py, repo HEAD 11/11/2026)"


def porta_sqcircuit_transmon(r):
    """SQcircuit: un condensatore + una giunzione. E_C passata a SQcircuit IN GHz (sue costanti e, ħ: units.py) e
    sottratta la capacità propria della giunzione (VerySmallCap = 1e-20 F, elements.py:235-238 e :489-490), così la
    capacità TOTALE vista da SQcircuit dà esattamente E_C (NEMESIS 11/11: lo scarto 2,8e-7…1,3e-6 GHz veniva per l'88 %
    da quei 1e-20 F e per il 12 % dalle costanti troncate)."""
    import importlib.metadata
    import SQcircuit as sq
    m = r["modello"]
    sq.set_unit_cap("fF")
    sq.set_unit_JJ("GHz")
    sq.set_unit_freq("GHz")
    giunzione = sq.Junction(value=m["E_J"], unit="GHz")
    c_tot = float(sq.Capacitor(value=m["E_C"], unit="GHz").get_value("F"))
    c_shunt = c_tot - float(giunzione.cap.get_value("F"))
    if not c_shunt > 0:
        raise ValueError("E_C troppo grande: la capacità propria della giunzione supera quella totale")
    circ = sq.Circuit({(0, 1): [sq.Capacitor(value=c_shunt, unit="F"), giunzione]})
    circ.set_trunc_nums([int(r["troncamento"]["ncut"])])
    circ.set_charge_offset(1, m["n_g"])
    efreqs, _ = circ.diag(n_eig=r["livelli"])
    return [float(x) for x in efreqs], (f"SQcircuit {importlib.metadata.version('SQcircuit')} "
                                        f"(C shunt = {c_shunt * 1e15:.9f} fF + giunzione {float(giunzione.cap.get_value('F')):.1e} F)")


def porta_pyepr_fock(r):
    """pyEPR black_box_hamiltonian: un modo, f_lin = √(8E_JE_C), L_J = (Φ₀/2π)²/E_J, φ_zpf = (2E_C/E_J)^¼; coseno
    Taylor a cos_trunc (senza 1 − φ²/2) su Fock fock_trunc. Livelli letti COME pyEPR (make_dispersive): per il Fock j
    l'autostato di massima sovrapposizione, non i k autovalori più bassi (NEMESIS 11/11: con fock_trunc grande la base
    raggiunge i pozzi vicini φ ≈ ±2π della fase NON compatta e i più bassi sono stati spuri con ⟨n⟩ ≈ 22). La fase non
    compatta non rappresenta n_g: n_g ≠ 0 → errore col motivo (mai ignorato in silenzio). Uscita in GHz, costante e φ²
    esclusi dal loro modello: confrontare le TRANSIZIONI."""
    import importlib.metadata
    import numpy as np
    from pyEPR.calcs.back_box_numeric import black_box_hamiltonian
    from pyEPR.calcs.constants import fluxQ
    m = r["modello"]
    if m["n_g"] != 0:
        raise ValueError("pyEPR (fase non compatta, base di Fock) non rappresenta n_g: richiesto n_g = 0")
    h = 6.62607015e-34
    EJ, EC = m["E_J"] * 1e9, m["E_C"] * 1e9                       # Hz
    f_lin = (8.0 * EJ * EC) ** 0.5
    Lj = fluxQ ** 2 / (EJ * h)
    phi_zpf = (2.0 * EC / EJ) ** 0.25
    H = black_box_hamiltonian([f_lin], [Lj], [[fluxQ * phi_zpf]], cos_trunc=int(r["troncamento"]["cos_trunc"]),
                              fock_trunc=int(r["troncamento"]["fock_trunc"]))
    w, V = np.linalg.eigh(H.full())
    k = r["livelli"]
    if k > V.shape[0]:
        raise ValueError("livelli richiesti oltre fock_trunc")
    scelti = [int(np.argmax(np.abs(V[j, :]) ** 2)) for j in range(k)]
    if len(set(scelti)) != k:
        raise ValueError(f"assegnazione per sovrapposizione ambigua: {scelti}")
    return [float(w[i]) / 1e9 for i in scelti], (f"pyEPR {importlib.metadata.version('pyEPR-quantum')} "
                                                 "black_box_hamiltonian (livelli per sovrapposizione col Fock)")


def porta_centrex_tlf(r):
    """CeNTREX-TlF: H dello stato X in base disaccoppiata (Hff + E·HS + B·HZ, campi lungo z), settore M_F."""
    import importlib.metadata
    import numpy as np
    from centrex_tlf.hamiltonian import (generate_uncoupled_hamiltonian_X,
                                         generate_uncoupled_hamiltonian_X_function)
    from centrex_tlf.states import generate_uncoupled_states_ground
    m = r["modello"]
    QN = generate_uncoupled_states_ground(Js=np.arange(0, int(m["Jmax"]) + 1))
    Hf = generate_uncoupled_hamiltonian_X_function(generate_uncoupled_hamiltonian_X(QN))
    M = Hf(np.array([0.0, 0.0, m["E_Vcm"]]), np.array([0.0, 0.0, m["B_G"]])) / (2 * np.pi)      # rad/s → Hz
    ii = [i for i, s in enumerate(QN) if int(round(2 * (s.mJ + s.m1 + s.m2))) == m["due_MF"]]
    sub = M[np.ix_(ii, ii)]
    if np.abs(sub.imag).max() > 1e-6 * max(1.0, np.abs(sub).max()):
        raise RuntimeError("parte immaginaria non trascurabile nel settore")
    ev = np.linalg.eigvalsh(sub.real)[:r["livelli"]]
    return [float(x) for x in ev], f"centrex-tlf {importlib.metadata.version('centrex-tlf')} (settore 2M_F = {m['due_MF']}, J ≤ {m['Jmax']})"


PORTE = {
    "numpy_rotore": porta_numpy_rotore,
    "prova_sbagliata": porta_prova_sbagliata,
    "scqubits_transmon": porta_scqubits_transmon,
    "diatomic_py": porta_diatomic_py,
    "prova_rete": porta_prova_rete,
    "prova_scrittura": porta_prova_scrittura,
    "prova_loop": porta_prova_loop,
    "prova_memoria": porta_prova_memoria,
    "prova_uscita_sporca": porta_prova_uscita_sporca,
    "prova_ostile": porta_prova_ostile,
    "metal_hcpb": porta_metal_hcpb,
    "metal_mathieu": porta_metal_mathieu,
    "sqcircuit_transmon": porta_sqcircuit_transmon,
    "pyepr_fock": porta_pyepr_fock,
    "centrex_tlf": porta_centrex_tlf,
}


def main(cartella: str) -> int:
    t0 = time.time()
    for v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(v, "1")               # prima di numpy: i thread BLAS sotto RLIMIT_AS falliscono (SIGINT)
    with open(os.path.join(cartella, "richiesta.json"), encoding="utf-8") as f:
        r = json.load(f)
    uscita = {"contratto": CONTRATTO, "porta": r.get("porta"), "versione_solutore": "", "livelli": [],
              "unita": r.get("unita"), "stato": "ERRORE", "motivo": "", "secondi": 0.0}
    try:
        if r.get("contratto") != CONTRATTO:
            raise RuntimeError(f"contratto {r.get('contratto')!r} non è {CONTRATTO}")
        _rlimit(int(r["limiti"]["secondi"]), int(r["limiti"]["mem_mib"]))
        for sp in r.get("site_packages", []):
            sys.path.insert(0, sp)
        fn = PORTE.get(r["porta"])
        if fn is None:
            raise RuntimeError(f"porta {r['porta']!r} non nella lista chiusa")
        ris = fn(r)
        livelli, versione = ris[0], ris[1]
        if len(ris) > 2:
            uscita.update(ris[2])
        if any(not math.isfinite(x) for x in livelli):
            raise RuntimeError("livelli non finiti")
        uscita.update(livelli=livelli, versione_solutore=versione, stato="OK")
    except BaseException as e:  # noqa: BLE001 — qualunque cosa succeda, l'uscita è un JSON con il motivo
        tb = traceback.format_exc().strip().splitlines()
        uscita["motivo"] = (f"{type(e).__name__}: {e}" + (" | " + " / ".join(tb[-3:-1]) if not isinstance(e, RuntimeError) else ""))[:600]
    uscita["secondi"] = round(time.time() - t0, 3)
    with open(os.path.join(cartella, "uscita.json"), "w", encoding="utf-8") as f:
        json.dump(uscita, f)
    return 0 if uscita["stato"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
