import { it, before, after } from 'node:test';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import assert from 'node:assert/strict';
import { runRecoveryBatch } from '../src/recoveryBatch.ts';
import { OpenMatesClient } from '../src/client.ts';

const previousStateDir = process.env.OPENMATES_STATE_DIR;
const stateDir = mkdtempSync(join(tmpdir(), 'cli-recovery-batch-'));
before(() => { process.env.OPENMATES_STATE_DIR = stateDir; });
after(() => {
  if (previousStateDir === undefined) delete process.env.OPENMATES_STATE_DIR; else process.env.OPENMATES_STATE_DIR = previousStateDir;
  rmSync(stateDir, { recursive: true, force: true });
});

const tick = () => new Promise<void>(resolve => setImmediate(resolve));
const gate = () => { let release!: () => void; const promise = new Promise<void>(resolve => { release = resolve; }); return { promise, release }; };

// contract-test: supporting surface=cli assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
it('bounds recovery to four, fences children and same-subject versions, and waits for durable completion', async () => {
  const rows = [{id:'child', parent:'parent'}, {id:'parent'}, ...Array.from({length:8},(_,i)=>({id:`root-${i}`}))];
  const gates = rows.map(gate), started: number[] = [], done = new Set<number>();
  let active=0, peak=0, settled=false;
  const pending=runRecoveryBatch(rows, async (row,index)=>{
    if(row.parent) assert.ok(done.has(rows.findIndex(item=>item.id===row.parent)));
    started.push(index); peak=Math.max(peak,++active);
    await gates[index].promise; active--; done.add(index); return row.id;
  }, (row,dependency)=>row.parent===dependency.id).then(result=>{settled=true;return result;});
  await tick(); assert.equal(started.length,4); assert.equal(started.includes(0),false); assert.equal(settled,false);
  gates[1].release(); await tick(); assert.ok(started.includes(0)); assert.equal(settled,false);
  for(const item of gates)item.release();
  assert.equal((await pending).length,rows.length); assert.equal(peak,4);
  const versions:number[]=[];
  await runRecoveryBatch([3,1,2],async version=>{versions.push(version);},(version,previous)=>previous<version);
  assert.deepEqual(versions,[1,2,3]);
});

// contract-test: supporting surface=cli assertions=storage.background.complete-sealed-recovery
it('drains started recovery workers on failure without starting queued work or returning readiness',async()=>{
  const blocked=gate(), started:number[]=[]; let settled=false;
  const pending=runRecoveryBatch([0,1,2,3,4,5],async value=>{
    started.push(value); if(value===0)throw Error('canonical verification failed'); await blocked.promise;
  });
  const outcome=pending.then(()=>{settled=true;return null;},error=>{settled=true;return error;});
  await tick(); assert.deepEqual(started,[0,1,2,3]); assert.equal(settled,false);
  blocked.release(); assert.match((await outcome).message,/canonical verification failed/); assert.deepEqual(started,[0,1,2,3]);
  await assert.rejects(runRecoveryBatch(['a','b'],async()=>{},()=>true),/dependency is cyclic/);
});

function clientFixture(){
  const client=Object.create(OpenMatesClient.prototype) as any;
  client.session={sessionId:'fixture',hashedEmail:'fixture',activeTeamId:null,apiUrl:'http://fixture.invalid',createdAt:1,masterKeyExportedB64:'fixture'};
  client.getMasterKeyBytes=()=>new Uint8Array(32);
  return client;
}

// contract-test: supporting surface=cli assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
it('streams independent heads concurrently while child storage waits for full parent receipts',{timeout:10_000},async()=>{
  const client=clientFixture(), frames:Array<{type:string,payload:any}>=[],waiters:Array<{type:string,predicate:(value:any)=>boolean,resolve:(value:any)=>void}>=[];
  const held=gate(), parentHistory=gate(), fourStores=gate(), diffStarted=gate(); let rootsInFlight=0,peak=0,parentStored=false,settled=false;
  const ws={waitForMessage:(type:string,predicate:(value:any)=>boolean)=>new Promise(resolve=>waiters.push({type,predicate,resolve})),
    sendAsync:async(type:string,payload:any)=>{
      frames.push({type,payload});
      if(type==='store_embed'){
        if(payload.parent_embed_id)assert.equal(parentStored,true,'parent wrappers must be durable before child starts');
        peak=Math.max(peak,++rootsInFlight); if(rootsInFlight===4)fourStores.release(); await held.promise; rootsInFlight--;
      }
      if(type==='store_embed_keys' && payload.keys[0].hashed_embed_id===createHash('sha256').update('parallel-root-0').digest('hex')) parentStored=true;
      if(type==='store_embed_diff'){diffStarted.release();await parentHistory.promise;}
      const responseType=type==='store_embed'?'store_embed_confirmed':type==='store_embed_diff'?'store_embed_diff_confirmed':'store_embed_keys_confirmed';
      const response={...payload,created_count:2,failed_count:0,...(type==='store_embed_diff'?{canonical_source:'version_row',
        canonical_digest:createHash('sha256').update(JSON.stringify([payload.encrypted_snapshot??null,payload.encrypted_patch??null])).digest('hex')}: {})};
      const i=waiters.findIndex(item=>item.type===responseType&&item.predicate(response));assert.ok(i>=0);
      waiters.splice(i,1)[0].resolve({payload:response});
    }};
  const roots=Array.from({length:8},(_,i)=>({embed_id:`parallel-root-${i}`,type:'code',content:'synthetic',status:'finished',
    ...(i===0?{version_history_rows:[{embed_id:'parallel-root-0',version_number:2,snapshot:'synthetic',created_at:1}]}:{})}));
  const pending=client.persistStreamedEmbeds({ws,embeds:[{embed_id:'child',parent_embed_id:roots[0].embed_id,type:'code',content:'child'},...roots],
    chatId:'chat',chatKeyBytes:new Uint8Array(32),fallbackMessageId:'message',ownerId:'owner'}).then(()=>{settled=true;});
  await fourStores.promise;
  assert.equal(frames.filter(frame=>frame.type==='store_embed').length,4);assert.equal(settled,false);
  assert.equal(frames.some(frame=>frame.payload.embed_id==='child'),false);
  held.release();
  await diffStarted.promise;
  assert.ok(frames.some(frame=>frame.type==='store_embed_diff'));
  assert.equal(frames.some(frame=>frame.payload.embed_id==='child'),false,'child waits for parent historical receipt too');
  parentHistory.release();await pending;assert.equal(peak,4);assert.equal(frames.filter(frame=>frame.type==='store_embed').length,9);
});

for(const change of ['account','team','key'] as const){
  // contract-test: supporting surface=cli assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it(`rejects a changed recovery ${change} after an async receipt without storing wrappers`,async()=>{
    const client=clientFixture();let wrappers=0;
    const ws={waitForMessage:async(_type:string)=>{
      await tick();
      if(change==='account')client.session={...client.session,hashedEmail:'other'};
      if(change==='team')client.session.activeTeamId='other';
      if(change==='key')client.getMasterKeyBytes=()=>new Uint8Array(32).fill(1);
      return {payload:{}};
    },sendAsync:async(type:string)=>{if(type==='store_embed_keys')wrappers++;}};
    await assert.rejects(client.persistStreamedEmbeds({ws,embeds:[{embed_id:'root',type:'code',content:'synthetic'}],chatId:'chat',
      chatKeyBytes:new Uint8Array(32),fallbackMessageId:'message',ownerId:'owner'}),/Recovery account, Team or key changed/);
    assert.equal(wrappers,0);
  });
}

import { readFileSync } from 'node:fs';
import { createHash, randomUUID } from 'node:crypto';
import { deriveEmbedKeyFromChatKey, encryptBytesWithAesGcm, encryptWithAesGcmCombined, sealRecoveryOutputEnvelopeForTest } from '../src/crypto.ts';

// contract-test: supporting surface=cli assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
it('verifies sealed outputs with four canonical readers and never ACKs before the final reread',{timeout:10_000},async()=>{
  const vector=JSON.parse(readFileSync(new URL('../../../../backend/tests/fixtures/chat_completion_recovery_vectors.json',import.meta.url),'utf8')).vectors[0];
  const identity=JSON.parse(readFileSync(new URL('../../../../backend/tests/fixtures/chat_recovery_output_v2.json',import.meta.url),'utf8')).identity;
  const rawKey=new Uint8Array(Buffer.from(vector.chat_key,'base64url')),master=new Uint8Array(32),client=clientFixture();
  client.getChatWrappingKey=async()=>master;client.resolveChatKey=async()=>rawKey;client.getCliRequestHeaders=()=>({});
  const hash=(value:string)=>createHash('sha256').update(value).digest('hex');
  const records=new Map<string,any>(),bySubject=new Map<string,any>();
  for(let i=0;i<8;i++){
    const output={record_id:randomUUID(),root_chat_id:identity.root_chat_id,target_chat_id:identity.target_chat_id,turn_id:identity.turn_id,
      subject_id:randomUUID(),output_kind:'embed',output_version:1,chat_key_version:identity.key_version};
    const content={embed_id:output.subject_id,content:'synthetic source',type:'code',message_id:randomUUID(),version_number:1};
    const key=await deriveEmbedKeyFromChatKey(rawKey,output.subject_id);
    const sealed=await sealRecoveryOutputEnvelopeForTest(new TextEncoder().encode(JSON.stringify({...output,content})),{
      ownerId:identity.owner_id,rootChatId:output.root_chat_id,targetChatId:output.target_chat_id,turnId:output.turn_id,
      recordId:output.record_id,subjectId:output.subject_id,outputKind:'embed',outputVersion:1,keyVersion:output.chat_key_version,
      recoveryPublicKey:vector.recovery_public_key,ephemeralPrivateKey:vector.ephemeral_private_key,nonce:vector.nonce});
    const embed={hashed_chat_id:hash(output.target_chat_id),hashed_message_id:hash(content.message_id),version_number:1,
      encrypted_content:await encryptWithAesGcmCombined(content.content,key),encrypted_type:await encryptWithAesGcmCombined('code',key)};
    const embed_keys=await Promise.all(['master','chat'].map(async key_type=>({key_type,hashed_embed_id:hash(output.subject_id),
      hashed_chat_id:key_type==='chat'?hash(output.target_chat_id):null,encrypted_embed_key:await encryptBytesWithAesGcm(key,key_type==='master'?master:rawKey)})));
    const record={output,sealed,embed,embed_keys,reads:0};records.set(output.record_id,record);bySubject.set(output.subject_id,record);
  }
  const blocked=gate(), ackBlocked=gate(), fourReaders=gate(), fourAcks=gate();let active=0,peak=0,acks=0,settled=false;
  client.http={post:async(path:string,body:{embed_ids:string[]})=>{
    assert.equal(path,`/v1/embeds/chats/${identity.target_chat_id}/references/availability`);
    assert.equal(body.embed_ids.length,1);
    assert.ok(bySubject.has(body.embed_ids[0]));
    return {ok:true,status:200,data:{results:body.embed_ids.map(embed_id=>({embed_id,state:'ready'}))}};
  },get:async(path:string)=>{
    const record=bySubject.get(path.split('/').at(-1));assert.ok(record);
    peak=Math.max(peak,++active);if(active===4)fourReaders.release();await blocked.promise;active--;record.reads++;
    return {ok:true,status:200,data:{embed:record.embed,embed_keys:record.embed_keys}};
  }};
  const waiters:Array<{type:string,predicate:(value:any)=>boolean,resolve:(value:any)=>void}>=[];
  const ws={waitForMessage:(type:string,predicate:(value:any)=>boolean)=>new Promise(resolve=>waiters.push({type,predicate,resolve})),
    sendAsync:async(type:string,payload:any)=>{
      const record=records.get(payload.record_id);assert.ok(record);
      if(type==='recovery_output_ack_embed'){
        assert.ok(record.reads>=2,'ACK requires canonical-before and final canonical rereads');
        assert.equal(payload.canonical_digest,hash(record.embed.encrypted_content));acks++;if(acks===4)fourAcks.release();await ackBlocked.promise;
      }else assert.equal(type,'recovery_output_get','verified existing heads must not be rewritten');
      const responseType=type==='recovery_output_get'?'recovery_output_ready':'recovery_output_embed_acknowledged';
      const response={...record.output,request_id:payload.request_id,...(type==='recovery_output_get'
        ?{sealed_payload:JSON.stringify(record.sealed),messages_v:1,encrypted_chat_key:'wrapped'}:{state:'ACKNOWLEDGED'})};
      const i=waiters.findIndex(item=>item.type===responseType&&item.predicate(response));assert.ok(i>=0);waiters.splice(i,1)[0].resolve({payload:response});
    }};
  const cache={chats:[{details:{id:identity.root_chat_id},messages:[]}],chatKeyWrappers:[]};
  const pending=client.persistAvailableRecoveryOutputs(ws,identity.owner_id,cache,[...records.values()].map(record=>record.output),null).then((value:number)=>{settled=true;return value;});
  await fourReaders.promise;
  assert.equal(active,4);assert.equal(acks,0);assert.equal(settled,false);
  blocked.release();
  await fourAcks.promise;
  assert.equal(acks,4);assert.equal(settled,false,"batch readiness also waits for durable ACK receipts");
  ackBlocked.release();assert.equal(await pending,8);assert.equal(acks,8);assert.equal(peak,4);
});
