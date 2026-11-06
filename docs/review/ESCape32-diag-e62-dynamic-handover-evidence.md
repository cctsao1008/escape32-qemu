Add passive changed-reference request/load/post-shutdown journal events and an explicit SIM_ONLY affine calibration profile on top of PR9. No PR9 control-policy change or production board calibration is introduced.

Validation: ARM build,107 full SDK regression groups, native changing-reference sample/DAC chains and invalid/stale shutdown observations. The first persistent decision rejects a2782us capture under unchanged5000us startup policy; rotor reversal still occurs with fresh matched reference observations. See mcu/_support/AM13E/reports/e62-dynamic-source-handover-v4.md and the companion QEMU v4 report. No physical approval or production merge requested.

Detailed evidence: https://github.com/cctsao1008/escape32-qemu/blob/report/e62-engineering-execution/docs/current/e62-engineering-status-v4.md
