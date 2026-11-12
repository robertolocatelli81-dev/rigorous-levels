#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
# Local reproduction of the CI matrix (limit A of 0.3.0): the whole suite against the INSTALLED package on every venv
# given, with the stack at its default, unlimited and 1 MiB, with the sandbox engines available and with bwrap absent
# from PATH and with a fake bwrap that fails. Every run uses a fresh temporary HOME. Results in matrix_<stamp>/.
#
#   bench/matrix.sh VENV...        e.g. bench/matrix.sh /path/to/venv-3.11 /path/to/venv-3.12
#   NICE=19 MAX_PARALLEL=1 bench/matrix.sh ...   (defaults; one run at a time, low priority)
#
# What is measured: for each (venv, stack, sandbox state) the unittest summary line and the list of skips with their
# reasons; a run is wrong if the summary is not "OK" or if a sandbox test is skipped while its engine is available.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="${OUT:-$ROOT/matrix_$STAMP}"
NICE="${NICE:-19}"
TESTS="test_guaranteed_intervals test_rotor_spectrum test_scqubits_adapter test_readme_example test_spherical_rotor test_hyperfine_molecule test_inputs_review test_duffing_vs_transmon test_multiport test_port_centrex_tlf test_mathieu test_fluxonium test_parameter_balls test_matrix_elements test_cos4phi_origin test_examples test_generative_inputs test_deprecated_aliases test_spec_bounds"
mkdir -p "$OUT"
echo "matrix $STAMP, root $ROOT, out $OUT" | tee "$OUT/SUMMARY.txt"

run_one() {   # venv stack sandbox_state
  local venv="$1" stack="$2" sb="$3" py="$1/bin/python" tag label home fake
  label="$(basename "$venv")_stack-${stack}_${sb}"
  home="$(mktemp -d)"
  fake="$(mktemp -d)"
  tag="$OUT/$label"
  (
    export HOME="$home" PYTHONUSERBASE="${PYTHONUSERBASE:-$HOME/.local}" PIP_NO_CACHE_DIR=1 OMP_NUM_THREADS=1
    unset PYTHONPATH
    # podman needs its own store even with a temporary HOME: the real XDG folders are passed explicitly
    export XDG_DATA_HOME="${XDG_DATA_HOME:-$(getent passwd "$(id -u)" | cut -d: -f6)/.local/share}"
    export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$(getent passwd "$(id -u)" | cut -d: -f6)/.config}"
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    case "$sb" in
      no-bwrap)   # hide bwrap from PATH: a folder of links to every other tool (on merged-usr systems /bin and
                  # /usr/bin both hold bwrap, so removing one folder from PATH is not enough)
                  for d in $(echo "$PATH" | tr ':' ' '); do
                    [ -d "$d" ] && for f in "$d"/*; do n="$(basename "$f")"; [ "$n" = bwrap ] && continue; [ -e "$fake/$n" ] || ln -s "$f" "$fake/$n" 2>/dev/null; done
                  done
                  export PATH="$fake" ;;
      fake-bwrap) printf '#!/bin/sh\nexit 1\n' > "$fake/bwrap"; chmod 755 "$fake/bwrap"; export PATH="$fake:$PATH" ;;
    esac
    case "$stack" in default) ;; unlimited) ulimit -s unlimited ;; *) ulimit -s "$stack" ;; esac
    "$py" -m pip install -q --no-deps --force-reinstall "$ROOT" >/dev/null 2>&1
    cd "$ROOT/tests"
    "$py" -c 'import qraft_ra; assert "site-packages" in qraft_ra.__file__' || { echo "NOT INSTALLED" ; exit 3; }
    nice -n "$NICE" "$py" -B -m unittest -v $TESTS > "$tag.log" 2>&1
    echo $? > "$tag.rc"
  )
  local rc; rc="$(cat "$tag.rc" 2>/dev/null || echo "?")"
  local summary; summary="$(grep -E '^(OK|FAILED)' "$tag.log" | tail -1)"
  local ran; ran="$(grep -E '^Ran ' "$tag.log" | tail -1)"
  echo "$label: rc=$rc | $ran | $summary" | tee -a "$OUT/SUMMARY.txt"
  grep -E "skipped" "$tag.log" | sed -E 's/.*skipped/skipped/' | sort | uniq -c | sort -rn > "$tag.skips"
  rm -rf "$home" "$fake"
}

for venv in "$@"; do
  for stack in default unlimited 1024; do
    run_one "$venv" "$stack" engines
  done
  run_one "$venv" default no-bwrap
  run_one "$venv" default fake-bwrap
done
echo "done: $(date)" | tee -a "$OUT/SUMMARY.txt"
