import assert from 'node:assert/strict';
import { test } from 'node:test';
import { executeOperation } from '../src/operations.js';
import { fakeDatabase } from './history-fake.js';

const owner = 'user_sha256:' + 'a'.repeat(64);
const now = new Date('2026-09-14T10:00:00Z');
const base = {protocol_version:1,workflow_id:'workflow-1',hashed_user_id:owner};
function db() { return fakeDatabase({workflows:[{id:'w',workflow_id:'workflow-1',hashed_user_id:owner}],workflow_runs:[
  {id:'r1',run_id:'run-1',workflow_id:'workflow-1',hashed_user_id:owner,status:'running'},
  {id:'r2',run_id:'run-2',workflow_id:'workflow-1',hashed_user_id:owner,status:'running'}]}); }
function reserve(run='run-1',delivery='delivery-1') { return {...base,action:'reserve',run_id:run,node_id:'send',delivery_id:delivery,destination_hash:'b'.repeat(64),candidates:[{index:0,fingerprint:'c'.repeat(64),only_new:true}],expires_at:Math.floor(now/1000)+1000}; }
const execute=(database,body)=>executeOperation(database,'delivery_history',JSON.parse(JSON.stringify(body)),now);

// contract-test: supporting surface=rest_api assertions=workflows.history.delivered-membership
test('concurrent result reservations are batched and destination-scoped; deletion forgets and fences late writes', async()=>{
  const database=db();
  const [a,b]=await Promise.all([execute(database,reserve()),execute(database,reserve('run-2','delivery-2'))]);
  assert.equal(a.selected_indexes.length+b.selected_indexes.length,1);
  assert.deepEqual(await execute(database,reserve()),a);
  const separate = await execute(database,{...reserve('run-2','delivery-3'),destination_hash:'d'.repeat(64)});
  assert.deepEqual(separate.selected_indexes,[0]);
  await execute(database,{...base,action:'delete_run',run_id:'run-1'});
  assert.equal(database.rows.workflow_runs.find(r=>r.run_id==='run-1').status,'deleted');
  assert.equal(database.rows.workflow_delivery_history.filter(r=>r.run_id==='run-1').length,0);
  await assert.rejects(execute(database,reserve()),/run_deleted/);
  const reopened=await execute(database,reserve('run-2','delivery-4'));
  assert.deepEqual(reopened.selected_indexes,[0]);
  await assert.rejects(execute(database,{...base,action:'save_run',run_id:'run-1',run:{run_id:'run-1',workflow_id:'workflow-1',hashed_user_id:owner,status:'completed'}}),/run_deleted/);
});

function pending() {return {delivery_id:'delivery-1',workflow_id:'workflow-1',run_id:'run-1',node_id:'send',hashed_user_id:'a'.repeat(64),chat_id:'chat-1',message_id:'message-1',encrypted_payload:'vault-ciphertext',status:'delivery_pending',revision:0,claim_generation:0,created_at:Math.floor(now/1000),expires_at:Math.floor(now/1000)+1000};}
// contract-test: supporting surface=rest_api assertions=workflows.chat-delivery.client-encrypted,workflows.history.delivery-reservations
test('client ciphertext transaction commits normal message before ACK and rolls back invalid selected embeds', async()=>{
  const database=db();
  await execute(database,reserve());
  let {delivery}=await execute(database,{...base,action:'save_delivery',run_id:'run-1',delivery:pending()});
  ({delivery}=await execute(database,{...base,action:'save_delivery',run_id:'run-1',delivery:{...delivery,id:undefined,status:'claimed',claim_generation:1,claim_token_hash:'token',claim_expires_at:Math.floor(now/1000)+60}}));
  const persisted={...delivery,id:undefined,client_persisted_at:Math.floor(now/1000),encrypted_chat_metadata:JSON.stringify({encrypted_title:'title-cipher',encrypted_category:'category-cipher',encrypted_chat_key:'wrapped-chat-key'}),encrypted_message:JSON.stringify({role:'assistant',encrypted_content:'message-cipher',embeds:[]})};
  // There is a selected result, so omitting its permanent embed must roll back.
  await assert.rejects(execute(database,{...base,action:'save_delivery',run_id:'run-1',delivery:persisted}),/selected_embeds_required/);
  assert.equal(database.rows.messages?.length || 0,0);
  assert.equal(database.rows.workflow_chat_deliveries[0].client_persisted_at,undefined);
  assert.equal(database.rows.workflow_delivery_history[0].status,'reserved');
  await assert.rejects(execute(database,{...base,action:'save_delivery',run_id:'run-1',delivery:{...delivery,id:undefined,status:'acknowledged'}}),/delivery_ack_not_persisted/);
  persisted.encrypted_message = JSON.stringify({role:'assistant',encrypted_content:'message-cipher',embeds:[{
    embed_id:'115f0a79-cd6d-53e4-a1da-3bd9d344a89e',encrypted_content:'embed-cipher',encrypted_type:'type-cipher',encrypted_text_preview:'preview-cipher',
    embed_keys:[{key_type:'master',encrypted_embed_key:'master-wrapped'},{key_type:'chat',encrypted_embed_key:'chat-wrapped'}]}]});
  ({delivery}=await execute(database,{...base,action:'save_delivery',run_id:'run-1',delivery:persisted}));
  assert.equal(database.rows.embeds[0].encrypted_content,'embed-cipher');
  assert.equal(database.rows.embed_keys.length,2);
  assert.equal(database.rows.workflow_delivery_history[0].status,'reserved');
  assert.equal(database.rows.messages[0].encrypted_content,'message-cipher');
  assert.equal(database.rows.chats[0].encrypted_chat_key,'wrapped-chat-key');
  assert.equal(database.rows.workflow_delivery_history[0].expires_at,null);
  const afterExpiry = await executeOperation(database,'delivery_history',{...reserve('run-2','delivery-later'),expires_at:Math.floor(now/1000)+4000},new Date(now.getTime()+2_000_000));
  assert.deepEqual(afterExpiry.selected_indexes,[]);
  assert.equal(database.rows.messages[0].content,undefined);
  const {delivery:acked}=await execute(database,{...base,action:'save_delivery',run_id:'run-1',delivery:{...delivery,id:undefined,status:'acknowledged',acknowledged_at:Math.floor(now/1000)}});
  assert.equal(acked.status,'acknowledged');
  assert.equal(database.rows.workflow_delivery_history[0].status,'delivered');
  await execute(database,{...base,action:'delete_run',run_id:'run-1'});
  assert.equal(database.rows.messages.length,1);
  await assert.rejects(execute(database,{...base,action:'save_delivery',run_id:'run-1',delivery:persisted}),/run_deleted/);
});

// contract-test: supporting surface=rest_api assertions=workflows.chat-delivery.key-recovery
test('existing chat requires its canonical owner-encrypted key wrapper and rejects before any durable mutation', async()=>{
  const database=db();
  database.rows.chats=[{id:'chat-1',hashed_user_id:'a'.repeat(64),encrypted_chat_key:'canonical-wrapper',messages_v:3}];
  let {delivery}=await execute(database,{...base,action:'save_delivery',run_id:'run-1',delivery:pending()});
  ({delivery}=await execute(database,{...base,action:'save_delivery',run_id:'run-1',delivery:{...delivery,id:undefined,status:'claimed',claim_generation:1,claim_token_hash:'token',claim_expires_at:Math.floor(now/1000)+60}}));
  const candidate={...delivery,id:undefined,client_persisted_at:Math.floor(now/1000),encrypted_chat_metadata:JSON.stringify({encrypted_title:'title-cipher',encrypted_category:'category-cipher',encrypted_chat_key:'wrong-wrapper'}),encrypted_message:JSON.stringify({role:'assistant',encrypted_content:'message-cipher',embeds:[]})};
  await assert.rejects(execute(database,{...base,action:'save_delivery',run_id:'run-1',delivery:candidate}),/chat_key_resync_required/);
  assert.equal(database.rows.messages?.length || 0,0);
  assert.equal(database.rows.chats[0].messages_v,3);
  assert.equal(database.rows.workflow_chat_deliveries[0].client_persisted_at,undefined);
});
