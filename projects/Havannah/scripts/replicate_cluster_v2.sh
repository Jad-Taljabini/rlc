#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TIME_BUDGET="${TIME_BUDGET_SECONDS:-240}"
REPORT_EVERY="${REPORT_EVERY:-200}"
SLEEP_BETWEEN="${SLEEP_BETWEEN_SECONDS:-10}"
OUT="${OUT_DIR:-fuzz_out/cluster_final_v2_$(date +%Y%m%d_%H%M)}"

MODES=(
  random_raw
  coverage_guided
  coverage_guided_rate
  rgr_positive
  rgr_positive_rate
  anti_rgr_negative
  anti_rgr_negative_rate
)
X_VALUES=(1 10 100 500)
SEEDS=(1 2 3)

echo "==> Build"
./run.sh build

mkdir -p "$OUT"
echo "Output: $OUT"
echo "Time budget per run: ${TIME_BUDGET}s"

for x in "${X_VALUES[@]}"; do
  for seed in "${SEEDS[@]}"; do
    for mode in "${MODES[@]}"; do
      run_id="${mode}_x${x}_s${seed}"
      echo "==> Run $run_id"
      python3 src/ui_fuzz_engine.py \
        --target gui \
        --gui-file src/gui_buggy.py \
        --mode "$mode" \
        --bug-variant-mod "$x" \
        --time-budget-seconds "$TIME_BUDGET" \
        --iterations 100000000 \
        --report-every "$REPORT_EVERY" \
        --seed "$seed" \
        --run-id "$run_id" \
        --out-dir "$OUT/$run_id"
      sleep "$SLEEP_BETWEEN"
    done
  done
done

zip -r "${OUT}.zip" "$OUT"
echo "DONE: $OUT"
echo "Archive: ${OUT}.zip"
