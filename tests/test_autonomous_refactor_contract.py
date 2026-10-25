"""Guard historical Python imports and CLI while implementation is split."""
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TESTS=str(ROOT / 'tests')
if TESTS not in sys.path: sys.path.insert(0,TESTS)
from tools import native_arming, autonomous_sitl_host
from tools import sitl_autonomous_transport, sitl_autonomous_evidence, sitl_stage_oracle
import g13b2_native_drive_probe as historical_probe
import g13b4_functional_dshot_sitl as historical_sitl
import functional_dshot_sitl as current_sitl


class RefactorCompatibilityTests(unittest.TestCase):
    def test_zero_arm_and_wfi_symbols_preserve_identity(self):
        for name in ('native_original_zero_throttle_arm',
                     'resolve_original_rel17_wfi_roles',
                     'native_pa26_receiver_rearm_snapshot','resume_to'):
            self.assertIs(getattr(historical_probe,name),
                          getattr(native_arming,name))
    def test_legacy_and_canonical_cli_same_main(self):
        self.assertIs(historical_sitl.main,current_sitl.main)
        self.assertIs(historical_sitl._run_guest,current_sitl._run_guest)
    def test_sitl_facade_preserves_all_public_apis(self):
        for module,names in [
            (sitl_autonomous_transport,
                ('AUTO_ABI','AUTO_BASE','REG','configure_auto','read_auto',
                 'compile_autonomous_stages','native_end_oracle',
                 'read_stage_checkpoints')),
            (sitl_autonomous_evidence,
                ('summarize_stage_samples','read_timing_evidence')),
            (sitl_stage_oracle,('sampled_stage_regression_gate',))
        ]:
            for name in names:
                self.assertIs(getattr(autonomous_sitl_host,name),
                              getattr(module,name))


if __name__=='__main__':
    unittest.main()
