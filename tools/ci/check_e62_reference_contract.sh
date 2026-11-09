#!/usr/bin/env bash
# Existing production-source HOST/register fixtures; not native QEMU qualification.
set -euo pipefail
fw=$(realpath "${1:?firmware checkout required}")
sdk=$(realpath "${2:?official TI SDK checkout required}")
test "$(git -C "$fw" rev-parse HEAD)" = 53953c04f7d857f3b402b3a19870605ed0471d8f
test "$(git -C "$sdk" rev-parse HEAD)" = b872469ceef18de5e39a1d3acb0821ec158b44c7
git -C "$fw" diff --quiet HEAD --
git -C "$sdk" diff --quiet HEAD --
cd "$fw"
export AM13E_SDK_ROOT="$sdk"
bash mcu/_support/AM13E/tools/run_host_regressions.sh
bash mcu/_support/AM13E/tools/run_motor_register_regression.sh
git diff --quiet HEAD --
echo PASS_E62_REFERENCE_HOST_REGISTER_CONTRACT_NOT_QEMU_OR_P1
