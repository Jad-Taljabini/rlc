#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Build Rulebook wrapper"
./run.sh build

echo "==> Fuzz model (1 iterazione, no GUI)"
python3 src/ui_fuzz_engine.py \
  --target model \
  --mode coverage_guided \
  --iterations 1 \
  --seed 1 \
  --out-dir fuzz_out/smoke_model \
  --report-every 1

echo "==> Fuzz GUI buggy (1 iterazione)"
python3 src/ui_fuzz_engine.py \
  --target gui \
  --gui-file src/gui_buggy.py \
  --mode rgr_positive_rate \
  --bug-variant-mod 10 \
  --iterations 1 \
  --seed 1 \
  --out-dir fuzz_out/smoke_gui \
  --report-every 1

test -f fuzz_out/smoke_model/stats.json
test -f fuzz_out/smoke_gui/stats.json

echo "OK: smoke test completato."
