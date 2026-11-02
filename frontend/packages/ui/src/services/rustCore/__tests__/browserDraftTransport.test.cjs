// contract-test-file: tooling
// Exact Host draft transport, inert EventTarget/native-brand fixture only.
// No Worker, Rust, browser, IDB, ciphertext policy or runtime proof.
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),ts=require('typescript');
const own=path.resolve(__dirname,'..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'openmates-draft-transport-'));
for(const n of['browserDraftProtocol','browserDraftTransport'])fs.writeFileSync(path.join(dir,n+'.js'),ts.transpileModule(fs.readFileSync(path.join(own,n+'.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText);
fs.writeFileSync(path.join(dir,'browserAdapters.js'),"const originals=new WeakMap();exports.native=(event,target)=>(originals.set(event,target),event);exports.isNativeChatIOEvent=(event,target)=>originals.get(event)===target&&event.target===target;");
process.on('exit',()=>fs.rmSync(dir,{recursive:true,force:true}));
const {createBrowserDraftHostChannel}=require(path.join(dir,'browserDraftTransport.js')),{draftProjection}=require(path.join(dir,'browserDraftProtocol.js')),{native}=require(path.join(dir,'browserAdapters.js'));
const OWNER='11111111-1111-4111-8111-111111111111',CHAT='22222222-2222-4222-8222-222222222222',HANDLE='33333333-3333-4333-8333-333333333333',OP='44444444-4444-4444-8444-444444444444',RESOURCE='55555555-5555-4555-8555-555555555555';
const gate=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};},tick=()=>new Promise(r=>setImmediate(r));
function fixture({holdClose=false,failClose=false}={}){const closed=gate(),sent=[],root=new AbortController();let failures=0,channel;
 class OriginalPort extends EventTarget{postMessage(value){sent.push(structuredClone(value));}}
 const worker=new OriginalPort(),effect={current(){},async execute(encoded){const p=JSON.parse(encoded);return JSON.stringify({version:1,kind:p.kind,operationId:p.operationId,chatId:p.chatId,transactionCommitted:true});},async close(){if(holdClose)await closed.promise;if(failClose)throw Error('drain_failure');}};
 channel=createBrowserDraftHostChannel({worker,expectedPrincipal:OWNER,current(){},fatal(){failures++;channel.fail();void channel.close().catch(()=>undefined);}});
 const body={operation:'prepare_local_draft',handle:HANDLE,generation:1,expectedPrincipal:OWNER,chatId:CHAT,scope:{lifecycleGeneration:2,workspaceEpoch:3},nowSeconds:4,markdown:new TextEncoder().encode('Synthetic editor text')};
 const pending=channel.requestDraft(body,root.signal,effect);void pending.catch(()=>undefined);
 const emit=(payload,{trusted=true,shadow,origin=worker}={})=>{const event=new MessageEvent('message',{data:payload});if(trusted)native(event,origin);if(shadow!==undefined)Object.defineProperty(event,'data',{value:shadow});worker.dispatchEvent(event);};
 const effectPlan=(kind)=>{const row={chat_id:CHAT,draft_v:0};return{version:1,kind,operationId:OP,owner:OWNER,chatId:CHAT,scope:body.scope,expected:kind==='capture_draft'?null:draftProjection(row),queueMaximum:kind==='capture_draft'?null:0,patch:kind==='capture_draft'?null:{encrypted_draft_md:'cipher',encrypted_draft_preview:'preview',draft_v:1,updated_at:4},change:kind==='capture_draft'?null:{change_id:OP,chat_id:CHAT,type:'draft',value:'cipher',encrypted_draft_preview:'preview',version_before_edit:0,queue_order:1,queue_token:RESOURCE}};};
 return{worker,body,pending,channel,sent,root,closed,emit,effectPlan,failures:()=>failures,async plans(){for(const[index,kind]of['capture_draft','store_draft','readback_draft'].entries()){emit({version:1,draftId:1,effectId:index+1,draftEffect:JSON.stringify(effectPlan(kind))});await tick();}},prepared(){emit({version:1,draftId:1,draftPrepared:{resourceId:RESOURCE,kind:'local'}});},reply(){emit({version:1,draftId:1,draftReply:{kind:'local',resourceId:RESOURCE,result:{source:'browser_rust_draft',chatId:CHAT,version:1,localSaved:true,remoteSynced:false,pending:true,credentialAcknowledged:false}}});}};
}
test('same original Host owns private native listener; no public JSON acceptance bypass',async()=>{
 const f=fixture();assert.equal('accept'in f.channel,false);assert.equal(f.body.markdown.every(byte=>byte===0),true);assert.equal(new TextDecoder().decode(f.sent[0].draftRequest.markdown),'Synthetic editor text');
 f.emit({version:1,draftId:1,draftError:'unavailable'},{trusted:false});await assert.rejects(f.pending,/draft_worker_failed/);assert.equal(f.failures(),1);await assert.rejects(f.channel.close(),/draft_worker_failed/);
});
test('opaque prepared release waits actual handler drain after all three IO stages',async()=>{
 const f=fixture({holdClose:true});await f.plans();f.prepared();await tick();assert.equal(f.sent.some(row=>row.draftDrained),false);assert.equal(f.channel.hasPending(),true);
 f.closed.resolve();await tick();assert.equal(f.sent.filter(row=>row.draftDrained).length,1);f.reply();assert.equal((await f.pending).kind,'local');await f.channel.close();
});
test('native data getter defeats shadowed event data',async()=>{
 const f=fixture();await f.plans();f.emit({version:1,draftId:1,draftPrepared:{resourceId:RESOURCE,kind:'local'}},{shadow:{version:1,draftId:1,draftError:'forged'}});await tick();assert.equal(f.sent.filter(row=>row.draftDrained).length,1);f.reply();await f.pending;assert.equal(f.failures(),0);await f.channel.close();
});
test('prepared before complete IO sequence fails closed rather than creating a local receipt',async()=>{
 const f=fixture();f.prepared();await assert.rejects(f.pending,/draft_worker_failed/);assert.equal(f.sent.some(row=>row.draftDrained),false);await assert.rejects(f.channel.close(),/draft_worker_failed/);
});
test('root Worker failure during held handler drain retains pending ownership until actual terminal',async()=>{
 const f=fixture({holdClose:true});await f.plans();f.prepared();await tick();f.channel.fail();let done=false;const closing=f.channel.close();const rejected=assert.rejects(closing,/draft_worker_failed/).then(()=>done=true);await tick();assert.equal(done,false);assert.equal(f.channel.hasPending(),true);
 f.closed.resolve();await assert.rejects(f.pending,/draft_worker_failed|cancelled/);await rejected;assert.equal(done,true);
});
test('failed original IO drain cannot become successful close even after final response',async()=>{
 const f=fixture({failClose:true});await f.plans();f.prepared();await tick();f.emit({version:1,draftId:1,draftError:'unavailable'});await assert.rejects(f.pending,/draft_io_drain_failed/);await assert.rejects(f.channel.close(),/draft_io_drain_failed/);
});

test('foreign original native event lineage cannot authorize a draft reply',async()=>{
 const f=fixture();f.emit({version:1,draftId:1,draftError:'unavailable'},{origin:new EventTarget()});await assert.rejects(f.pending,/draft_worker_failed/);assert.equal(f.failures(),1);await assert.rejects(f.channel.close(),/draft_worker_failed/);
});

test('ordinary HostRPC events remain outside the draft channel before native draft validation',async()=>{
 const f=fixture();f.emit({version:1,id:99,ok:true,status:null},{trusted:false});assert.equal(f.failures(),0);assert.equal(f.channel.hasPending(),true);await f.plans();f.prepared();await tick();f.reply();await f.pending;assert.equal(f.failures(),0);await f.channel.close();
});
