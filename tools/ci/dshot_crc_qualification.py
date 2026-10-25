#!/usr/bin/env python3
"""Independent proof of original-Guest physical PA26 DShot CRC policy.

Positive and negative cases are two *separate QEMU boot sessions*. Both
must traverse 32 external edges, physical capture/DMA, source-owned
callback return, and source-owned WWDT valid-frame feed. No hardware
motor / input-loss reset / rotor certification is inferred.
"""
import json
from pathlib import Path
import sys


def verify_pair(valid,invalid):
    problems=[]
    if len(valid)!=1 or len(invalid)!=1:
        return ['requires_exactly_one_native_callback_record_per_case']
    good,bad=valid[0],invalid[0]
    for label,d in [('valid',good),('invalid',bad)]:
        if not all(isinstance(d.get(k),int) for k in
                   ('frame','guest_frame','callback_return','delivered',
                    'capture','dma_beats','throttle_pre_callback',
                    'throttle_after_callback','watchdog_valid_feeds_delta')):
            problems.append(label+':missing_source_owned_evidence')
            continue
        if d['frame']!=d['guest_frame'] or d['delivered']!=32 or (
            d['capture']<32 or d['dma_beats']<32):
            problems.append(label+':wire_capture_dma_callback_mismatch')
        if d.get('gate_output_inactive_after_callback') is not True:
            problems.append(label+':gate_not_neutral_inactive')
        if d.get('ipsr')==3:
            problems.append(label+':original_cpu_fault_exception')
    if problems:
        return problems
    payload=good['frame']>>4
    source_crc=(payload^(payload>>4)^(payload>>8))&15
    if (good['frame']&15)!=source_crc:
        problems.append('positive_wire_crc_not_valid')
    if (bad['frame']&15)==source_crc:
        problems.append('negative_wire_crc_still_valid')
    if (good['frame'] ^ bad['frame'])!=1 or (
        good['frame']>>4)!=(bad['frame']>>4):
        problems.append('not_single_crc_bit_physical_negative_control')
    if (good['callback_return']!=1 or
        good['watchdog_valid_feeds_delta']!=1 or
        good['throttle_after_callback']<=good['throttle_pre_callback']):
        problems.append('valid_frame_source_crc_throttle_or_wwdt_feed_incorrect')
    if (bad['callback_return']!=0 or
        bad['watchdog_valid_feeds_delta']!=0 or
        bad['throttle_after_callback']!=bad['throttle_pre_callback']):
        problems.append('invalid_frame_rejection_or_wwdt_feed_incorrect')
    return problems

def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('--valid',type=Path,required=True)
    ap.add_argument('--invalid',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    a=json.loads(args.valid.read_text())
    b=json.loads(args.invalid.read_text())
    problems=verify_pair(a,b)
    result={'status':('PASS_ORIGINAL_GUEST_PHYSICAL_BAD_CRC_REJECTED'
                      if not problems else 'FAIL_NATIVE_CRC_POLICY'),
            'issues':problems,
            'scope':'PHYSICAL_PA26_DSHOT600_SOURCE_CRC_AND_WWDT_FEED_ONLY',
            'input_loss_watchdog_reset':'OPEN_NOT_MODELED',
            'physical_rotor_safety':'NOT_QUALIFIED'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print('E62_NATIVE_DSHOT_CRC_INDEPENDENT_QUALIFICATION '+
          json.dumps(result,sort_keys=True),flush=True)
    return 0 if not problems else 1

if __name__=='__main__':sys.exit(main())
