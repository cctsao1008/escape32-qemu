#!/usr/bin/env bash
# Compile pinned QEMU into a separate ignored worktree.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
PIN=44f28df24767cf9dca1ddc9b23157737c4cbb645
SUB="$ROOT/qemu"
SRC="$ROOT/.build/qemu-src"

if [[ ! -f "$SUB/hw/arm/meson.build" ]]; then
    echo "ERROR: git submodule update --init qemu" >&2
    exit 1
fi
if [[ "$(git -C "$SUB" rev-parse HEAD)" != "$PIN" ]]; then
    echo "ERROR: wrong QEMU source commit; expected v6.2.0" >&2
    exit 1
fi
if [[ ! -d "$SRC" ]]; then
    mkdir -p "$ROOT/.build"
    git -C "$SUB" worktree add --detach "$SRC" "$PIN"
fi
if [[ "$(git -C "$SRC" rev-parse HEAD)" != "$PIN" ]]; then
    echo "ERROR: generated QEMU worktree commit mismatch" >&2
    exit 1
fi
python3 - "$ROOT" "$SRC" <<'PY'
from pathlib import Path
import sys
root, qemu = map(Path, sys.argv[1:])
patches = {
    'hw/arm/meson.build': (
        "arm_ss.add(when: 'CONFIG_MPS2', if_true: files('mps2.c'))\n",
        "arm_ss.add(when: 'CONFIG_AM13E23019', if_true: files('am13e23019.c'))\n"
        "arm_ss.add(when: 'CONFIG_MPS2', if_true: files('mps2.c'))\n"),
    'hw/arm/Kconfig': (
        'config ARM_V7M\n    bool\n',
        'config AM13E23019\n    bool\n    select ARM_V7M\n\n'
        'config ARM_V7M\n    bool\n'),
    'configs/devices/arm-softmmu/default.mak': (
        'CONFIG_MPS2=y\n',
        'CONFIG_MPS2=y\nCONFIG_AM13E23019=y\n')
}
updates = {}
for rel, (anchor, replacement) in patches.items():
    file = qemu / rel
    contents = file.read_text()
    if replacement in contents:
        continue
    if contents.count(anchor) != 1:
        sys.exit('ERROR: QEMU v6.2.0 integration anchor changed: ' + rel)
    updates[file] = contents.replace(anchor, replacement, 1)
source = root / 'machine/am13e23019.c'
target = qemu / 'hw/arm/am13e23019.c'
if target.exists() and target.read_bytes() != source.read_bytes():
    sys.exit('ERROR: generated machine source unexpectedly changed')
for file, contents in updates.items():
    file.write_text(contents)
if not target.exists():
    target.write_bytes(source.read_bytes())
print('G0 machine integration: OK')
PY
git -C "$SRC" diff --check
if ! pkg-config --exists glib-2.0 gthread-2.0 pixman-1; then
    echo "ERROR: sudo apt install libglib2.0-dev libpixman-1-dev pkg-config" >&2
    exit 1
fi
cd "$SRC"
./configure --target-list=arm-softmmu --disable-werror --disable-docs
ninja -C build qemu-system-arm
if ! build/qemu-system-arm -M help | grep -q am13e23019; then
    echo "ERROR: AM13E machine not registered" >&2
    exit 1
fi
echo "PASS_G0_BUILD: $SRC/build/qemu-system-arm"
