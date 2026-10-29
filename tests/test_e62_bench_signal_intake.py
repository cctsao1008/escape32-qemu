"""All traces in this test are SYNTHETIC UNIT fixtures, NEVER bench data."""
import csv
from datetime import datetime
import hashlib
import io
import unittest

from tools.e62_board_adc_epoch_intake import (
    audit as adc_audit,HEADER,SECTOR)
from tools.e62_board_gate_fault_intake import (
    audit as gate_audit,FIELDS,GATES)

SHA="c"*40
def table(headers,records):
    out=io.StringIO(newline="")
    writer=csv.writer(out,lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(records)
    return out.getvalue().encode()

def adc_fixture():
    data=[]
    for i,sector in enumerate((0,1,2,3,4,5)):
        phase=[2048]*3
        order=SECTOR[sector]
        phase[order[0]]=2100
        phase[order[2]]=2000
        acq=100+10*i
        data.append([i+1,acq,acq+2,acq+3,*phase,1,1,1,1,1,1,0])
    raw=table(HEADER,data)
    meta=dict(schema="e62.bench.adc-epoch.v1",
        capture_kind="BENCH_CAPTURE_DECLARED_UNVERIFIED",
        board_revision="UNVERIFIED_UNIT_BOARD",board_serial="UNVERIFIED_UNIT_SERIAL",
        firmware_commit=SHA,instrument_id="UNIT_INSTRUMENT_NOT_REAL",
        measured_at_utc="2026-10-30T00:00:00Z",
        trace_sha256=hashlib.sha256(raw).hexdigest(),
        phase_pinmap_ref="DRAFT/board-pinmap-pending",
        adc_calibration_ref="DRAFT/ADC-transfer-pending",
        sample_clock_ref="DRAFT/tick-frequency-pending",
        tick_hz=1000,max_scan_ticks=4,max_gap_ticks=20,
        max_age_ticks=5,max_rank_hold_ticks=35,min_adjacent_codes=3)
    return raw,meta,data

def gate_fixture():
    rows=[]
    for i in range(18):
        fault=int(5<=i<12)
        active=int(i in (1,2,3,4,5))
        # One gate toggling, other outputs low. Scope discriminator is
        # a mock signal and contains no actual 47V gate measurement.
        gate=[active,0,0,0,0,0]
        rows.append([i*10,fault,*gate])
    raw=table(FIELDS,rows)
    meta=dict(schema="e62.bench.six-gate-fault.v1",
        capture_kind="BENCH_VGS_SCOPE_DIGITALIZED_UNVERIFIED",
        fault_source="oc_u",board_revision="UNVERIFIED_UNIT_BOARD",
        board_serial="UNVERIFIED_UNIT_SERIAL",firmware_commit=SHA,
        instrument_id="UNIT_INSTRUMENT_NOT_REAL",
        measured_at_utc="2026-10-30T00:00:00Z",
        raw_trace_sha256=hashlib.sha256(raw).hexdigest(),
        gate_probe_reference="UNIT test only: VGS-per-device six probes",
        fault_probe_reference="UNIT test only: fault external source",
        gate_discriminator_ref="UNIT threshold chosen for fake data",
        fault_polarity_ref="UNIT active-high digital input",
        max_sample_gap_ns=10,min_pre_fault_ns=20,min_post_release_ns=20,
        approved_max_gate_off_ns=None)
    return raw,meta,rows

def signed(raw,meta,key):
    meta[key]=hashlib.sha256(raw).hexdigest()
    return raw,meta

class BoardADCIntake(unittest.TestCase):
    def test_unverified_synthetic_data_never_qualifies_motor(self):
        raw,meta,_=adc_fixture()
        x=adc_audit(raw,meta)
        self.assertEqual(x["epochs_checked"],6)
        self.assertEqual(x["adjacent_phase_rank_transitions_only"],5)
        self.assertFalse(x["hardware_qualified"])
        self.assertFalse(x["motor_rearm_permitted"])
        self.assertFalse(x["physical_rotor_direction_or_angle_qualified"])

    def test_source_tamper_rejected(self):
        raw,meta,_=adc_fixture()
        with self.assertRaisesRegex(ValueError,"SHA256"):
            adc_audit(raw+b" ",meta)

    def test_simulation_not_hardware(self):
        raw,meta,_=adc_fixture()
        meta["capture_kind"]="SIM_ONLY"
        with self.assertRaisesRegex(ValueError,"synthetic model"):
            adc_audit(raw,meta)

    def test_stale_or_future_timestamp_rejected(self):
        _,m,d=adc_fixture()
        d[2][3]=1000
        r=table(HEADER,d);signed(r,m,"trace_sha256")
        with self.assertRaisesRegex(ValueError,"scan/staleness"):
            adc_audit(r,m)

    def test_lost_epoch_rejected(self):
        _,m,d=adc_fixture()
        d[2][0]=9
        r=table(HEADER,d);signed(r,m,"trace_sha256")
        with self.assertRaisesRegex(ValueError,"Lost/repeated"):
            adc_audit(r,m)

    def test_overrun_or_unfinished_adc_rejected(self):
        _,m,d=adc_fixture()
        d[2][-1]=1
        r=table(HEADER,d);signed(r,m,"trace_sha256")
        with self.assertRaisesRegex(ValueError,"overrun"):
            adc_audit(r,m)
        _,m,d=adc_fixture()
        d[2][7]=0
        r=table(HEADER,d);signed(r,m,"trace_sha256")
        with self.assertRaisesRegex(ValueError,"incomplete"):
            adc_audit(r,m)

    def test_ambiguous_phase_rank_must_never_authorize(self):
        _,m,d=adc_fixture()
        d[2][4:7]=[2048,2048,2048]
        r=table(HEADER,d);signed(r,m,"trace_sha256")
        x=adc_audit(r,m)
        self.assertGreater(x["ambiguous_low_code_contrast_epochs"],0)
        self.assertEqual(x["interpretation"],
                         "INCOMPLETE_OR_AMBIGUOUS_PHASE_RANK_EVIDENCE")
        self.assertFalse(x["motor_rearm_permitted"])

    def test_missing_channel_header_rejected(self):
        _,m,d=adc_fixture()
        r=table(HEADER[:-1],[v[:-1] for v in d]);signed(r,m,"trace_sha256")
        with self.assertRaisesRegex(ValueError,"header"):
            adc_audit(r,m)


    def test_overlapping_adc_acquisition_rejected_even_with_valid_each_scan(self):
        _,m,d=adc_fixture()
        # 2nd conversion begins before the prior published snapshot is read.
        # Each individual scan and the completion-to-completion gap fit.
        d[1][1:4]=[102,104,105]
        r=table(HEADER,d);signed(r,m,"trace_sha256")
        with self.assertRaisesRegex(ValueError,"overlapping or reordered"):
            adc_audit(r,m)

    def test_noncanonical_adc_budget_type_fails_closed(self):
        raw,m,_=adc_fixture()
        m["max_scan_ticks"]="4"
        with self.assertRaisesRegex(ValueError,"JSON integer"):
            adc_audit(raw,m)
        raw,m,_=adc_fixture()
        m["tick_hz"]=True
        with self.assertRaisesRegex(ValueError,"JSON integer"):
            adc_audit(raw,m)

    def test_adc_manifest_not_an_object_rejected(self):
        raw,_,_=adc_fixture()
        with self.assertRaisesRegex(ValueError,"JSON object"):
            adc_audit(raw,[])

class SixGateFaultIntake(unittest.TestCase):
    def test_scoped_fault_gates_stable_after_release_needs_review(self):
        raw,meta,_=gate_fixture()
        x=gate_audit(raw,meta)
        self.assertEqual(x["sampled_gate_off_upper_bound_ns"],20)
        self.assertEqual(x["sampled_gate_off_lower_bound_ns"],0)
        self.assertEqual(x["fault_assert_sample_ns"],50)
        self.assertEqual(x["all_six_vgs_discriminators_off_at_ns"],60)
        self.assertEqual(x["gate_off_numeric_acceptance"],
                         "NO_APPROVED_NUMERIC_CRITERION")
        self.assertFalse(x["hardware_qualified"])
        self.assertFalse(x["actual_silicon_fault_latch_readback_verified"])

    def test_lost_raw_waveform_digest_rejected(self):
        raw,meta,_=gate_fixture()
        with self.assertRaisesRegex(ValueError,"SHA"):
            gate_audit(raw+b"\n",meta)

    def test_missing_physical_gate_channel_rejected(self):
        _,m,d=gate_fixture()
        r=table(FIELDS[:-1],[v[:-1] for v in d])
        signed(r,m,"raw_trace_sha256")
        with self.assertRaisesRegex(ValueError,"header"):
            gate_audit(r,m)

    def test_fault_before_any_gate_drive_fails(self):
        _,m,d=gate_fixture()
        for row in d:row[2:]=[0]*6
        r=table(FIELDS,d);signed(r,m,"raw_trace_sha256")
        with self.assertRaisesRegex(ValueError,"No active"):
            gate_audit(r,m)

    def test_postfault_gate_rearm_fails(self):
        _,m,d=gate_fixture()
        d[15][2]=1
        r=table(FIELDS,d);signed(r,m,"raw_trace_sha256")
        with self.assertRaisesRegex(ValueError,"Gate reactivation|persistent"):
            gate_audit(r,m)

    def test_release_not_captured_fails(self):
        _,m,d=gate_fixture()
        for v in d[12:]:v[1]=1
        r=table(FIELDS,d);signed(r,m,"raw_trace_sha256")
        with self.assertRaisesRegex(ValueError,"assertion/release"):
            gate_audit(r,m)

    def test_scope_sample_gap_fails(self):
        _,m,d=gate_fixture()
        d[9][0]=d[8][0]+20
        r=table(FIELDS,d);signed(r,m,"raw_trace_sha256")
        with self.assertRaisesRegex(ValueError,"discontinuity"):
            gate_audit(r,m)

    def test_unapproved_numeric_limit_not_hardware_pass(self):
        raw,meta,_=gate_fixture()
        meta["approved_max_gate_off_ns"]=5
        x=gate_audit(raw,meta)
        self.assertEqual(x["gate_off_numeric_acceptance"],
                         "TIMING_INDETERMINATE_AT_SAMPLE_RESOLUTION")
        self.assertFalse(x["hardware_qualified"])

    def test_true_lower_bound_exceeds_approved_latency(self):
        _,m,d=gate_fixture()
        d[6][2]=1  # actual gate remains ON at a later sampled instant
        r=table(FIELDS,d);signed(r,m,"raw_trace_sha256")
        m["approved_max_gate_off_ns"]=5
        x=gate_audit(r,m)
        self.assertEqual(x["sampled_gate_off_lower_bound_ns"],10)
        self.assertEqual(x["sampled_gate_off_upper_bound_ns"],30)
        self.assertEqual(x["gate_off_numeric_acceptance"],
                         "CAPTURED_TIMING_LOWER_BOUND_EXCEEDS_DECLARED_LIMIT")
        self.assertFalse(x["hardware_qualified"])

    def test_upper_bound_within_declared_limit_still_requires_lab(self):
        raw,m,_=gate_fixture()
        m["approved_max_gate_off_ns"]=20
        x=gate_audit(raw,m)
        self.assertEqual(x["gate_off_numeric_acceptance"],
                         "CAPTURED_TIMING_UPPER_BOUND_WITHIN_DECLARED_LIMIT")
        self.assertFalse(x["hardware_qualified"])

    def test_missing_capture_provenance_rejected(self):
        raw,meta,_=gate_fixture()
        meta["gate_probe_reference"]="qemu:fake"
        with self.assertRaisesRegex(ValueError,"provenance"):
            gate_audit(raw,meta)


    def test_gate_redispatch_after_stable_off_while_fault_asserted_rejected(self):
        _,m,d=gate_fixture()
        # Old last-active-sample logic incorrectly accepted off->on->off.
        d[10][2]=1
        r=table(FIELDS,d);signed(r,m,"raw_trace_sha256")
        with self.assertRaisesRegex(ValueError,"Gate reactivation"):
            gate_audit(r,m)

    def test_gate_reactivation_after_release_then_final_off_rejected(self):
        _,m,d=gate_fixture()
        d[13][2]=1
        r=table(FIELDS,d);signed(r,m,"raw_trace_sha256")
        with self.assertRaisesRegex(ValueError,"Gate reactivation"):
            gate_audit(r,m)

    def test_off_observation_only_two_samples_before_release_rejected(self):
        _,m,d=gate_fixture()
        # Final safe-off begins at sample 10, fault releases at sample 12.
        d[8][2]=1
        d[9][2]=1
        r=table(FIELDS,d);signed(r,m,"raw_trace_sha256")
        with self.assertRaisesRegex(ValueError,"across fault release"):
            gate_audit(r,m)

    def test_scope_time_overflow_rejected(self):
        _,m,d=gate_fixture()
        d[1][0]=2**63
        r=table(FIELDS,d);signed(r,m,"raw_trace_sha256")
        with self.assertRaisesRegex(ValueError,"bounded unsigned"):
            gate_audit(r,m)

    def test_gate_manifest_not_an_object_rejected(self):
        raw,_,_=gate_fixture()
        with self.assertRaisesRegex(ValueError,"JSON object"):
            gate_audit(raw,[])

    def test_gate_provenance_prefix_with_leading_spaces_rejected(self):
        raw,m,_=gate_fixture()
        m["gate_probe_reference"]="   qemu:invalid-physical-proof"
        with self.assertRaisesRegex(ValueError,"provenance"):
            gate_audit(raw,m)

if __name__=="__main__":
    unittest.main()
