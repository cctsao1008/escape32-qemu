"""Passive first-restart Guest acquisition record; never a motor qualification oracle."""
import re,subprocess
FIELDS=('guest_tick','oldstep','selected_step','phase_pattern','guest_inferred_direction','coast_transitions','stable_epochs','sample','acquisition_tick','decision','first_capture_us','second_capture_us')
STATUS=('INCOMPLETE_NO_RECORD','SECTOR_SELECTED_NOT_QUALIFICATION','REFUSED_BEFORE_POWER_NOT_REACQUISITION','FIRST_REAL_CAPTURE_NOT_LOCKED','TWO_CAPTURES_NOT_ROTOR_QUALIFICATION','SHADOW_ONLY_NOT_AUTHORIZATION','ACQUISITION_TIMEOUT_REFUSAL')
def symbol(elf):
    text=subprocess.check_output(['arm-none-eabi-nm','-n',str(elf)],text=True);matches=re.findall(r'^([0-9a-fA-F]+)\s+[bBdD]\s+am13e_coast_acquire_diag$',text,re.M)
    if len(matches)!=1 or not 0x20000000<=int(matches[0],16)<=0x20018000-48:raise ValueError('Missing/ambiguous coast acquisition record')
    return int(matches[0],16)
def snapshot(read32,address):
    first=[read32(address+4*i) for i in range(12)];last=[read32(address+4*i) for i in range(12)]
    if first!=last:raise RuntimeError('Coast acquisition record changed while read')
    if first[9]>=len(STATUS):raise ValueError('Invalid coast acquisition record')
    d=dict(zip(FIELDS,first));d['guest_inferred_direction']=d['guest_inferred_direction'] if d['guest_inferred_direction']<2**31 else d['guest_inferred_direction']-2**32
    return dict(d,status=STATUS[first[9]],timestamp_domain='GUEST_TICKS_NOT_SOURCE_VNS',hardware_qualified=False,original_qualified=False)
