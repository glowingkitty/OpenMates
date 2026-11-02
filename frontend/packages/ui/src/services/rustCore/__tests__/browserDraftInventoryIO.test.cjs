// contract-test-file: tooling
// Actual adapter closure, inert native-event/IDB-shape fixture only. No real
// browser, IDB, Worker, WASM, account, network or native-provenance acceptance.
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const source=fs.readFileSync(path.join(__dirname,'..','browserDraftInventoryIO.ts'),'utf8');
const out=ts.transpileModule(source,{reportDiagnostics:true,compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}});assert.equal(out.diagnostics.length,0);
const OP='33333333-3333-4333-8333-333333333333',id=n=>`${String(n).padStart(8,'0')}-0000-4000-8000-000000000000`;
const plan=(after=null,page=1)=>JSON.stringify({version:1,kind:'read_original_draft_inventory_page',operationId:OP,page,after,maxRows:20,maxBytes:2*1024*1024});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(records,options={}){
 const states=new WeakMap(),brands=new WeakMap(),owned=new WeakSet();const env={records,transactions:[],databases:[],opens:[],terminals:[],holdTerminals:!!options.holdTerminals,holdOpens:!!options.holdOpens,revoked:false,scanned:[]};
 const state=obj=>{const s=states.get(obj);if(!s)throw Error('fixture_internal_slot');return s;};
 const event=target=>{const e={target};brands.set(e,target);return e;};
 const terminal=(tx,kind)=>{const s=state(tx);if(s.ended)return;const fire=()=>{if(s.ended||kind==='complete'&&s.aborted)return;s.ended=true;tx[kind==='complete'?'oncomplete':'onabort']?.(event(tx));};if(env.holdTerminals)env.terminals.push(fire);else queueMicrotask(fire);};
 class Request{constructor(s){states.set(this,s);}get result(){return state(this).result;}get transaction(){return state(this).transaction??null;}get source(){return state(this).source??null;}}
 class Database{constructor(){states.set(this,{version:1,closed:0});env.databases.push(this);}get version(){return state(this).version;}close(){state(this).closed++;}}
 class Transaction{constructor(db){states.set(this,{db,aborted:false,ended:false});env.transactions.push(this);}objectStore(name){if(name!=='chats')throw Error('fixture_store');return new Store(this);}abort(){const s=state(this);if(s.ended)throw Error('fixture_already_terminal');if(s.aborted)return;s.aborted=true;terminal(this,'abort');}}
 class Store{constructor(tx){states.set(this,{tx});}get name(){state(this);return'chats';}get keyPath(){state(this);return'chat_id';}get(key){const tx=state(this).tx,request=new Request({transaction:tx,source:this,result:undefined});queueMicrotask(()=>{if(state(tx).aborted)return;state(request).result=records.find(row=>row.chat_id===key);request.onsuccess?.(event(request));if(!state(tx).aborted)terminal(tx,'complete');});return request;}openCursor(range,direction){
   const tx=state(this).tx;if(direction!=='next')throw Error('fixture_direction');const store=this,list=records.filter(row=>!range||row.chat_id>state(range).lower).slice().sort((a,b)=>a.chat_id<b.chat_id?-1:a.chat_id>b.chat_id?1:0);
   const request=new Request({transaction:options.foreignRequest?new Transaction(state(tx).db):tx,source:store,result:null,index:0,continued:false});
   const step=()=>{if(state(tx).aborted)return;const s=state(request);s.continued=false;const value=list[s.index];s.result=value?new CursorValue({request,store,value,key:value.chat_id,step}):null;if(value)env.scanned.push(value.chat_id);request.onsuccess?.(event(request));if(!s.continued&&!state(tx).aborted)terminal(tx,'complete');};queueMicrotask(step);return request;
 }}
 class Cursor{constructor(s){states.set(this,s);}get key(){return state(this).key;}get source(){return state(this).store;}continue(){const s=state(this),r=state(s.request);r.continued=true;r.index++;queueMicrotask(s.step);}}
 class CursorValue extends Cursor{get value(){return state(this).value;}}
 class Range{constructor(lower,open){states.set(this,{lower,open});}get lower(){return state(this).lower;}get upper(){state(this);return undefined;}get lowerOpen(){return state(this).open;}static lowerBound(lower,open){return new Range(lower,open);}}
 const ports={current(){if(env.revoked)throw Error('fixture_revoked');},open(){if(env.revoked)throw Error('fixture_revoked');const request=new Request({result:null});env.opens.push(request);const fire=()=>{state(request).result=new Database();request.onsuccess?.(event(request));};if(env.holdOpens)state(request).fire=fire;else queueMicrotask(fire);return request;},transaction(db,stores,mode){assert.equal(stores,'chats');assert.equal(mode,'readonly');state(db);if(env.revoked)throw Error('fixture_revoked');return new Transaction(db);}};owned.add(ports);
 const module={exports:{}};vm.runInNewContext(out.outputText,{exports:module.exports,module,require(name){if(name!=='./browserAdapters')throw Error('fixture_import');return{assertRustChatIOPortsNegative:p=>{if(!owned.has(p)||env.revoked)throw Error('original_ports_required');},assertRustChatIOPorts:p=>{if(!owned.has(p))throw Error('original_ports_required');p.current();},isNativeChatIOEvent:(e,target)=>brands.get(e)===target};},TextEncoder,AbortController,IDBRequest:Request,IDBDatabase:Database,IDBTransaction:Transaction,IDBObjectStore:Store,IDBCursor:Cursor,IDBCursorWithValue:CursorValue,IDBKeyRange:Range},{filename:'browserDraftInventoryIO.actual.js'});
 env.create=(current=()=>{})=>module.exports.createBrowserDraftInventoryIO(ports,current);env.copy=()=>module.exports.createBrowserDraftInventoryIO({...ports},()=>{});env.release=()=>{env.holdTerminals=false;for(const fire of env.terminals.splice(0))fire();};env.releaseOpens=()=>{env.holdOpens=false;for(const r of env.opens){const fire=state(r).fire;if(fire){delete state(r).fire;fire();}}};env.closed=db=>state(db).closed;env.fakeComplete=tx=>tx.oncomplete?.({target:tx,native:true});env.event=event;return env;
}
const rows=n=>Array.from({length:n},(_,i)=>({chat_id:id(i+1),draft_v:i+1,encrypted_draft_md:`cipher-${i+1}`,title:'MUST_NOT_RETURN_PLAINTEXT',messages:[{content:'MUST_NOT_RETURN_MESSAGES'}]}));
test('actual adapter pages all original readonly keys, projects ciphertext only and resumes without losing cutoff row',async()=>{
 const env=fixture(rows(25)),io=env.create();const a=JSON.parse(await io.execute(plan(),new AbortController().signal));assert.equal(a.rows.length,20);assert.equal(a.lastKey,id(20));assert.equal(a.cursorExhausted,false);assert.equal(JSON.stringify(a).includes('MUST_NOT_RETURN'),false);const b=JSON.parse(await io.execute(plan(a.lastKey,2),new AbortController().signal));assert.equal(b.rows.length,5);assert.equal(b.rows[0].chat_id,id(21));assert.equal(b.cursorExhausted,true);assert.equal(env.transactions.length,2);await io.close();
});
test('byte cutoff resumes at omitted row and oversized first row fails without advancing or deleting',async()=>{
 const input=rows(2);for(const row of input)row.encrypted_draft_md='c'.repeat(1100*1024);const env=fixture(input),io=env.create();const a=JSON.parse(await io.execute(plan(),new AbortController().signal));assert.equal(a.rows.length,1);assert.equal(a.cursorExhausted,false);const b=JSON.parse(await io.execute(plan(a.lastKey,2),new AbortController().signal));assert.equal(b.rows.length,1);assert.equal(b.rows[0].chat_id,id(2));await io.close();const huge=rows(1);huge[0].encrypted_draft_md='c'.repeat(2*1024*1024);const big=fixture(huge),blocked=big.create();await assert.rejects(blocked.execute(plan(),new AbortController().signal),/draft_inventory_row_oversized/);assert.equal(huge[0].encrypted_draft_md.length,2*1024*1024);await blocked.close();
});
test('forged transaction terminal cannot settle actual owned IO or close receipt before actual abort drains',async()=>{
 const env=fixture(rows(1),{holdTerminals:true}),io=env.create();let settled=false;const task=io.execute(plan(),new AbortController().signal).then(()=>{settled=true;throw Error('no_success');},()=>{settled=true;});await tick();assert.equal(env.transactions.length,1);env.fakeComplete(env.transactions[0]);let drained=false;const close=io.close().then(()=>{drained=true;});await tick();assert.equal(settled,false);assert.equal(drained,false);env.release();await task;await close;assert.equal(drained,true);assert.equal(env.closed(env.databases[0]),1);
});
test('cancelled open stays owned until actual native-shaped open terminal and closes only original handle',async()=>{
 const env=fixture(rows(1),{holdOpens:true}),io=env.create(),abort=new AbortController();let settled=false;const task=io.execute(plan(),abort.signal).then(()=>{throw Error('no_success');},()=>{settled=true;});abort.abort();let drained=false;const close=io.close().then(()=>{drained=true;});await tick();assert.equal(settled,false);assert.equal(drained,false);env.releaseOpens();await task;await close;assert.equal(env.transactions.length,0);assert.equal(env.closed(env.databases[0]),1);
});
test('copied ports and caller-selected store or budget reject before opening',async()=>{
 const env=fixture(rows(1));assert.throws(()=>env.copy(),/original_ports_required/);const io=env.create();for(const patch of [{database:'foreign'},{maxRows:21},{maxBytes:999},{page:0}]){await assert.rejects(io.execute(JSON.stringify({...JSON.parse(plan()),...patch}),new AbortController().signal));}assert.equal(env.opens.length,0);await io.close();
});
test('original lease revocation before real terminal refuses private page and drains actual readonly transaction',async()=>{
 const env=fixture(rows(1),{holdTerminals:true}),io=env.create();const task=io.execute(plan(),new AbortController().signal);await tick();env.revoked=true;const close=io.close();env.release();await assert.rejects(task);await close;assert.equal(env.closed(env.databases[0]),1);
});
test('closed request/source association and descriptor-only projection reject forged request or getter without execution',async()=>{
 const foreign=fixture(rows(1),{foreignRequest:true}),io=foreign.create();await assert.rejects(io.execute(plan(),new AbortController().signal));await io.close();let invoked=0;const records=rows(1);Object.defineProperty(records[0],'encrypted_draft_md',{get(){invoked++;return'secret';}});const env=fixture(records),guarded=env.create();await assert.rejects(guarded.execute(plan(),new AbortController().signal));assert.equal(invoked,0);await guarded.close();
});
test('synchronous negative current callback cannot hide close and admit a late open',async()=>{
 const env=fixture(rows(1));let io,armed=false;io=env.create(()=>{if(armed)void io.close();});armed=true;await assert.rejects(io.execute(plan(),new AbortController().signal));assert.equal(env.opens.length,0);await io.close();
});

test('fixed selected-row reread returns actual current projection or null DATA without cursor/deletion/completion flags',async()=>{
 const input=rows(2),env=fixture(input),io=env.create(),request=key=>JSON.stringify({version:1,kind:'reread_original_draft_inventory_row',operationId:OP,page:1,chatId:key});
 const initial=JSON.parse(await io.execute(plan(),new AbortController().signal));input[0].draft_v=99;input[0].encrypted_draft_md='actual-new-cipher';
 const changed=JSON.parse(await io.execute(request(id(1)),new AbortController().signal));assert.equal(changed.row.draft_v,99);assert.equal(changed.row.encrypted_draft_md,'actual-new-cipher');assert.notDeepEqual(changed.row,initial.rows[0]);assert.equal(Object.hasOwn(changed,'cursorExhausted'),false);assert.equal(Object.hasOwn(changed,'lastKey'),false);assert.equal(Object.hasOwn(changed.row,'title'),false);
 const absent=JSON.parse(await io.execute(request(id(7)),new AbortController().signal));assert.equal(absent.row,null);assert.equal(env.transactions.length,3);await io.close();
});
test('reread closed selector rejects extra cursor or noncanonical target before native open',async()=>{
 const env=fixture(rows(1)),io=env.create(),base={version:1,kind:'reread_original_draft_inventory_row',operationId:OP,page:1,chatId:id(1)};
 for(const changed of [{...base,after:null},{...base,chatId:'not-a-chat'},{...base,maxBytes:99}])await assert.rejects(io.execute(JSON.stringify(changed),new AbortController().signal));assert.equal(env.opens.length,0);await io.close();
});
