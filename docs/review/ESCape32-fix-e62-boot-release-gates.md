Boot CMD_SETWRP declares a variable directly after a C case label, failing GCC14 pedantic builds. Add a compound scope. Link/include production app_validity in the existing flash host test. Motor control is unchanged.

Validation: ARM Boot/App and diagnostic targets, image audit,107 host groups and ASan/UBSan flash tests with actual BIN pass. Existing full-image integrity/atomic rollback limitations remain explicit.

Related to cctsao1008/escape32-qemu issues #10, #4, #3, #5, #6 and #8 as applicable. Draft for review; do not merge or close issues automatically.
