#!/usr/bin/env python3
"""Export source-authentic P0 QEMU rotor/switch traces as unit-labelled CSV."""
import argparse
import csv
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_p0_strict import parse_events


def export_events(events,rotor,sw):
    nr=ns=0
    with Path(rotor).open("w",newline="") as out:
        writer=csv.writer(out)
        writer.writerow(["source_sequence","virtual_time_ns","rpm",
                         "electrical_angle_unwrapped_rad",
                         "phase_u_current_a","phase_v_current_a",
                         "phase_w_current_a","electromagnetic_torque_nm"])
        for event in events:
            if event["kind"]!="ROTOR":continue
            a=event["data"]
            writer.writerow([event["seq"],event["vns"],a[0]/1000,
                             a[1]/1000,a[2]/1000,a[3]/1000,
                             a[4]/1000,a[5]/1e6])
            nr+=1
    with Path(sw).open("w",newline="") as out:
        writer=csv.writer(out)
        writer.writerow(["source_sequence","virtual_time_ns",
                         "six_pad_mask","gate_qualified","raw_gate_word",
                         "native_energy_integrated_steps"])
        for event in events:
            if event["kind"]!="SWITCH":continue
            a=event["data"]
            writer.writerow([event["seq"],event["vns"],
                             f"0x{a[0]:02x}",a[1],a[2],a[3]])
            ns+=1
    return {"rotor_samples":nr,"switch_changes":ns}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--events",type=Path,required=True)
    p.add_argument("--rotor-csv",type=Path,required=True)
    p.add_argument("--switch-csv",type=Path,required=True)
    a=p.parse_args()
    a.rotor_csv.parent.mkdir(parents=True,exist_ok=True)
    a.switch_csv.parent.mkdir(parents=True,exist_ok=True)
    with a.events.open(errors="replace") as file:
        parsed=parse_events(file)
    print("E62_P0_CSV_EXPORT "+
          str(export_events(parsed,a.rotor_csv,a.switch_csv)))


if __name__=="__main__":
    main()
