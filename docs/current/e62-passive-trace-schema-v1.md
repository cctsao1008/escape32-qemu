# Passive source schema ingestion correction v1

The native ADC source emits ADC_PHASE_EOC/READ and the reviewed runtime branch
emits ADC_VBUS_EOC and PWM_TBCTL/AUDIO_PERIOD. The strict parser rejected these
first-party observation records before evaluating actual P1 criteria. The parser
now admits those exact five types losslessly. Unknown records, sequence gaps,
malformed fields, time reversal, limits, Original SHA guard, fault safety and all
P0/P1 acceptance predicates and thresholds remain unchanged.

Replaying the native SC5 candidate with the standard P1 CLI now reaches the
actual criteria and FAILS with ORIGINAL_GUEST_NATIVE_SOURCE_NOT_PROVEN and
STARTUP_SIGNIFICANT_DIRECTION_REVERSAL. Observation admission does not turn
that experiment into an Original Guest or motor-performance PASS.

```sh
PYTHONPATH=.:tests python3 -m unittest tests.test_e62_passive_trace_schema \
  tests.test_e62_native_p0_strict tests.test_native_p1_qualification -v
python3 tools/native_p1_qualification.py --scenario SCENARIO \
  --events RAW_EVENTS --evidence RUN_METADATA --output VERDICT
```
