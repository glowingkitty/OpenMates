// Tooling-only inert admission tests. No native browser/IDB/auth/SDK proof.
// Every IDB IO method throws; this suite executes only actual kernel capture.
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm');
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const source=fs.readFileSync(path.resolve(__dirname,'../src/platform/browser_metadata_native.js'),'utf8');
const fixed={artifact:'a'.repeat(64),apiUrl:'https://api.example.invalid',appOrigin:'https://app.example.invalid'};
const owner='11111111-1111-4111-8111-111111111111',session='22222222-2222-4222-8222-222222222222';
function realm(){
 const context=vm.createContext({console});
 vm.runInContext(`
 const states=new WeakMap();const fixed=${JSON.stringify(fixed)};
 function captureMetadataConfiguredBackend(){return fixed}function readMetadataConfiguredBackend(actual){if(actual!==fixed)throw Error('foreign');return fixed}
 class EventTarget{addEventListener(){}removeEventListener(){}}
 class Event extends EventTarget{constructor(target,type,data,ports,trust=true){super();states.set(this,{target,type,data,ports,trust})}get target(){if(!states.has(this))throw Error('copied');return states.get(this).target}get type(){if(!states.has(this))throw Error('copied');return states.get(this).type}get isTrusted(){return states.get(this)?.trust===true}}
 class MessageEvent extends Event{get data(){if(!states.has(this))throw Error('copied');return states.get(this).data}get ports(){if(!states.has(this))throw Error('copied');return states.get(this).ports}}
 class IDBFactory{open(){throw Error('NO_NATIVE_IO_IN_TOOLING')}cmp(){return 0}}
 const factory=new IDBFactory();class WorkerGlobalScope extends EventTarget{get indexedDB(){return factory}}class DedicatedWorkerGlobalScope extends WorkerGlobalScope{}
 class IDBRequest{get result(){throw Error('NO_NATIVE_IO_IN_TOOLING')}get transaction(){throw Error('NO_NATIVE_IO_IN_TOOLING')}}
 class IDBDatabase{get name(){return ''}get version(){return 1}get objectStoreNames(){return {contains(){return true}}}transaction(){throw Error('NO_NATIVE_IO_IN_TOOLING')}close(){throw Error('NO_NATIVE_IO_IN_TOOLING')}}
 class IDBObjectStore{get keyPath(){return null}get name(){return ''}get(){throw Error('NO_NATIVE_IO_IN_TOOLING')}put(){throw Error('NO_NATIVE_IO_IN_TOOLING')}}
 class IDBTransaction{get db(){return null}get mode(){return ''}objectStore(){throw Error('NO_NATIVE_IO_IN_TOOLING')}abort(){throw Error('NO_NATIVE_IO_IN_TOOLING')}}
 Object.setPrototypeOf(globalThis,DedicatedWorkerGlobalScope.prototype);globalThis.location={origin:fixed.appOrigin};
 `,context);
 const inert=source.replace(/^import[^\n]+\n/m,'').replace(/^export /gm,'');vm.runInContext(inert,context);
 return {run:code=>vm.runInContext(code,context),capture:(frame,extra='')=>vm.runInContext(`metadataCaptureStartup(new MessageEvent(globalThis,'message',JSON.parse(${JSON.stringify(JSON.stringify(frame))}),[],true)${extra})`,context)};
}
const frame=()=>({version:1,operation:'bootstrap_existing_key',...fixed,sessionId:session,expectedPrincipal:owner});
const actualFrame=()=>{const value=frame();value.apiUrl=fixed.apiUrl;value.appOrigin=fixed.appOrigin;return value};
test('actual kernel saved-bootstrap capture is one-use in an inert realm',()=>{const r=realm();assert.ok(r.capture(actualFrame()));assert.throws(()=>r.capture(actualFrame()));});
test('copied event, wrong target and untrusted event never admit',()=>{
 assert.throws(()=>realm().run(`metadataCaptureStartup({target:globalThis,type:'message',isTrusted:true,data:${JSON.stringify(actualFrame())},ports:[]})`));
 for(const expression of [`new MessageEvent({},'message',${JSON.stringify(actualFrame())},[],true)`,`new MessageEvent(globalThis,'message',${JSON.stringify(actualFrame())},[],false)`])assert.throws(()=>realm().run(`metadataCaptureStartup(${expression})`));
});
test('foreign configured backend/principal/shape selectors refuse',()=>{
 for(const patch of [{apiUrl:'https://foreign.invalid'},{appOrigin:'https://foreign.invalid'},{artifact:'b'.repeat(64)},{expectedPrincipal:'not-an-owner'},{operation:'bootstrap_metadata'},{extra:true}])assert.throws(()=>realm().capture({...actualFrame(),...patch}));
 const omitted=actualFrame();delete omitted.expectedPrincipal;assert.throws(()=>realm().capture(omitted));
});
test('existing standalone no-Master metadata capture stays callable',()=>{
 const value=actualFrame();delete value.expectedPrincipal;value.operation='bootstrap_metadata';
 assert.ok(realm().run(`metadataCapture(new MessageEvent(globalThis,'message',${JSON.stringify(value)},[],true))`));
});
const held={
  "metadataCapture": "c15ba998f57ac3d763f3a5cd426601b42c801ed8b68c890c55863ffb1b9cb6b9",
  "rowTransaction": "bf4a2b590c30d42903920aa1f06b3c4a965dd7a635dae10d81c29252a5dad041",
  "metadataStart": "60a8aaedb73b0a9bef0abc746d7fdc80e4eeccdd8099ada439cea1f2b26126da",
  "metadataConsume": "8587b888ad82b57af7aa0d8188aa7f07fef67fd8ce405c7f686dbe8550ba3b9e",
  "metadataCloseCaptured": "0b9318c885ce8287308b094ac7fae741880c39c5873cb236b5aeab3b866f968d"
};
test('original standalone and physical CAS/readback/terminal kernel bodies stay byte-exact',()=>{
 for(const[name,expected]of Object.entries(held)){const start=source.indexOf('function '+name+'('),end=source.indexOf('\n}',start)+2;assert.ok(start>=0&&end>start);assert.equal(crypto.createHash('sha256').update(source.slice(start,end)).digest('hex'),expected,name);}
});
