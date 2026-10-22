# G13B3L: simulation-only *original Rel17 configuration* A/B trial.
# This inherits every Gate, RED/FED, Trip and calibrated BEMF safety
# requirement from the original SIM_ONLY baseline. No hardware claim.
# DUTY_RATE=100 is inside original ESCape32 defs.h supported 1..100.
# It changes only the stock Rel17 startup ramp configuration, not
# its timing/zero-crossing/commutation algorithm or safety code.
# Keep baseline DShot1000 / DUTY_RATE=30 separately pinned in CI.
include("${CMAKE_CURRENT_LIST_DIR}/g13b2_sim_only_board.cmake")
list(APPEND AM13E_BOARD_BOARD_DEFINITIONS DUTY_RATE=100)
message(WARNING "G13B3L DUTY_RATE=100 SIM_ONLY closed-loop diagnostic; NOT a Quanta E62 motor/tuning profile")
