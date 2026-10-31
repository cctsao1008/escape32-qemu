"""Physical-flux consistency contract for SIM_ONLY Maxon EC87 BEMF A/B.

These are independent host mathematical guards, NOT real-motor calibration
and NOT acceptance of the Original Guest's P1 startup behavior.
"""
import math
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KT = 0.0454
OFFSETS = (0, -2 * math.pi / 3, 2 * math.pi / 3)

def trapezoid(angle):
    a = math.remainder(angle, 2 * math.pi)
    sign = -1 if a < 0 else 1
    a = abs(a)
    if a <= math.pi / 6:
        return sign * 6 * a / math.pi
    if a <= 5 * math.pi / 6:
        return float(sign)
    return sign * 6 * (math.pi - a) / math.pi

def flux(waveform, angle):
    return math.sin(angle) if waveform == "historical_sine" else trapezoid(angle)

def coeff(waveform):
    return KT / (math.sqrt(3) if waveform == "historical_sine" else 2)

class IdealWaveformAB(unittest.TestCase):
    def test_ideal_plateau_transition_odd_and_continuous(self):
        for degrees, expected in [(0, 0), (15, .5), (30, 1),
                                  (90, 1), (150, 1), (165, .5),
                                  (180, 0), (195, -.5), (210, -1),
                                  (270, -1), (330, -1), (345, -.5),
                                  (360, 0)]:
            with self.subTest(angle=degrees):
                self.assertAlmostEqual(trapezoid(math.radians(degrees)),
                                       expected, places=12)
        for degrees in range(-900, 901, 7):
            x = math.radians(degrees)
            self.assertAlmostEqual(trapezoid(x), -trapezoid(-x), places=12)
            self.assertAlmostEqual(trapezoid(x),trapezoid(x+2*math.pi),places=12)

    def test_line_line_peak_and_six_step_center_match_terminal_kt(self):
        for wave in ("historical_sine", "ideal_trapezoid"):
            maximum = max(abs(coeff(wave) * (flux(wave, x+OFFSETS[2]) -
                             flux(wave, x+OFFSETS[1]))) for x in
                          (2*math.pi*i/3600 for i in range(3600)))
            self.assertAlmostEqual(maximum,KT,delta=1e-6)
        # W-high/V-low pair=8: trapezoid has constant Kt*I across sector.
        for theta in [-29, -15, 0, 15, 29]:
            torque = coeff("ideal_trapezoid") * 10 * (
                trapezoid(math.radians(theta)+OFFSETS[2]) -
                trapezoid(math.radians(theta)+OFFSETS[1]))
            self.assertAlmostEqual(torque,KT*10,places=12)

    def test_electromagnetic_reciprocity_for_balanced_star_currents(self):
        for wave in ("historical_sine","ideal_trapezoid"):
            for degrees in range(-180,181,5):
                for omega in (-87.,0.,53.):
                    currents=(5.7,-13.1,7.4)  # Kirchhoff sum zero
                    e=[coeff(wave)*omega*flux(wave,math.radians(degrees)+o)
                       for o in OFFSETS]
                    torque=coeff(wave)*sum(i*flux(wave,math.radians(degrees)+o)
                                          for i,o in zip(currents,OFFSETS))
                    self.assertAlmostEqual(sum(i*v for i,v in zip(currents,e)),
                                           torque*omega,places=10)

    def test_source_default_off_and_analog_motor_same_basis(self):
        plant=(ROOT/"machine/am13e_native_motor_plant.inc").read_text()
        motor=(ROOT/"machine/am13e_native_motor_dynamics.inc").read_text()
        analog=(ROOT/"machine/am13e_native_analog_frontend.inc").read_text()
        machine=(ROOT/"machine/am13e23019.c").read_text()
        self.assertIn('if (!m->trapezoid_bemf)',plant)
        self.assertIn('return sin(radians);',plant)
        self.assertIn('AM13E_NATIVE_KT_TERMINAL/2.0',plant)
        self.assertIn('AM13E_NATIVE_K_FLUX*m->omega*basis[p]',motor)
        self.assertIn('torque *= AM13E_NATIVE_K_FLUX;',motor)
        self.assertIn('am13e_native_flux_basis(m,m->theta+offs[p])',analog)
        self.assertIn('esc-sim-native-trapezoid-bemf',machine)
        self.assertIn('bool trapezoid_bemf;',machine)

if __name__ == "__main__":
    unittest.main()
