#!/usr/bin/env bash
set -euo pipefail

RLC="$HOME/Documents/rlc-infrastructure/rlc-release/install/bin/rlc"
PYTHON_BIN="${PYTHON_BIN:-python3}"

mkdir -p build

case "${1:-gui}" in
  main)
    "$RLC" src/main.rl -o build/app
    exec ./build/app
    ;;
  gui)
    "$RLC" src/main.rl --shared -o build/lib.dylib
    "$RLC" --python src/main.rl -o build/wrapper.py
    exec "$PYTHON_BIN" src/gui.py
    ;;
  build)
    "$RLC" src/main.rl -o build/app
    "$RLC" src/main.rl --shared -o build/lib.dylib
    "$RLC" --python src/main.rl -o build/wrapper.py
    ;;
  *)
    echo "Uso: $0 [gui|main|build]"
    exit 1
    ;;
esac