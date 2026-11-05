// contract-test-file: tooling
// Actual Page endpoint and actual readonly inventory adapter. DECLARED inert
// native-event/IDB/port realms only; no actual browser/Rust/port/durability proof.
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const base=require('./helpers/recoveryPortInertRealm.cjs');
const source=fs.readFileSync(path.join(__dirname,'browserDraftInventoryIO.test.cjs'),'utf8');
// Reuse the exact frozen producer's inert platform harness, without registering
// its tests. Only expose its fixture ports to join the two DECLARED test realms.
const end=source.indexOf("test('actual adapter pages");assert.ok(end>0);
const prefix=source.slice(0,end).replace('owned.add(ports);','owned.add(ports);env.fixturePorts=ports;')+'\nmodule.exports={fixture,rows};';
const m={exports:{}};vm.runInNewContext('(function(module,exports,require,__dirname){'+prefix+'\n})',{TextEncoder,AbortController,queueMicrotask,setImmediate})(m,m.exports,require,__dirname);
function inventory(f,rows=m.exports.rows(2),options={}){const env=m.exports.fixture(rows,options);base.inventoryFixtures.set(env.fixturePorts,{root:f.root,factory:f.factory,create:current=>env.create(current)});return env;}
const request=(f,sequence,operationId=base.OP,patch={})=>f.send({version:1,domain:'draft_inventory',contextId:f.contextId,sequence,operationId,effect:{version:1,kind:'read_original_draft_inventory_page',operationId,page:1,after:null,maxRows:20,maxBytes:2097152,...patch}});
const result=(f,id)=>f.worker.wire.find(v=>v?.sequence===id&&v?.domain==='draft_inventory'&&v.result);
test('only genuine fixture ports for SAME original Root/factory bind; no caller copy/foreign ports',async()=>{
 const f=base.setup();await base.tick();const env=inventory(f);assert.throws(()=>f.bootstrap.bindInventoryPorts({...env.fixturePorts}),/invalidated_snapshot/);
 const foreign=base.setup();await base.tick();assert.throws(()=>foreign.bootstrap.bindInventoryPorts(env.fixturePorts),/invalidated_snapshot/);
 f.bootstrap.bindInventoryPorts(env.fixturePorts);await base.tick();assert.equal(f.worker.wire.filter(v=>v?.domain==='draft_inventory'&&v.ready).length,1);f.bootstrap.bindInventoryPorts(env.fixturePorts);await base.tick();assert.equal(f.worker.wire.filter(v=>v?.domain==='draft_inventory'&&v.ready).length,1);await base.closeFixture(f);await base.closeFixture(foreign);
});
test('native-shaped inventory Page DATA waits actual readonly terminal and excludes plaintext and checkpoint record',async()=>{
 const f=base.setup();await base.tick();const env=inventory(f,undefined,{holdTerminals:true});f.bootstrap.bindInventoryPorts(env.fixturePorts);request(f,1);await base.tick();assert.equal(env.transactions.length,1);assert.equal(result(f,1),undefined);
 env.release();await base.tick();const reply=result(f,1);assert.equal(reply.result.ok,true);assert.equal('record'in reply.result,false);const page=JSON.parse(reply.result.packet);assert.equal(page.rows.length,2);assert.equal(page.cursorExhausted,true);assert.equal(reply.result.packet.includes('MUST_NOT_RETURN'),false);await base.closeFixture(f);
});
test('inventory refusal retires only B; original checkpoint write can still complete under SAME Root',async()=>{
 const f=base.setup();await base.tick();base.request(f);await base.tick();const io=f.open();f.all(io.tx);
 const rows=m.exports.rows(1);rows[0].encrypted_draft_md='c'.repeat(2*1024*1024);const env=inventory(f,rows);f.bootstrap.bindInventoryPorts(env.fixturePorts);request(f,2);await base.tick();assert.equal(result(f,2).result.ok,false);assert.equal(f.worker.wire.some(v=>v?.revoked),false);assert.equal(base.transactions.get(io.tx).abortRequested,0);
 io.tx.complete();await base.tick();assert.equal(f.worker.wire.find(v=>v?.sequence===1&&v.result).result.ok,true);await base.closeFixture(f);
});
test('inventory cancel drains only exact original readonly tx; stale A cannot cancel newer B',async()=>{
 const f=base.setup();await base.tick();const env=inventory(f,undefined,{holdTerminals:true});f.bootstrap.bindInventoryPorts(env.fixturePorts);request(f,1);await base.tick();
 f.send({version:1,contextId:f.contextId,sequence:1,operationId:base.OP,cancel:true});await base.tick();assert.equal(result(f,1),undefined);env.release();await base.tick();assert.equal(result(f,1).result.ok,false);
 env.holdTerminals=true;const bid='44444444-4444-4444-8444-444444444444';request(f,2,bid);await base.tick();f.send({version:1,contextId:f.contextId,sequence:1,operationId:base.OP,cancel:true});await base.tick();assert.equal(result(f,2),undefined);env.release();await base.tick();assert.equal(result(f,2).result.ok,true);await base.closeFixture(f);
});
test('close waits BOTH actual checkpoint and inventory terminals; no early private closed frame',async()=>{
 const f=base.setup();await base.tick();base.request(f);await base.tick();const io=f.open();f.all(io.tx);const env=inventory(f,undefined,{holdTerminals:true});f.bootstrap.bindInventoryPorts(env.fixturePorts);request(f,2);await base.tick();let ended=false;
 const closing=f.bootstrap.closeAndDrain().then(()=>{ended=true});f.send({version:1,contextId:f.contextId,close:true});await base.tick();assert.equal(ended,false);io.tx.abortTerminal();await base.tick();assert.equal(ended,false);assert.equal(f.worker.wire.some(v=>v?.closed),false);env.release();await closing;assert.equal(result(f,2).result.ok,false);assert.equal(f.worker.wire.at(-1).closed,true);
});
test('closed native row reread stays readonly and cannot become checkpoint/absence/whole-hint proof',async()=>{
 const f=base.setup();await base.tick();const env=inventory(f);f.bootstrap.bindInventoryPorts(env.fixturePorts);const id=m.exports.rows(1)[0].chat_id;
 f.send({version:1,domain:'draft_inventory',contextId:f.contextId,sequence:1,operationId:base.OP,effect:{version:1,kind:'reread_original_draft_inventory_row',operationId:base.OP,page:1,chatId:id}});await base.tick();const reply=result(f,1);assert.equal(reply.result.ok,true);const row=JSON.parse(reply.result.packet);assert.equal(row.row.chat_id,id);assert.equal('rows'in row,false);assert.equal('record'in reply.result,false);assert.equal(reply.result.packet.includes('MUST_NOT_RETURN'),false);await base.closeFixture(f);
});
