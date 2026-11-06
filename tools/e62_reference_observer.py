"""Read-only experimental SC5 journal; MCU timestamps are not QEMU absolute time."""
import re
import subprocess

NAMES=('am13e_reference_diag_seq','am13e_reference_diag_first','am13e_reference_diag_ring')
FIELDS=('seq','event','tick','ecap_counter','selected_code','pending_code','expected_code',
        'active_code','calculated','published','ready','armed','sample','acquisition_tick',
        'completion_tick','max_age_ticks','blackout_epoch','fresh','latest_valid','latest_sample')


def symbols(elf):
    text=subprocess.run(['arm-none-eabi-nm','-n',str(elf)],capture_output=True,text=True,check=True).stdout
    found={k:[] for k in NAMES}
    for line in text.splitlines():
        m=re.fullmatch(r'([0-9a-fA-F]+)\s+[bBdD]\s+(\w+)',line.strip())
        if m and m[2] in found:found[m[2]].append(int(m[1],16))
    if any(len(v)!=1 or not 0x20000000<=v[0]<0x20018000 for v in found.values()):
        raise ValueError('Missing/ambiguous experimental reference journal symbols')
    return {k:v[0] for k,v in found.items()}


def decode(words,sequence):
    if len(words)!=20 or words[0]!=sequence or words[1] not in (1,2,3,4,5,6,7,8,9):
        raise ValueError('Uncommitted/invalid reference record')
    row=dict(zip(FIELDS,words));row['age_ticks']=(row['tick']-row['acquisition_tick'])&0xffffffff
    problems=[]
    if row['armed'] and row['event'] != 5:
        if not all(row[k] for k in ('calculated','published','ready','fresh','latest_valid')):
            problems.append('ARMED_WITHOUT_VALID_PUBLICATION')
        if row['max_age_ticks']==0 or row['age_ticks']>row['max_age_ticks']:
            problems.append('ARMED_STALE_REFERENCE')
        if row['expected_code']!=row['active_code']:problems.append('ARMED_DAC_MISMATCH')
        if row['selected_code']&3 not in (1,2,3):problems.append('ARMED_INVALID_PHASE')
    row['violations']=problems
    return row


def snapshot(read32,addresses):
    before=read32(addresses[NAMES[0]])
    first=range(1,min(before,64)+1);tail=range(max(1,before-255),before+1)
    rows={}
    for seq in list(first)+list(tail):
        base=(addresses[NAMES[1]]+(seq-1)*80 if seq<=64 else
              addresses[NAMES[2]]+((seq-1)%256)*80)
        rows[seq]=decode([read32(base+i*4) for i in range(20)],seq)
    if read32(addresses[NAMES[0]])!=before:
        raise RuntimeError('Concurrent reference journal update; incomplete snapshot')
    gaps=[(a+1,b-1) for a,b in zip(sorted(rows),sorted(rows)[1:]) if b>a+1]
    entries=list(rows.values())
    return dict(schema='e62.reference-observer.v1',seq_after=before,entries=entries,
        missing_sequence_ranges=gaps,history_complete=not gaps,
        status='INCOMPLETE' if not entries else
               'VIOLATIONS' if any(r['violations'] for r in entries) else
               'FAIL_CLOSED_ENTRY_OBSERVED' if any(r['event']==5 for r in entries) else 'OBSERVED_INVARIANTS_ONLY',
        timestamp_domain='MCU_TICK_AND_ECAP_COUNTER_NOT_ABSOLUTE_QEMU_VNS',
        source_publication_proven=False,p1_qualified=False,hardware_qualified=False)
