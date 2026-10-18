#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
if [[ $# -ne 1 ]]; then
    echo "Usage: ./test.sh /path/to/AM13E-rev17.3.elf" >&2
    exit 2
fi
python3 "$ROOT/tests/g0_memory.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
python3 "$ROOT/tests/g2_sysctl.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
python3 "$ROOT/tests/g2_fri.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
python3 "$ROOT/tests/g2_mclkcfg.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
python3 "$ROOT/tests/g1_handoff.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
