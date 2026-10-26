#!/usr/bin/env bash
# One command: original Rel17.3 Guest, preboot cfg telem_poles=42,
# then independent 900/1040/1285 Hz full T01 DShot300 QEMU tests.
# Not original Guest UART CLI; not a physical 12S motor model.
set -euo pipefail
cd "$(dirname "$0")/.."
ELF=baseline/e62-g13b3/firmware/AM13E-rev17.3.elf
QEMU=.build/qemu-src/build/qemu-system-arm
PLAN=scenarios/e62-dshot-v1.json
INPUT=configs/e62-functional-input.json
TEMPLATE=configs/e62-functional-bemf.json
DIR=artifacts/e62-ecx87-kv210-full-batch
CFG="$DIR/e62-g13b3-ecx87-kv210-cfg-flash.bin"
mkdir -p "$DIR"
test -f "$ELF" && test -x "$QEMU" && test -f "$PLAN" && test -f "$INPUT"
python3 tools/sim_motor_cfg.py --sim-only-opt-in --elf "$ELF" \
  --motor-profile ecx87-kv210 --output "$CFG"

for HZ in 900 1040 1285; do
    PREFIX="$DIR/e62-dshot300-$HZ-hz"
    BEMF="$PREFIX-bemf.json"
    EVIDENCE="$PREFIX-evidence.json"
    LOG="$PREFIX.log"
    python3 - "$HZ" "$TEMPLATE" "$BEMF" <<'PY'
import json,sys
from pathlib import Path
from tools.functional_three_phase_bemf import load_three_phase_config
hz=int(sys.argv[1])
original=json.loads(Path(sys.argv[2]).read_text())
assert original["mode"]=="INDEPENDENT_THREE_PHASE_FIXED_HZ"
original["electrical_hz"]=hz
Path(sys.argv[3]).write_text(json.dumps(original,indent=2)+"\n")
assert load_three_phase_config(sys.argv[3]).electrical_hz==hz
PY
    echo "E62_BATCH_START hz=$HZ expected_erpm=$((HZ*60))"
    set +e
    python3 tests/functional_dshot_sitl.py \
      --qemu "$QEMU" --elf "$ELF" --cfg-flash "$CFG" \
      --require-motor-profile ecx87-kv210 \
      --plan "$PLAN" --id T01 --input-config "$INPUT" \
      --bemf-config "$BEMF" --six-phase-audit \
      --six-phase-max-sectors 100000 \
      --artifact "$EVIDENCE" >"$LOG" 2>&1
    RC=$?
    set -e
    echo "$RC" >"$PREFIX-exit-code.txt"
    echo "E62_BATCH_END hz=$HZ child_rc=$RC evidence=$EVIDENCE log=$LOG"
done

python3 - "$DIR" <<'PY'
import json,sys
from pathlib import Path
d=Path(sys.argv[1]); entries=[]
for hz in (900,1040,1285):
    base=d/f"e62-dshot300-{hz}-hz"
    path=Path(str(base)+"-evidence.json")
    rc_path=Path(str(base)+"-exit-code.txt")
    rc=int(rc_path.read_text()) if rc_path.exists() else 127
    try:
        e=json.loads(path.read_text())
    except (OSError,ValueError) as err:
        e={"status":"FAIL_EVIDENCE_UNAVAILABLE","error":str(err)}
    phase=e.get("six_phase_audit") or {}
    cfg=e.get("sim_only_motor_cfg") or {}
    bemf=e.get("independent_bemf_diagnostics") or {}
    stage=e.get("stages") or []
    good=(
        rc==0 and
        e.get("status")=="PASS_FUNCTIONAL_INDEPENDENT_THREE_PHASE_BEMF_ONLY" and
        e.get("completed_full_duration") is True and
        e.get("dshot_frames_sent")==11000 and
        e.get("issues")==[] and
        len(stage)==2 and all(s.get("status")=="PASS" for s in stage) and
        (e.get("teardown") or {}).get("qualified_original_neutral") is True and
        phase.get("status")=="PASS_WFI_BRACKETED_SIX_PHASE_FUNCTIONAL_ONLY" and
        phase.get("failed_commutation_total")==0 and
        phase.get("issues")==[] and
        cfg.get("telem_poles")==42 and
        cfg.get("original_guest_elf_unchanged") is True and
        bemf.get("electrical_hz")==float(hz) and
        e.get("guest_register_writes") is False and
        e.get("guest_ecap_irq_injection") is False)
    hold=next((s for s in stage if s.get("kind")=="hold" and
               s.get("start_ns")==1000000000 and
               s.get("end_ns")==11000000000),None)
    services=hold.get("original_timg12_service_delta") if hold else None
    rate=(services/10.0)/(6*hz) if type(services) is int else None
    rate_match=rate is not None and abs(rate-1)<=0.10
    entries.append({
        "electrical_hz":hz,"expected_erpm":hz*60,
        "expected_mechanical_rpm_for_21_pole_pairs":hz*60/21,
        "original_guest_functional_status":"PASS" if good else "FAIL",
        "original_guest_status":e.get("status"),
        "child_return_code":rc,
        "six_phase_sector_count":phase.get("settled_commutation_count"),
        "hold_timg12_services":services,
        "observed_average_commutation_to_ideal_ratio":rate,
        "rate_screen_only_10percent":"MATCH" if rate_match else "MISMATCH_OR_UNAVAILABLE",
        "physical_rotor_phase_lock_qualified":False,
        "evidence_file":str(path),
        "log_file":str(base)+".log"})
functional=all(r["original_guest_functional_status"]=="PASS" for r in entries)
rate_ok=all(r["rate_screen_only_10percent"]=="MATCH" for r in entries)
report={
    "scope":"SIM_ONLY_ORIGINAL_REL17_3_FULL_T01_FIXED_BEMF_BATCH",
    "pole_pairs":21,"esc_telem_poles":42,
    "firmware_elf_unchanged":True,
    "guest_uart_cli_executed":False,
    "12s_power_model_qualified":False,
    "electrical_phase_lock_qualified":False,
    "all_functional_points_pass":functional,
    "all_average_rate_screens_match":rate_ok,
    "overall_status":(
        "PASS_FUNCTIONAL_AND_RATE_SCREEN_ONLY" if functional and rate_ok
        else "FAIL_FUNCTIONAL_POINT" if not functional
        else "FAIL_AVERAGE_SECTOR_RATE_SCREEN"),
    "points":entries}
p=d/"batch-summary.json"
p.write_text(json.dumps(report,indent=2)+"\n")
print("E62_BATCH_SUMMARY "+json.dumps({
    "overall_status":report["overall_status"],
    "all_functional_points_pass":functional,
    "all_average_rate_screens_match":rate_ok,
    "points":entries,"file":str(p)},sort_keys=True))
if not functional or not rate_ok:
    sys.exit(1)
PY
