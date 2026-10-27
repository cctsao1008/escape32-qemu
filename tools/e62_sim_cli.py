#!/usr/bin/env python3
"""Interactive E62 original-Guest ESCape32 *simulator* console.

Inspired by ESCape32 help/info/show/get/throt syntax but deliberately
NOT connected to the Guest UART or its real firmware CLI. Commands
operate on source-authentic, virtual-clock QEMU flight-controller input
and READ-ONLY original Guest symbols; no Guest register/CPU writes.
"""
from __future__ import annotations
import argparse
import cmd
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/"tests"))
from tools.native_dshot_scenario import SHA, load_native_scenario
from tools.native_p1_fault_plan import load_fault_plan
from tools.sitl_autonomous_transport import AUTO_BASE, REG, read_auto
from e62_autonomous_native_motor_probe import (
    TimedAutonomousQTest, _configure_autonomous_dshot,
    _guest_symbol_addresses, _read_original_guest_telemetry,
    _motor_snapshot, _pwm_source_snapshot, _receiver_snapshot,
)

MOTOR_BASE=0x5ffeb000
MCPWM_BASE=0x40014000
P1_OC_BASE=0x5ffe5000


def percent_to_permille(text):
    try:
        pct=Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("throt needs exact percentage 0..100 (0.1% resolution)") from exc
    scaled=pct*10
    if not pct.is_finite() or not 0<=pct<=100 or scaled!=scaled.to_integral_value():
        raise ValueError("throt needs 0..100% in steps of 0.1%")
    return int(scaled)


def _tokens(arg):
    return shlex.split(arg)


def _present(value):
    return json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False)


class E62SimConsole(cmd.Cmd):
    intro=("E62 Native ESC-SIM Console [SIM_ONLY, Original Guest, No-WFI]\n"
           "Type help for commands. 'throt' changes the *external* FC PA26 "
           "DShot stream, not Original Guest firmware.")
    prompt="e62-sim> "

    def __init__(self, *,qemu,elf,cfg_flash,scenario,artifacts):
        super().__init__()
        self.qemu=Path(qemu)
        self.elf=Path(elf)
        self.cfg_flash=Path(cfg_flash)
        self.artifacts=Path(artifacts)
        self.scenario=None
        self.stages=None
        self.meta=None
        self.fault_plan_path=None
        self.fault_plan=None
        self.proc=None
        self.conn=None
        self.qtest=None
        self.sockdir=None
        self.log_handle=None
        self.log_path=None
        self.run_artifact=None
        self.started_wall=None
        self.original_symbols=None
        self.last_report=None
        self.monitor_interval_s=1.0
        self.live_changed=False
        self.load_scenario(Path(scenario))

    def load_scenario(self,path):
        stages,meta=load_native_scenario(path)
        self.scenario=Path(path)
        self.stages=stages
        self.meta=meta
        if self.fault_plan_path is not None:
            self.fault_plan=load_fault_plan(self.fault_plan_path,stages)
        return meta

    @property
    def active(self):
        return self.qtest is not None and self.proc is not None and (
            self.proc.poll() is None)

    def _require_live(self):
        if not self.active:
            raise RuntimeError("run first; the QEMU simulator is not active")
        return self.qtest

    def _cannot_replace(self):
        if self.active:
            raise RuntimeError("Stop/finish current QEMU before changing scenario")

    def _run_checked(self, args):
        proc=subprocess.run(args,check=False,text=True,
                            stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if proc.returncode:
            raise RuntimeError("Command failed:\n"+proc.stdout[-1000:]+proc.stderr[-1500:])

    def _validate_inputs(self):
        if not self.qemu.is_file() or not self.elf.is_file():
            raise FileNotFoundError("QEMU binary or original Guest ELF missing. Run ./build.sh first")
        actual=hashlib.sha256(self.elf.read_bytes()).hexdigest()
        if actual!=SHA:
            raise RuntimeError("Original Guest ELF SHA256 mismatch (fail closed)")
        if not self.cfg_flash.is_file():
            self.cfg_flash.parent.mkdir(parents=True,exist_ok=True)
            self._run_checked([
                sys.executable,str(ROOT/"tools/sim_motor_cfg.py"),
                "--sim-only-opt-in","--elf",str(self.elf),
                "--motor-profile","ecx87-kv147",
                "--output",str(self.cfg_flash),
            ])
        if not self.cfg_flash.is_file():
            raise FileNotFoundError(self.cfg_flash)

    def _launch(self):
        self._cannot_replace()
        self._validate_inputs()
        self.artifacts.mkdir(parents=True,exist_ok=True)
        self.sockdir=tempfile.TemporaryDirectory(prefix="e62-cli-")
        sockpath=Path(self.sockdir.name)/"qtest.sock"
        listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:
            listener.bind(str(sockpath))
            listener.listen(1)
            listener.settimeout(15)
            suffix=time.strftime("%Y%m%d-%H%M%S")
            self.run_artifact=self.artifacts/("e62-sim-console-"+suffix+".json")
            # Avoid accidental overwrite for rapid consecutive runs.
            num=0
            while self.run_artifact.exists():
                num+=1
                self.run_artifact=self.artifacts/("e62-sim-console-"+suffix+f"-{num}.json")
            self.log_path=self.run_artifact.with_suffix(".qemu.log")
            self.log_handle=self.log_path.open("wb")
            argv=[str(self.qemu.resolve()),"-M",
                  "am13e23019,esc-sim=on,esc-sim-native-motor=on,"
                  "esc-sim-nfault-asserted=off",
                  "-kernel",str(self.elf.resolve()),
                  "-display","none","-serial","none","-monitor","none",
                  "-qtest",f"unix:path={sockpath}",
                  "-icount","shift=2,sleep=off,align=off",
                  "-device","loader,file="+str(self.cfg_flash.resolve())+
                            ",addr=0x4000,force-raw=on"]
            # Explicitly no -S/-gdb/WFI stepping. Guest starts independently
            # and DShot is armed on the existing non-silicon FC port.
            self.started_wall=time.monotonic()
            self.proc=subprocess.Popen(argv,stdout=subprocess.DEVNULL,
                                       stderr=self.log_handle)
            self.conn,_=listener.accept()
            self.qtest=TimedAutonomousQTest(self.conn,response_timeout_s=20)
            self.original_symbols,_=_guest_symbol_addresses(self.elf)
            fault=self.fault_plan
            frames=_configure_autonomous_dshot(
                self.qtest,neutral_ms=1500,ramp_ms=1000,
                hold_ms=300,coast_ms=200,drive_permille=200,
                ramp_update_ms=5,scenario_stages=self.stages,
                external_fault=fault)
            self.live_changed=False
            print(f"OK run: {frames} virtual DShot frames, 1kHz PA26; "
                  f"scenario_sha256={self.meta['sha256'][:16]}")
            print(f"original ELF: {SHA[:16]}...  log: {self.log_path}")
        except BaseException:
            self._teardown()
            raise
        finally:
            listener.close()

    def _teardown(self):
        if self.conn:
            try:self.conn.close()
            except OSError:pass
        self.conn=None
        self.qtest=None
        if self.proc:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:self.proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=4)
        self.proc=None
        if self.log_handle:
            self.log_handle.close()
        self.log_handle=None
        if self.sockdir:
            self.sockdir.cleanup()
        self.sockdir=None

    def _snapshot(self):
        q=self._require_live()
        d=read_auto(q.read)
        m=_motor_snapshot(q)
        return {
            "source_dshot":{
                "sent":d["sent"],"expected":d["target_frames"],
                "stage":d["stage"],"last_dshot":d["last_dshot"],
                "virtual_elapsed_ms":round(d["elapsed_ns"]/1e6,3),
                "running":bool(d["status"]&1),"done":bool(d["status"]&2),
                "error":d["error"],
                "live_override":bool(q.read(AUTO_BASE+REG["live_override"])),
                "live_permille":q.read(AUTO_BASE+REG["live_permille"]),
                "live_changes":q.read(AUTO_BASE+REG["live_changes"]),
                "live_applied_frame":q.read(AUTO_BASE+REG["live_applied_frame"]),
            },
            "motor":{
                "rpm":m["model_rpm_integer"],
                "six_pad_mask":m["actual_pwm_six_bit_mask"],
                "analog_codes":m["analog_codes"],
                "physics_ticks":m["native_1us_physics_ticks"],
                "fault_code":m["model_fault"],
            },
            "safety":{
                "ost_latch":q.read(MCPWM_BASE+0xb0),
                "oc_pin_trip":q.read(P1_OC_BASE+0x14),
            },
            "original_guest":_read_original_guest_telemetry(
                q,self.original_symbols),
        }

    def _finish(self):
        if not self.active:return None
        q=self.qtest
        auto=read_auto(q.read)
        if not (auto["status"]&2):
            raise RuntimeError("Scenario still running, use status/watch")
        result={
            "status":"SIM_ONLY_ORIGINAL_GUEST_CONSOLE_OBSERVATION_NOT_STRICT",
            "original_elf_sha256":SHA,
            "host_guest_register_writes":False,
            "used_guest_wfi_or_gdb":False,
            "synthetic_timed_bemf_enabled":False,
            "physical_motor_qualified":False,
            "native_dshot_scenario":self.meta,
            "native_external_fault_plan":self.fault_plan,
            "configured_dshot_frames":self.meta["dshot_frames"],
            "autonomous_dshot":auto,
            "native_motor":_motor_snapshot(q),
            "original_guest_after":_read_original_guest_telemetry(
                q,self.original_symbols),
            "receiver_after":_receiver_snapshot(q.read),
            "pwm_source_after":_pwm_source_snapshot(q),
            "legacy_synthetic_bemf_callbacks":auto["bemf_timer_callbacks"],
            "live_throttle_used":self.live_changed,
            "qemu_run_wall_elapsed_s":round(
                time.monotonic()-self.started_wall,6),
            "original_guest_config_changed":False,
            "source_log_path":str(self.log_path),
        }
        self.log_handle.flush()
        p0_path=self.run_artifact.with_suffix(".p0.events.log")
        count=0
        with self.log_path.open(errors="replace") as inp,p0_path.open("w") as out:
            for row in inp:
                if "E62_P0_EVENT " in row:
                    out.write(row)
                    count+=1
        result["p0_event_trace_path"]=str(p0_path)
        result["p0_source_event_count"]=count
        self.run_artifact.write_text(_present(result)+"\n")
        self.last_report=self.run_artifact
        self._teardown()
        return result

    def _command(self,verb,fn):
        try:
            fn()
        except (ValueError,OSError,RuntimeError,subprocess.SubprocessError,
                KeyError,IndexError) as exc:
            print(f"ERROR {verb}: {exc}")

    def emptyline(self):
        pass

    def default(self,line):
        print(f"ERROR unknown command: {line.split()[0]!r}. Type help")

    def do_info(self,arg):
        """info: Original Guest hash, model scope and simulator paths."""
        def act():
            if arg.strip():raise ValueError("usage: info")
            print(_present({
                "name":"E62 Original Guest QEMU ESC-SIM Python CLI",
                "reference_style":"ESCape32 command convention, NOT Guest UART",
                "original_guest_elf":str(self.elf),
                "original_guest_expected_sha256":SHA,
                "native_qemu":str(self.qemu),
                "sim_cfg_flash":str(self.cfg_flash),
                "motor_model":"24V ECX87-KV147 21 pole pairs SIM_ONLY",
                "live_throttle_path":"QEMU virtual 1kHz PA26 physical DShot source",
                "physical_qualified":False,
                "qemu_active":self.active,
            }))
        self._command("info",act)

    def do_load(self,arg):
        """load <scenario.json>: validate and load a 1kHz FC throttle profile."""
        def act():
            self._cannot_replace()
            tokens=_tokens(arg)
            if len(tokens)!=1:raise ValueError("usage: load <scenario.json>")
            d=self.load_scenario(Path(tokens[0]))
            print(f"OK loaded: {d['name']}, frames={d['dshot_frames']}, SHA={d['sha256']}")
        self._command("load",act)

    def do_fault(self,arg):
        """fault load <fault.json> | fault clear | fault show: PA22 SIM_ONLY."""
        def act():
            tokens=_tokens(arg)
            if tokens==["show"]:
                print(_present(self.fault_plan or {"fault":"not staged"}))
                return
            self._cannot_replace()
            if tokens==["clear"]:
                self.fault_plan=self.fault_plan_path=None
                print("OK physical fault calendar disabled")
            elif len(tokens)==2 and tokens[0]=="load":
                candidate=Path(tokens[1])
                d=load_fault_plan(candidate,self.stages)
                self.fault_plan_path=candidate
                self.fault_plan=d
                print("OK fault fixture loaded: "+_present(d))
            else:
                raise ValueError("usage: fault load <json> | fault clear | fault show")
        self._command("fault",act)

    def do_show(self,arg):
        """show [scenario|sim|guest|cfg|all]: simulated input and read-only Guest telemetry."""
        def act():
            tokens=_tokens(arg)
            if len(tokens)>1:raise ValueError("usage: show [scenario|sim|guest|cfg|all]")
            key=tokens[0] if tokens else "all"
            if key not in ("scenario","sim","guest","cfg","all"):
                raise ValueError("Unknown view")
            if key in ("cfg","all"):
                if not self.cfg_flash.is_file():
                    print("CFG: no dedicated SIM_ONLY preboot flash image; run first")
                else:
                    raw=self.cfg_flash.read_bytes()
                    if len(raw)!=336 or not 1<=raw[57]<=255:
                        raise RuntimeError("SIM_ONLY flash CFG size/telem_poles invalid")
                    print("CFG "+_present({
                        "scope":"DEDICATED_SIM_ONLY_PREBOOT_CFG_IMAGE",
                        "flash_base":"0x00004000",
                        "byte_offset_57_telem_poles":raw[57],
                        "guest_uart_settings_not_read":True,
                        "firmware_cfg_not_editable":True,
                    }))
            if key in ("scenario","all"):
                print("SCENARIO "+_present({
                    "path":str(self.scenario),"sha256":self.meta["sha256"],
                    "stage_rows":self.meta["stages"],
                    "fault":self.fault_plan,
                    "continuous_dshot_hz":1000,
                    "signal_is_external_simulated_pa26":True,
                }))
            if key in ("sim","guest","all"):
                if not self.active:
                    print("INFO: no live Guest; use run")
                else:
                    snap=self._snapshot()
                    print(_present({k:v for k,v in snap.items()
                                    if key=="all" or
                                    (key=="sim" and k!="original_guest") or
                                    (key=="guest" and k=="original_guest")}))
        self._command("show",act)

    def do_get(self,arg):
        """get <dshot.sent|motor.rpm|guest.throt|safety.ost_latch|...>."""
        def act():
            token=_tokens(arg)
            if len(token)!=1 or "." not in token[0]:
                raise ValueError("usage: get <domain.param> ; show all lists fields")
            domain,key=token[0].split(".",1)
            if domain=="cfg" and key=="telem_poles":
                if not self.cfg_flash.is_file():
                    raise RuntimeError("Dedicated SIM_ONLY cfg not yet generated")
                raw=self.cfg_flash.read_bytes()
                if len(raw)!=336 or not 1<=raw[57]<=255:
                    raise RuntimeError("Unknown or unqualified SIM_ONLY CFG image")
                print(f"cfg.telem_poles = {raw[57]} (SIM_ONLY preboot only)")
                return
            snap=self._snapshot()
            if domain=="dshot":domain="source_dshot"
            if domain=="guest":domain="original_guest"
            if domain not in snap or key not in snap[domain]:
                raise ValueError("unavailable or ambiguous property: "+token[0])
            print(f"{token[0]} = "+_present(snap[domain][key]))
        self._command("get",act)

    def do_status(self,arg):
        """status: source-clocked DShot, rotor RPM, Guest CRC and OST flags."""
        def act():
            if arg.strip():raise ValueError("usage: status")
            snap=self._snapshot()
            d=snap["source_dshot"]
            m=snap["motor"]
            g=snap["original_guest"]
            print(
                f"FC {d['sent']}/{d['expected']} frame stage={d['stage']} "
                f"virtual_ms={d['virtual_elapsed_ms']} "
                f"last_dshot={d['last_dshot']} "
                f"live={d['live_override']}({d['live_permille']/10:.1f}%) | "
                f"motor={m['rpm']}rpm mask=0x{m['six_pad_mask']:02x} "
                f"ticks={m['physics_ticks']} | "
                f"Guest crc_feed={g.get('valid_frame_feeds','NA')} "
                f"throt={g.get('throt','NA')} | "
                f"OST=0x{snap['safety']['ost_latch']:x}")
            if d["done"]:
                self._finish()
                print(f"OK completed: {self.last_report}")
        self._command("status",act)

    def do_run(self,arg):
        """run: start independent QEMU + source-clocked 1kHz DShot scenario."""
        def act():
            if arg.strip():raise ValueError("usage: run")
            self._launch()
        self._command("run",act)

    def do_throt(self,arg):
        """throt <percent>|auto: live external FC override next DShot frame.

        Example: throt 20.0 ; throt 0 ; throt auto.
        Input is 0..100%, NOT ESCape32 firmware CLI -2000..2000.
        """
        def act():
            tokens=_tokens(arg)
            if len(tokens)!=1:
                raise ValueError("usage: throt <0..100%> | throt auto")
            q=self._require_live()
            if q.read(AUTO_BASE+REG["status"])!=1:
                raise RuntimeError("No running DShot frames for live throttle")
            if tokens[0]=="auto":
                q.write(AUTO_BASE+REG["live_override"],0)
                if q.read(AUTO_BASE+REG["live_override"])!=0:
                    raise RuntimeError("Auto scenario handback was not accepted")
                self.live_changed=True
                print("OK live throttle override disabled; JSON source resumed")
                return
            value=percent_to_permille(tokens[0])
            q.write(AUTO_BASE+REG["live_permille"],value)
            if q.read(AUTO_BASE+REG["live_permille"])!=value:
                raise RuntimeError("Live throttle data write not accepted")
            q.write(AUTO_BASE+REG["live_override"],1)
            if q.read(AUTO_BASE+REG["live_override"])!=1:
                raise RuntimeError("FC throttle enable rejected")
            self.live_changed=True
            start=q.read(AUTO_BASE+REG["sent"])
            print(f"OK FC command requested {value/10:.1f}% at observed "
                  f"frame={start}; takes effect on NEXT QEMU virtual "
                  "1kHz frame, consult THROT_SET/DSHOT source trace")
        self._command("throt",act)

    def do_watch(self,arg):
        """watch [wall-seconds]: repeat status until scenario ends or Ctrl+C."""
        def act():
            args=_tokens(arg)
            if len(args)>1:raise ValueError("usage: watch [interval-seconds]")
            seconds=float(args[0]) if args else self.monitor_interval_s
            if not .1<=seconds<=30:raise ValueError("watch interval must be 0.1..30s")
            print("Watching source, Ctrl+C stops WATCH only (Guest keeps running).")
            try:
                while self.active:
                    self.do_status("")
                    if not self.active:break
                    time.sleep(seconds)
            except KeyboardInterrupt:
                print("Monitoring interrupted; QEMU still running")
        self._command("watch",act)

    def do_results(self,arg):
        """results: write source-owned event trace and completed Guest snapshot."""
        def act():
            if arg.strip():raise ValueError("usage: results")
            if self.active:
                if not (read_auto(self.qtest.read)["status"]&2):
                    raise RuntimeError("Simulator still running; use status or watch")
                self._finish()
            if not self.last_report:
                print("No completed run")
                return
            doc=json.loads(self.last_report.read_text())
            print("REPORT "+_present({
                "file":str(self.last_report),
                "event_file":doc.get("p0_event_trace_path"),
                "event_count":doc.get("p0_source_event_count"),
                "frames":(doc.get("autonomous_dshot") or {}).get("sent"),
                "guest_crc_feeds":(doc.get("original_guest_after") or {}).get(
                    "valid_frame_feeds"),
                "native_motor_model_fault":(doc.get("native_motor") or {}).get(
                    "model_fault"),
                "live_throttle_used":doc.get("live_throttle_used"),
                "strict_P0_or_P1_qualified":False,
            }))
            print("Run native_p0_strict.py/native_p1_qualification.py separately "
                  "only on compatible, unmodified JSON scenarios.")
        self._command("results",act)

    def do_history(self,arg):
        """history [n]: last virtual-time DShot/THROT_SET FC source events."""
        def act():
            from collections import deque
            tok=_tokens(arg)
            if len(tok)>1:raise ValueError("usage: history [1..100]")
            limit=int(tok[0]) if tok else 10
            if not 1<=limit<=100:raise ValueError("history limit 1..100")
            log=self.log_path
            if (log is None or not log.is_file()) and self.last_report:
                log=self.last_report.with_suffix(".qemu.log")
            if not log or not log.is_file():
                raise RuntimeError("No QEMU source log; run first")
            q=deque(maxlen=limit)
            with log.open(errors="replace") as source:
                for line in source:
                    if "E62_P0_EVENT " in line and (
                        "kind=DSHOT " in line or "kind=THROT_SET " in line):
                        q.append(line[line.index("E62_P0_EVENT "):].strip())
            print("\\n".join(q) if q else "No FC source events flushed yet")
        self._command("history",act)

    def do_stop(self,arg):
        """stop: terminate SIMULATOR; does not claim Guest safe-off/recovery."""
        def act():
            if arg.strip():raise ValueError("usage: stop")
            if self.active:
                q=self.qtest
                if q.read(AUTO_BASE+REG["status"])==1:
                    # Hand source command to neutral first; allow at least
                    # one real PA26 frame, then stop simulator. Does not
                    # claim rotor stopped or silicon-safe shutdown.
                    q.write(AUTO_BASE+REG["live_permille"],0)
                    q.write(AUTO_BASE+REG["live_override"],1)
                    start=q.read(AUTO_BASE+REG["sent"])
                    limit=time.monotonic()+5
                    while time.monotonic()<limit:
                        if q.read(AUTO_BASE+REG["sent"])>=start+10:
                            break
                        time.sleep(.05)
                self._teardown()
                print("OK QEMU terminated (SIM_ONLY); not an ESC safe-off acceptance")
            else:
                print("OK simulator not running")
        self._command("stop",act)

    def do_quit(self,arg):
        """quit: exit CLI and terminate owned QEMU (simulator only)."""
        if self.active:
            self.do_stop("")
        return True

    do_exit=do_quit

    def do_EOF(self,arg):
        print("")
        return self.do_quit(arg)

    def do_set(self,arg):
        """set monitor_interval <seconds>: only Python CLI-local UI setting."""
        def act():
            tok=_tokens(arg)
            if len(tok)!=2 or tok[0]!="monitor_interval":
                raise ValueError("Firmware configuration set is unsupported; "
                                 "only 'set monitor_interval <seconds>'")
            value=float(tok[1])
            if not .1<=value<=30:
                raise ValueError("monitor_interval must be 0.1..30s")
            self.monitor_interval_s=value
            print(f"OK Python monitor_interval={value:.2f} wall seconds")
        self._command("set",act)


def main():
    p=argparse.ArgumentParser(description="E62 source-authentic native QEMU console")
    p.add_argument("--qemu",type=Path,default=ROOT/".build/qemu-src/build/qemu-system-arm")
    p.add_argument("--elf",type=Path,default=ROOT/"baseline/e62-g13b3/firmware/AM13E-rev17.3.elf")
    p.add_argument("--cfg-flash",type=Path,default=ROOT/"artifacts/e62-g13b3-native-autonomous-cfg-flash.bin")
    p.add_argument("--scenario",type=Path,default=ROOT/"scenarios/e62-native-console-10s.json")
    p.add_argument("--artifacts-dir",type=Path,default=ROOT/"artifacts")
    args=p.parse_args()
    console=E62SimConsole(qemu=args.qemu,elf=args.elf,cfg_flash=args.cfg_flash,
                          scenario=args.scenario,artifacts=args.artifacts_dir)
    try:
        console.cmdloop()
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        console._teardown()


if __name__=="__main__":
    main()
