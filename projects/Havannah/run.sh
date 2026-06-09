#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ -n "${RLC:-}" ]]; then
  :
elif [[ -x "$ROOT/../../../rlc-release/install/bin/rlc" ]]; then
  RLC="$ROOT/../../../rlc-release/install/bin/rlc"
elif [[ -x "$HOME/Documents/rlc-infrastructure/rlc-release/install/bin/rlc" ]]; then
  RLC="$HOME/Documents/rlc-infrastructure/rlc-release/install/bin/rlc"
else
  echo "Compilatore RLC non trovato." >&2
  echo "Imposta RLC=/percorso/a/rlc oppure compila rlc-release (vedi README)." >&2
  exit 1
fi

mkdir -p build

build_python_wrapper() {
  "$RLC" src/main.rl --shared -o build/lib.dylib
  "$RLC" --python src/main.rl -o build/wrapper.py
}

case "${1:-gui}" in
  main)
    "$RLC" src/main.rl -o build/app
    exec ./build/app
    ;;

  gui)
    build_python_wrapper
    exec "$PYTHON_BIN" src/gui.py
    ;;

  fuzz)
    build_python_wrapper
    exec "$PYTHON_BIN" src/ui_fuzz_engine.py "${@:2}"
    ;;

  build)
    "$RLC" src/main.rl -o build/app
    build_python_wrapper
    ;;

  *)
    echo "Uso: $0 [gui|main|build|fuzz] [argomenti fuzzer...]"
    exit 1
    ;;
esac
