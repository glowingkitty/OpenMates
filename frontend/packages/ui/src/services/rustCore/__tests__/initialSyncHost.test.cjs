// contract-test-file: tooling
// Actual maintained Host/protocol, synthetic platform transport only.
// No Worker/WASM/account/IDB/network/native runtime acceptance is claimed.
const{test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),ts=require('typescript');
const root=path.resolve(__dirname,'..'),out=fs.mkdtempSync(path.join(os.tmpdir(),'openmates-initial-host-inert-'));
for(const name of fs.readdirSync(root).filter(n=>n.endsWith('.ts')))fs.writeFileSync(path.join(out,name.replace(/\.ts$/,'.js')),ts.transpileModule(fs.readFileSync(path.join(root,name),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText);
process.on('exit',()=>fs.rmSync(out,{recursive:true,force:true}));
const{BrowserCoreWorkerHost}=require(path.join(out,'workerHost.js')),{MAX_INITIAL_SYNC_REQUEST_MS,MAX_REQUEST_MS}=require(path.join(out,'protocol.js')),{validInitialSyncStop}=require(path.join(out,'initialSyncProtocol.js'));
const OWNER='11111111-1111-4111-8111-111111111111',status={handle:'actual-inert-original',generation:1,principal:OWNER,persistence:'memory_only',localReadOnly:false};
class Endpoint extends EventTarget{sent=[];terminated=false;postMessage(value){this.sent.push(value);}terminate(){this.terminated=true;}reply(value){this.dispatchEvent(new MessageEvent('message',{data:value}));}}
const respond=(worker,request,extra={})=>worker.reply({version:1,id:request.id,ok:true,status,...extra});
// contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy,auth.session.isolation
// spec-assertion: B can only be released after an actual original A postMessage; dispatch is not actor, IO or persistence readiness.
test('actual Host dispatch precedes return and completion remains distinct',async()=>{
 const worker=new Endpoint(),host=new BrowserCoreWorkerHost(worker,undefined,OWNER),signal=new AbortController();
 const dispatched=host.startInitialSync(status.handle,status.generation,OWNER,signal.signal);assert.equal(worker.sent.length,1);assert.equal(worker.sent[0].operation,'run_initial_sync');let completed=false;void dispatched.completion.then(()=>{completed=true;});await Promise.resolve();assert.equal(completed,false);
 respond(worker,worker.sent[0],{initialSync:{receivedMetadataCount:123,storedMetadataCount:123}});assert.equal((await dispatched.completion).ok,true);host.close();
});
// contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy,auth.session.isolation
// spec-assertion: A's phase budget exceeds the ordinary30-second RPC limit without weakening ordinary deadlines or terminating B's parent.
test('held startup beyond ordinary deadline leaves same Host available',async(t)=>{
 t.mock.timers.enable({apis:['setTimeout']});const worker=new Endpoint(),host=new BrowserCoreWorkerHost(worker,undefined,OWNER),signal=new AbortController();const a=host.startInitialSync(status.handle,status.generation,OWNER,signal.signal);
 assert.equal(MAX_REQUEST_MS,30000);assert.equal(MAX_INITIAL_SYNC_REQUEST_MS,300000);t.mock.timers.tick(MAX_REQUEST_MS+1);assert.equal(worker.terminated,false);assert.equal(worker.sent.length,1);
 const b=host.request({operation:'status',handle:status.handle,generation:status.generation},signal.signal);respond(worker,worker.sent[1]);assert.equal((await b).ok,true);
 respond(worker,worker.sent[0],{initialSync:{receivedMetadataCount:123,storedMetadataCount:123}});await a.completion;assert.equal(worker.terminated,false);host.close();
});
// contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy,auth.session.isolation
// spec-assertion: Initial deadline sends one exact original negative control, retains pending ownership and leaves B usable; it is no drain or rearm acknowledgement.
test('initial deadline cancels only exact original scope and never closes sibling Host',async(t)=>{
 t.mock.timers.enable({apis:['setTimeout']});const worker=new Endpoint(),host=new BrowserCoreWorkerHost(worker,undefined,OWNER),signal=new AbortController(),a=host.startInitialSync(status.handle,status.generation,OWNER,signal.signal),rejected=assert.rejects(a.completion,{message:'deadline'});
 t.mock.timers.tick(MAX_INITIAL_SYNC_REQUEST_MS);await rejected;assert.equal(worker.terminated,false);assert.equal(worker.sent.length,2);assert.deepEqual(worker.sent[1],{version:1,id:worker.sent[0].id,initialSyncStop:{handle:status.handle,generation:status.generation,owner:OWNER}});assert.equal(validInitialSyncStop(worker.sent[1]),true);
 const b=host.request({operation:'status',handle:status.handle,generation:status.generation},signal.signal);respond(worker,worker.sent[2]);assert.equal((await b).ok,true);assert.equal(worker.terminated,false);
 worker.reply({version:1,id:worker.sent[0].id,ok:false,error:'unavailable'});assert.equal(worker.terminated,false);host.close();
});
// contract-test: supporting surface=gui.web assertions=auth.session.isolation,sync.client.shared-rust-policy
// spec-assertion: No dispatch resource escapes when the actual Host cannot post or a caller supplies malformed original selectors.
test('no actual post means no dispatch handoff; negative control framing stays closed',()=>{
 const worker=new Endpoint(),host=new BrowserCoreWorkerHost(worker,undefined,OWNER),signal=new AbortController();assert.throws(()=>host.startInitialSync('',status.generation,OWNER,signal.signal),/unavailable/);assert.equal(worker.sent.length,0);
 const good={version:1,id:1,initialSyncStop:{handle:status.handle,generation:1,owner:OWNER}};
 for(const bad of [{...good,settled:true},{...good,initialSyncStop:{...good.initialSyncStop,connected:true}},{...good,id:0},{...good,initialSyncStop:{...good.initialSyncStop,owner:'other'}}])assert.equal(validInitialSyncStop(bad),false);
 host.close();
});
