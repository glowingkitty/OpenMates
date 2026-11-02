// contract-test-file: tooling
// Pure byte/framing budget cases only. NO native receipt, IDB, Worker or crypto proof.
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),ts=require('typescript');
const source=process.env.OPENMATES_PRODUCTION_RUST_CORE_ROOT||path.resolve(__dirname,'..');
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'openmates-original-draft-budget-'));
for(const name of ['originalPhysicalDraftIOBudget','savedReadProtocol'])fs.writeFileSync(path.join(dir,name+'.js'),ts.transpileModule(fs.readFileSync(path.join(source,name+'.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText);
process.on('exit',()=>fs.rmSync(dir,{recursive:true,force:true}));
const {boundedOriginalPhysicalDraft:packetBound,boundedOriginalPhysicalDraftHeader:headerBound}=require(path.join(dir,'originalPhysicalDraftIOBudget.js'));const bound=value=>value&&typeof value==='object'&&typeof Object.getOwnPropertyDescriptor(value,'chat_id')?.value==='string'?headerBound(value):packetBound(value);const {boundedJson}=require(path.join(dir,'savedReadProtocol.js'));
const row=()=>({chat_id:'11111111-1111-4111-8111-111111111111',encrypted_draft_md:'A'.repeat(1_400_000),encrypted_draft_preview:null,draft_v:7,unknown_local:{retain:true}});
test('large original ciphertext header fits distinct bound and ordinary metadata stays 256KiB',()=>{const header=row(),encoded=JSON.stringify(header);assert.equal(boundedJson(header),false);assert.equal(bound(header),true);assert.equal(JSON.stringify(header),encoded);assert.equal(header.unknown_local.retain,true)});
test('full original before and after header is preserved within distinct4MiB packet',()=>{const header=row(),packet={before:header,record:{...header,title_v:2}};const encoded=JSON.stringify(packet);assert.ok(Buffer.byteLength(encoded)>2*1024*1024);assert.equal(bound(packet),true);assert.equal(JSON.stringify(packet),encoded)});
test('ordinary metadata and message fields do not inherit a larger draft budget',()=>{assert.equal(bound({chat_id:'owned',encrypted_title:'A'.repeat(300000)}),false);assert.equal(bound({rows:[{encrypted_content:'A'.repeat(300000)}]}),false)});
test('each complete physical header remains bounded2MiB including both ciphertexts',()=>{const header=row();header.encrypted_draft_preview='B'.repeat(1_400_000);assert.equal(bound(header),false)});
test('aggregate full header packet cannot exceed distinct4MiB',()=>{const header=row();assert.equal(bound({metadata:header,record:header,before:header}),false)});
test('ciphertext-shaped arbitrary nested data cannot bypass normal bound without header shape',()=>{assert.equal(bound({encrypted_draft_md:'A'.repeat(300000)}),false);assert.equal(bound({chat_id:'owned',other:'A'.repeat(300000)}),false)});
test('accessors are refused without executing caller code',()=>{let calls=0;const header=row();Object.defineProperty(header,'encrypted_draft_md',{enumerable:true,get(){calls++;return'A'}});assert.equal(bound(header),false);assert.equal(calls,0)});
test('depth nodes sparse arrays and invalid primitives retain normal framing restrictions',()=>{assert.equal(bound(new Array(3)),false);assert.equal(bound({n:NaN}),false);assert.equal(bound({bad:()=>0}),false);assert.equal(bound(Array(17000).fill(0)),false);let value=0;for(let i=0;i<34;i++)value={x:value};assert.equal(bound(value),false)});

test('normal UTF8 and escaped JSON metadata budget stays256KiB inside draft compatibility packet',()=>{assert.equal(bound({...row(),unowned:'界'.repeat(100000)}),false);assert.equal(bound({...row(),unowned:'\u0000'.repeat(60000)}),false)});

test('message-row ciphertext-shaped extension cannot borrow the original header draft budget',()=>{assert.equal(packetBound({metadata:row(),rows:[{chat_id:'owned',message_id:'message',encrypted_draft_md:'A'.repeat(300000)}]}),false);assert.equal(packetBound({nested:{chat_id:'owned',encrypted_draft_md:'A'.repeat(300000)}}),false)});
