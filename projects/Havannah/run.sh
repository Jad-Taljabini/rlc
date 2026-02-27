#!/usr/bin/env bash
set -u -o pipefail
set -e

RLC="$HOME/Documents/rlc-infrastructure/rlc-release/install/bin/rlc"
mkdir -p build
"$RLC" src/main.rl -o build/app

set +e
./build/app
code=$?
set -e

echo "Exit code: $code"
exit $code
