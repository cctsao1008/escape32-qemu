Add an explicitly SIM_ONLY bounded passive journal and a calibrated virtual transfer profile. The profile derives DAC values from ADC/reference networks; it does not seed production midpoint codes. This is measurement tooling only.

Validation: Official SDK register suite and full native host regression pass. Baseline QEMU trace exposes stale staged sample despite a valid latest sample. Journal gaps are explicit.

Related to cctsao1008/escape32-qemu issues #10, #4, #3, #5, #6 and #8 as applicable. Draft for review; do not merge or close issues automatically.
