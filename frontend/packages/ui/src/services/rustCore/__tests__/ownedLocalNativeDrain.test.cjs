// contract-test-file: tooling
// Actual Root/native-event observers with explicit inert platform resources.
// No browser, IDB, WASM, network, auth or storage acceptance is claimed.
const{test}=require('node:test'),assert=require('node:assert/strict');
const{api,fixture,connection,tick,tmp,core,ts}=require('./helpers/nativeRustChatIOSetup.cjs');
const fs=require('node:fs'),path=require('node:path');fs.writeFileSync(path.join(tmp,'existingSavedChatIO.js'),ts.transpileModule(fs.readFileSync(path.join(core,'existingSavedChatIO.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText);const{readExisting}=require(path.join(tmp,'existingSavedChatIO.js'));
// contract-test: supporting surface=gui.web assertions=auth.session.isolation,chats.persistence.client-encrypted
// spec-assertion: A new readonly local cursor transaction belongs to the original Root and cannot drain from copied/synthetic completion or a new write capability.
test('fixed readonly metadata cursor waits same native terminal and leaves existing write store policy unchanged',async()=>{
 const f=await fixture(),root=f.root(),lease=api.openRustChatIORoutingLease(root,f.gate),db=connection(f,lease);
 for(const names of [['chats'],['chat_compression_checkpoints'],['messages','chats'],['user_data'],['pending_sync_changes']])assert.throws(()=>api.createRustChatReadonlyCursorTransaction(lease,db,names),/invalid_request/);
 assert.throws(()=>api.createRustChatTransaction(lease,db,['chats','chat_compression_checkpoints'],'readonly'),/invalid_request/);
 assert.throws(()=>api.createRustChatTransaction(lease,db,['chat_compression_checkpoints'],'readwrite'),/invalid_request/);
 const tx=api.createRustChatReadonlyCursorTransaction(lease,db,['chats','chat_compression_checkpoints']);let done=false;const drain=api.revokeAndDrainRustChatIORoot(root).then(()=>done=true);
 await tick();assert.equal(done,false);assert.ok(tx.abortCalls>0);tx.dispatchEvent(new Event('complete'));await tick();assert.equal(done,false);tx.native('abort');await drain;assert.equal(done,true);await f.host.closeAndDrain();
});
// contract-test: supporting surface=gui.web assertions=auth.session.isolation,chats.persistence.client-encrypted
// spec-assertion: Cancelling a local callback while native open is pending cannot erase the original request; its actual terminal still owns Root drain and late connection closure.
test('actual original pending open remains owned through local negative and late native success',async()=>{
 const f=await fixture(),root=f.root(),lease=api.openRustChatIORoutingLease(root,f.gate),request=api.createRustChatOpenRequest(lease,f.factory);let done=false;const drain=api.revokeAndDrainRustChatIORoot(root).then(()=>done=true);
 await tick();assert.equal(done,false);request.dispatchEvent(new Event('success'));await tick();assert.equal(done,false);request.native('success');await drain;assert.equal(done,true);assert.equal(request.result.closed,true);await f.host.closeAndDrain();
});

// contract-test: supporting surface=gui.web assertions=auth.session.isolation,chats.persistence.client-encrypted
// spec-assertion: The actual maintained routed readonly callback stays owned through cancelled enumeration/open and synthetic property callbacks, until the independent original native terminal.
test('routed readonly IO cancellation awaits original enumeration and native open terminal',async()=>{
 const f=await fixture(),root=f.root(),lease=api.openRustChatIORoutingLease(root,f.gate),signal=new AbortController();let enumerated;f.factory.databases=()=>new Promise(r=>{enumerated=r});let settled=false;const io=readExisting(f.factory,'chats_db',['messages'],signal.signal,()=>{},()=>()=>null,lease);const rejected=assert.rejects(io,/cancelled/).then(()=>settled=true);
 await tick();signal.abort();await tick();assert.equal(settled,false);assert.equal(f.factory.requests.length,0);enumerated([{name:'chats_db',version:1}]);await rejected;assert.equal(f.factory.requests.length,0);await f.host.closeAndDrain();
 const g=await fixture(),otherRoot=g.root(),otherLease=api.openRustChatIORoutingLease(otherRoot,g.gate),negative=new AbortController();g.factory.databases=async()=>[{name:'chats_db',version:1}];settled=false;const open=readExisting(g.factory,'chats_db',['messages'],negative.signal,()=>{},()=>()=>null,otherLease),refused=assert.rejects(open,/cancelled/).then(()=>settled=true);await tick();const request=g.factory.requests.at(-1);negative.abort();request.onblocked();request.onerror();await tick();assert.equal(settled,false);request.native('success');request.onsuccess();await refused;assert.equal(request.result.closed,true);assert.equal(g.worker.terminated,false);await g.host.closeAndDrain();
});
// contract-test: supporting surface=gui.web assertions=auth.session.isolation,chats.persistence.client-encrypted
// spec-assertion: A synthetic transaction property callback cannot publish a routed result before the same actual native terminal; post-terminal cancellation remains negative.
test('routed result awaits same native readonly transaction after property callback',async()=>{
 for(const cancel of [false,true]){const f=await fixture(),root=f.root(),lease=api.openRustChatIORoutingLease(root,f.gate),signal=new AbortController();f.factory.databases=async()=>[{name:'chats_db',version:1}];let settled=false;const io=readExisting(f.factory,'chats_db',['messages'],signal.signal,()=>{},()=>()=>({private:'same original result'}),lease);const observed=io.then(value=>{settled=true;return value},error=>{settled=true;throw error});const rejected=cancel?assert.rejects(observed,/cancelled/):null;await tick();const request=f.factory.requests.at(-1);request.native('success');request.onsuccess();await tick();const tx=request.result.created.at(-1);tx.oncomplete();await tick();assert.equal(settled,false);if(cancel)signal.abort();tx.native('complete');if(rejected)await rejected;else assert.deepEqual(await observed,{private:'same original result'});assert.equal(settled,true);await f.host.closeAndDrain();}
});
