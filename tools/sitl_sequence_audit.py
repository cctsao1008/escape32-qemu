"""Non-coherent read-only original Rel17.3 six-step source audit.

This is intentionally diagnostic. Sparse QTest Guest SRAM sampling
cannot prove complete sector order or ISR entry causality.
"""
from tools.native_closed_loop_audit import ORIGINAL_REL17_ROUTE

def sampled_original_sequence_audit(scenario, samples):
    stages=[]
    for stage in scenario.stages:
        a=stage.start_ns//1_000_000
        b=stage.end_ns//1_000_000
        rows=[r for r in samples if a<=r['sim_elapsed_ms']<b]
        pairs=[]
        invalid=[]
        for r in rows:
            step=r.get('guest_step_sample')
            code=r.get('guest_selected_code_sample')
            if step is None or code is None:continue
            if not isinstance(step,int) or not 1<=step<=6:
                invalid.append({'elapsed_ms':r['sim_elapsed_ms'],
                                'step':step,'code':code})
                continue
            expected=ORIGINAL_REL17_ROUTE[step][0]
            pairs.append({'elapsed_ms':r['sim_elapsed_ms'],
                          'step':step,'selected_code':code,
                          'expected_source_code':expected,
                          'sample_code_matches':code==expected})
        counters=[r for r in rows if
                  r.get('guest_cap1_total') is not None and
                  r.get('guest_timg12_serviced_total') is not None]
        cap_progress=(counters[-1]['guest_cap1_total']-
                      counters[0]['guest_cap1_total']) if len(counters)>1 else None
        svc_progress=(counters[-1]['guest_timg12_serviced_total']-
                      counters[0]['guest_timg12_serviced_total']) if len(counters)>1 else None
        stages.append({
            'index':stage.index,'kind':stage.kind,
            'observed_pairs':len(pairs),
            'source_code_matches':sum(p['sample_code_matches'] for p in pairs),
            'source_code_mismatches':sum(not p['sample_code_matches'] for p in pairs),
            'invalid_or_transition_step_samples':len(invalid),
            'unique_guest_steps':sorted(set(p['step'] for p in pairs)),
            'guest_cap1_progress_sampled':cap_progress,
            'guest_timg12_service_progress_sampled':svc_progress,
            'status':'OPEN_FULL_SEQUENCE_AND_ISR_ENTRY_NOT_PROVEN',
            'scope':'NON_COHERENT_GUEST_PAIR_SAMPLES_NOT_ALL_TRANSITIONS',
        })
    return {
        'source':'PINNED_REL17_3_COMMUTATION_H_WORDS_FROM_NATIVE_CLOSED_LOOP_AUDIT',
        'pinned_source_sequence':[ORIGINAL_REL17_ROUTE[i][0] for i in range(1,7)],
        'stages':stages,
        'status':'OPEN_FULL_SEQUENCE_AND_ISR_ENTRY_NOT_PROVEN',
        'warning':'Guest step/code sampling can straddle an ISR; complete six-step ordering requires a chronological hardware event trace'
    }
