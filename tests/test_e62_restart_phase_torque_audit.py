"""Fail-closed unit checks of read-only source/plant observability."""
import unittest

from tools.e62_restart_phase_torque_audit import diagnose

def scenario(coast=300):
    return {"schema":"e62.native.dshot.v1","protocol":"DSHOT600",
            "frame_period_ns":1_000_000,"guest_ready_gating":False,
            "stages":[
                {"kind":"hold","duration_ms":1500,"permille":0},
                {"kind":"hold","duration_ms":1500,"permille":200},
                {"kind":"hold","duration_ms":coast,"permille":0},
                {"kind":"hold","duration_ms":1500,"permille":200},
                {"kind":"hold","duration_ms":300,"permille":0}]}

def events(s,torque=-125000,rpm=8):
    ds=[]
    stage=0
    border=s["stages"][0]["duration_ms"]
    for i in range(sum(z["duration_ms"] for z in s["stages"])):
        while i>=border:
            stage+=1
            border+=s["stages"][stage]["duration_ms"]
        ds.append({"kind":"DSHOT","vns":26_872+i*1_000_000,
                   "data":(i,stage,s["stages"][stage]["permille"],0,0,0)})
    restart_at=ds[3000+s["stages"][2]["duration_ms"]]["vns"]
    ds.extend([
        {"kind":"ROTOR","vns":restart_at-310_000,
         "data":(rpm*1000,2907144,0,0,0,0)},
        *[
          {"kind":"ROTOR","vns":restart_at+695_000+i*1_000_000,
           "data":((-65_000 if i==2 else 5_000),2907155,
                    200,0,-200,torque if i==0 else 4_000)}
          for i in range(20)
         ],
        {"kind":"CAP1_ACK","vns":restart_at+4_105_000,
         "data":(1,0,0,0,0,0)}
    ])
    return sorted(ds,key=lambda x:x["vns"])

class NativeRestartPhaseTorqueAuditTest(unittest.TestCase):
    def test_first_negative_model_torque_visible_not_guest_input(self):
        x=diagnose(events(scenario()),scenario())
        self.assertTrue(x["first_post_demand_model_torque_negative"])
        self.assertEqual(x["first_20ms_negative_rpm_samples_le_minus50"],1)
        self.assertEqual(x["first_post_demand_model_torque_nm"],-0.125)
        self.assertFalse(x["has_guest_rotor_angle_measurement"])
        self.assertTrue(x["do_not_use_angle_or_torque_as_guest_input"])
        self.assertAlmostEqual(x["first_new_guest_cap1_ack_ms"],4.105)

    def test_long_coast_positive_initial_torque(self):
        x=diagnose(events(scenario(3000),torque=215453,rpm=1),
                   scenario(3000))
        self.assertFalse(x["first_post_demand_model_torque_negative"])
        self.assertEqual(x["pre_demand_rpm"],1.0)
        self.assertEqual(x["coast_duration_ms"],3000)

    def test_missing_rotor_trace_is_red(self):
        e=[z for z in events(scenario()) if z["kind"]!="ROTOR"]
        with self.assertRaisesRegex(ValueError,"rotor records"):
            diagnose(e,scenario())

    def test_missing_independent_dshot_frame_is_red(self):
        with self.assertRaisesRegex(ValueError,"Incomplete DShot"):
            diagnose(events(scenario())[:-2],scenario())

    def test_clock_mismatch_is_red(self):
        e=events(scenario())
        next(x for x in e if x["kind"]=="DSHOT" and x["data"][0]==3300)["vns"]+=200
        with self.assertRaisesRegex(ValueError,"source clock discontinuity"):
            diagnose(e,scenario())

    def test_scenario_with_unbounded_motor_power_is_rejected(self):
        s=scenario()
        s["stages"][2]["permille"]=200
        with self.assertRaisesRegex(ValueError,"five-stage"):
            diagnose(events(scenario()),s)

if __name__=="__main__":
    unittest.main()
