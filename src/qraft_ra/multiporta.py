# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra/multiporta.py — MULTIPORTA: un'interfaccia chiusa e versionata ("qraft-porta/0.1") con cui QRAFT-RA esegue un
solutore ESTERNO dentro una sandbox (bubblewrap) e confronta il risultato con i propri intervalli garantiti.

Codice altrui = non fidato per costruzione: gira in un processo separato dentro `bwrap --unshare-all` (niente rete,
nuovo PID/IPC/UTS), con SOLO /usr, /lib, /lib64, /bin, /etc e il site-packages dichiarato montati in sola lettura; la
HOME vera NON è montata (HOME = tmpfs), scrittura possibile solo nella cartella di lavoro temporanea; ambiente
ripulito (`--clearenv`); rlimit CPU/memoria/file nel runner; timeout del chiamante. FAIL-CLOSED: senza bwrap
`SandboxAssente`, nessun ripiego (CVE-2026-57144: il ripiego silenzioso è una vulnerabilità).
L'uscita è un JSON validato contro uno schema CHIUSO (chiave ignota, tipo sbagliato, NaN, lunghezza ≠ k, unità o
contratto diversi = NON_CONFRONTABILE col motivo). Verdetto per livello: DENTRO / FUORI (con distanza) /
NON_CONFRONTABILE (con motivo), in frazioni esatte.
Specifica (scritta prima): note dell'autore (non pubblicate). Runner: qraft_ra/porte_runner.py.
Cosa NON è: un certificato del calcolo; una VM (bwrap = namespace utente); un giudizio sulla fisica del solutore altrui.
QRAFT-RA è un modello interno, non un validatore esterno."""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from qraft_ra.intervallo_garantito import FuoriDominio, Intervalli

__all__ = ["CONTRATTO", "PORTE", "Richiesta", "Uscita", "Verdetto", "SandboxAssente", "esegui_porta", "confronta",
           "valida_uscita", "FuoriDominio"]

CONTRATTO = "qraft-porta/0.1"
UNITA = {"GHz": Fraction(10 ** 9), "MHz": Fraction(10 ** 6), "Hz": Fraction(1)}
SECONDI_MAX, MEM_MIB_MAX, LIVELLI_MAX = 3600, 65536, 10000       # tetti dichiarati (NEMESIS 11/11: secondi 2**31 → OverflowError)
USCITA_MAX_BYTE = 1 << 20                                         # l'uscita è letta al più per 1 MiB
TMPFS_BYTE = 256 << 20                                            # /tmp, /home, /dev/shm della sandbox: tetto di RAM
JMAX_TLF = 20                                                     # tlf_centrex: J ≤ 20 = 1764 stati, 0,4 s, 47 MiB (NEMESIS B 11/11)
PORTE = ("numpy_rotore", "prova_sbagliata", "scqubits_transmon", "diatomic_py", "prova_rete", "prova_scrittura",
         "prova_loop", "prova_memoria", "prova_uscita_sporca",
         "prova_ostile",                                                                           # NEMESIS 11/11
         "metal_hcpb", "metal_mathieu", "sqcircuit_transmon", "pyepr_fock", "centrex_tlf")      # bersagli 11/11
MODELLI: Dict[str, Tuple[str, ...]] = {
    "rotore_cos": ("tipo", "E_C", "E_J", "n_g"),
    "molecola_sigma": ("tipo", "due_I1", "due_I2", "due_MF", "B", "D", "c1", "c2", "c3", "c4", "eQq1", "eQq2",
                       "z_N", "z1", "z2", "dE"),
    "tlf_centrex": ("tipo", "E_Vcm", "B_G", "Jmax", "due_MF"),      # costanti = quelle di centrex-tlf (XConstants)
}
# porte dei bersagli (11/11): troncamento CHIUSO (chiavi esatte, interi ≥ 1) e modello obbligato (NEMESIS 11/11:
# chiavi ignote, 15.9 e "15" passavano in silenzio con int() nel runner). Le porte più vecchie restano aperte (dichiarato).
TRONCAMENTI: Dict[str, Tuple[str, ...]] = {"metal_hcpb": ("nlevels",), "metal_mathieu": (), "sqcircuit_transmon": ("ncut",),
                                           "pyepr_fock": ("cos_trunc", "fock_trunc"), "centrex_tlf": ()}
MODELLO_DI_PORTA = {"metal_hcpb": "rotore_cos", "metal_mathieu": "rotore_cos", "sqcircuit_transmon": "rotore_cos",
                    "pyepr_fock": "rotore_cos", "centrex_tlf": "tlf_centrex"}
CHIAVI_USCITA = ("contratto", "porta", "versione_solutore", "livelli", "unita", "stato", "motivo", "secondi")
RUNNER = Path(__file__).resolve().parent / "porte_runner.py"
MONTAGGI_RO = ("/usr", "/lib", "/lib64", "/bin", "/etc")


class SandboxAssente(RuntimeError):
    """bwrap non disponibile: nessuna esecuzione (fail-closed)."""


def _finito(x) -> bool:
    """Numero reale finito (int o float, non bool), interi enormi compresi: mai OverflowError."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    try:
        return math.isfinite(float(x))
    except OverflowError:
        return False


def _reale(x, nome):
    if not _finito(x):
        raise FuoriDominio(f"{nome}: atteso un numero reale finito")
    return float(x)


def _intero(x, nome, minimo=None):
    if isinstance(x, bool) or not isinstance(x, int):
        raise FuoriDominio(f"{nome}: atteso un intero")
    if minimo is not None and x < minimo:
        raise FuoriDominio(f"{nome}: atteso >= {minimo}")
    return x


@dataclass(frozen=True)
class Richiesta:
    porta: str
    modello: Dict[str, object]
    livelli: int
    troncamento: Dict[str, object]
    unita: str = "GHz"
    secondi: int = 60
    mem_mib: int = 1024
    site_packages: Tuple[str, ...] = ()

    def __post_init__(self):
        if self.porta not in PORTE:
            raise FuoriDominio(f"porta {self.porta!r} non nella lista chiusa {PORTE}")
        if not isinstance(self.modello, dict) or not isinstance(self.modello.get("tipo"), str) \
                or self.modello.get("tipo") not in MODELLI:
            raise FuoriDominio(f"modello: tipo non nella lista chiusa {tuple(MODELLI)}")
        attese = MODELLI[self.modello["tipo"]]
        ignote = set(self.modello) - set(attese)
        mancanti = set(attese) - set(self.modello)
        if ignote or mancanti:
            raise FuoriDominio(f"modello {self.modello['tipo']}: chiavi ignote {sorted(ignote)}, mancanti {sorted(mancanti)}")
        for c in attese[1:]:
            if c.startswith("due_") or c == "Jmax":
                _intero(self.modello[c], f"modello.{c}")
            else:
                _reale(self.modello[c], f"modello.{c}")
        if self.modello["tipo"] == "tlf_centrex":       # settore e base chiusi PRIMA della sandbox (NEMESIS B 11/11)
            jm, dmf = self.modello["Jmax"], self.modello["due_MF"]
            if not 0 <= jm <= JMAX_TLF:
                raise FuoriDominio(f"modello.Jmax: atteso 0 <= Jmax <= {JMAX_TLF}")
            if dmf % 2 or abs(dmf) > 2 * jm + 2:
                raise FuoriDominio("modello.due_MF: atteso pari (I1 = I2 = 1/2, J intero) con |M_F| <= Jmax + 1")
        _intero(self.livelli, "livelli", 1)
        if self.livelli > LIVELLI_MAX:
            raise FuoriDominio(f"livelli: al più {LIVELLI_MAX}")
        if not isinstance(self.troncamento, dict) or not all(isinstance(k, str) for k in self.troncamento):
            raise FuoriDominio("troncamento: atteso un dizionario con chiavi stringa")
        for k, v in self.troncamento.items():
            if isinstance(v, bool) or not isinstance(v, (int, float, str)) or (isinstance(v, float) and not math.isfinite(v)):
                raise FuoriDominio(f"troncamento.{k}: atteso int, float finito o stringa")
        if self.porta in TRONCAMENTI:
            if self.modello["tipo"] != MODELLO_DI_PORTA[self.porta]:
                raise FuoriDominio(f"porta {self.porta}: modello atteso {MODELLO_DI_PORTA[self.porta]!r}")
            if set(self.troncamento) != set(TRONCAMENTI[self.porta]):
                raise FuoriDominio(f"porta {self.porta}: troncamento con chiavi esattamente {TRONCAMENTI[self.porta]}")
            for k in TRONCAMENTI[self.porta]:
                _intero(self.troncamento[k], f"troncamento.{k}", 1)
        if not isinstance(self.unita, str) or self.unita not in UNITA:
            raise FuoriDominio(f"unita: non in {tuple(UNITA)}")
        _intero(self.secondi, "secondi", 1)
        _intero(self.mem_mib, "mem_mib", 16)
        if self.secondi > SECONDI_MAX or self.mem_mib > MEM_MIB_MAX:
            raise FuoriDominio(f"limiti: secondi ≤ {SECONDI_MAX}, mem_mib ≤ {MEM_MIB_MAX}")
        if not isinstance(self.site_packages, tuple) or not all(isinstance(p, str) and os.path.isdir(p) for p in self.site_packages):
            raise FuoriDominio("site_packages: atteso una tupla di cartelle esistenti")
        # solo cartelle site-/dist-packages (percorso reale): la casa dell'utente montata esporrebbe le sue cartelle nascoste (NEMESIS 11/11)
        if not all(os.path.basename(os.path.realpath(p)) in ("site-packages", "dist-packages") for p in self.site_packages):
            raise FuoriDominio("site_packages: ammesse solo cartelle site-packages o dist-packages")

    def json(self) -> Dict[str, object]:
        return {"contratto": CONTRATTO, "porta": self.porta, "modello": dict(self.modello), "livelli": self.livelli,
                "troncamento": dict(self.troncamento), "unita": self.unita,
                "limiti": {"secondi": self.secondi, "mem_mib": self.mem_mib}, "site_packages": list(self.site_packages)}


@dataclass(frozen=True)
class Uscita:
    porta: str
    versione_solutore: str
    livelli: Tuple[float, ...]
    unita: str
    stato: str            # OK | ERRORE | NON_VALIDA
    motivo: str
    secondi: float
    sandbox: str


def valida_uscita(doc: object, r: Richiesta) -> Tuple[Optional[Uscita], str]:
    """Schema CHIUSO: (Uscita, "") se valida, (None, motivo) altrimenti. Nessuna chiave ignota passa."""
    if not isinstance(doc, dict):
        return None, "uscita non è un oggetto JSON"
    ignote = set(doc) - set(CHIAVI_USCITA)
    mancanti = set(CHIAVI_USCITA) - set(doc)
    if ignote or mancanti:
        return None, f"chiavi ignote {sorted(ignote)}, mancanti {sorted(mancanti)}"
    if doc["contratto"] != CONTRATTO:
        return None, f"contratto {doc['contratto']!r} ≠ {CONTRATTO}"
    if doc["porta"] != r.porta:
        return None, f"porta {doc['porta']!r} ≠ {r.porta!r}"
    for c in ("versione_solutore", "motivo", "stato", "unita"):
        if not isinstance(doc[c], str):
            return None, f"{c}: atteso una stringa"
    if doc["stato"] not in ("OK", "ERRORE"):
        return None, f"stato {doc['stato']!r} non in (OK, ERRORE)"
    if doc["unita"] not in UNITA:
        return None, f"unita {doc['unita']!r} non in {tuple(UNITA)}"
    if not _finito(doc["secondi"]):
        return None, "secondi: atteso un numero finito"
    liv = doc["livelli"]
    if not isinstance(liv, list):
        return None, "livelli: atteso una lista"
    if doc["stato"] == "OK":
        if len(liv) != r.livelli:
            return None, f"livelli: {len(liv)} valori, attesi {r.livelli}"
        for x in liv:
            if not _finito(x):
                return None, "livelli: atteso numeri reali finiti"
    else:
        liv = []                       # ERRORE: i livelli non servono e non vengono convertiti (mai un'eccezione)
    return Uscita(doc["porta"], doc["versione_solutore"], tuple(float(x) for x in liv), doc["unita"], doc["stato"],
                  doc["motivo"], float(doc["secondi"]), ""), ""


def _bwrap() -> str:
    b = shutil.which("bwrap")
    if b is None:
        raise SandboxAssente("bwrap (bubblewrap) non trovato: nessuna esecuzione di codice esterno (fail-closed)")
    st = os.stat(os.path.realpath(b))
    if st.st_uid != 0 or st.st_mode & 0o022:          # un «bwrap» scrivibile dall'utente nel PATH non è una sandbox
        raise SandboxAssente(f"bwrap {b!r} non è di root o è scrivibile da altri: nessuna esecuzione (fail-closed)")
    return b


def _no_dup(coppie):
    d = {}
    for k, v in coppie:
        if k in d:
            raise ValueError(f"chiave duplicata {k!r}")
        d[k] = v
    return d


def _no_costante(nome):
    raise ValueError(f"costante non JSON {nome}")


def leggi_uscita(percorso: str) -> Tuple[Optional[object], str]:
    """Legge uscita.json come file REGOLARE (O_NOFOLLOW), al più USCITA_MAX_BYTE, JSON stretto: niente NaN/Infinity,
    niente chiavi duplicate, profondità limitata dal parser (RecursionError = rifiuto). (doc, "") oppure (None, motivo)."""
    try:
        fd = os.open(percorso, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError as e:
        return None, f"nessuna uscita leggibile: {type(e).__name__}"
    try:
        import stat as _stat
        if not _stat.S_ISREG(os.fstat(fd).st_mode):
            return None, "uscita non è un file regolare"
        with os.fdopen(fd, "rb") as f:
            fd = -1
            dati = f.read(USCITA_MAX_BYTE + 1)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(dati) > USCITA_MAX_BYTE:
        return None, f"uscita oltre {USCITA_MAX_BYTE} byte"
    try:
        return json.loads(dati.decode("utf-8"), object_pairs_hook=_no_dup, parse_constant=_no_costante), ""
    except (ValueError, RecursionError) as e:
        return None, f"uscita non JSON: {type(e).__name__}: {str(e)[:200]}"


def _case_utente() -> Tuple[str, ...]:
    """Le case dell'utente: $HOME e quella del database utenti (possono differire: sudo -E, servizi, HOME temporanea)."""
    case = {os.path.realpath(os.path.expanduser("~"))}
    try:
        import pwd
        case.add(os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir))
    except (ImportError, KeyError, OSError):
        pass
    return tuple(sorted(case))


def _dentro(p: str, cartella: str) -> bool:
    return p == cartella or p.startswith(cartella.rstrip("/") + "/")


def _prefisso_interprete(python: str) -> Tuple[str, ...]:
    """Pezzi dell'interprete da montare in sola lettura quando sta fuori da /usr (python di uv, pyenv, runner CI):
    l'eseguibile, la libreria standard (stdlib, platstdlib) e le libpython*.so* di LIBDIR; MAI la cartella del prefisso
    intera (con prefisso <casa>/.local o la casa stessa esporrebbe le cartelle nascoste dell'utente: NEMESIS 11/11).
    Chiusa: prefisso mai «/», «/home», una casa dell'utente ($HOME o pwd) o un suo antenato; ogni pezzo dentro il
    prefisso; nulla già sotto i montaggi di sistema."""
    reale = os.path.realpath(python)
    if any(_dentro(reale, m) for m in MONTAGGI_RO):
        return ()
    codice = ("import sys, sysconfig, json; v = sysconfig.get_config_var; "
              "print(json.dumps([sys.base_prefix, sysconfig.get_path('stdlib'), sysconfig.get_path('platstdlib'), "
              "v('LIBDIR') or '']))")
    try:
        p = subprocess.run([reale, "-I", "-c", codice], capture_output=True, text=True, timeout=30,
                           env={"PATH": "/usr/bin:/bin"})
        dati = json.loads(p.stdout) if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        dati = None
    if not (isinstance(dati, list) and len(dati) == 4 and all(isinstance(x, str) for x in dati)):
        raise FuoriDominio(f"python {python!r}: prefisso di installazione non determinabile")
    prefisso = os.path.realpath(dati[0]) if dati[0] else ""
    if not prefisso or not os.path.isdir(prefisso) or not reale.startswith(prefisso + "/"):
        raise FuoriDominio(f"python {python!r}: prefisso di installazione non determinabile o incoerente ({prefisso!r})")
    for vietato in ("/", "/home") + _case_utente():
        if _dentro(vietato, prefisso):
            raise FuoriDominio(f"python {python!r}: il prefisso {prefisso!r} conterrebbe la casa dell'utente: rifiutato")
    pezzi = [reale]
    for d in dati[1:3]:
        if d and os.path.isdir(d):
            pezzi.append(os.path.realpath(d))
    libdir = os.path.realpath(dati[3]) if dati[3] else ""
    if libdir and os.path.isdir(libdir):
        pezzi += sorted(os.path.join(libdir, n) for n in os.listdir(libdir)
                        if n.startswith("libpython") and ".so" in n and os.path.isfile(os.path.join(libdir, n)))
    fuori = []
    for x in dict.fromkeys(os.path.realpath(x) for x in pezzi):
        if any(_dentro(x, m) for m in MONTAGGI_RO):
            continue                                   # già montato (es. stdlib che punta a /usr/lib)
        if not _dentro(x, prefisso) or x == prefisso:
            raise FuoriDominio(f"python {python!r}: {x!r} fuori dal prefisso {prefisso!r} o uguale a esso: rifiutato")
        fuori.append(x)
    return tuple(fuori)


def esegui_porta(r: Richiesta, python: Optional[str] = None) -> Uscita:
    """Esegue la porta nella sandbox e restituisce l'Uscita validata (stato NON_VALIDA col motivo se lo schema non passa,
    il processo è stato ucciso o non ha scritto JSON). Mai un'eccezione per un difetto del codice esterno."""
    if not isinstance(r, Richiesta):
        raise FuoriDominio("atteso una Richiesta")
    bwrap = _bwrap()
    python = os.path.realpath(python or sys.executable)      # il venv (symlink) non è montato: serve il binario vero
    if not os.path.isfile(python):
        raise FuoriDominio(f"python {python!r} non esiste")
    work = tempfile.mkdtemp(prefix="qraft_porta_")
    try:
        with open(os.path.join(work, "richiesta.json"), "w", encoding="utf-8") as f:
            json.dump(r.json(), f)
        shutil.copy(RUNNER, os.path.join(work, "porte_runner.py"))
        percorso = os.path.join(work, "uscita.json")
        open(percorso, "wb").close()               # l'UNICO file scrivibile della porta: bind di un file, non della cartella
        err_path = os.path.join(work, "stderr.txt")
        cmd = [bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--clearenv"]
        for m in MONTAGGI_RO:
            if os.path.isdir(m):
                cmd += ["--ro-bind", m, m]
        # ordine: i tmpfs PRIMA dei bind sotto di essi (un montaggio successivo copre i precedenti)
        sz = str(TMPFS_BYTE)
        cmd += ["--dev", "/dev", "--size", sz, "--tmpfs", "/dev/shm", "--proc", "/proc", "--size", sz, "--tmpfs", "/tmp",
                "--size", sz, "--tmpfs", "/home"]
        for sp in r.site_packages:
            sp = os.path.realpath(sp)
            cmd += ["--ro-bind", sp, sp]
        for pr in _prefisso_interprete(python):                    # interprete fuori da /usr (venv uv, CI): solo i suoi pezzi, ro
            cmd += ["--ro-bind", pr, pr]
        cmd += ["--ro-bind", work, "/tmp/work", "--bind", percorso, "/tmp/work/uscita.json",
                "--setenv", "HOME", "/tmp/casa_assente", "--setenv", "PATH", "/usr/bin:/bin",
                "--setenv", "PYTHONDONTWRITEBYTECODE", "1", "--setenv", "OMP_NUM_THREADS", "1",
                "--setenv", "OPENBLAS_NUM_THREADS", "1", "--chdir", "/tmp",
                python, "-I", "-S", "-B", "/tmp/work/porte_runner.py", "/tmp/work"]
        descr = "bwrap --unshare-all --clearenv; ro: " + ",".join(MONTAGGI_RO) + " + site-packages; HOME tmpfs"
        # ambiente MINIMO già per bwrap: il suo processo init (PID 1 nella sandbox) conserva l'ambiente con cui è
        # lanciato e la porta lo legge in /proc/1/environ (NEMESIS 11/11: token di sessione letti dalla porta).
        # stdout scartato e stderr su file: un flusso illimitato non entra nella memoria del lato fidato.
        try:
            with open(err_path, "wb") as ferr:
                p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=ferr,
                                   env={"PATH": "/usr/bin:/bin"}, timeout=r.secondi + 5)
        except subprocess.TimeoutExpired:
            return Uscita(r.porta, "", (), r.unita, "NON_VALIDA", f"timeout: oltre {r.secondi + 5} s", float(r.secondi + 5), descr)
        with open(err_path, "rb") as ferr:
            ferr.seek(max(0, os.path.getsize(err_path) - 600))
            coda = ferr.read().decode("utf-8", "replace")
        if os.path.getsize(percorso) == 0:
            return Uscita(r.porta, "", (), r.unita, "NON_VALIDA", f"nessuna uscita (codice {p.returncode}): {coda}", 0.0, descr)
        doc, motivo = leggi_uscita(percorso)
        if doc is None:
            return Uscita(r.porta, "", (), r.unita, "NON_VALIDA", motivo, 0.0, descr)
        u, motivo = valida_uscita(doc, r)
        if u is None:
            return Uscita(r.porta, "", (), r.unita, "NON_VALIDA", f"schema: {motivo}", 0.0, descr)
        if u.stato == "OK" and p.returncode != 0:      # specifica §3.2: codice ≠ 0 → non confrontabile
            return Uscita(r.porta, "", (), r.unita, "NON_VALIDA", f"stato OK ma codice di uscita {p.returncode}: {coda}", 0.0, descr)
        return Uscita(u.porta, u.versione_solutore, u.livelli, u.unita, u.stato, u.motivo, u.secondi, descr)
    finally:
        shutil.rmtree(work, ignore_errors=True)


@dataclass(frozen=True)
class Verdetto:
    complessivo: str                              # DENTRO | DENTRO_TOLLERANZA | FUORI | NON_CONFRONTABILE
    per_livello: Tuple[Tuple[str, str], ...]      # (DENTRO|DENTRO_TOLLERANZA|FUORI, distanza)
    motivo: str


def confronta(iv: Intervalli, unita_intervalli: str, u: Uscita, tolleranza: float = 0.0) -> Verdetto:
    """Confronto esatto (Fraction): E_j dell'uscita convertito nell'unità degli intervalli con fattori 10^n.
    `tolleranza` (stessa unità degli intervalli, ≥ 0, predefinita 0) è il rumore DICHIARATO dal chiamante per il
    solutore float (eigvalsh: ~eps·‖H‖, misurato 1e-13 GHz a ncut 30 in note dell'autore (non pubblicate)): un
    livello fuori di meno è DENTRO_TOLLERANZA, con la distanza; oltre è FUORI. Lista chiusa dei verdetti."""
    if not isinstance(iv, Intervalli):
        raise FuoriDominio("atteso Intervalli")
    if unita_intervalli not in UNITA:
        raise FuoriDominio(f"unita_intervalli: non in {tuple(UNITA)}")
    if not isinstance(u, Uscita):
        raise FuoriDominio("atteso Uscita")
    tol = Fraction(_reale(tolleranza, "tolleranza"))
    if tol < 0:
        raise FuoriDominio("tolleranza: atteso >= 0")
    if u.stato != "OK":
        return Verdetto("NON_CONFRONTABILE", (), f"uscita {u.stato}: {u.motivo}")
    if u.unita not in UNITA or not all(_finito(x) for x in u.livelli):
        raise FuoriDominio("Uscita OK con unità ignota o livelli non finiti")
    k = len(u.livelli)
    if k == 0:
        return Verdetto("NON_CONFRONTABILE", (), "nessun livello")
    if k != len(iv.bassi):                            # mai un DENTRO su una parte dei livelli senza dirlo
        return Verdetto("NON_CONFRONTABILE", (), f"livelli dell'uscita {k} ≠ intervalli {len(iv.bassi)}")
    fattore = UNITA[u.unita] / UNITA[unita_intervalli]
    righe: List[Tuple[str, str]] = []
    for j in range(k):
        e = Fraction(u.livelli[j]) * fattore
        if iv.bassi[j] <= e <= iv.alti[j]:
            righe.append(("DENTRO", "0"))
        else:
            d = iv.bassi[j] - e if e < iv.bassi[j] else e - iv.alti[j]
            righe.append(("DENTRO_TOLLERANZA" if d <= tol else "FUORI", f"{float(d):.6e} {unita_intervalli}"))
    stati = {s for s, _ in righe}
    comp = "FUORI" if "FUORI" in stati else ("DENTRO_TOLLERANZA" if "DENTRO_TOLLERANZA" in stati else "DENTRO")
    return Verdetto(comp, tuple(righe), f"{k} livelli confrontati, intervalli {iv.stato} (larghezza max {iv.larghezza_max:.3e})")
