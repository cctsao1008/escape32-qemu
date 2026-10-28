#!/usr/bin/env node
"use strict";
/* Actual inline WebGUI JS runtime, strict DShot600 compiler parity.
 * No QEMU/Guest control or external libraries. */
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const os=require("node:os");
const path=require("node:path");
const {spawnSync}=require("node:child_process");
const ROOT=path.join(__dirname,"..");
const html=fs.readFileSync(path.join(ROOT,"web/sitl_trace_viewer.html"),"utf8");
const matches=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
assert.equal(matches.length,1);
class Ctx {
 clearRect(){} beginPath(){} moveTo(){} lineTo(){} stroke(){}
 fillText(){} fillRect(){} arc(){} fill(){} setLineDash(){}
}
class Element {
 constructor(tag) {
   this.tag=tag;this.children=[];this.listeners=new Map();this.attrs={};
   this.value="";this.disabled=false;this.textContent="";
   this.style={};this.hidden=false;this.dataset={};
   this.width=1200;this.height=250;this.ctx=new Ctx();this.clicked=false;
 }
 setAttribute(k,v){this.attrs[k]=String(v);}
 addEventListener(k,f){this.listeners.set(k,f);}
 appendChild(x){this.children.push(x);return x;}
 replaceChildren(...x){this.children=x.flatMap(y=>y.tag==="fragment"?y.children:[y]);}
 getContext(){return this.ctx;}
 click(){this.clicked=true;}
 remove(){this.removed=true;}
 getBoundingClientRect(){return {left:0,width:1200};}
}
const elements=new Map(),downloads=[],stored=new Map();
const body=new Element("body");
body.appendChild=function(x){this.children.push(x);if(x.tag==="a")downloads.push(x);return x;};
const document={
 body,
 getElementById(id){if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);},
 createElement:tag=>new Element(tag),
 createDocumentFragment:()=>new Element("fragment")
};
const url={
 createObjectURL(blob){const k="blob:test-"+(stored.size+1);stored.set(k,blob);return k;},
 revokeObjectURL(){}
};
const ctx=vm.createContext({document,location:{protocol:"file:",hostname:""},
 requestAnimationFrame:f=>f(),URL:url,Blob,console,setTimeout:f=>f()});
vm.runInContext(matches[0][1],ctx,{filename:"sitl_trace_viewer.html",timeout:4500});
const evaluate=expr=>vm.runInContext(expr,ctx,{timeout:4500});
const clone=x=>JSON.parse(JSON.stringify(x));
const temp=fs.mkdtempSync(path.join(os.tmpdir(),"e62-throttle-"));
const python="import sys\nfrom tools.native_dshot_scenario import load_native_scenario\n"+
 "try:\n    stages,meta=load_native_scenario(sys.argv[1])\n"+
 "except Exception as exc:\n    print(type(exc).__name__+': '+str(exc))\n    sys.exit(1)\n"+
 "print(meta['dshot_frames'])\n";
let count=0,validChecks=0,invalidChecks=0;
function compiler(doc,expected){
 const file=path.join(temp,"case"+(++count)+".json");
 fs.writeFileSync(file,JSON.stringify(doc,null,2)+"\n");
 const p=spawnSync("python3",["-c",python,file],{cwd:ROOT,encoding:"utf8"});
 assert.equal(p.status,expected?0:1,
   "Python native compiler mismatch: "+p.stdout+" "+p.stderr);
 if(expected)validChecks++;else invalidChecks++;
}
(async()=>{
 try{
  assert.equal(elements.get("profile-preset").value,"smoke");
  assert.equal(elements.get("profile-export").disabled,false);
  const names=["smoke","gentle","direct20","steps"];
  const filenames={
    smoke:"e62-native-p0-smoke.json",
    gentle:"e62-native-p0-gentle.json",
    direct20:"e62-native-p0-direct20.json",
    steps:"e62-native-p0-steps.json"
  };
  for(const name of names){
    const doc=JSON.parse(fs.readFileSync(path.join(ROOT,"scenarios",filenames[name]),"utf8"));
    assert.deepEqual(clone(evaluate("THROTTLE_PRESETS["+JSON.stringify(name)+"]")),doc);
    assert.deepEqual(clone(evaluate("profileValidate("+JSON.stringify(doc)+")")),[]);
    compiler(doc,true);
    evaluate("profileSetPreset("+JSON.stringify(name)+")");
    assert.equal(elements.get("profile-stages").children.length,doc.stages.length);
    assert.equal(elements.get("profile-export").disabled,false);
    assert.equal(clone(evaluate("profilePoints(profileDraft)")).total,
      doc.stages.reduce((n,s)=>n+s.duration_ms,0));
  }
  const base=clone(evaluate("THROTTLE_PRESETS.smoke"));
  const bad=[];
  function invalid(change){const d=clone(base);change(d);bad.push(d);}
  invalid(d=>d.target_elf_sha256="0".repeat(64));
  invalid(d=>d.protocol="DSHOT300");
  invalid(d=>d.frame_period_ns=2000000);
  invalid(d=>d.guest_ready_gating=true);
  invalid(d=>d.unexpected=true);
  invalid(d=>d.stages[0].permille=10);
  invalid(d=>d.stages.at(-1).permille=10);
  invalid(d=>d.stages[1].update_ms=3);
  invalid(d=>{d.stages[1].update_ms=4;d.stages[1].to_permille=201;});
  invalid(d=>d.stages[1].from_permille=10);
  invalid(d=>d.stages[0].duration_ms=120001);
  invalid(d=>{d.stages[0].duration_ms=120000;d.stages[1].duration_ms=120000;});
  invalid(d=>d.stages.push(...Array.from({length:13},()=>({
    kind:"hold",duration_ms:100,permille:0}))));
  invalid(d=>d.stages[1].surprise=1);
  invalid(d=>d.stages[1].duration_ms=true);
  invalid(d=>d.stages[1].to_permille=1000.2);
  invalid(d=>d.stages[1].duration_ms=0);
  for(const d of bad){
    assert.ok(clone(evaluate("profileValidate("+JSON.stringify(d)+")")).length>0);
    compiler(d,false);
  }
  const neutralRamp=clone(base);
  neutralRamp.stages[0]={kind:"ramp",duration_ms:1500,from_permille:0,to_permille:0,update_ms:10};
  assert.deepEqual(clone(evaluate("profileValidate("+JSON.stringify(neutralRamp)+")")),[]);
  compiler(neutralRamp,true);

  // Trigger the real stage table DOM handler.
  evaluate('profileSetPreset("steps")');
  let row=elements.get("profile-stages").children[1];
  const field=row.children[3].children[0];
  assert.equal(field.value,"100");
  field.value="250";field.listeners.get("change")();
  assert.equal(evaluate("profileDraft.stages[1].permille"),250);
  assert.equal(elements.get("profile-export").disabled,false);
  elements.get("profile-add-hold").listeners.get("click")();
  assert.equal(elements.get("profile-stages").children.length,6);
  row=elements.get("profile-stages").children[4];
  row.children[6].children[0].listeners.get("click")();
  assert.equal(elements.get("profile-stages").children.length,5);
  evaluate('profileSetPreset("gentle")');
  row=elements.get("profile-stages").children[1];
  const update=row.children[5].children[0];
  update.value="3";update.listeners.get("change")();
  assert.equal(elements.get("profile-export").disabled,true);
  assert.match(elements.get("profile-errors").textContent,/representable/);
  update.value="20";update.listeners.get("change")();
  assert.equal(elements.get("profile-export").disabled,false);

  const before=clone(evaluate("profileDraft"));
  await assert.rejects(()=>evaluate("profileImportFile({size:30,text:async()=>'{bad'})"));
  await assert.rejects(()=>evaluate("profileImportFile({size:30,text:async()=>"+
    JSON.stringify(JSON.stringify(bad[0]))+"})"));
  assert.deepEqual(clone(evaluate("profileDraft")),before);
  const custom=clone(base);custom.name="Custom Field Test";
  await evaluate("profileImportFile({size:3000,text:async()=>"+
    JSON.stringify(JSON.stringify(custom))+"})");
  assert.equal(evaluate("profileDraft.name"),"Custom Field Test");
  elements.get("profile-export").listeners.get("click")();
  assert.equal(downloads.length,1);
  assert.equal(downloads[0].download,"e62-native-custom-field-test.json");
  assert.equal(downloads[0].clicked,true);
  const exported=JSON.parse(await stored.get(downloads[0].href).text());
  assert.deepEqual(exported,custom);
  compiler(exported,true);
  assert.match(elements.get("profile-result").textContent,/EXPORTED/);
  assert.equal(elements.get("source-rpm").width,1200);
  console.log("PASS_E62_PROFILE_EDITOR_SOURCE_PRESETS_EDIT_IMPORT_EXPORT_COMPILER"+
    " valid="+validChecks+" invalid="+invalidChecks);
 }finally{
  fs.rmSync(temp,{recursive:true,force:true});
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
