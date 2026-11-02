// contract-test-file: tooling
// Actual pure ledger tests; no Worker, native IO, auth or acceptance claimed.
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),ts=require('typescript');
const root=path.resolve(__dirname,'..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'owned-local-ledger-'));
for(const name of ['savedReadProtocol','ownedLocalReadProtocol'])fs.writeFileSync(path.join(dir,name+'.js'),ts.transpileModule(fs.readFileSync(path.join(root,name+'.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText);
process.on('exit',()=>fs.rmSync(dir,{recursive:true,force:true}));
const {createOwnedLocalReadState:create,beginOwnedLocalRead:begin,completeOwnedLocalRead:complete,ownedLocalReadReady:ready,ownedLocalReadFallbackReady:fallback}=require(path.join(dir,'ownedLocalReadProtocol.js'));
const owner='11111111-1111-4111-8111-111111111111',chatId='22222222-2222-4222-8222-222222222222',operationId='33333333-3333-4333-8333-333333333333',expected={owner,chatId},json=JSON.stringify;
const metaPlan=()=>({version:1,kind:'owned_metadata',operationId,owner,chatId,maxPacketBytes:262144,maxCheckpointRows:128,maxPayloadRows:0,lower:null,upper:null,direction:'next'});
const meta=(missing=false)=>({version:1,kind:'owned_metadata',operationId,databaseVersion:7,chat_metadata:missing?null:{id:chatId,chat_id:chatId,user_id:owner,encrypted_chat_key:'opaque ciphertext',messages_v:1,extension:{exact:['all','fields']}},messages:[],wrappers:[],boundary:null,compression_checkpoints:[]});
const rowPlan=m=>({...metaPlan(),kind:'messages',maxPacketBytes:262144-Buffer.byteLength(json(m))-2048,maxCheckpointRows:0,maxPayloadRows:20,direction:'prev'});
const rows=()=>({version:1,kind:'messages',operationId,databaseVersion:7,messages:[{message_id:'physical:2',client_message_id:'logical:2',chat_id:chatId,created_at:2,role:'user',encrypted_content:'cipher',rich:{retained:true}},{message_id:'physical:1',chat_id:chatId,created_at:1,role:'assistant'}],nextKey:null,rangeExhausted:true});
function read(s,p,r){begin(s,json(p),expected);complete(s,json(r));}
function first(){const s=create(),m=meta();read(s,metaPlan(),m);return {s,m,p:rowPlan(m)};}
test('four actual callbacks required; repeated full trees accept key reorder, retain extensions',()=>{const {s,m,p}=first(),r=rows();assert.equal(s.count,1);assert.equal(ready(s),false);assert.equal(fallback(s),false);read(s,p,r);read(s,metaPlan(),Object.fromEntries(Object.entries(m).reverse()));assert.equal(ready(s),false);read(s,p,r);assert.equal(s.count,4);assert.equal(ready(s),true);assert.equal(fallback(s),true);assert.equal(s.pending,false);assert.throws(()=>begin(s,json(metaPlan()),expected));assert.equal(ready(s),false);});
test('actual missing header permits fallback after one callback only, never local publication',()=>{const s=create();assert.equal(fallback(s),false);begin(s,json(metaPlan()),expected);assert.equal(fallback(s),false);complete(s,json(meta(true)));assert.equal(s.metadataMissing,true);assert.equal(s.count,1);assert.equal(fallback(s),true);assert.equal(ready(s),false);assert.throws(()=>begin(s,json(metaPlan()),expected));assert.equal(fallback(s),false);});
test('overlap/reorder/replay/error are terminal and keep pending',()=>{
 for(const action of [s=>{begin(s,json(metaPlan()),expected);begin(s,json(metaPlan()),expected);},s=>complete(s,json(meta())),s=>begin(s,json(rowPlan(meta())),expected),s=>begin(s,'{',expected)]){const s=create();assert.throws(()=>action(s));assert.equal(s.pending,true);assert.equal(ready(s),false);assert.throws(()=>begin(s,json(metaPlan()),expected));}
 const {s,m}=first();assert.throws(()=>complete(s,json(m)));assert.equal(s.pending,true);
});
test('plan identity, closed keys, actual metadata budget, bounds and exact repeats refuse drift',()=>{
 for(const patch of [{owner:chatId},{chatId:owner},{operationId:'bad'},{extra:true},{maxCheckpointRows:127},{maxPacketBytes:262143}])assert.throws(()=>begin(create(),json({...metaPlan(),...patch}),expected));
 for(const patch of [{maxPacketBytes:262144},{maxPayloadRows:21},{direction:'next'},{lower:{createdAt:1,messageId:'x',open:true}},{upper:{createdAt:2,messageId:null,open:true}},{operationId:owner}]){const {s,p}=first();assert.throws(()=>begin(s,json({...p,...patch}),expected));}
 const {s,m,p}=first();read(s,p,rows());assert.throws(()=>begin(s,json({...metaPlan(),maxPacketBytes:262143}),expected));assert.equal(s.pending,true);
});
test('closed reply envelope/version/typed arrays/absent checkpoints remain strict',()=>{
 for(const patch of [{extra:true},{databaseVersion:0},{databaseVersion:Number.MAX_SAFE_INTEGER+1},{operationId:owner},{messages:{}},{wrappers:[{}]},{boundary:{}},{chat_metadata:null,compression_checkpoints:[{id:'c',chat_id:chatId,created_at:1,compressed_up_to_timestamp:1,compressed_message_count:0}]}]){const s=create();begin(s,json(metaPlan()),expected);assert.throws(()=>complete(s,json({...meta(),...patch})));assert.equal(s.pending,true);assert.equal(s.count,0);assert.equal(fallback(s),false);}
 for(const patch of [{databaseVersion:8},{messages:['encoded row']},{rangeExhausted:false},{messages:[{message_id:'a',created_at:1,role:'user',encrypted_content:5}]}]){const {s,p}=first();begin(s,json(p),expected);assert.throws(()=>complete(s,json({...rows(),...patch})));assert.equal(s.pending,true);}
});
test('full metadata and message replay compare every nested field without normalization',()=>{
 for(const change of ['metadata','messages']){const {s,m,p}=first(),r=rows();read(s,p,r);if(change==='metadata'){m.chat_metadata.extension.exact.push('changed');begin(s,json(metaPlan()),expected);assert.throws(()=>complete(s,json(m)));}else{read(s,metaPlan(),m);r.messages[0].rich.retained=false;begin(s,json(p),expected);assert.throws(()=>complete(s,json(r)));}assert.equal(ready(s),false);assert.equal(fallback(s),false);assert.equal(s.pending,true);}
});
test('bounded message packet, order/aliases and open compression bound are checked',()=>{
 for(const mutate of [r=>r.messages.reverse(),r=>r.messages[1].message_id=r.messages[0].message_id,r=>r.messages[0].encrypted_content='x'.repeat(262144),r=>{r.nextKey={createdAt:3,messageId:'future'};r.rangeExhausted=false;}]){const {s,p}=first(),r=rows();mutate(r);begin(s,json(p),expected);assert.throws(()=>complete(s,json(r)));}
 const {s,p}=first();p.lower={createdAt:1,messageId:null,open:true};begin(s,json(p),expected);assert.throws(()=>complete(s,json(rows())));
});
test('keyless/empty nonmissing metadata is only a physical observation, not host key policy',()=>{const s=create(),m=meta();delete m.chat_metadata.encrypted_chat_key;m.chat_metadata.is_metadata_only=true;const p=rowPlan(m),r={...rows(),messages:[]};read(s,metaPlan(),m);assert.equal(fallback(s),false);read(s,p,r);read(s,metaPlan(),m);read(s,p,r);assert.equal(ready(s),true);assert.equal(fallback(s),true);});

test('canonical plan refuses duplicate keys and completed metadata accepts valid checkpoints without choosing policy',()=>{
 const duplicated=json(metaPlan()).replace('"version":1','"version":2,"version":1');assert.throws(()=>begin(create(),duplicated,expected));
 const s=create(),m=meta();m.compression_checkpoints=[{id:'checkpoint:one',chat_id:chatId,created_at:5,compressed_up_to_timestamp:1,compressed_message_count:1,covered_message_ids:['physical:1'],encrypted_summary:'opaque',extension:{exact:true}}];
 const p=rowPlan(m);p.lower={createdAt:1,messageId:null,open:true};const r=rows();r.messages.pop();read(s,metaPlan(),m);read(s,p,r);read(s,metaPlan(),m);read(s,p,r);assert.equal(ready(s),true);
});

// contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy,chats.persistence.client-encrypted
test('Rust float spelling budget is bounded independently of actual native wire aggregate',()=>{
 for(const delta of [-5,5]){const s=create(),m=meta();m.chat_metadata.extension.float=0.000001;const wire=json(m).replace('0.000001','1e-6');begin(s,json(metaPlan()),expected);complete(s,wire);const p=rowPlan(m);p.maxPacketBytes+=delta;const r=rows();read(s,p,r);read(s,metaPlan(),m);read(s,p,r);assert.equal(ready(s),true);}
 const s=create(),m=meta();m.chat_metadata.extension.padding='x'.repeat(150000);read(s,metaPlan(),m);const p=rowPlan(m);p.maxPacketBytes=262144-2048;begin(s,json(p),expected);const r=rows();r.messages[0].encrypted_content='x'.repeat(120000);assert.ok(Buffer.byteLength(json(r))<p.maxPacketBytes);assert.throws(()=>complete(s,json(r)));assert.equal(ready(s),false);assert.equal(s.pending,true);
});
