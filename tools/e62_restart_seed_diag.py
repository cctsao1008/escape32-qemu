"""Read-only optional experimental first-restart seed. Guest ticks are not vns."""
import re,subprocess
NAME='am13e_restart_seed_diag'
def symbol(elf):
    output=subprocess.check_output(['arm-none-eabi-nm','-n',str(elf)],text=True)
    addresses=[]
    for line in output.splitlines():
        m=re.fullmatch(r'([0-9a-fA-F]+)\s+[bBdD]\s+'+NAME,line.strip())
        if m:addresses.append(int(m[1],16))
    if len(addresses)!=1 or not 0x20000000<=addresses[0]<=0x20018000-24:raise ValueError('Missing/ambiguous experimental restart record')
    return addresses[0]
def snapshot(read32,address):
    a=[read32(address+4*i) for i in range(6)]
    b=[read32(address+4*i) for i in range(6)]
    if a!=b:raise RuntimeError('Restart record changed while read')
    if a[5] not in (0,1,2,3):raise ValueError('Invalid restart record result')
    return dict(zip(('guest_tick','oldstep','powered_step','capture_us','apparent_sector_period_us','result'),a),status=('INCOMPLETE_NO_RECORD','SEED_SELECTED_NOT_QUALIFICATION','REFUSAL_NOT_REACQUISITION','OBSERVED_NOT_APPLIED')[a[5]],time_basis='GUEST_TICK_NOT_SOURCE_VNS')
