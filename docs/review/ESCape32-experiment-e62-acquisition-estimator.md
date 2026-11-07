Preserve failed acquisition hypotheses as opt-in SIM_ONLY variants: first-capture window, first interval seed, bounded acquisition window and measured acquisition estimator. Default locked filtering and production compilation remain unchanged. Actual-Core tests exercise original/candidate paths, interval overflow/negative/early capture, timeout, safe stop and locked-mode restoration under UBSan.

Native results are failures: first-window/seed variants each59 significant reversals, bounded-window60, estimator56 at−30° and58 at90°. Accepting more captures alone does not prove synchronization. The estimator exposes an independent SC5 blind window; its correction is a separate review branch. Do not promote this policy family to production or treat experimental tests as changes to P1 thresholds.

Draft only; review the v5 causal chronology and regression evidence before choosing a production control strategy. No merge/issue closure.
