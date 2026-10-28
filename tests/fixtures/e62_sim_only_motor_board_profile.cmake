# E62 EXPERIMENT ONLY. DO NOT FLASH OR SHIP. NOT a reviewed ESC board.
# This E62 motor experiment REQUIRES AM13E_MOTOR_OUTPUT_CONFIGURED=1.
# Motor-output-disabled builds fail rather than masquerading as a motor test.
# This profile supplies values only for the QEMU SIM_ONLY gate/pad model.
# OST3 comparator DAC thresholds are UNCALIBRATED raw code 2048; any
# trace depending on this comparator outcome is NOT physical qualified.
# It is NOT a physical schematic, non-overlap validation or external
# nFAULT circuit / reset safety proof.
#
# Same exact definitions MUST be used for BOTH Guest A/B variants.
# Never inject motor events or bypass the production Gate / Trip policy.
set(AM13E_BOARD_BOARD_DEFINITIONS
    AM13E_E62_REQUIRE_MOTOR_OUTPUT=1
    AM13E_MOTOR_GATE_ACTIVE_LEVEL=1
    AM13E_MOTOR_PAD_INVERT_MASK=0
    AM13E_MOTOR_OUTPUT_RED_TICKS=92
    AM13E_MOTOR_OUTPUT_FED_TICKS=0
    AM13E_MOTOR_MIN_DEAD_TICKS=15
    AM13E_MOTOR_NFAULT_ACTIVE_LOW=1
    AM13E_MOTOR_GATE_RESET_INACTIVE=1
    # QEMU-only raw CMPSS1/2/3 DAC midpoint; not a calibrated
    # motor current trip point in amps. OST3 is still connected;
    # do NOT turn off OC checks to get a rotor PASS.
    AM13E_OC_U_DAC_CODE=2048
    AM13E_OC_V_DAC_CODE=2048
    AM13E_OC_W_DAC_CODE=2048
    AM13E_OC_U_INVERT=0
    AM13E_OC_V_INVERT=0
    AM13E_OC_W_INVERT=0
)
