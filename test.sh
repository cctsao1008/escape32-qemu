#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
if [[ $# -ne 1 ]]; then
    echo "Usage: ./test.sh /path/to/AM13E-rev17.3.elf" >&2
    exit 2
fi
python3 "$ROOT/tests/test_rsp.py"
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
python3 "$ROOT/tests/g2_xtalcr.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
python3 "$ROOT/tests/g2_hsclken.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
python3 "$ROOT/tests/g2_hfclkcfg.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
python3 "$ROOT/tests/g2_virtual_xtal.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
python3 "$ROOT/tests/g2_pllcfg.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
python3 "$ROOT/tests/g2_factory.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
python3 "$ROOT/tests/g2_pllparam.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
python3 "$ROOT/tests/g2_esc_sim.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
python3 "$ROOT/tests/g3_gpio.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
python3 "$ROOT/tests/g3_iomux.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
python3 "$ROOT/tests/g3_gpio_bootstrap.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
python3 "$ROOT/tests/g4_peripheral_gprcm.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
python3 "$ROOT/tests/g4_adc_sequencer.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
python3 "$ROOT/tests/g5_wwdt.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
python3 "$ROOT/tests/g1_handoff.py" \
    --qemu "$ROOT/.build/qemu-src/build/qemu-system-arm" \
    --elf "$1"
