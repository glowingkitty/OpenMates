import assert from 'node:assert/strict';
import { test } from 'node:test';
import { executeOperation } from '../src/operations.js';
import { fakeDatabase } from './history-fake.js';
const owner='user_sha256:'+'a'.repeat(64), now=new Date('2026-10-01T00:00:00Z');
const base={protocol_version:1,workflow_id:'w',hashed_user_id:owner,run_id:'run',version_id:'v'};
const execute=(db,body)=>executeOperation(db,'website_changes',structuredClone({...base,...body}),now);
function database() { return fakeDatabase({workflows:[{id:'w',workflow_id:'w',hashed_user_id:owner,current_version_id:'v'}],workflow_runs:[{id:'r',run_id:'run',workflow_id:'w',hashed_user_id:owner,status:'running',version_id:'v'}]}); }
function commit(revision=0) {
 const snapshot={id:'source',source_id:'source',workflow_id:'w',hashed_user_id:owner,origin_run_id:'run',generation:'b'.repeat(64),created_at:1,observed_at:1000+revision,kind:'snapshot',consumer_key:'',revision:revision+1,encrypted_ref:`vault://workflows/website_state/s${revision}`};
 const event={...snapshot,id:`event${revision}`,kind:'event',consumer_key:'c'.repeat(64),revision:1,encrypted_ref:`vault://workflows/website_state/e${revision}`};
 return {action:'commit',source_id:'source',expected_revision:revision,remove_ids:[],rows:[snapshot,event],blobs:[snapshot,event].map(r=>({ref:r.encrypted_ref,kind:'website_state',hashed_user_id:owner,ciphertext:'vault:ciphertext',checksum:'opaque',created_at:1}))};
}
// contract-test: supporting surface=rest_api assertions=workflows.website-change.lifecycle,workflows.website-change.retry
test('baseline and occurrences commit atomically; overlapping revisions, stale versions and wrong owners are fenced',async()=>{
 const db=database();
 const results=await Promise.all([execute(db,commit()),execute(db,commit())]);
 assert.equal(results.filter(r=>r.committed).length,1);
 assert.equal(results.filter(r=>r.conflict).length,1);
 assert.equal(db.rows.workflow_website_state.length,2);
 assert.equal(db.rows.workflow_encrypted_blobs.length,2);
 const stale=commit(1);stale.rows[0].observed_at=999;
 await assert.rejects(execute(db,stale),/website_stale_read/);
 assert.equal(db.rows.workflow_website_state[0].revision,1);
 const invalid=commit(1);invalid.blobs[1].hashed_user_id='other';
 await assert.rejects(execute(db,invalid),/invalid_blob/);
 assert.equal(db.rows.workflow_website_state[0].revision,1);
 assert.equal(db.rows.workflow_encrypted_blobs.length,2);
 await assert.rejects(execute(db,{action:'read',source_id:'source',hashed_user_id:'other'}),/workflow_not_found/);
 await assert.rejects(execute(db,{action:'read',source_id:'source',version_id:'old'}),/workflow_version_changed/);
 await executeOperation(db,'delivery_history',{protocol_version:1,workflow_id:'w',hashed_user_id:owner,run_id:'run',action:'delete_run'},now);
 assert.equal(db.rows.workflow_website_state.length,0);
 await assert.rejects(execute(db,commit(1)),/run_not_writable/);
});
// contract-test: supporting surface=rest_api assertions=workflows.website-change.retry
test('one run evaluates an occurrence; expired leases recover and fence the former evaluator',async()=>{
 const db=database();await execute(db,commit());
 db.rows.workflow_runs.push({id:'r2',run_id:'other',workflow_id:'w',hashed_user_id:owner,status:'running',version_id:'v'});
 assert.equal((await execute(db,{action:'claim_event',event_id:'event0'})).claimed,true);
 assert.equal((await execute(db,{action:'claim_event',event_id:'event0',run_id:'other'})).claimed,false);
 const later=new Date(now.getTime()+301000);
 assert.equal((await executeOperation(db,'website_changes',{...base,action:'claim_event',event_id:'event0',run_id:'other'},later)).claimed,true);
 assert.equal((await execute(db,{action:'update_event',event_id:'event0',expected_revision:1,blob:null})).conflict,true);
 await assert.rejects(executeOperation(db,'delivery_history',{protocol_version:1,workflow_id:'w',hashed_user_id:owner,run_id:'run',action:'reserve',node_id:'send',delivery_id:'d',destination_hash:'d'.repeat(64),expires_at:Math.floor(later/1000)+1000,candidates:[{index:0,fingerprint:'e'.repeat(64),only_new:true,membership_kind:'website_change',change_id:'event0'}]},later),/website_event_lease_lost/);
 assert.equal((await executeOperation(db,'website_changes',{...base,action:'update_event',event_id:'event0',expected_revision:1,blob:null,run_id:'other'},later)).updated,true);
});
// contract-test: supporting surface=rest_api assertions=workflows.website-change.retry,workflows.chat-delivery.client-encrypted
test('website occurrence membership acknowledges a text-only message without weakening result embed checks',async()=>{
 const db=database();await execute(db,commit());
 const tx=body=>executeOperation(db,'delivery_history',{protocol_version:1,workflow_id:'w',hashed_user_id:owner,run_id:'run',...body},now);
 await tx({action:'reserve',node_id:'send',delivery_id:'d',destination_hash:'d'.repeat(64),candidates:[{index:0,fingerprint:'e'.repeat(64),only_new:true,membership_kind:'website_change',change_id:'event0'}],expires_at:Math.floor(now/1000)+1000});
 let {delivery}=await tx({action:'save_delivery',delivery:{delivery_id:'d',hashed_user_id:'a'.repeat(64),workflow_id:'w',run_id:'run',node_id:'send',chat_id:'chat',message_id:'message',encrypted_payload:'vault:cipher',status:'delivery_pending',revision:0,claim_generation:0,created_at:Math.floor(now/1000),expires_at:Math.floor(now/1000)+1000}});
 const clean=d=>{const {id,...row}=d;return row;};
 ({delivery}=await tx({action:'save_delivery',delivery:{...clean(delivery),status:'claimed',claim_generation:1,claim_token_hash:'token',claim_expires_at:Math.floor(now/1000)+60}}));
 ({delivery}=await tx({action:'save_delivery',delivery:{...clean(delivery),client_persisted_at:Math.floor(now/1000),encrypted_chat_metadata:JSON.stringify({encrypted_title:'title',encrypted_category:'category',encrypted_chat_key:'wrapped'}),encrypted_message:JSON.stringify({role:'assistant',encrypted_content:'ciphertext',embeds:[]})}}));
 assert.equal(db.rows.messages.length,1);
 assert.equal(db.rows.workflow_delivery_history[0].status,'reserved');
 await tx({action:'save_delivery',delivery:{...clean(delivery),status:'acknowledged',acknowledged_at:Math.floor(now/1000)}});
 assert.equal(db.rows.workflow_delivery_history[0].status,'delivered');
});
// contract-test: supporting surface=rest_api assertions=workflows.website-change.lifecycle
test('definition edits immediately fence unpersisted website delivery and current reads release it for retry',async()=>{
 const db=database();await execute(db,commit());
 const tx=body=>executeOperation(db,'delivery_history',{protocol_version:1,workflow_id:'w',hashed_user_id:owner,run_id:'run',...body},now);
 await tx({action:'reserve',node_id:'send',delivery_id:'d',destination_hash:'d'.repeat(64),candidates:[{index:0,fingerprint:'e'.repeat(64),only_new:true,membership_kind:'website_change',change_id:'event0'}],expires_at:Math.floor(now/1000)+1000});
 const row={delivery_id:'d',hashed_user_id:'a'.repeat(64),workflow_id:'w',run_id:'run',node_id:'send',chat_id:'chat',message_id:'message',encrypted_payload:'vault:cipher',status:'delivery_pending',revision:0,claim_generation:0,created_at:Math.floor(now/1000),expires_at:Math.floor(now/1000)+1000};
 const {delivery}=await tx({action:'save_delivery',delivery:row});
 db.rows.workflows[0].current_version_id='new';
 const {id,...saved}=delivery;
 await assert.rejects(tx({action:'save_delivery',delivery:{...saved,status:'claimed',claim_generation:1,claim_token_hash:'token',claim_expires_at:Math.floor(now/1000)+60}}),/website_version_changed/);
 db.rows.workflow_runs.push({id:'next',run_id:'new-run',workflow_id:'w',hashed_user_id:owner,status:'running',version_id:'new'});
 const read=await execute(db,{action:'read',source_id:'source',run_id:'new-run',version_id:'new'});
 assert.equal(read.events.length,1);
 assert.equal(read.memberships.length,0);
 assert.equal(db.rows.workflow_chat_deliveries[0].status,'cancelled');
});
