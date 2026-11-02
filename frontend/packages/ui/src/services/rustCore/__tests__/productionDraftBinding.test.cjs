// contract-test-file: tooling
// Exact original-session orchestration with inert Host/source ports only.
// No Rust/Worker/browser/IDB/network/crypto execution or policy proof.
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),ts=require('typescript');
const own=path.resolve(__dirname,'..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'openmates-draft-binding-'));
for(const n of ['browserDraftProtocol','productionDraftBinding'])fs.writeFileSync(path.join(dir,n+'.js'),ts.transpileModule(fs.readFileSync(path.join(own,n+'.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText);
process.on('exit',()=>fs.rmSync(dir,{recursive:true,force:true}));const {createProductionDraftBinding}=require(path.join(dir,'productionDraftBinding.js'));
const OWNER='11111111-1111-4111-8111-111111111111',A='22222222-2222-4222-8222-222222222222',B='33333333-3333-4333-8333-333333333333',HANDLE='44444444-4444-4444-8444-444444444444',RESOURCE='55555555-5555-4555-8555-555555555555';
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};},tick=()=>new Promise(r=>setImmediate(r));
const result=(chatId=A)=>({source:'browser_rust_draft',chatId,version:5,localSaved:true,remoteSynced:false,pending:true,credentialAcknowledged:false});
function fixture({holdDrain=false,holdSync=false,failDrain=false}={}){
 const root=new AbortController(),drain=deferred(),sync=deferred(),reads=deferred(),requests=[],published=[];let live=true,effects=0;
 let selection={ownerId:OWNER,chatId:A,teamId:null,workspaceEpoch:2,selectionGeneration:1,revision:1};
 const input={host:{async requestDraft(body,signal){requests.push({...body,markdown:body.markdown?new Uint8Array(body.markdown):undefined});if(body.operation==='prepare_local_draft')return {kind:'local',resourceId:RESOURCE,result:result()};if(body.operation==='sync_draft'){if(holdSync)await sync.promise;return{kind:'synced',result:result()};}if(body.operation==='close_draft')return{kind:'closed'};return reads.promise;}},status:{handle:HANDLE,generation:1,principal:OWNER,persistence:'memory_only',localReadOnly:false},signal:root.signal,current(){if(!live)throw Error('original_revoked');},async verifyOriginal(){if(!live)throw Error('original_revoked');},currentSelection:()=>selection,profileGeneration:9,io:{clockSeconds:()=>20,createEffects(current){const ordinal=++effects;return{current,execute(){assert.fail('No IO in binding unit test');},async close(){if(holdDrain&&ordinal===1)await drain.promise;if(failDrain)throw Error('actual_drain_failed');}};}}};
 const binding=createProductionDraftBinding(input);return{binding,input,root,drain,sync,reads,requests,published,selectB(){selection={...selection,chatId:B,selectionGeneration:2,revision:2};},revoke(){live=false;},save:()=>binding.save({chatId:A,markdown:'Synthetic original editor content'},root.signal,r=>published.push(r))};
}
test('local UI acknowledgement waits actual effect drain and original final witness',async()=>{
 const f=fixture({holdDrain:true}),pending=f.save();await tick();assert.equal(f.published.length,0);f.drain.resolve();await pending;assert.equal(f.published.length,1);assert.equal(f.requests[0].scope.lifecycleGeneration,9);assert.equal(new TextDecoder().decode(f.requests[0].markdown),'Synthetic original editor content');await f.binding.close();
});
test('held A cleanup closes only its exact resource after ordinary B navigation',async()=>{
 const f=fixture({holdDrain:true}),pending=f.save(),rejected=assert.rejects(pending,/invalidated_snapshot/);await tick();f.selectB();f.drain.resolve();await rejected;assert.equal(f.published.length,0);assert.deepEqual(f.requests.filter(r=>r.operation==='close_draft').map(r=>r.resourceId),[RESOURCE]);assert.equal(f.requests.some(r=>r.operation==='sync_draft'),false);await f.binding.close();
});
test('local save resolves before held remote receipt; close drains owned remote operation',async()=>{
 const f=fixture({holdSync:true});await f.save();await tick();assert.equal(f.published.length,1);assert.equal(f.requests[1].operation,'sync_draft');let closed=false;const closing=f.binding.close().then(()=>closed=true);await tick();assert.equal(closed,false);f.sync.resolve();await closing;
});
test('restore plaintext is refused and wiped after original source revocation',async()=>{
 const f=fixture(),plain={source:'browser_rust_draft',chatId:A,version:5,present:true,markdown:'Synthetic private restore',preview:'Synthetic',localOnly:true,credentialAcknowledged:false};
 const pending=f.binding.restore(A,f.root.signal,()=>assert.fail('late plaintext'));const rejected=assert.rejects(pending,/original_revoked/);await tick();f.revoke();f.reads.resolve({kind:'restored',result:plain});await rejected;assert.equal(plain.markdown,'');assert.equal(plain.preview,null);await f.binding.close();
});
test('later mutation of supplied status/Host/source fields cannot replace original captured ports',async()=>{
 const f=fixture();f.input.host.requestDraft=async()=>assert.fail('replacement Host');f.input.status.principal=B;f.input.profileGeneration=100;f.input.verifyOriginal=async()=>assert.fail('replacement witness');await f.save();assert.equal(f.requests[0].expectedPrincipal,OWNER);assert.equal(f.requests[0].scope.lifecycleGeneration,9);await f.binding.close();
});
test('failed actual IO drain rejects save and prevents successful close receipt',async()=>{
 const f=fixture({failDrain:true});await assert.rejects(f.save(),/actual_drain_failed/);assert.equal(f.published.length,0);await assert.rejects(f.binding.close(),/actual_drain_failed/);
});
