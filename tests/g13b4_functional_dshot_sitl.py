#!/usr/bin/env python3
"""EXPERIMENTAL E62 Functional SITL: scripted DShot + BEMF on original ELF.

An independent functional test, not G13B3M physical rotor proof. This
runner has NOT been qualified against the user's pinned QEMU in this
package. It FAILS CLOSED and always writes JSON evidence, including when
incomplete. Inputs touch only the existing non-silicon PA26 DShot wire,
three-channel analog port, and pre-CPU factory configuration Flash.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from elf_image import app_vector_from_elf, elf_function_address
from g0_memory import QTest
from g1_handoff import RSP, wait_for_socket
from g11_exception_lifecycle import (
    reach_release, observer, add_bp, del_bp)
from g12_runtime_progress import native_wfi_locations
from g13b_native_wfi import wait_for_native_main_wfi
from g13b_native_no_drive import symbol_address
from g13b_native_dshot import queue_dshot600_wire, WAVE
from g13b2_native_drive_probe import (
    resolve_original_rel17_wfi_roles, native_original_zero_throttle_arm,
    native_wait_for_bemf_calibration, step_unchanged_native_wfi, EXT_OC)
from g7b_pa26_capture import dshot_frame
from tools.functional_dshot_scenario import (
    load_scenario, ScenarioError, VirtualTimeDShotSequencer)
from tools.functional_bemf import FunctionalBemf
from tools.functional_guest_clock import OriginalGuestTickClock
from tools.native_bemf_qualification import (
    audit_native_bemf_arm_elf, observe_original_bemf_route)
from tools.native_pwm_qualification import observe_original_pwm
from tools.native_runtime_timeline import ECAP1_TSCTR
from tools.virtual_bldc_feedback import SIM_BEMF_INPUT


def _checked_symbols(elf: Path) -> dict:
    names = ("tick", "calibration_done", "valid_frame_feeds", "throt",
             "step", "selected_code", "captured_events", "scheduled",
             "serviced")
    result = {k: symbol_address(elf, k) for k in names}
    audit = audit_native_bemf_arm_elf(elf)
    if audit.address is None:
        raise AssertionError("Original native BEMF armed symbol ambiguous: " + audit.reason)
    result["armed"] = audit.address
    return result


def _make_stage_records(scenario):
    return [{"index": s.index, "kind": s.kind, "start_ns": s.start_ns,
             "end_ns": s.end_ns, "from_pct": float(s.from_pct),
             "to_pct": float(s.to_pct), "frames_sent": 0,
             "valid_crc_feeds_observed": 0, "guest_pwm_powered_observed": False,
             "guest_nonzero_throttle_observed": False,
             "guest_neutral_throttle_observed": False,
             "original_cap1_count_delta": 0,
             "original_timg12_service_delta": 0,
             "native_steps_observed": [], "status": "OPEN_NOT_EXECUTED"}
            for s in scenario.stages]


def _stage_index(scenario, t_ns):
    for s in scenario.stages:
        if s.start_ns <= t_ns < s.end_ns:
            return s.index
    return len(scenario.stages)-1


def _guest_values(rsp, addresses):
    return {name: rsp.mem32(addr) for name, addr in addresses.items()
            if name in ("throt", "valid_frame_feeds", "step", "selected_code",
                        "armed", "captured_events", "scheduled", "serviced")}


def _run_guest(args, scenario, evidence):
    app_vector_from_elf(args.elf)
    observed_sha = hashlib.sha256(args.elf.read_bytes()).hexdigest()
    if observed_sha != scenario.pinned_elf_sha256:
        raise AssertionError("Original Guest ELF SHA does not match scenario")
    wfi = resolve_original_rel17_wfi_roles(
        args.elf, native_wfi_locations(args.elf, args.objdump))
    addresses = _checked_symbols(args.elf)
    original_callback = elf_function_address(args.elf,
                        "am13e_app_io_dshot_packet")[0]
    stage_records = evidence["stages"]
    with tempfile.TemporaryDirectory(prefix="e62-functional-sitl-") as tmp:
        tmp = Path(tmp)
        qtpath, gdbpath = (str(tmp/'qtest.sock'), str(tmp/'gdb.sock'))
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(qtpath)
            listener.listen(1)
            listener.settimeout(15)
            with open(tmp/'qemu-stderr.log', 'w+b') as stderr:
                command = [str(args.qemu.resolve()), '-M',
                    'am13e23019,esc-sim=on,esc-sim-nfault-asserted=off',
                    '-kernel', str(args.elf.resolve()), '-S',
                    '-display', 'none', '-serial', 'none', '-monitor', 'none',
                    '-chardev', f'socket,path={gdbpath},server=on,wait=off,id=gdb0',
                    '-gdb', 'chardev:gdb0', '-qtest', f'unix:path={qtpath}',
                    '-icount', 'shift=2,sleep=off,align=off', '-device',
                    'loader,file='+str(args.cfg_flash.resolve())+
                    ',addr=0x4000,force-raw=on']
                proc = subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                        stderr=stderr)
                qconn = None
                armed = set()
                try:
                    qconn, _ = listener.accept()
                    qtest = QTest(qconn)
                    for phase in range(3):
                        qtest.write(EXT_OC+4*phase, 0x10000 | 1000)
                    with wait_for_socket(gdbpath, proc) as conn:
                        rsp = RSP(conn)
                        if not rsp.command('?').startswith(('S','T')):
                            raise AssertionError('QEMU original guest not halted at reset')
                        if 'qXfer:features:read+' not in rsp.command(
                                'qSupported:qXfer:features:read+'):
                            raise AssertionError('QEMU GDB target XML not advertised')
                        if not rsp.command(
                                'qXfer:features:read:target.xml:0,1').startswith(
                                    ('m<','l<')):
                            raise AssertionError('QEMU GDB target XML missing')
                        if rsp.command('Qqemu.sstep:1') != 'OK':
                            raise AssertionError('QEMU timed IRQ stepping unavailable')
                        expected = args.cfg_flash.read_bytes()
                        for off in (0,28,32):
                            actual = rsp.mem32(0x4000+off)
                            wanted = int.from_bytes(expected[off:off+4], 'little')
                            if actual != wanted:
                                raise AssertionError('Pre-CPU source Flash cfg mismatch')
                        _, hardfault, _ = reach_release(
                            rsp, args.elf, args.startup_steps)
                        for pc in (*wfi, hardfault):
                            add_bp(rsp, pc)
                            armed.add(pc)
                        checkpoint = wait_for_native_main_wfi(
                            rsp, wfi, hardfault, args.slice_ms,
                            args.runtime_slices, stage='FUNCTIONAL_NEUTRAL')
                        checkpoint = native_wait_for_bemf_calibration(
                            rsp, wfi, checkpoint, hardfault, armed,
                            addresses['calibration_done'], args.slice_ms,
                            args.runtime_slices, args.calibration_wfi_visits)
                        for pc in wfi:
                            del_bp(rsp, pc)
                            armed.remove(pc)
                        if checkpoint != wfi[1]:
                            raise AssertionError('Expected original ARM-loop WFI before zero arming')
                        neutral = native_original_zero_throttle_arm(
                            rsp, qtest, wfi=wfi, hardfault=hardfault,
                            armed_breakpoints=armed, throt=addresses['throt'],
                            callback=original_callback, slice_ms=args.slice_ms,
                            runtime_slices=args.runtime_slices,
                            bemf_state=addresses)
                        if not neutral.get('qualified'):
                            raise AssertionError('Original neutral DShot arming not qualified')
                        evidence['native_zero_arming'] = neutral
                        if args.autonomous:
                            # Keep legacy G13B4 per-WFI path unchanged.
                            # G13B5 runs the unmodified Guest continuously.
                            from tools.autonomous_sitl_runner import run_autonomous
                            return run_autonomous(
                                args, scenario, evidence, rsp, qtest,
                                hardfault, armed, addresses, wfi)
                        checkpoint = wfi[0]
                        for pc in wfi:
                            if pc not in armed:
                                add_bp(rsp, pc)
                                armed.add(pc)
                        # ECAP1.TSCTR can be stopped during zero-throttle ARM.
                        # Drive *scenario time* from the original Guest-owned
                        # 16 kHz SysTick; ECAP stays diagnostic, not a clock.
                        first_tick = rsp.mem32(addresses['tick'])
                        clock = OriginalGuestTickClock(first_tick)
                        first_tsctr = qtest.read(ECAP1_TSCTR)
                        elapsed_ns = clock.elapsed_ns
                        last_values = _guest_values(rsp, addresses)
                        last_feeds = last_values['valid_frame_feeds']
                        last_cap = last_values['captured_events']
                        last_service = last_values['serviced']
                        feedback = FunctionalBemf(
                            crossing_delay_ns=args.bemf_crossing_delay_us * 1000,
                            amplitude_codes=args.bemf_amplitude_codes)
                        evidence['scenario_t0'] = {
                            'origin': 'AFTER_ORIGINAL_ZERO_DSHOT_ARM_AT_RUNNING_WFI',
                            'original_ecap_tsctr': first_tsctr,
                            'original_guest_tick': first_tick,
                            'scenario_clock_source': 'ORIGINAL_GUEST_SYSTICK_16KHZ',
                            'ecap_tsctr_used_for_scenario_clock': False,
                            'host_guest_register_writes': False}
                        print('E62_FUNCTIONAL_GUEST_CLOCK ' +
                              json.dumps(evidence['scenario_t0'],
                                         sort_keys=True), flush=True)
                        def send_frame(throttle):
                            # Do not print 110,000 redundant QTest waveform lines.
                            with redirect_stdout(io.StringIO()):
                                frame = queue_dshot600_wire(
                                    qtest, throttle, allow_zero=True,
                                    reset_completed_wave=True)
                            if frame != dshot_frame(throttle):
                                raise AssertionError('Transmitted DShot CRC mismatch')
                            return frame
                        last_command_value = None
                        evidence['command_transitions'] = []
                        sequencer = VirtualTimeDShotSequencer(
                            scenario, send_frame,
                            max_lateness_ns=args.max_lateness_us*1000)
                        native_wfi_count = 0
                        while True:
                            native_wfi_count += 1
                            if native_wfi_count > args.max_wfi_visits:
                                raise AssertionError('Exceeded bounded original WFI visits')
                            cpu = observer(rsp)
                            if (cpu['cfsr'] or cpu['hfsr'] or
                                    cpu['pc'] == hardfault):
                                raise AssertionError('Original Guest HardFault')
                            step = _guest_values(rsp, addresses)
                            if step['captured_events'] < last_cap or step['serviced'] < last_service:
                                raise AssertionError('Original CAP1/TIMG12 source counters regressed')
                            if step['valid_frame_feeds'] < last_feeds:
                                raise AssertionError('Original DShot CRC valid counter regressed')
                            if checkpoint != wfi[0]:
                                raise AssertionError('Original firmware returned to ARM WFI during scenario')
                            stage_id = _stage_index(scenario, elapsed_ns)
                            stage = stage_records[stage_id]
                            stage['valid_crc_feeds_observed'] += (
                                step['valid_frame_feeds'] - last_feeds)
                            stage['original_cap1_count_delta'] += (
                                step['captured_events'] - last_cap)
                            stage['original_timg12_service_delta'] += (
                                step['serviced'] - last_service)
                            if 1 <= step['step'] <= 6 and step['step'] not in stage['native_steps_observed']:
                                stage['native_steps_observed'].append(step['step'])
                            stage['guest_nonzero_throttle_observed'] |= step['throt'] > 1
                            stage['guest_neutral_throttle_observed'] |= step['throt'] == 0
                            last_feeds = step['valid_frame_feeds']
                            last_cap = step['captured_events']
                            last_service = step['serviced']
                            last_values = step
                            if native_wfi_count % args.pwm_sample_interval == 0:
                                p = observe_original_pwm(qtest.read, gate_active_level=1)
                                if p.acceptable_for_plant:
                                    stage['guest_pwm_powered_observed'] = True
                                    if p.physical_ost2 or p.physical_ost3:
                                        raise AssertionError('Unexpected native OST after gate')
                            event = sequencer.poll(elapsed_ns)
                            if event is not None:
                                if (not evidence['command_transitions'] or
                                      evidence['command_transitions'][-1]['dshot_value']
                                      != event['dshot_value']):
                                    evidence['command_transitions'].append({
                                        'scheduled_virtual_ns': event['scheduled_virtual_ns'],
                                        'observed_guest_elapsed_ns': event['observed_guest_elapsed_ns'],
                                        'dshot_value': event['dshot_value'],
                                        'throttle_pct': event['throttle_pct'],
                                        'stage_index': event['stage_index'],
                                        'original_valid_crc_feeds_at_send': step['valid_frame_feeds'],
                                    })
                                stage_records[event['stage_index']]['frames_sent'] += 1
                                if (event['frame_index'] % 1000 == 0 or
                                        event['scheduled_virtual_ns'] == stage['start_ns']):
                                    print('E62_FUNCTIONAL_DSHOT_SENT ' +
                                          json.dumps(event,sort_keys=True),flush=True)
                            # Only real original comparator/ECAP readiness
                            # authorizes synthetic analog stimulus.
                            if (native_wfi_count % args.bemf_sample_interval == 0 and
                                    step['armed'] == 1 and step['throt'] > 1):
                                route = observe_original_bemf_route(
                                    qtest.read, selected_code=step['selected_code'],
                                    native_armed=True)
                                if route.channel_ready_for_voltage_samples:
                                    p = observe_original_pwm(qtest.read,
                                                              gate_active_level=1)
                                    if p.acceptable_for_plant:
                                        vector = feedback.evaluate(
                                            guest_ns=elapsed_ns,
                                            guest_step=step['step'],
                                            selected_code=step['selected_code'],
                                            selected_phase=route.selected_phase,
                                            expected_edge_falling=route.expected_edge_falling,
                                            dac_code=route.active_dac_code)
                                        feedback.inject(vector, qtest.write,
                                                        qtest.read, SIM_BEMF_INPUT)
                            elif step['throt'] <= 1:
                                feedback.neutralize(qtest.write, qtest.read,
                                                    SIM_BEMF_INPUT)
                            if ((sequencer.complete and elapsed_ns >= scenario.duration_ns)
                                    or (args.max_frames and
                                        sequencer.next_index >= args.max_frames)):
                                evidence['completed_full_duration'] = (
                                    sequencer.complete and elapsed_ns >= scenario.duration_ns)
                                break
                            # Existing helper validates the real Guest WFI,
                            # but its per-visit print would produce millions
                            # of lines for T02. Retain it on exception.
                            wfi_diagnostics = io.StringIO()
                            try:
                                with redirect_stdout(wfi_diagnostics):
                                    checkpoint = step_unchanged_native_wfi(
                                        rsp, checkpoint, armed_breakpoints=armed,
                                        wfi=wfi, hardfault=hardfault,
                                        slice_ms=args.slice_ms,
                                        runtime_slices=args.runtime_slices,
                                        stage='FUNCTIONAL_DSHOT_WFI')
                            except Exception:
                                print(wfi_diagnostics.getvalue(), file=sys.stderr)
                                raise
                            # Read-only original source tick advances even
                            # before motor ECAP1 is enabled. A same-tick WFI
                            # adds zero time; repeated stalls still fail.
                            elapsed_ns = clock.observe(
                                rsp.mem32(addresses['tick']))
                            evidence['last_guest_virtual_elapsed_ns'] = elapsed_ns
                            evidence['native_wfi_visits'] = native_wfi_count
                            evidence['dshot_frames_sent'] = sequencer.next_index
                            evidence['last_guest_state'] = last_values
                            if native_wfi_count % 1000 == 0:
                                print('E62_FUNCTIONAL_PROGRESS ' + json.dumps({
                                    'native_wfi_visits': native_wfi_count,
                                    'guest_elapsed_ms': elapsed_ns/1_000_000,
                                    'sent_frames': sequencer.next_index,
                                    'source_captured': last_cap,
                                    'source_serviced': last_service},
                                    sort_keys=True),flush=True)
                        # Fixture teardown is separate from the declared
                        # scenario. Repeat CRC-valid physical neutral until
                        # the unchanged Guest itself decodes throt=0.
                        if evidence['completed_full_duration']:
                            teardown_before = last_feeds
                            teardown_packets = 0
                            next_zero_ns = elapsed_ns
                            teardown_start_ns = elapsed_ns
                            for attempt in range(args.teardown_max_wfi):
                                if elapsed_ns >= next_zero_ns:
                                    send_frame(0)
                                    teardown_packets += 1
                                    next_zero_ns += scenario.frame_period_ns
                                diag = io.StringIO()
                                try:
                                    with redirect_stdout(diag):
                                        checkpoint = step_unchanged_native_wfi(
                                            rsp, checkpoint,
                                            armed_breakpoints=armed,
                                            wfi=wfi, hardfault=hardfault,
                                            slice_ms=args.slice_ms,
                                            runtime_slices=args.runtime_slices,
                                            stage='FUNCTIONAL_DSHOT_TEARDOWN')
                                except Exception:
                                    print(diag.getvalue(),file=sys.stderr)
                                    raise
                                elapsed_ns = clock.observe(
                                    rsp.mem32(addresses['tick']))
                                last_values = _guest_values(rsp,addresses)
                                if (last_values['valid_frame_feeds'] > teardown_before and
                                      last_values['throt'] == 0):
                                    break
                                if elapsed_ns-teardown_start_ns > 20_000_000:
                                    raise AssertionError('Original neutral teardown did not complete within 20ms')
                            else:
                                raise AssertionError('Original neutral teardown exhausted WFI bound')
                            feedback.neutralize(qtest.write,qtest.read,SIM_BEMF_INPUT)
                            evidence['teardown'] = {
                                'qualified_original_neutral': True,
                                'physical_zero_frames_sent': teardown_packets,
                                'original_crc_feeds_increased': True,
                                'original_guest_throt_zero': True,
                                'excluded_from_scenario_time': True,
                                'teardown_guest_duration_ns': elapsed_ns-teardown_start_ns}
                        evidence['native_wfi_visits'] = native_wfi_count
                        evidence['last_guest_virtual_elapsed_ns'] = elapsed_ns
                        evidence['last_guest_state'] = last_values
                        evidence['dshot_frames_sent'] = sequencer.next_index
                        evidence['scripted_bemf_crossings_issued'] = feedback.crossings_issued
                        evidence['guest_clock_observations'] = {
                            'origin_tick': clock.origin_tick,
                            'last_tick': clock.previous_tick,
                            'elapsed_ns': clock.elapsed_ns,
                            'last_delta_ticks': clock.last_delta_ticks,
                            'total_zero_delta_wfi': clock.total_zero_delta_observations,
                            'consecutive_zero_delta_wfi': clock.stalled_observations,
                            'source': 'ORIGINAL_GUEST_SYSTICK_16KHZ'}
                        if not evidence['completed_full_duration']:
                            evidence['status'] = 'OPEN_BOUNDED_SMOKE_NOT_FULL_DURATION'
                        else:
                            issues = []
                            for row in stage_records:
                                require_positive = row['to_pct'] > 0
                                ok = (row['frames_sent'] > 0 and
                                      row['valid_crc_feeds_observed'] > 0 and
                                      (row['guest_nonzero_throttle_observed'] if require_positive
                                       else row['guest_neutral_throttle_observed']) and
                                      (not require_positive or
                                       (row['guest_pwm_powered_observed'] and
                                        row['original_cap1_count_delta'] > 0 and
                                        row['original_timg12_service_delta'] > 0)))
                                row['status'] = 'PASS' if ok else 'FAIL'
                                if not ok:
                                    issues.append('stage_'+str(row['index']))
                            if feedback.crossings_issued == 0:
                                issues.append('no_scripted_comparator_crossing')
                            evidence['status'] = ('PASS_FUNCTIONAL_SCRIPTED_BEMF_ONLY'
                                if not issues else 'FAIL_FUNCTIONAL_SITL_ORACLE')
                            evidence['issues'] = issues
                        print('E62_FUNCTIONAL_SITL_VERDICT ' +
                              json.dumps({k:evidence[k] for k in (
                                'status','completed_full_duration',
                                'native_wfi_visits','dshot_frames_sent',
                                'scripted_bemf_crossings_issued')},
                                sort_keys=True),flush=True)
                        return evidence['status'].startswith('PASS')
                finally:
                    # Cleanup is debugger-owned; no Guest register writes.
                    if qconn is not None:
                        qconn.close()
                    if proc.poll() is None:
                        proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
                    stderr.flush()
                    if args.artifact:
                        (args.artifact.parent / (args.artifact.stem+'.qemu-stderr.log')).write_bytes(
                            (tmp/'qemu-stderr.log').read_bytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--qemu', type=Path, required=True)
    ap.add_argument('--elf', type=Path, required=True)
    ap.add_argument('--cfg-flash', type=Path, required=True)
    ap.add_argument('--plan', type=Path, required=True)
    ap.add_argument('--id', dest='case_id', choices=('T01','T02'), required=True)
    ap.add_argument('--artifact', type=Path, required=True)
    ap.add_argument('--objdump', default='arm-none-eabi-objdump')
    ap.add_argument('--startup-steps', type=int, default=32768)
    ap.add_argument('--slice-ms', type=int, default=300)
    ap.add_argument('--runtime-slices', type=int, default=20)
    ap.add_argument('--calibration-wfi-visits', type=int, default=24)
    ap.add_argument('--max-wfi-visits', type=int, default=3000000)
    ap.add_argument('--max-frames', type=int, default=0,
                    help='Bounded native smoke, 0 means full duration; smoke NEVER PASS')
    ap.add_argument('--autonomous', action='store_true',
                    help='G13B5 opt-in: QEMU virtual-time DShot/BEMF, no per-WFI GDB')
    ap.add_argument('--autonomous-wall-timeout-s', type=int, default=300,
                    help='Host guard only; never the scenario virtual clock')
    ap.add_argument('--autonomous-poll-ms', type=int, default=50,
                    help='Host diagnostic polling, not stimulus timing')
    ap.add_argument('--autonomous-telemetry-interval-ms', type=int, default=200,
                    help='Guest virtual time between async stage telemetry samples')
    ap.add_argument('--max-lateness-us', type=int, default=500)
    ap.add_argument('--bemf-crossing-delay-us', type=int, default=750)
    ap.add_argument('--bemf-amplitude-codes', type=int, default=128)
    ap.add_argument('--pwm-sample-interval', type=int, default=10)
    ap.add_argument('--bemf-sample-interval', type=int, default=2)
    ap.add_argument('--teardown-max-wfi', type=int, default=1000)
    args = ap.parse_args()
    for f in (args.qemu,args.elf,args.cfg_flash,args.plan):
        if not f.is_file():
            ap.error('File missing: '+str(f))
    if (not 256 <= args.cfg_flash.stat().st_size <= 4096 or
        not 1 <= args.max_wfi_visits <= 5000000 or
        not 0 <= args.max_frames <= 110000 or
        not 0 <= args.max_lateness_us < 1000 or
        not 1 <= args.pwm_sample_interval <= 1000 or
        not 1 <= args.bemf_sample_interval <= 1000 or
        not 1 <= args.teardown_max_wfi <= 5000):
        ap.error('Unsafe fixture bounds')
    if (not 10 <= args.autonomous_wall_timeout_s <= 7200 or
            not 10 <= args.autonomous_poll_ms <= 1000 or
            not 50 <= args.autonomous_telemetry_interval_ms <= 10000):
        ap.error('Unsafe autonomous observation bound')
    scenario = load_scenario(args.plan,args.case_id)
    args.artifact.parent.mkdir(parents=True,exist_ok=True)
    evidence = dict(scope='EXPERIMENTAL_FUNCTIONAL_SCRIPTED_BEMF_NO_MOTOR_RPM_PROOF',
                    status='OPEN_NOT_EXECUTED', scenario=scenario.summary(),
                    stages=_make_stage_records(scenario),
                    guest_register_writes=False,
                    guest_ecap_irq_injection=False,
                    physical_rotor_stability_qualified=False)
    ok=False
    try:
        ok=_run_guest(args,scenario,evidence)
    except Exception as exc:
        evidence['status']='FAIL_NATIVE_FUNCTIONAL_SITL'
        evidence['error_type']=type(exc).__name__
        evidence['error']=str(exc)
        evidence['traceback']=traceback.format_exc(limit=12)
        print('E62_FUNCTIONAL_SITL_FAIL '+str(exc),file=sys.stderr,flush=True)
    finally:
        args.artifact.write_text(json.dumps(evidence,indent=2)+'\n')
        print('E62_FUNCTIONAL_SITL_EVIDENCE '+str(args.artifact),flush=True)
    return 0 if ok else 1


if __name__=='__main__':
    sys.exit(main())
