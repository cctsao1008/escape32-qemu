"""Static opt-in ownership, no default mutation of T01/T02."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class WWDTBootrstSourceContract(unittest.TestCase):
    def test_reset_is_opt_in_and_native_reason_0e(self):
        s=(ROOT/'machine/am13e23019.c').read_text()
        self.assertIn('esc-sim-wwdt-bootrst',s)
        self.assertIn('s->wwdt_reset_pending ? 0x0eU',s)
        self.assertIn('qemu_system_reset_request(SHUTDOWN_CAUSE_GUEST_RESET)',s)
        self.assertIn('s->gpio[1].dout &= ~(1U << 13)',s)
        self.assertIn('am13e_pwm4_reset(&s->pwm4)',s)
        self.assertIn('!(w->machine->sysctl_systemcfg & 1U)',s)
    def test_diagnostic_mode_retained(self):
        s=(ROOT/'machine/am13e23019.c').read_text()
        self.assertIn('BOOTRST/reset cause/motor output shutdown NOT MODELED',s)
