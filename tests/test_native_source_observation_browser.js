#!/usr/bin/env node
"use strict";
/* Execute ACTUAL single-file WebGUI, not a separate chart implementation.
 * Source-only readout tests: no synthetic Guest/PWM/rotor transitions.
 */
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const html=fs.readFileSync(path.join(__dirname,"../web/sitl_trace_viewer.html"),"utf8");
const scripts=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
assert.equal(scripts.length,1);
const nodes=new Map();
class CanvasCtx {
 clearRect(){}beginPath(){}moveTo(){}lineTo(){}stroke(){}fillText(){}
 fillRect(){}arc(){}fill(){}setLineDash(){}
}
class Element {
 constructor(id){
  this.id=id;this.hidden=false;this.textContent="";this.value="";
  this.checked=id==="source-follow"||id==="follow-live";
  this.children=[];this.listeners=new Map();this.dataset={};
  this.style={};this.disabled=false;this.width=1200;this.height=205;
  this.ctx=new CanvasCtx();
 }
 addEventListener(type,fn){this.listeners.set(type,fn);}
 setAttribute(){}
 appendChild(el){this.children.push(el);return el;}
 replaceChildren(...els){this.children=els;}
 getContext(){return this.ctx;}
 getBoundingClientRect(){return {left:0,width:1200};}
}
const document={
 getElementById(id){if(!nodes.has(id))nodes.set(id,new Element(id));return nodes.get(id);},
 createElement:tag=>new Element(tag),
 createDocumentFragment:()=>new Element("fragment"),
};
class EventSource {
 static last=null;
 constructor(url){this.url=url;this.listeners=new Map();this.closed=false;EventSource.last=this;}
 addEventListener(kind,cb){this.listeners.set(kind,cb)}
 close(){this.closed=true}
 send(kind,data){const cb=this.listeners.get(kind);assert(cb);cb({data:JSON.stringify(data)})}
}
const sandbox=vm.createContext({
 document,location:{protocol:"http:",hostname:"127.0.0.1"},
 requestAnimationFrame:fn=>fn(),EventSource,console
});
vm.runInContext(scripts[0][1],sandbox,{filename:"sitl_trace_viewer.html",timeout:4500});
const js=x=>vm.runInContext(x,sandbox,{timeout:4500});
const $=id=>document.getElementById(id);
const meta={format:"e62.sitl.native-source.v1",
 timebase:"QEMU_CLOCK_VIRTUAL",no_guest_memory_writes:true,
 elf_sha256:"05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"};
function sample(t,seq,rpm,torque,current,raw){
 return {t_ns:t,source_seq:seq,motor_rpm:rpm,theta_mrad:40,torque_nm:torque,
  phase_currents_a:current,bemf_codes:[2000,2048,2090],
  bemf_selected_phase:0,bemf_dac_code:2048,cmp_filtered:false,
  pwm_six_pad_mask:null,pwm_gate:null,pwm_pair:2,
  last_dshot_raw:raw,last_dshot_frame:seq,last_dshot_ns:t-1000,
  cap1_count:1,timg12_count:1,wwdt_feed_count:2,
  last_cap1_ticks:null,last_timg12_ns:null}
}
const samples=[
 sample(100000000,10,400,0.1,[1,-1,0],448),
 sample(110000000,20,375,-0.25,[2,-2,0],0),
 sample(111000000,30,220,-2.0,[11,-10,-1],0),
 sample(120000000,40,40,-0.1,[0.5,-0.3,-0.2],0),
 sample(145000000,50,5,0,[0,0,0],0)
];
const events=[
 {seq:1,t_ns:100000000,kind:"DSHOT",data:[0,0,448,0,0,0]},
 {seq:2,t_ns:110000000,kind:"DSHOT",data:[0,0,0,0,0,0]},
 {seq:3,t_ns:111000000,kind:"CAP1",data:[0,0,0,0,0,0]},
 {seq:4,t_ns:112000000,kind:"TIMG12",data:[0,0,0,0,0,0]},
 {seq:5,t_ns:113000000,kind:"PWM_PAIR",data:[0,0,0,0,0,0]},
 {seq:6,t_ns:114000000,kind:"SWITCH_FOCUS",data:[24,1,15,3000,100,75]}
];
const source={format:meta.format,scope:"SIM_ONLY_NATIVE_NO_WFI_SOURCE_ONLY",
 metadata:meta,samples,events,capture_state:"SOURCE_LOG_COMPLETE"};
const sock=EventSource.last;assert(sock);assert.equal(sock.url,"/events");
sock.send("snapshot",{
 metadata:meta,truncated:true,oldest_seq:934,seq:2981,complete:null,
 packets:samples.map((s,i)=>({seq:i+934,sample:s,events:i===0?events:[]}))
});
assert.equal($("source-dashboard").hidden,false);
assert.equal($("dashboard").hidden,true);
assert.equal($("wfi-semantics").hidden,true);
assert.equal($("native-semantics").hidden,false);
assert.equal($("live-status").textContent,"SSE CONNECTED · LIVE SOURCE");
assert.match($("source-gap").textContent,/933 older sample packets not retained/);
assert.doesNotMatch($("source-gap").textContent,/QEMU source-event loss$/);
assert.equal($("source-focus-neutral").disabled,false);
assert.match($("source-focused-switch-count").textContent,/1 actual mask\/gate changes/);
assert.equal($("source-focused-switch").width,1200);
assert.match($("source-pwm-coverage").textContent,/NO FRESH SWITCH MASK/);
$("source-bemf-scale").value="center";js("sourceRedraw()");
assert.match($("source-bemf-range").textContent,/center · NOT volts/);
assert.doesNotMatch($("source-bemf-range").textContent,/0–4095/);
$("source-bemf-scale").value="auto";js("sourceRedraw()");
assert.match($("source-bemf-range").textContent,/auto · NOT volts/);
$("source-bemf-scale").value="full";js("sourceRedraw()");
assert.match($("source-bemf-range").textContent,/ADC codes 0–4095/);
$("source-focus-neutral").listeners.get("click")();
assert.equal(js("sourceWindow()[0]"),110000000);
assert.equal(js("sourceWindow()[1]"),145000000);
assert.match($("source-window").textContent,/110.000 – 145.000/);
assert.match($("source-focus-evidence").textContent,/minimum torque -2.0000 Nm/);
assert.match($("source-focus-evidence").textContent,/max sampled \|phase I\| 11.000 A/);
assert.match($("source-focus-evidence").textContent,/braking\/coast mechanism NOT DETERMINED/);
$("source-full-run").listeners.get("click")();
assert.equal(js("sourceFocusRange"),null);
assert.equal(js("sourceWindow()[0]"),100000000);
sock.send("gap",{missing_packets:3,since_seq:2981});
assert.match($("source-gap").textContent,/933 older sample packets not retained/);
assert.match($("source-gap").textContent,/SSE STREAM GAP: 3 packets unavailable/);
sock.send("complete",{error_type:null,native_result:{
 probe_exit_code:0,no_wfi_source_is_not_motor_strict_pass:true
}});
assert.equal($("live-status").textContent,"NATIVE PROBE FINISHED");
assert.match($("source-state").textContent,/NATIVE SOURCE PROBE ENDED/);
assert.match($("status").textContent,/strict Motor P1 Gate NOT EXECUTED/);
assert.match($("source-gap").textContent,/933 older sample packets not retained/);
// The exact local file path and motor gate are not sent back to QEMU.
assert.equal(sock.closed,false);
console.log("PASS_E62_BROWSER_SOURCE_SSE_STATUS_ADC_SCALE_NEUTRAL_FOCUS_PWM_PROVENANCE_NO_STRICT_P1");
