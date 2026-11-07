Add an explicit SIM_ONLY2kHz ADC interleave fixture to separate invalid-input failure from prior-reference expiry, without changing calibration, epoch checks or age32. Default Core1kHz ADC cadence remains unchanged and is tested directly. The real native invalid sample is read before the fault, prior reference is fresh at age17, and actual capture/gates remain off after shutdown. Separate missing-EOC expiry is retained.

This is diagnostic fault-isolation tooling, not a production cadence change or motor qualification. A later independent prompt-producer correction also proves invalid-only at the original1kHz cadence (age18), so this fixture is not a prerequisite for production correctness.

Draft only; no merge or issue closure, no physical settling approval.
