"""Fail-closed evidence milestones: T01/T02 functional != rotor/physics/hardware.

Status report never converts known failure or absent measurement to PASS.
"""
import json

def _load(path):
    return json.load(open(path,encoding='utf-8')) if path else None

def summarize(*,t01=None,t02=None,strict_rotor=None,
              fault_native=None,physics=None):
    from tools.ci.verify_t02 import validate
    results={}
    def functional(d,name,expected,nstages):
        if d is None:
            return {'status':'OPEN_NOT_RUN'}
        good=(d.get('status')=='PASS_AUTONOMOUS_AGGREGATE_FUNCTIONAL'
              and d.get('dshot_frames_sent')==expected
              and len(d.get('stages',[]))==nstages
              and not d.get('issues') and
              all(s.get('sampled_stage_gate',{}).get('status')==
                  'PASS_SAMPLED_STAGE_DIAGNOSTIC' for s in d.get('stages',[]))
              and d.get('autonomous',{}).get('neutral_teardown',{}).get('qualified'))
        if name=='T02' and validate(d):
            good=False
        return {'status':'PASS_FUNCTIONAL_ONLY' if good else 'FAIL_FUNCTIONAL_GATE'}
    results['M1_T01']=functional(t01,'T01',11000,2)
    results['M1_T02']=functional(t02,'T02',110000,11)
    results['M2_GUEST_SIXSTEP_ISR_CAUSALITY']={
        'status':'OPEN_SPARSE_SAMPLES_DO_NOT_PROVE_COMPLETE_SECTOR_ORDER_OR_ISR_CAUSALITY'}
    results['M3_SIM_ONLY_FAULT_NEGATIVE_GATES']={
        'status': ('PASS_MODELED_GUEST_FAULT_GATES'
            if fault_native and fault_native.get('independent_cases_passed')==
               ['nfault','oc-u','oc-v','oc-w']
            else 'OPEN_OR_FAIL_REQUIRES_FOUR_INDEPENDENT_NATIVE_FAULT_CASES')}
    results['M4_STRICT_ROTOR_G13B3M']={
        'status':('PASS_STRICT_NATIVE_ROTOR_ONLY'
                  if strict_rotor and strict_rotor.get('strict_gate')==
                     'PASS_G13B3M_INDEPENDENT_NATIVE_ROTOR'
                  else 'KNOWN_FAIL_ROTOR_REVERSAL_NOT_WAIVED')}
    results['M4_PHYSICS_GUEST_COUPLING']={
        'status':('PASS_SIM_ONLY_COUPLED_PHYSICS_ONLY'
                  if physics and physics.get('edge_source')==
                    'ORIGINAL_QEMU_PWM_SWITCH_TIMESTAMPS' and
                    physics.get('analog_input_route')==
                    'MODELED_BEMF_THROUGH_CMPSS_AND_ECAP' and
                    physics.get('guest_memory_writes') is False and
                    physics.get('rotor_energy_qualified') is True and
                    physics.get('original_isr_causality_qualified') is True
                  else 'OPEN_NO_GUEST_COUPLED_CALIBRATED_PHYSICS_EVIDENCE')}
    results['M5_BOARD_THERMAL_FLIGHT']={'status':'NOT_QUALIFIED_BY_QEMU'}
    results['overall']={
        'status':'OPEN_NOT_PRODUCTION_QUALIFIED',
        'reason':'Functional simulation cannot replace real board, power stage, rotor and protection qualification'}
    return results


def main():
    import argparse
    p=argparse.ArgumentParser()
    for name in ('t01','t02','strict-rotor','fault-native','physics'):
        p.add_argument('--'+name)
    p.add_argument('--output',default='artifacts/e62-qualification-matrix.json')
    a=p.parse_args()
    result=summarize(t01=_load(a.t01),t02=_load(a.t02),
                     strict_rotor=_load(a.strict_rotor),
                     fault_native=_load(a.fault_native),
                     physics=_load(a.physics))
    from pathlib import Path
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print('E62_QUALIFICATION_MATRIX '+json.dumps(result,sort_keys=True))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
