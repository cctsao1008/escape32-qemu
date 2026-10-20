#!/usr/bin/env python3
"""G13A QTest: independently programmed PWM -> BLDC -> BEMF -> CMPSS/ECAP.

This is NOT ESCape32 native firmware closed-loop: QTest programs the
bridge/gate/peripheral fixture. Six PWM duties are subsequently read
from the QEMU MCPWM4 output observer, never from a fabricated throttle.
"""
import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.virtual_bldc import (
    MotorParameters, PWMObservation, VirtualBLDC, MCPWM4_ROUTES,
    GPIO1_BASE, PINCM_BASE, GATE_EN, OBS_BASE
)
from tools.virtual_bldc_feedback import (
    AnalogFrontend, bridge_pwm_to_bemf, SIM_BEMF_INPUT
)
from g9_mcpwm_observer import run, set_pwm_pair
from g10_feedback import readw, writew

SYS = 0x400af000
POWER = SYS + 0x1424
MUX = SYS + 0x1444
SYNC = SYS + 0x148c
PWM = 0x40014000
ECAP = 0x40441000
CMP = 0x40460000


def params():
    # Deliberate idealized virtual motor TEST FIXTURE. No Quanta ESC BOM
    # or unmeasured physical Kv/Ke/R/L/J is implied.
    return MotorParameters(
        vbus_v=24.0,
        phase_resistance_ohm=.3,
        phase_inductance_h=.002,
        bemf_constant_v_per_rad_s=.02,
        torque_constant_nm_per_a=.02,
        inertia_kg_m2=1e-6,
        viscous_friction_nm_per_rad_s=.0001,
        load_torque_nm=0,
        pole_pairs=7
    )


def setup(q):
    q.write(POWER, 0x26000610)  # TI PWM4 + ECAP1 + CMPSS0 power
    q.write(GPIO1_BASE + 0x800, 0x26000001)
    q.write(GPIO1_BASE + 0x1280, GATE_EN)
    q.write(GPIO1_BASE + 0x12C0, GATE_EN)
    q.write(PINCM_BASE + 45 * 4, 0x81)  # actual PB13 GPIO pad
    for pin, function in MCPWM4_ROUTES:
        q.write(PINCM_BASE + pin*4, 0x80 | function)
    q.write(PWM + 0x14, 99)
    q.write(PWM + 0x18, 99)
    # Test fixture: U high 75%, V low 75%, W floating.
    set_pwm_pair(q, 0, (75, 1), (0x12, 0x1))
    set_pwm_pair(q, 1, (1, 75), (0x1, 0x102))
    set_pwm_pair(q, 2, (1, 1), (0x1, 0x1))
    q.write(PWM + 0x10, 0)
    q.write(SYNC, 1)
    obs = PWMObservation.from_qemu(q.read)
    assert obs.high_ticks == (75, 0, 0, 75, 0, 0), obs
    return obs


def setup_comparator(q):
    q.write(MUX, 0)                        # HP0 selects phase U
    q.write(ECAP + 0x24, 45)                # comparator HP to input 45
    writew(q, ECAP + 0x28, 0x100)           # CAPLDEN rising event 1
    writew(q, ECAP + 0x2c, 0x02)            # enable CEVT1 interrupt
    writew(q, ECAP + 0x2a, 0x10)            # start TSCTR
    writew(q, CMP + 0x08, 0)                # update active DAC with MCLK
    writew(q, CMP + 0x0c, 2048)             # explicit midscale threshold
    writew(q, CMP + 0x30, 0x420)            # 5 samples, threshold 3
    writew(q, CMP + 0x32, 0)
    writew(q, CMP + 0x72, 0)
    writew(q, CMP, 0x8008)                  # enable comparator + CTRIPH filter
    assert readw(q, ECAP + 0x2e) == 0
    assert q.read(ECAP + 8) == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--elf", type=Path, required=True)
    args = parser.parse_args()
    analog = AnalogFrontend(
        reference_v=3.3, zero_bemf_bias_v=1.65,
        input_gain_v_per_bemf_v=.02)
    assert analog.code(0) == 2048
    assert analog.code(-10) < 2048 < analog.code(10)
    try:
        analog.code(100)
    except ValueError:
        print("G13A_ANALOG_SATURATION_REJECTED=PASS")
    else:
        raise AssertionError("Analog frontend silently saturated")

    def qtest(q):
        motor = VirtualBLDC(params())
        # Power/gate/PWM are uninitialized here: bridge must reject and
        # MUST NOT write a synthetic comparator value to the guest.
        try:
            bridge_pwm_to_bemf(
                motor, analog, q.read, q.write,
                lambda ns: q.cmd(f"clock_step {ns}"),
                gate_active_level=1, pwm_timer_hz=100_000_000,
                hold_periods=2000)
        except ValueError:
            pass
        else:
            raise AssertionError("Disconnected motor must not inject BEMF")
        assert q.read(SIM_BEMF_INPUT) == 0
        assert motor.sample().mechanical_rpm == 0
        print("G13A_DISCONNECTED_GATE_ZERO_MOTION_NO_STIMULUS=PASS")

        obs = setup(q)
        setup_comparator(q)
        # Physically meaningful rest state: source phase values from the
        # motor object itself, NOT a hard-coded synthetic comparator edge.
        for phase, word in enumerate(analog.words(motor.sample())):
            q.write(SIM_BEMF_INPUT + 4*phase, word)
        q.cmd("clock_step 100")
        assert q.read(ECAP + 8) == 0, "No comparator transition at rest"

        result = bridge_pwm_to_bemf(
            motor, analog, q.read, q.write,
            lambda ns: q.cmd(f"clock_step {ns}"),
            gate_active_level=1, pwm_timer_hz=100_000_000,
            hold_periods=2000, input_phase=0)
        assert result.original_pwm_duties == obs.six_duties
        assert result.hold_periods == 2000
        assert result.elapsed_virtual_ns == 2_000_000
        assert result.motor.mechanical_rpm > 0
        assert any(abs(i) > 0 for i in result.motor.phase_currents_a)
        assert (result.comparator_words[0] & 0xfff) > 2048
        assert q.read(SIM_BEMF_INPUT) == result.comparator_words[0]
        q.cmd("clock_step 100")  # allow actual QEMU digital filter transition
        timestamp = q.read(ECAP + 8)
        assert timestamp != 0, "No genuine ECAP1 capture from BLDC-driven BEMF"
        assert readw(q, ECAP + 0x2e) & 3 == 3
        print(f"G13A_QEMU_MCPWM_TO_MOTOR_TO_CMPSS_ECAP_CAPTURE=PASS "
              f"rpm={result.motor.mechanical_rpm:.2f} "
              f"phase_u_code={result.comparator_words[0] & 0xfff} "
              f"CAP1={timestamp}")

        # PB13 GPIO DOE held high but pad mux disconnected: no new
        # bridge step and no injected phase sample can be justified.
        q.write(PINCM_BASE + 45*4, 0)
        original = q.read(SIM_BEMF_INPUT)
        for reason in ("gate_pad", "pwm_invalid"):
            if reason == "pwm_invalid":
                q.write(PINCM_BASE + 45*4, 0x81)
                q.write(SYNC, 0)
            try:
                bridge_pwm_to_bemf(
                    motor, analog, q.read, q.write,
                    lambda ns: q.cmd(f"clock_step {ns}"),
                    gate_active_level=1, pwm_timer_hz=100_000_000,
                    hold_periods=1)
            except ValueError:
                pass
            else:
                raise AssertionError(f"Invalid {reason} accepted")
            assert q.read(SIM_BEMF_INPUT) == original
        print("PASS_G13A_GATE_PAD_AND_INVALID_PWM_FAIL_CLOSED")

    run(args.qemu.resolve(), args.elf.resolve(), True, qtest)
    print("PASS_G13A_QTEST_ONLY_NO_NATIVE_CLOSED_LOOP_CLAIM")


if __name__ == "__main__":
    main()
