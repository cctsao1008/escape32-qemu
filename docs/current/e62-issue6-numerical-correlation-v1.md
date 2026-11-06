# Issue #6 numerical and measurement correlation v1

No physical model, firmware or P1 threshold changed. SIM_ONLY numerical
consistency is separate from physical parameter calibration.

The existing motor metadata traces EC87 KV210 nominal terminal R=0.0566 ohm,
L=17.5 microhenry, Kv=210rpm/V, terminal Kt=0.0454Nm/A, rotor J=0.00013kg m2
and 21 pole pairs to the April 2025 manufacturer datasheet. Phase R/L=half the
terminal values assumes a balanced star; phase-peak Kt=terminal/sqrt(3) and
Ke=phase-Kt/pole-pairs assume balanced sine reciprocity. Viscous friction
0.0001Nm/(rad/s) and unloaded torque zero are model assumptions, not measurements.
Propeller inertia is not measured. Existing APC 24x12E static analytical data and
inertia-sensitivity study are not a measured transient or windmilling curve.

Existing numerical regressions passed: continuous-current active-set/diode,
energy ledger, reciprocity, frozen PWM and source-energy audit. An actual
Original Guest/KV147/-30-degree raw trace from the current cloud was replayed by
the unchanged `native_p0_reference_replay.compare` using a lossless observer-aware
parser (ADC observation event types retained). Result PASS_FROZEN_SWITCH_PHYSICS:
107 recorded switch events, 90 rotor samples, maximum RPM error 3.75e-12,
angle error 0.0004013rad, current error 0.0004991A. Coarse-to-half difference
0.000322096 versus half-to-quarter 0.000157590, at 1000/500/250ns steps.
This is only the recorded initial 90ms switch window; it does not validate a
later startup transient, KV210/47V profile or physical propeller performance.
Raw result: ignored artifacts/mission-model/frozen-real-source.json.

The new `e62_model_correlation.py` reports measured-minus-model error bands
without fitting any physical constants or granting hardware/model approval.
A manifest names measurement and prediction JSON files and their SHA256 values.
The measurement requires origin PHYSICAL_BENCH, sensor_calibration,
fixture_identity, motor_id, propeller_id, clock_synchronization, positive finite
uncertainty for voltage_v/current_a/rpm and samples with exact monotonic t_ns.
Prediction requires origin SIM_ONLY, effective_parameters readback and matched
samples. Timestamps must already be explicitly aligned; no silent interpolation.
It reports RMSE, signed error range, maximum absolute error and counts outside
the supplied measurement uncertainty. An error-band result is not a pass gate.

```sh
python3 -m unittest tests.test_e62_model_correlation -v
python3 tools/e62_model_correlation.py physical.manifest.json --output errors.json
```

Current measured correlation: BLOCKED_EXTERNAL. Needed: traceable loaded/unloaded
RPM/VBUS/phase-or-bus-current transient, sensor calibration/uncertainties, motor
winding and temperature, inertia/load configuration, propeller identity, source
limits and synchronized acquisition. Needed separately: thrust/torque/load points
and propeller inertia for APC24x12E, battery/PSU/ESC limits and independent safety
approval. No current/thrust/thermal points have been invented. New bounded 47V
model qualification remains blocked until those parameter and safety gates pass.
Existing 47V source-only diagnostic studies do not satisfy them.
