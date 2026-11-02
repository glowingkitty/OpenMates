// contract-test-file: tooling
// Exact draft protocol/IO with synthetic native transaction terminals only.
// No real browser, IDB, Worker, WASM, account, network or crypto execution.
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),ts=require('typescript');
const own=path.resolve(__dirname,'..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'openmates-draft-io-'));
for(const name of ['browserDraftProtocol','browserDraftIO']){const r=ts.transpileModule(fs.readFileSync(path.join(own,name+'.ts'),'utf8'),{reportDiagnostics:true,compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}});assert.equal(r.diagnostics.length,0);fs.writeFileSync(path.join(dir,name+'.js'),r.outputText);}
fs.writeFileSync(path.join(dir,'browserAdapters.js'),"const owned=new WeakSet();exports.fixture=ports=>(owned.add(ports),ports);exports.assertRustChatIOPorts=ports=>{if(!owned.has(ports))throw Error('original_ports_required');};exports.isNativeChatIOEvent=(event,target)=>event?.native===true&&event.target===target;");
process.on('exit',()=>fs.rmSync(dir,{recursive:true,force:true}));
const {createBrowserDraftEffectHandler}=require(path.join(dir,'browserDraftIO.js')),{draftProjection,parseBrowserDraftPlan}=require(path.join(dir,'browserDraftProtocol.js')),{fixture:brand}=require(path.join(dir,'browserAdapters.js'));
const OWNER='11111111-1111-4111-8111-111111111111',CHAT='22222222-2222-4222-8222-222222222222',OP='33333333-3333-4333-8333-333333333333',CHANGE='44444444-4444-4444-8444-444444444444',TOKEN='55555555-5555-4555-8555-555555555555';
const base=()=>({chat_id:CHAT,user_id:OWNER,encrypted_chat_key:'wrapped-original',messages_v:7,draft_v:4,cleared_draft_v:2,encrypted_draft_md:'old-cipher',encrypted_draft_preview:'old-preview',updated_at:10,pinned:true,local:{untouched:true}});
function plan(kind='capture_draft'){const patch={encrypted_draft_md:'new-cipher',encrypted_draft_preview:'new-preview',draft_v:5,updated_at:11},change={change_id:CHANGE,chat_id:CHAT,type:'draft',value:'new-cipher',encrypted_draft_preview:'new-preview',version_before_edit:4,queue_order:1,queue_token:TOKEN};return{version:1,kind,operationId:OP,owner:OWNER,chatId:CHAT,scope:{lifecycleGeneration:1,workspaceEpoch:2},expected:kind==='capture_draft'?null:draftProjection(base()),queueMaximum:kind==='capture_draft'?null:0,patch:kind==='capture_draft'?null:patch,change:kind==='capture_draft'?null:change};}
const tick=()=>new Promise(r=>setImmediate(r));
function fixture(p=plan(),options={}){
 const state={row:base(),queue:new Map(),transactions:[],writes:[],opens:0,current:true};const root=new AbortController();
 const db={objectStoreNames:{contains:n=>['chats','pending_sync_changes'].includes(n)},close(){},transaction(stores,mode){assert.deepEqual(stores,['chats','pending_sync_changes']);const oldRow=structuredClone(state.row),oldQueue=structuredClone(state.queue);const tx={mode,aborted:false,abort(){this.aborted=true;},abortTerminal(){state.row=oldRow;state.queue=oldQueue;this.onabort?.({native:true,target:this});},complete(){assert.equal(this.aborted,false);this.oncomplete?.({native:true,target:this});},objectStore(name){const operation=(kind,key,value)=>{const req={};queueMicrotask(()=>{if(tx.aborted)return;try{
 if(kind==='get'){req.result=structuredClone(name==='chats'?state.row:state.queue.get(key));if(options.badReadback&&state.writes.length&&name==='chats')req.result.encrypted_draft_md='foreign';}
 else if(kind==='put'){state.row=structuredClone(value);state.writes.push(['chat',key]);req.result=key;}
 else if(kind==='add'){if(state.queue.has(key)){req.error=Error('duplicate');req.onerror?.();return;}state.queue.set(key,structuredClone(value));state.writes.push(['queue',key]);}
 else{state.queue.delete(key);state.writes.push(['delete',key]);}req.onsuccess?.({native:true,target:req});}catch(error){req.error=error;req.onerror?.();}});return req;};
 return {keyPath:name==='chats'?'chat_id':'change_id',get:key=>operation('get',key),put:value=>operation('put',value.chat_id,value),add:value=>operation('add',value.change_id,value),delete:key=>operation('delete',key),openCursor(){const req={},rows=[...state.queue.values()];let at=0;const next=()=>queueMicrotask(()=>{if(tx.aborted)return;req.result=at<rows.length?{value:structuredClone(rows[at++]),continue:next}:null;req.onsuccess?.({native:true,target:req});});next();return req;}};}};state.transactions.push(tx);return tx;}};
 const ports=brand({current(){if(!state.current)throw Error('root_revoked');},open(){state.opens++;const req={};queueMicrotask(()=>{req.result=db;req.onsuccess?.({native:true,target:req});});return req;},transaction:(...args)=>db.transaction(...args.slice(1))});
 const handler=createBrowserDraftEffectHandler(ports,ports.current),pending=handler.execute(JSON.stringify(p),root.signal);void pending.catch(()=>undefined);return{state,handler,pending,root,ports,p};
}
test('requires ORIGINAL branded ports and validates closed plan before opening database',async()=>{
 assert.throws(()=>createBrowserDraftEffectHandler({open(){assert.fail();},transaction(){assert.fail();},current(){}},()=>{}),/original_ports/);
 const p=plan();p.rawKey='forbidden';const f=fixture(p);await assert.rejects(f.pending,/invalid_draft_plan/);assert.equal(f.state.opens,0);
});
test('capture resolves ONLY actual complete and has no plaintext/write authority',async()=>{
 const f=fixture();await tick();let settled=false;void f.pending.then(()=>settled=true);await tick();assert.equal(settled,false);assert.equal(f.state.writes.length,0);f.state.transactions[0].complete();const packet=JSON.parse(await f.pending);assert.deepEqual(packet.row,draftProjection(base()));assert.equal(packet.transactionCommitted,true);
});
test('store atomically preserves unrelated fields and reads back encrypted row+exact intent before complete',async()=>{
 const f=fixture(plan('store_draft'));await tick();assert.deepEqual(f.state.writes.map(w=>w[0]),['chat','queue']);assert.deepEqual(f.state.row.local,{untouched:true});assert.equal(f.state.row.pinned,true);assert.equal(f.state.row.messages_v,7);assert.equal(f.state.row.encrypted_chat_key,'wrapped-original');
 let settled=false;void f.pending.then(()=>settled=true);await tick();assert.equal(settled,false);f.state.transactions[0].complete();const out=JSON.parse(await f.pending);assert.equal(out.row.encrypted_draft_md.value,'new-cipher');assert.deepEqual(out.change,f.p.change);assert.equal(Object.hasOwn(f.state.queue.get(CHANGE),'markdown'),false);
});
test('CAS rejects changed owner/key/tombstone/version before first write',async()=>{
 for(const[field,value]of[['user_id',CHAT],['encrypted_chat_key','new-key'],['cleared_draft_v',8],['draft_v',9]]){const f=fixture(plan('store_draft'));f.state.row[field]=value;await tick();assert.equal(f.state.transactions[0].aborted,true);assert.equal(f.state.writes.length,0);f.state.transactions[0].abortTerminal();await assert.rejects(f.pending,/aborted/);}
});
test('queue order race refuses atomic insertion without discarding existing encrypted intent',async()=>{
 const f=fixture(plan('store_draft'));f.state.queue.set('existing',{change_id:'existing',queue_order:4,value:'preserved'});await tick();assert.equal(f.state.transactions[0].aborted,true);assert.equal(f.state.writes.length,0);f.state.transactions[0].abortTerminal();await assert.rejects(f.pending,/aborted/);assert.equal(f.state.queue.get('existing').value,'preserved');
});
test('failed actual row readback and cancellation await abort terminal before handler drain',async()=>{
 for(const badReadback of[true,false]){const f=fixture(plan('store_draft'),{badReadback});await tick();if(!badReadback)f.root.abort();let drained=false;const close=f.handler.close().then(()=>drained=true);await tick();assert.equal(drained,false);assert.equal(f.state.transactions[0].aborted,true);f.state.transactions[0].abortTerminal();await assert.rejects(f.pending,/aborted/);await close;assert.equal(f.state.row.encrypted_draft_md,'old-cipher');assert.equal(f.state.queue.size,0);}
});
test('late root revocation after committed write refuses local acknowledgement',async()=>{
 const f=fixture(plan('store_draft'));await tick();f.state.current=false;f.state.transactions[0].complete();await assert.rejects(f.pending,/root_revoked/);assert.equal(f.state.row.encrypted_draft_md,'new-cipher');assert.equal(f.state.queue.get(CHANGE).value,'new-cipher');
});
test('synthetic complete cannot release a local receipt or end actual native abort ownership',async()=>{
 const f=fixture(plan('store_draft'));await tick();const tx=f.state.transactions[0];tx.oncomplete({native:false,target:tx});let settled=false;void f.pending.catch(()=>settled=true);await tick();assert.equal(settled,false);assert.equal(tx.aborted,true);tx.abortTerminal();await assert.rejects(f.pending,/aborted/);
});
test('local absence is explicit and cannot relabel supplied plaintext or omit presence evidence',()=>{
 const {validBrowserDraftRestore}=require(path.join(dir,'browserDraftProtocol.js'));
 const empty={source:'browser_rust_draft',chatId:CHAT,version:0,present:false,markdown:'',preview:null,localOnly:true,credentialAcknowledged:false};assert.equal(validBrowserDraftRestore(empty),true);assert.equal(validBrowserDraftRestore({...empty,markdown:'not absence'}),false);const missing={...empty};delete missing.present;assert.equal(validBrowserDraftRestore(missing),false);
});
