# E62 SIM_ONLY: SAME electrical fixture as Control, different BEMF startup policy.
# This is NOT a board design and MUST NEVER be flashed to real hardware.
include("${CMAKE_CURRENT_LIST_DIR}/e62_sim_only_motor_board_profile.cmake")
list(APPEND AM13E_BOARD_BOARD_DEFINITIONS
    AM13E_SIM_ONLY_EXPERIMENTAL_EARLY_BEMF=1)
