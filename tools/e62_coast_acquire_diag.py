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

def reference_symbols(elf):
    """Exact ARM ABI of AM13E_BemfReference: codes[3], two padding bytes, five u32.
    Require ELF sizes instead of reading an invented or ambiguous structure.
    """
    text=subprocess.check_output(['arm-none-eabi-nm','-S','-n',str(elf)],text=True)
    sizes={'reference_valid':4,'reference_latest':28,'tick':4,'blackout_epoch':4};found={n:[] for n in sizes}
    for line in text.splitlines():
        m=re.fullmatch(r'([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[bBdD]\s+(\w+)',line.strip())
        if m and m[3] in found and int(m[2],16)==sizes[m[3]]:found[m[3]].append(int(m[1],16))
    if any(len(v)!=1 or not 0x20000000<=v[0]<=0x20018000-sizes[n] for n,v in found.items()):raise ValueError('Missing/ambiguous/calibration ABI reference snapshot')
    return {n:v[0] for n,v in found.items()}

def pending_reference(read32,addresses):
    def read():return [read32(addresses['reference_valid']),read32(addresses['tick']),read32(addresses['blackout_epoch'])]+[read32(addresses['reference_latest']+i*4) for i in range(7)]
    a=read();b=read()
    if a!=b:return {'status':'INCOMPLETE_CHANGING_REFERENCE','controller_usable_not_inferred':True}
    valid,now,epoch,*words=a
    codes=[words[0]&0xffff,words[0]>>16,words[1]&0xffff]
    sample,acq,complete,age_limit,acq_epoch=words[2:]
    age=(now-acq)&0xffffffff
    return dict(status='PASSIVE_STABLE_SNAPSHOT',valid_flag=valid,guest_tick=now,current_epoch=epoch,codes=codes,sample=sample,acquisition_tick=acq,completion_tick=complete,max_age_ticks=age_limit,acquisition_epoch=acq_epoch,age_ticks=age,inside_age_bound=age_limit>0 and age<=age_limit,timestamp_domain='GUEST_TICKS_NOT_SOURCE_VNS',controller_usable_not_inferred=True)
