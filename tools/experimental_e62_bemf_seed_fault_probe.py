#!/usr/bin/env python3
"""SIM_ONLY E62 BEMF reference negative-control fault probe.

Start QEMU normally; feed its existing independent preboot Direct20 source.
No QTest, GDB, Guest SRAM/MMIO writes, synthetic CAP1 or PWM scheduling.
After the final external DShot frame, read linked SRAM safety symbols
through QMP *read-only* monitor inspection and stop the host process.
Never treat a QEMU-only result as a board/electrical qualification.
"""
import argparse
import hashlib
import json
import re
import socket
import subprocess
import time
from pathlib import Path

ORIGINAL_SHA="05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"
SYMBOLS=(
    "audio_owner", "fault_latched", "safety_initialized",
    "e62_sim_runtime_fault_caller_pc", "e62_sim_runtime_fault_prestate",
    "e62_sim_runtime_fault_reason", "e62_sim_motor_output_start_reject",
)
FRAME_RE=re.compile(r"\\bkind=DSHOT a=(\\d+)\\b")
EVENT_RE=re.compile(r"\\bkind=([A-Z0-9_]+)\\b")
VAL_RE=re.compile(r":\\s*0x([0-9a-fA-F]+)")


def get_symbols(elf):
    result={}
    lines=subprocess.run(["arm-none-eabi-nm","-an",str(elf)],check=True,
                         capture_output=True,text=True,timeout=20).stdout
    for line in lines.splitlines():
        words=line.split()
        if len(words)==3 and words[-1] in SYMBOLS:
            addr=int(words[0],16)
            if not 0x20000000<=addr<=0x2001fffc:
                raise ValueError("Safety symbol outside SRAM: "+words[-1])
            result[words[-1]]=addr
    if set(result)!=set(SYMBOLS):
        raise ValueError("Missing linked read-only safety markers: "+str(result))
    return result


def read_qmp(sock, symbols):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(12)
        client.connect(str(sock))
        stream=client.makefile("rb")
        hello=json.loads(stream.readline())
        if "QMP" not in hello:
            raise ValueError("Missing QMP greeting")
        def request(command,arguments=None):
            msg={"execute":command}
            if arguments is not None:
                msg["arguments"]=arguments
            client.sendall((json.dumps(msg)+"\\n").encode())
            while True:
                line=stream.readline()
                if not line:
                    raise ValueError("QMP disconnected during "+command)
                answer=json.loads(line)
                if "return" in answer:
                    return answer["return"]
                if "error" in answer:
                    raise ValueError("QMP "+command+": "+str(answer["error"]))
        request("qmp_capabilities")
        values={}
        for name,addr in symbols.items():
            raw=request("human-monitor-command",
                        {"command-line":f"xp /1wx 0x{addr:08x}"})
            matches=VAL_RE.findall(raw)
            if len(matches)!=1:
                raise ValueError(f"Unreadable {name} @0x{addr:08x}: {raw!r}")
            values[name]={"address":f"0x{addr:08x}",
                          "value":int(matches[0],16),"raw":raw}
        return {"symbols":values,
                "cpu":request("query-cpus-fast"),
                "status":request("query-status"),
                "read_only":True,"guest_writes":False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("qemu","elf","cfg","output"):
        p.add_argument("--"+arg,required=True,type=Path)
    p.add_argument("--label",required=True,choices=("with_seed","no_seed"))
    p.add_argument("--expect-start-reject",required=True,type=int)
    p.add_argument("--expect-runtime-fault",required=True,type=int)
    p.add_argument("--wall-timeout-s",type=int,default=250)
    a=p.parse_args()
    for path in (a.qemu,a.elf,a.cfg):
        if not path.is_file():
            p.error("Missing input "+str(path))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    digest=lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    if digest(a.elf)==ORIGINAL_SHA:
        p.error("Experiment must never use/modify the Original pinned guest")
    symbols=get_symbols(a.elf)
    log=a.output.with_suffix(".qemu.log")
    sock=Path("/tmp")/("e62-bemf-seed-fault-"+a.label+".sock")
    sock.unlink(missing_ok=True)
    report={"label":a.label,"classification":"SIM_ONLY_BEMF_SEED_FAULT_NEGATIVE_CONTROL",
            "hardware_qualified":False,"original_p1_qualified":False,
            "guest_writes":False,"elf_sha256":digest(a.elf),
            "cfg_sha256":digest(a.cfg),"qemu_sha256":digest(a.qemu)}
    proc=None
    try:
        with log.open("wb") as log_out:
            proc=subprocess.Popen([
                str(a.qemu.resolve()),"-machine",
                "am13e23019,esc-sim=on,esc-sim-native-motor=on,"
                "esc-sim-nfault-asserted=off,esc-sim-experimental-fc-direct20=on",
                "-kernel",str(a.elf.resolve()),"-display","none",
                "-serial","none","-monitor","none",
                "-qmp",f"unix:{sock},server=on,wait=off",
                "-icount","shift=2,sleep=off,align=off",
                "-device","loader,file="+str(a.cfg.resolve())+
                          ",addr=0x4000,force-raw=on"],
                stdout=subprocess.DEVNULL,stderr=log_out)
            frames=0
            limit=time.monotonic()+a.wall_timeout_s
            with log.open("r",errors="replace") as log_in:
                while time.monotonic()<limit:
                    line=log_in.readline()
                    if line:
                        m=FRAME_RE.search(line)
                        if m:
                            if int(m.group(1))!=frames:
                                raise ValueError("Physical DShot source frame missing/reordered")
                            frames+=1
                            if frames==3300:
                                break
                    else:
                        if proc.poll() is not None:
                            raise RuntimeError("QEMU exited before 3300 frames")
                        time.sleep(.04)
            if frames!=3300:
                raise TimeoutError(f"Source DShot incomplete {frames}/3300")
            report["external_dshot_frames"]=frames
            report["post_frames"]=read_qmp(sock,symbols)
    except Exception as exc:
        report["error"]=type(exc).__name__+": "+str(exc)
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        sock.unlink(missing_ok=True)
        counts={}
        for line in log.open(errors="replace") if log.exists() else ():
            m=EVENT_RE.search(line)
            if m:
                k=m.group(1)
                counts[k]=counts.get(k,0)+1
        report["total_physical_source_events"]=counts
    values=report.get("post_frames",{}).get("symbols",{})
    get=lambda key: values.get(key,{}).get("value")
    expected={
        "e62_sim_motor_output_start_reject":a.expect_start_reject,
        "e62_sim_runtime_fault_reason":a.expect_runtime_fault,
        "safety_initialized":1,
        "fault_latched":int(a.expect_runtime_fault!=0),
    }
    report["expected_fields"]=expected
    report["observed_fields"]={key:get(key) for key in expected}
    report["result"]="PASS" if (report.get("external_dshot_frames")==3300 and
        report.get("post_frames",{}).get("read_only") is True and
        all(get(key)==value for key,value in expected.items())) else "FAIL"
    a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\\n")
    print("E62_BEMF_SEED_FAULT_NEGATIVE_CONTROL "+json.dumps({
        "label":a.label,"result":report["result"],"expected":expected,
        "observed":report["observed_fields"],
        "source_frames":report.get("external_dshot_frames"),"error":report.get("error")
    },sort_keys=True),flush=True)
    return 0 if report["result"]=="PASS" else 1


if __name__=="__main__":
    raise SystemExit(main())
