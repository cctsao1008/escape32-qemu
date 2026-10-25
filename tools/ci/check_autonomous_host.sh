#!/usr/bin/env bash
# A single fail-closed entrypoint shared by CI and local developers.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
python3 -m py_compile \
    tools/native_arming.py \
    tools/sitl_autonomous_transport.py \
    tools/sitl_autonomous_evidence.py \
    tools/sitl_stage_oracle.py \
    tools/autonomous_sitl_host.py \
    tools/autonomous_sitl_runner.py \
    tests/functional_dshot_sitl.py \
    tests/g13b4_functional_dshot_sitl.py \
    tests/g13b2_native_drive_probe.py
python3 -m unittest discover -s tests -p 'test_autonomous*.py' -v
echo PASS_G13B7_1_AUTONOMOUS_REFACTOR_HOST
