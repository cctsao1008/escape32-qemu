#!/usr/bin/env node
"use strict";
/* Execute the exact inline WebGUI JS with minimal browser DOM/canvas stubs.
 * Not a screenshot/rendered browser qualification. This catches runtime
 * errors that node --check and string-based tests cannot detect.
 * No network, QEMU, Guest, motor, canvas packages or jsdom required.
 */
const fs=require("node:fs");
const vm=require("node:vm");
const assert=require("node:assert/strict");
const path=require("node:path");
const html=fs.readFileSync(path.join(__dirname,"../web/sitl_trace_viewer.html"),"utf8");
const scripts=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
assert.equal(scripts.length,1,"exactly one inline self-contained source JS required");
const nodes=new Map();
class FakeContext {
  constructor(){this.dots=[];}
  clearRect(){this.dots=[];}
  beginPath(){}
  moveTo(){}
  lineTo(){}
  stroke(){}
  fillText(){}
  fillRect(...args){this.dots.push(args);}
  arc(){}
  fill(){}
  setLineDash(){}
}
class Element {
  constructor(name){
    this.name=name;
    this.textContent="";
    this.hidden=false;
    this.style={};
    this.dataset={};
    this.children=[];
    this.value=/zoom/.test(name)?"1":/pan/.test(name)?"0":"";
    this.checked=(name==="source-follow"); // actual HTML default checked
    this.width=1200;
    this.height=name.endsWith("events")?125:205;
    this.ctx=new FakeContext();
  }
  setAttribute(key,value){if(!this.attrs)this.attrs={};this.attrs[key]=String(value);}
  getContext(type){assert.equal(type,"2d");return this.ctx;}
  addEventListener(type,handler){
    if(!this.handlers)this.handlers=new Map();
    this.handlers.set(type,handler);
  }
  appendChild(node){this.children.push(node);return node;}
  replaceChildren(...nodes){this.children=nodes;return undefined;}
  getBoundingClientRect(){return {left:0,width:1200};}
}
const document={
  getElementById(id){
    if(!nodes.has(id))nodes.set(id,new Element(id));
    return nodes.get(id);
  },
  createElement:tag=>new Element(tag),
  createDocumentFragment:()=>new Element("fragment")
};
const browser=vm.createContext({
  document,
  location:{protocol:"file:",hostname:""},
  requestAnimationFrame:callback=>callback(),
  console,
  setTimeout:()=>{throw Error("No browser timers expected in read-only page");}
});
vm.runInContext(scripts[0][1],browser,{filename:"sitl_trace_viewer.html",timeout:2500});
const expr=code=>vm.runInContext(code,browser,{timeout:2500});
function packet(t,seq,{dshotAgeNs=1000,mask=18,rpm=50,cap=0,timer=0}={}){
 return {
  sample:{
    t_ns:t,source_seq:seq,motor_rpm:rpm,theta_mrad:42,torque_nm:0.012,
    phase_currents_a:[0.5,-0.25,-0.25],
    bemf_codes:[2000,2030,2060],bemf_selected_phase:1,
    bemf_dac_code:2048,cmp_filtered:true,
    pwm_six_pad_mask:mask,pwm_gate:mask===null?null:true,
    pwm_pair:3,last_dshot_raw:449,last_dshot_frame:100,
    last_dshot_ns:t-dshotAgeNs,
    cap1_count:cap,timg12_count:timer,wwdt_feed_count:23,
    last_cap1_ticks:null,last_timg12_ns:null
  },
  events:[{seq:seq-1,t_ns:t-100,kind:"DSHOT",data:[0,0,449,0,0,0]}]
 };
}
const meta={
 format:"e62.sitl.native-source.v1",timebase:"QEMU_CLOCK_VIRTUAL",
 elf_sha256:"05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0",
 no_guest_memory_writes:true,model:"SIM_ONLY_UNCALIBRATED_ECX87_KV147"
};
let first=packet(1000000,4);
let second=packet(4000000,8,{dshotAgeNs:3000000,mask:null,rpm:-65,cap:1,timer:1});
const offline={
 format:meta.format,scope:"SIM_ONLY_NATIVE_NO_WFI_SOURCE_ONLY",
 metadata:meta,capture_state:"SOURCE_LOG_COMPLETE",
 samples:[first.sample,second.sample],events:[...first.events,...second.events],
 summary:{observed_samples:2},native_result:null
};
expr("load("+JSON.stringify(offline)+")");
assert.equal(nodes.get("source-dashboard").hidden,false);
assert.equal(nodes.get("dashboard").hidden,true);
assert.equal(nodes.get("source-count").textContent,"2");
assert.equal(nodes.get("source-cap").textContent,"1");
assert.equal(nodes.get("source-timer").textContent,"1");
assert.match(nodes.get("scope").textContent,/NO-WFI/);
assert.match(nodes.get("source-state").textContent,/SOURCE_LOG_COMPLETE/);
assert.equal(nodes.get("source-dshot").ctx.dots.length,1,
  "no DShot dots after source command loss >2ms");
assert.equal(nodes.get("source-pwm").ctx.dots.length,6,
  "stale PWM mask must not be carried into next source sample");
assert.match(nodes.get("source-detail").textContent,/RPM=-65/);
assert.match(nodes.get("source-detail").textContent,/last FC DShot/);
const invalid=structuredClone(offline);
invalid.samples[1].t_ns=1;
assert.throws(()=>expr("load("+JSON.stringify(invalid)+")"),/Malformed No-WFI source sample/);
const forged=structuredClone(offline);
forged.metadata.timebase="HOST_WALL_TIME";
assert.throws(()=>expr("load("+JSON.stringify(forged)+")"),/Unsupported No-WFI source trace/);
const noSamples={
 metadata:meta,packets:[],seq:0,oldest_seq:1,truncated:false,complete:null
};
expr("sourceSnapshot("+JSON.stringify(noSamples)+")");
assert.match(nodes.get("source-state").textContent,/WAITING/);
assert.equal(nodes.get("source-dashboard").hidden,false);
const liveSnap={
 metadata:meta,packets:[first],seq:1,oldest_seq:1,truncated:false,complete:null
};
expr("sourceSnapshot("+JSON.stringify(liveSnap)+")");
assert.equal(nodes.get("source-count").textContent,"1");
const next=packet(5000000,12,{dshotAgeNs:3100000,mask:null,rpm:-150,cap:2,timer:2});
expr("sourcePacket("+JSON.stringify(next)+")");
assert.equal(nodes.get("source-count").textContent,"2");
assert.equal(nodes.get("source-timer").textContent,"2");
assert.match(nodes.get("source-detail").textContent,/RPM=-150/);
assert.equal(nodes.get("source-dshot").ctx.dots.length,1);
expr('sourceComplete({"error_type":"NativeProbeFailed","native_result":{"probe_exit_code":1}})');
assert.match(nodes.get("source-state").textContent,/ERROR/);
assert.match(nodes.get("status").textContent,/NOT EXECUTED/);
assert.equal(nodes.get("source-dashboard").hidden,false);

// Re-open the original WFI format after No-WFI to ensure UI isolation.
const oldSample={
 wfi:1,t_ns:10,pwm_duties:[0,0,0,1,0.1,0.9],
 motor_rpm:12,bemf_phase_v:[0,0,0],phase_currents_a:[0,0,0],
 integrated_ns:10,guest_step:1,guest_armed:0,guest_captured:0,
 guest_scheduled:0,guest_serviced:0,ost2:false,ost3:false,
 gate_qualified:false,guest_selected_code:0,cap1_ticks:0
};
const wfi={
 format:"e62.sitl.native-wfi.v1",
 scope:"SIM_ONLY_UNCALIBRATED_OPEN_STAR_MODEL",
 capture_state:"COMPLETE",metadata:{elf_sha256:meta.elf_sha256},
 data_semantics:{pwm:"WFI sampled carrier average duty"},
 samples:[oldSample],events:[],native_result:null
};
expr("load("+JSON.stringify(wfi)+")");
assert.equal(nodes.get("dashboard").hidden,false);
assert.equal(nodes.get("source-dashboard").hidden,true);
assert.match(nodes.get("scope").textContent,/NATIVE WFI/);
assert.equal(nodes.get("sample-count").textContent,1);
/* Host localhost mode must not mix manual Offline file with live SSE.
 * Verify the actual file-input handler and rejection cleanup, not strings.
 */
(async()=>{
  const httpNodes=new Map();
  const httpDocument={
    getElementById(id){
      if(!httpNodes.has(id))httpNodes.set(id,new Element(id));
      return httpNodes.get(id);
    },
    createElement:tag=>new Element(tag),
    createDocumentFragment:()=>new Element("fragment")
  };
  class FakeEventSource {
    constructor(url){
      this.url=url;this.closed=false;this.listeners=new Map();
      FakeEventSource.last=this;
    }
    addEventListener(kind,handler){this.listeners.set(kind,handler);}
    close(){this.closed=true;}
  }
  const httpBrowser=vm.createContext({
    document:httpDocument,
    location:{protocol:"http:",hostname:"127.0.0.1"},
    requestAnimationFrame:cb=>cb(),
    EventSource:FakeEventSource,
    console
  });
  vm.runInContext(scripts[0][1],httpBrowser,
                  {filename:"sitl_trace_viewer.html",timeout:2500});
  assert.equal(FakeEventSource.last.url,"/events");
  assert.equal(FakeEventSource.last.closed,false);
  // Drive the actual EventSource handlers rather than direct UI helpers.
  const socket=FakeEventSource.last;
  socket.listeners.get("snapshot")({
    data:JSON.stringify({
      metadata:meta,packets:[first],seq:1,oldest_seq:1,
      truncated:false,complete:null
    })
  });
  assert.equal(httpNodes.get("source-count").textContent,"1");
  socket.listeners.get("gap")({
    data:JSON.stringify({missing_packets:3,since_seq:1})
  });
  assert.match(httpNodes.get("source-gap").textContent,/3 frames missing/);
  socket.listeners.get("frame")({data:JSON.stringify(next)});
  assert.equal(httpNodes.get("source-count").textContent,"2");
  assert.equal(httpNodes.get("source-timer").textContent,"2");
  assert.match(httpNodes.get("source-gap").textContent,/3 frames missing/);
  socket.listeners.get("complete")({
    data:JSON.stringify({error_type:"NativeProbeFailed",native_result:{}})
  });
  assert.match(httpNodes.get("source-state").textContent,/ERROR/);

  const onChange=httpNodes.get("file").handlers.get("change");
  assert.equal(typeof onChange,"function");
  await onChange({
    target:{files:[{size:3000,text:async()=>JSON.stringify(offline)}]}
  });
  assert.equal(FakeEventSource.last.closed,true,
    "Manual source file load must disconnect any live EventSource");
  assert.equal(httpNodes.get("source-dashboard").hidden,false);
  assert.equal(httpNodes.get("dashboard").hidden,true);
  assert.match(httpNodes.get("live-status").textContent,/LIVE DETACHED/);
  assert.equal(httpNodes.get("source-count").textContent,"2");

  // Subsequent WFI offline playback must not inherit live metadata.
  await onChange({
    target:{files:[{size:3000,text:async()=>JSON.stringify(wfi)}]}
  });
  assert.equal(httpNodes.get("source-dashboard").hidden,true);
  assert.equal(httpNodes.get("dashboard").hidden,false);
  assert.match(httpNodes.get("scope").textContent,/ACTUAL NATIVE WFI/);
  assert.equal(httpNodes.get("direction").textContent,"NOT YET QUALIFIED");

  // Malformed later offline file must hide stale source and WFI panels.
  await onChange({
    target:{files:[{size:3,text:async()=>"{bad-json"}]}
  });
  assert.equal(httpNodes.get("source-dashboard").hidden,true);
  assert.equal(httpNodes.get("dashboard").hidden,true);
  assert.equal(httpNodes.get("scope").textContent,"TRACE REJECTED");
  assert.match(httpNodes.get("status").textContent,/JSON/);

  // Reconnect disabled after explicit offline mode switch until reload.
  const previous=FakeEventSource.last;
  vm.runInContext("connectLive()",httpBrowser,{timeout:1000});
  assert.equal(FakeEventSource.last,previous);
  console.log("PASS_E62_BROWSER_JS_RUNTIME_OFFLINE_LIVE_GAP_DSHOT_STALE_PWM_WFI_COMPAT_AND_FILE_ISOLATION");
})().catch(error=>{
  console.error(error);
  process.exitCode=1;
});
