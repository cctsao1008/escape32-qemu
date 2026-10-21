# G13B2A — *SIMULATION-ONLY* electrical board profile.
# This is NOT Quanta E62 PCB, gate-driver, GaN, MOSFET, or safety data.
# Compiles ORIGINAL ESCape32 source without bypassing native preflight.
# Never add this to the default production configuration.
if(NOT DEFINED G13B2_SIM_ONLY_OPT_IN OR
   NOT G13B2_SIM_ONLY_OPT_IN)
  message(FATAL_ERROR
    "G13B2 SIM_ONLY board requires -DG13B2_SIM_ONLY_OPT_IN=ON; not a real board")
endif()
if(NOT ESCAPE32_BUILD_AM13E)
  message(FATAL_ERROR "G13B2 SIM_ONLY profile applies to AM13E only")
endif()

# Independently driven A/B MCPWM4 pads; do NOT infer PWM_ENABLE topology.
# Artificial standalone model assumptions for *functional simulation*:
#   PB13: active-high, externally held inactive during reset
#   INVERT: none; RED=32 ticks (320 ns at modeled 100MHz TBCLK)
#   FED path disabled; B is delayed by native compare policy
#   Minimum virtual non-overlap=32 ticks
#   PA22 nFAULT asserted-low
#   CMPSS1/2/3 high OC DACH thresholds: arbitrary midscale codes
# These values are not measurements, electrical design recommendations
# or qualified protective thresholds for any physical power stage.
set(AM13E_BOARD_BOARD_DEFINITIONS
  AM13E_SIM_ONLY_BOARD_PROFILE=1
  AM13E_MOTOR_GATE_ACTIVE_LEVEL=1
  AM13E_MOTOR_PAD_INVERT_MASK=0
  AM13E_MOTOR_OUTPUT_RED_TICKS=32
  AM13E_MOTOR_OUTPUT_FED_TICKS=0
  AM13E_MOTOR_MIN_DEAD_TICKS=32
  AM13E_MOTOR_NFAULT_ACTIVE_LOW=1
  AM13E_MOTOR_GATE_RESET_INACTIVE=1
  AM13E_OC_U_DAC_CODE=2048
  AM13E_OC_V_DAC_CODE=2048
  AM13E_OC_W_DAC_CODE=2048
  AM13E_OC_U_INVERT=0
  AM13E_OC_V_INVERT=0
  AM13E_OC_W_INVERT=0
)
message(STATUS
  "G13B2 SIM_ONLY test build: virtual PB13/RED/FED/nFAULT/OC; NEVER HARDWARE-QUALIFIED")
