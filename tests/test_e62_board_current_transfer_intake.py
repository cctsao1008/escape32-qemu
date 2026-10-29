"""Artificial current-injection fixture ONLY: no physical amplifier measurements."""
import csv
import hashlib
import io
import unittest

from tools.e62_board_current_transfer_intake import audit,COLUMNS

def csvbytes(rows):
    out=io.StringIO(newline="")
    w=csv.writer(out,lineterminator="\n")
    w.writerow(COLUMNS)
    w.writerows(rows)
    return out.getvalue().encode()

def fixture(topology="SIGNED_LINEAR"):
    rows=[]
    for phase in "UVW":
        for i,milliamps in enumerate((-3000,-2000,-1000,0,1000,2000,3000)):
            current=abs(milliamps) if topology=="ABSOLUTE_LINEAR" else milliamps
            rows.append((phase,f"unit-{phase}-{i}",milliamps,2050+current//500))
    raw=csvbytes(rows)
    meta={"schema":"e62.bench.current-transfer.v1",
          "capture_kind":"BENCH_INDEPENDENT_CURRENT_REFERENCE_UNVERIFIED",
          "board_revision":"UNIT_NOT_REAL",
          "board_serial":"UNIT_NOT_REAL",
          "firmware_commit":"a"*40,"measured_at_utc":"2026-10-30T01:00:00Z",
          "reference_instrument_id":"UNIT_METER",
          "adc_instrument_id":"UNIT_ADC",
          "raw_trace_sha256":hashlib.sha256(raw).hexdigest(),
          "current_probe_cal_ref":"CAL_UNVERIFIED_UNIT",
          "adc_reference_cal_ref":"ADC_UNVERIFIED_UNIT",
          "shunt_amplifier_schematic_ref":"SCHEMATIC_UNVERIFIED_UNIT",
          "adc_phase_route_ref":"MUX_UNVERIFIED_UNIT",
          "hardware_excitation_method":"LOW_ENERGY_NO_PROPELLER",
          "transfer_topology":topology}
    return raw,meta,rows

def checked(rows,meta):
    raw=csvbytes(rows)
    meta["raw_trace_sha256"]=hashlib.sha256(raw).hexdigest()
    return audit(raw,meta)

class CurrentTransferUnit(unittest.TestCase):
    def test_signed_three_phase_candidate_never_hardware(self):
        raw,meta,_=fixture()
        x=audit(raw,meta)
        self.assertEqual(set(x["channels"]),"UVW")
        for p in "UVW":
            self.assertAlmostEqual(x["channels"][p]["candidate_gain_adc_codes_per_amp"],2.)
            self.assertAlmostEqual(x["channels"][p]["candidate_adc_offset_code"],2050.)
        self.assertFalse(x["motor_generated_oc_qualified"])
        self.assertFalse(x["current_limit_autoconfig_permitted"])
        self.assertFalse(x["comparator_dac_trip_current_qualified"])
        self.assertFalse(x["hardware_qualified"])

    def test_explicit_absolute_transfer_not_assumed_signed(self):
        raw,meta,_=fixture("ABSOLUTE_LINEAR")
        x=audit(raw,meta)
        self.assertAlmostEqual(x["channels"]["U"]["candidate_gain_adc_codes_per_amp"],2.)
        self.assertFalse(x["hardware_qualified"])

    def test_raw_sample_hash_tampering_rejected(self):
        raw,meta,_=fixture()
        with self.assertRaisesRegex(ValueError,"SHA"):
            audit(raw+b" ",meta)

    def test_qemu_source_prohibited(self):
        raw,meta,_=fixture()
        meta["capture_kind"]="SIM_ONLY"
        with self.assertRaisesRegex(ValueError,"synthetic"):
            audit(raw,meta)

    def test_missing_zero_or_one_current_direction_rejected(self):
        _,meta,rows=fixture()
        rows=[r for r in rows if r[0]!="U" or r[2]!=0]
        with self.assertRaisesRegex(ValueError,"Missing zero"):
            checked(rows,meta)

    def test_incomplete_phase_set_rejected(self):
        _,meta,rows=fixture()
        rows=[r for r in rows if r[0]!="W"]
        with self.assertRaisesRegex(ValueError,"W"):
            checked(rows,meta)

    def test_saturated_adc_rejected(self):
        _,meta,rows=fixture()
        rows[0]=(*rows[0][:3],4095)
        with self.assertRaisesRegex(ValueError,"saturated"):
            checked(rows,meta)

    def test_duplicate_sample_identifier_rejected(self):
        _,meta,rows=fixture()
        rows[2]=(*rows[2][:1],rows[1][1],*rows[2][2:])
        with self.assertRaisesRegex(ValueError,"duplicate"):
            checked(rows,meta)

    def test_noncanonical_negative_current_rejected(self):
        _,meta,rows=fixture()
        rows[0]=(rows[0][0],rows[0][1],"-03",rows[0][3])
        with self.assertRaisesRegex(ValueError,"Noncanonical"):
            checked(rows,meta)

    def test_unproven_current_probe_reference_rejected(self):
        raw,meta,_=fixture()
        meta["current_probe_cal_ref"]="qemu:fake"
        with self.assertRaisesRegex(ValueError,"independently evidenced"):
            audit(raw,meta)

if __name__=="__main__":
    unittest.main()
