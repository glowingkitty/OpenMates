// contract-test-file: tooling
// Actual Host/protocol/adapters with explicit native-event/IO fixtures. No Rust,
// browser, IndexedDB, Worker or inference execution or durability acceptance.
const {test}=require('node:test'),assert=require('node:assert/strict');
const {api,fixture,connection,held,tick,FixtureNativeEvent,OWNER,CHAT}=require('./helpers/nativeRustChatIOSetup.cjs');
const A='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',OP='33333333-3333-4333-8333-333333333333',META='44444444-4444-4444-8444-444444444444',PUB='55555555-5555-4555-8555-555555555555',PUB2='66666666-6666-4666-8666-666666666666',MON='77777777-7777-4777-8777-777777777777';
const scope={lifecycleGeneration:1,workspaceEpoch:2},evidence={packetStamp:'a'.repeat(64),messagesVersion:2};
function retained(kind='monitor'){
 const meta={id:CHAT};for(const field of ['title','summary','category','slug','activeFocusId','parentId','chatVisibility','createdAt','lastEditedAt','metadataUpdatedAt','isSubChat','isHidden','pinned','hasDraft','participantUserHashes','followUpSuggestions'])meta[field]=null;
 return{source:'browser_retained_message_cache',cacheReadKind:kind,contentCoverage:'unknown',readOnly:true,cached:true,fresh:false,historyComplete:false,coverage:'retained_rows_only',chat:{id:CHAT,title:'Original B',category:'',messages:[]},chatMetadata:meta,messageMetadata:[],piiMappingsByMessageId:{},piiRestoration:'page_local',pagesRead:0,hasMoreBefore:null,hasMoreAfter:null,startCursor:null,endCursor:null,anchorFound:false,checkpointPresentation:null,rowDispositions:[],messagesVersionAdvanced:false,windowCoverageChanged:false,canonicalIncomingDurablyAcknowledged:false,credentialAcknowledged:false,nativeDurabilityAcknowledged:false,crossDatabaseAssociationProven:false,inventoryComplete:false,recoveryProof:false};
}
function finalUpdate(){const metadata={source:'browser_metadata_monitor',metadataOnly:true,metadataRowsPersisted:0,draftRowsNotPersisted:0,selectedChatInvalidated:null,items:[]};for(const key of ['inventoryComplete','historyComplete','messagesVersionAdvanced','canonicalIncomingWindow','selectedWindowPublished','credentialAcknowledged','nativeDurabilityAcknowledged','crossDatabaseAssociationProven','recoveryProof'])metadata[key]=false;return{source:'browser_incoming_cache_sync',readOnly:true,metadata,selected:null,canonicalIncomingDurablyAcknowledged:false,historyComplete:false,inventoryComplete:false,recoveryProof:false,credentialAcknowledged:false,nativeDurabilityAcknowledged:false};}
async function setup({cold=false,onSelected,holdNative=false,holdContinuation=false,local=false,holdLocal=null}={}){
 const f=await fixture(),root=f.root(),lease=api.openRustChatIORoutingLease(root,f.gate),db=connection(f,lease),native=holdNative?api.createRustChatTransaction(lease,db,'messages','readwrite'):null;
 const execute=[],published=[],factory=[],continuationDrain=held();let closeCalls=0;
 const current=()=>api.assertRustChatIORootCurrent(root);
 const handler={current,async execute(plan,_signal,_draft,ownedLocal){const p=JSON.parse(plan);execute.push(p);if(local){assert.equal(ownedLocal,true);if(holdLocal&&execute.length===4)await holdLocal.promise;return JSON.stringify(localReply(p));}return '{}';},async close(){closeCalls++;if(native)await api.localChatWriteTerminal(native);}};
 const operation=cold?'read_cold_retained_saved_chat':'read_cache_monitor_update';
 const progress={onSelected:async(value,source)=>{published.push({value,source});if(onSelected)await onSelected(value,source);},createContinuationEffects(guard){factory.push(guard);return{current:guard,async execute(plan){execute.push(JSON.parse(plan));return '{}';},async close(){closeCalls++;if(holdContinuation)await continuationDrain.promise;}};}};
 const rpc=f.host.request({operation,handle:f.status.handle,generation:1,expectedPrincipal:OWNER,chatId:CHAT,scope,selector:{direction:'latest'},nowSeconds:1,...(local?{localFirst:true}:{}),...(!cold?{monitorId:MON}:{})},f.controller.signal,30000,undefined,handler,cold?undefined:progress);const refused=rpc.catch(()=>undefined);
 const id=f.worker.messages.at(-1).id;
 const plan=(kind,metadata=false)=>({version:1,kind,operationId:metadata?META:OP,scope,owner:OWNER,chatId:CHAT,database:'chats_db',...(metadata?{store:'chats'}:{stores:['chats','messages']})});
 const effect=async(kind,number,{metadata=false,synthetic=false,shadow=false}={})=>{
  const message={version:1,id,effectId:number,cacheEffect:JSON.stringify(plan(kind,metadata)),...(!metadata?{cacheStage:'owned_selected'}:{})};
  if(synthetic)f.worker.dispatchEvent(new MessageEvent('message',{data:message}));
  else if(shadow){const event=new FixtureNativeEvent('message',{},f.worker);Object.defineProperty(event,'data',{value:message});for(const fn of [...f.worker.listeners.get('message')])fn(event);}
  else f.worker.native('message',message);await tick();
 };
 const stages=async()=>{for(const [i,kind]of ['capture_cold_incoming_insert','compare_and_patch_cold_incoming_insert','readback','readback'].entries())await effect(kind,i+1);};
 const prepared=(pub=PUB)=>f.worker.native('message',{version:1,id,cachePrepared:{publicationId:pub}});
 const selected=(overrides={})=>({version:1,id,cacheSelected:{publicationId:PUB,selected:retained(),pending:'metadata',sourceEvidence:{...evidence},...overrides}});
 const metadata=async()=>{for(const [i,kind]of ['capture','compare_and_patch','readback'].entries())await effect(kind,i+5,{metadata:true});prepared(PUB2);await tick();};
 const terminal=()=>f.worker.native('message',{version:1,id,cacheTerminal:{operation,handle:f.status.handle,generation:1,owner:OWNER,chatId:CHAT,...(!cold?{monitorId:MON}:{})},state:'drained'});
 const final=()=>{f.worker.native('message',{version:1,id,ok:true,status:f.status,cacheMonitorId:MON,cacheUpdate:finalUpdate()});terminal();};
 return{...f,handler,root,db,native,rpc,refused,id,execute,published,factory,continuationDrain,effect,stages,prepared,selected,metadata,final,terminal,closes:()=>closeCalls};
}
test('actual Host publishes B only after trusted old IO drain while A and metadata RPC remain owned; continuation waits original callback',async()=>{
 const verify=held();const f=await setup({holdNative:true,holdContinuation:true,onSelected:async()=>verify.promise});
 const started=f.host.request({operation:'start_send',handle:f.status.handle,generation:1,chatId:A,text:'held A'},f.controller.signal);let id=f.worker.messages.at(-1).id;
 f.worker.native('message',{version:1,id,ok:true,status:f.status,send:{kind:'started',operationId:A}});await started;
 const Arequest=f.host.request({operation:'next_send_event',handle:f.status.handle,generation:1,operationId:A},f.controller.signal),Arejected=Arequest.catch(()=>undefined);
 const originalPending=f.host.pending.get(f.id);await f.stages();f.prepared();await tick();
 assert.equal(f.worker.messages.some(m=>m.id===f.id&&m.cacheDrained),false);assert.equal(f.published.length,0);
 f.native.oncomplete=()=>{};f.native.oncomplete();f.native.dispatchEvent(new Event('complete'));await tick();assert.equal(f.published.length,0);
 f.native.native('complete');await tick();assert.ok(f.worker.messages.some(m=>m.id===f.id&&m.cacheDrained?.publicationId===PUB));
 const progress=f.selected(),postsBefore=f.worker.messages.length;f.worker.native('message',progress);await tick();assert.equal(f.worker.messages.length,postsBefore,'partial selected publication must not ACK or retry the hint');assert.equal(f.published.length,1);assert.equal(f.host.pending.get(f.id),originalPending);assert.equal(f.worker.terminated,false);
 progress.cacheSelected.selected.chat.title='later source mutation';assert.equal(f.published[0].value.chat.title,'Original B');
 let done=false;void f.rpc.then(()=>done=true,()=>done=true);await f.effect('capture',5,{metadata:true});assert.equal(f.factory.length,0);assert.equal(done,false);assert.equal(f.host.sends.has(A),true);
 verify.resolve();await tick();assert.equal(f.factory.length,1);assert.equal(f.execute.length,5);assert.equal(f.host.pending.get(f.id),originalPending);
 await f.effect('compare_and_patch',6,{metadata:true});await f.effect('readback',7,{metadata:true});f.prepared(PUB2);await tick();assert.equal(done,false);
 assert.equal(f.worker.messages.some(m=>m.id===f.id&&m.cacheDrained?.publicationId===PUB2),false);f.continuationDrain.resolve();await tick();f.final();const final=await f.rpc;assert.equal(final.cacheUpdate.selected,null);
 assert.equal(f.worker.terminated,false);assert.equal(f.host.sends.has(A),true);assert.equal(f.closes(),2);await f.host.closeAndDrain();await Arejected;
});
test('actual Host rejects synthetic or shadowed marked IO before executing any effect',async()=>{
 for(const mode of ['synthetic','shadow']){const f=await setup();await f.effect('capture_cold_incoming_insert',1,{[mode]:true});assert.equal(f.execute.length,0);assert.equal(f.worker.terminated,true);await f.refused;}
});
test('intrinsic native message reader rejects structural objects and native nonmessage event types',async()=>{
 const f=await setup();assert.throws(()=>api.readNativeChatIOMessage({isTrusted:true,target:f.worker,data:{}},f.worker),/invalidated_snapshot/);
 assert.throws(()=>api.readNativeChatIOMessage(new FixtureNativeEvent('messageerror',{},f.worker),f.worker),/invalidated_snapshot/);await f.host.closeAndDrain();await f.refused;
});
test('actual progress rejects pre-drain, copied publication, wrong chat, replay and synthetic native shapes',async()=>{
 for(const mode of ['pre-drain','wrong-publication','wrong-chat','synthetic','replay']){
  const f=await setup({holdNative:mode==='pre-drain'});await f.stages();f.prepared();await tick();
  const message=f.selected();if(mode==='wrong-publication')message.cacheSelected.publicationId=PUB2;if(mode==='wrong-chat')message.cacheSelected.selected.chat.id=A;
  if(mode==='synthetic')f.worker.dispatchEvent(new MessageEvent('message',{data:message}));else f.worker.native('message',message);
  if(mode==='replay'){await tick();assert.equal(f.published.length,1);f.worker.native('message',message);}
  await tick();assert.equal(f.host.closed,true);assert.equal(f.published.length,mode==='replay'?1:0);if(f.native)f.native.native('abort');await f.host.closeAndDrain();await f.refused;
 }
});
test('wrong continuation sequence refuses before reopening the actual original effect factory',async()=>{
 const f=await setup();await f.stages();f.prepared();await tick();f.worker.native('message',f.selected());await tick();
 await f.effect('capture',6,{metadata:true});assert.equal(f.factory.length,0);assert.equal(f.execute.length,4);assert.equal(f.host.closed,true);await f.refused;
});
test('callback failure stops only the original monitor and waits actual B error after negative ACK without closing parent',async()=>{
 const f=await setup({onSelected:async()=>{throw Error('ui_callback_failed');}});await f.stages();f.prepared();await tick();
 const started=f.host.request({operation:'start_send',handle:f.status.handle,generation:1,chatId:A,text:'held A'},f.controller.signal);let id=f.worker.messages.at(-1).id;
 f.worker.native('message',{version:1,id,ok:true,status:f.status,send:{kind:'started',operationId:A}});await started;
 f.worker.native('message',f.selected());await tick();const rejected=assert.rejects(f.rpc,/ui_callback_failed/);
 const stop=f.worker.messages.find(m=>m.operation==='stop_cache_monitor');assert.ok(stop);assert.equal(stop.monitorId,MON);assert.equal(stop.handle,f.status.handle);assert.equal(stop.generation,1);assert.equal(stop.expectedPrincipal,OWNER);
 assert.equal(f.worker.messages.some(m=>m.operation==='cancel_send'||m.operation==='close_send'),false);assert.equal(f.host.sends.has(A),true);assert.equal(f.host.closed,false);
 let done=false;void rejected.then(()=>done=true);f.worker.native('message',{version:1,id:stop.id,ok:true,status:null,cacheMonitor:{id:MON,state:'closed'}});await tick();assert.equal(done,false,'negative stop ACK cannot complete the original pending hint');
 f.worker.native('message',{version:1,id:f.id,ok:false,error:'cancelled'});f.terminal();await rejected;assert.equal(f.host.closed,false);assert.equal(f.worker.terminated,false);assert.equal(f.host.sends.has(A),true);await f.host.closeAndDrain();
});
test('root teardown drains local callback failure without awaiting its own unanswered nested negative reply',async()=>{
 const f=await setup({onSelected:async()=>{throw Error('render_failed');}});await f.stages();f.prepared();await tick();f.worker.native('message',f.selected());await tick();assert.ok(f.worker.messages.some(m=>m.operation==='stop_cache_monitor'));
 let done=false;const drain=f.host.closeAndDrain().then(()=>done=true);await tick();assert.equal(done,true);await drain;await f.refused;assert.equal(f.worker.terminated,true);
});
test('native adapter root revocation refuses progress and closeAndDrain retains the actual in-flight publication callback',async()=>{
 const revoked=await setup();await revoked.stages();revoked.prepared();await tick();revoked.db.native('versionchange');revoked.worker.native('message',revoked.selected());await revoked.refused;assert.equal(revoked.published.length,0);assert.equal(revoked.host.closed,true);
 const verify=held(),f=await setup({onSelected:async()=>verify.promise});await f.stages();f.prepared();await tick();f.worker.native('message',f.selected());await tick();
 let done=false;const drain=f.host.closeAndDrain().then(()=>done=true);await tick();assert.equal(done,false);assert.equal(f.worker.terminated,false);verify.resolve();await drain;await f.refused;assert.equal(f.worker.terminated,true);
});
test('selected progress alone cannot complete the original metadata hint',async()=>{
 const f=await setup();await f.stages();f.prepared();await tick();f.worker.native('message',f.selected());await tick();f.final();await f.refused;assert.equal(f.host.closed,true);
});
test('cold final source evidence requires original native owned stage and remains data only',async()=>{
 const f=await setup({cold:true});await f.stages();f.prepared();await tick();const original={version:1,id:f.id,ok:true,status:f.status,retainedRead:retained('cold'),cacheSourceEvidence:{...evidence}};f.worker.native('message',original);original.cacheSourceEvidence.packetStamp='b'.repeat(64);original.retainedRead.chat.title='mutated after native receive';f.terminal();
 const result=await f.rpc;assert.equal(result.retainedRead.chat.title,'Original B');assert.deepEqual(result.cacheSourceEvidence,evidence);assert.equal(result.retainedRead.historyComplete,false);assert.equal(f.published.length,0);assert.equal(f.host.closed,false);await f.host.closeAndDrain();
 const g=await setup({cold:true});await g.stages();g.prepared();await tick();g.worker.dispatchEvent(new MessageEvent('message',{data:{version:1,id:g.id,ok:true,status:g.status,retainedRead:retained('cold'),cacheSourceEvidence:evidence}}));await g.refused;assert.equal(g.host.closed,true);
});

function localPlan(kind){return{version:1,kind,operationId:OP,owner:OWNER,chatId:CHAT,maxPacketBytes:kind==='owned_metadata'?262144:262144-Buffer.byteLength(JSON.stringify(localReply({kind:'owned_metadata'})))-2048,maxCheckpointRows:kind==='owned_metadata'?128:0,maxPayloadRows:kind==='owned_metadata'?0:20,lower:null,upper:null,direction:kind==='owned_metadata'?'next':'prev'};}
function localReply(p){const base={version:1,kind:p.kind,operationId:OP,databaseVersion:1};return p.kind==='owned_metadata'?{...base,chat_metadata:{id:CHAT,chat_id:CHAT,encrypted_chat_key:'original-wrapped'},messages:[],wrappers:[],boundary:null,compression_checkpoints:[]}:{...base,messages:[],nextKey:null,rangeExhausted:true};}
async function localStages(f,count=4){for(let i=0;i<count;i++){f.worker.native('message',{version:1,id:f.id,effectId:i+1,cacheEffect:JSON.stringify(localPlan(i%2===0?'owned_metadata':'messages')),cacheStage:'owned_local'});await tick();}}
function localResult(f){const value=retained('local');value.checkpointPresentation={source:'local_profile',coverage:'retained_latest',historyComplete:false,piiRestoration:'stored',retainedCheckpointCount:0,checkpoint:null};return{version:1,id:f.id,ok:true,status:f.status,retainedRead:value};}
// contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy,auth.session.isolation
// spec-assertion: Explicit original local-first output requires all four actual native callbacks and the same native prepared/drain/terminal chain; it carries no HTTP source evidence.
test('local-first Host holds fourth callback and terminal before cached publication',async()=>{
 const last=held(),f=await setup({cold:true,local:true,holdLocal:last});await localStages(f);assert.equal(f.execute.length,4);assert.equal(f.worker.messages.filter(m=>m.id===f.id&&m.cacheReply).length,3);let done=false;void f.rpc.then(()=>done=true,()=>done=true);assert.equal(done,false);
 last.resolve();await tick();f.prepared();await tick();assert.ok(f.worker.messages.some(m=>m.cacheDrained));const original=localResult(f);f.worker.native('message',original);original.retainedRead.chat.title='mutated';assert.equal(done,false);f.terminal();const result=await f.rpc;assert.equal(result.retainedRead.cacheReadKind,'local');assert.equal(result.retainedRead.chat.title,'Original B');assert.equal('cacheSourceEvidence'in result,false);assert.deepEqual(result.retainedRead.checkpointPresentation,localResult(f).retainedRead.checkpointPresentation);assert.equal(f.host.closed,false);await f.host.closeAndDrain();
});
// contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy,auth.session.isolation
// spec-assertion: Legacy/non-local requests, skipped callbacks, fabricated source evidence and pre-local cold fallback cannot satisfy the separate local publication ledger.
test('local-first Host refuses unrequested, incomplete and falsely authenticated local output',async()=>{
 const unrequested=await setup({cold:true});await localStages(unrequested,1);await unrequested.refused;assert.equal(unrequested.execute.length,0);
 const skipped=await setup({cold:true,local:true});await localStages(skipped,3);skipped.prepared();await skipped.refused;assert.equal(skipped.host.closed,true);
 const source=await setup({cold:true,local:true});await localStages(source);source.prepared();await tick();source.worker.native('message',{...localResult(source),cacheSourceEvidence:evidence});await source.refused;assert.equal(source.host.closed,true);
 const fallback=await setup({cold:true,local:true});await fallback.effect('capture_cold_incoming_insert',1);await fallback.refused;assert.equal(fallback.execute.length,0);
});
