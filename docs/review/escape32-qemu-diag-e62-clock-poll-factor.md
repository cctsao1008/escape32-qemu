Make the existing host polling sleep an explicit bounded diagnostic argument (default unchanged), so source timing trials record this factor.

Validation:1ms baseline polling completes; an interrupted observer trial remains incomplete. A new observer trial overlapping one VBUS run also completes without reproducing timing failures. These are not labeled an isolated matched pair.

Detailed evidence: https://github.com/cctsao1008/escape32-qemu/blob/report/e62-engineering-execution/docs/current/e62-engineering-status-v4.md
