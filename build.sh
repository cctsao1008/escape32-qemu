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
# Create a Cortex-M33 variant with the Security Extension absent:
# AM13E's TRM says TrustZone is not enabled. A standard QEMU 6.2
# cortex-m33 has the M_SECURITY feature and resets in Secure state.
cpu_file = qemu / 'target/arm/cpu_tcg.c'
cpu_content = cpu_file.read_text()
model_start = '''static void cortex_m33_am13e_initfn(Object *obj)
{
    ARMCPU *cpu = ARM_CPU(obj);

    cortex_m33_initfn(obj);
    unset_feature(&cpu->env, ARM_FEATURE_M_SECURITY);
    cpu->sau_sregion = 0;
    cpu->isar.id_pfr1 &= ~0x000000f0U; /* Security field: absent */
}

'''
entry = '''    { .name = "cortex-m33-am13e", .initfn = cortex_m33_am13e_initfn,
                              .class_init = arm_v7m_class_init },
'''
if model_start not in cpu_content:
    anchor = 'static void cortex_m55_initfn(Object *obj)\n'
    if cpu_content.count(anchor) != 1:
        sys.exit('ERROR: QEMU v6.2.0 CPU model anchor missing')
    cpu_content = cpu_content.replace(anchor, model_start + anchor, 1)
if entry not in cpu_content:
    anchor = '    { .name = "cortex-m55",  .initfn = cortex_m55_initfn,\n'
    if cpu_content.count(anchor) != 1:
        sys.exit('ERROR: QEMU v6.2.0 CPU registry anchor missing')
    cpu_content = cpu_content.replace(anchor, entry + anchor, 1)
updates[cpu_file] = cpu_content
# G11 native + independent PendSV control reproduced a QEMU 6.2.0 bug:
# v7m_exception_taken() produces EXC_RETURN.ES=1 for a v8-M CPU with
# M_SECURITY intentionally absent, but do_v7m_exception_exit() rejects
# ES=1 on that same architecture with CFSR.INVPC. This is visible with
# the original ESCape32 SysTick handler AND a separate 20-instruction
# PendSV-only fixture. Repair the GENERATOR (not exception validation).
# The exact anchor is specific to the pinned QEMU revision, fail closed.
m_helper_file = qemu / 'target/arm/m_helper.c'
m_helper = m_helper_file.read_text()
bad_excret = '''        if (targets_secure || !arm_feature(env, ARM_FEATURE_M_SECURITY)) {
            lr |= R_V7M_EXCRET_ES_MASK;
        }
'''
good_excret = '''        /* G11: no Security Extension -> EXC_RETURN.ES must be zero.
         * QEMU 6.2's unmodified v8-M return integrity check explicitly
         * rejects ES=1 when M_SECURITY is absent. */
        if (targets_secure && arm_feature(env, ARM_FEATURE_M_SECURITY)) {
            lr |= R_V7M_EXCRET_ES_MASK;
        }
'''
if good_excret not in m_helper:
    if m_helper.count(bad_excret) != 1:
        sys.exit('ERROR: pinned QEMU v8-M EXC_RETURN.ES anchor changed')
    m_helper = m_helper.replace(bad_excret, good_excret, 1)
updates[m_helper_file] = m_helper
source = root / 'machine/am13e23019.c'
target = qemu / 'hw/arm/am13e23019.c'
feedback_source = root / 'machine/am13e_motor_feedback.inc'
feedback_target = qemu / 'hw/arm/am13e_motor_feedback.inc'
if feedback_target.is_symlink():
    sys.exit('ERROR: generated feedback path is a symlink')
if not feedback_target.exists() or feedback_target.read_bytes() != feedback_source.read_bytes():
    feedback_target.write_bytes(feedback_source.read_bytes())
trip_source = root / 'machine/am13e_trip_safety.inc'
trip_target = qemu / 'hw/arm/am13e_trip_safety.inc'
if trip_target.is_symlink():
    sys.exit('ERROR: generated G13B2 trip safety path is a symlink')
if not trip_target.exists() or trip_target.read_bytes() != trip_source.read_bytes():
    trip_target.write_bytes(trip_source.read_bytes())
wave_source = root / 'machine/am13e_pa26_waveform.inc'
wave_target = qemu / 'hw/arm/am13e_pa26_waveform.inc'
if wave_target.is_symlink():
    sys.exit('ERROR: generated PA26 waveform path is a symlink')
if not wave_target.exists() or wave_target.read_bytes() != wave_source.read_bytes():
    wave_target.write_bytes(wave_source.read_bytes())
if target.is_symlink():
    sys.exit('ERROR: generated machine path is a symlink; refusing overwrite')
if target.exists() and 'TYPE_AM13E_MACHINE MACHINE_TYPE_NAME("am13e23019")' not in target.read_text():
    sys.exit('ERROR: unexpected machine file in QEMU worktree')
for file, contents in updates.items():
    file.write_text(contents)
if not target.exists() or target.read_bytes() != source.read_bytes():
    print('G0: syncing generated Machine source into ignored QEMU worktree')
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
