# E62 EXPERIMENT ONLY. DO NOT FLASH OR SHIP. NOT a reviewed ESC board.
# The AM13E Reference board rightly compiles MOTOR_OUTPUT_CONFIGURED=0
# unless a complete board electrical definition is EXPLICITLY supplied.
# This profile supplies values only for the QEMU SIM_ONLY gate/pad model.
# It is NOT a physical schematic, non-overlap validation or external
# nFAULT circuit / reset safety proof.
#
# Same exact definitions MUST be used for BOTH Guest A/B variants.
# Never inject motor events or bypass the production Gate / Trip policy.
set(AM13E_BOARD_BOARD_DEFINITIONS
    AM13E_MOTOR_GATE_ACTIVE_LEVEL=1
    AM13E_MOTOR_PAD_INVERT_MASK=0
    AM13E_MOTOR_OUTPUT_RED_TICKS=92
    AM13E_MOTOR_OUTPUT_FED_TICKS=0
    AM13E_MOTOR_MIN_DEAD_TICKS=15
    AM13E_MOTOR_NFAULT_ACTIVE_LOW=1
    AM13E_MOTOR_GATE_RESET_INACTIVE=1
)
