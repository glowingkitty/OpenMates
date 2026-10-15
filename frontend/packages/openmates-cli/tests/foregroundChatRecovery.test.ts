/** Foreground sends must retain scoped privacy/durability without account replay. */
import { after, beforeEach, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const originalState = process.env.OPENMATES_STATE_DIR;
const state = mkdtempSync(join(tmpdir(), 'openmates-foreground-history-'));
process.env.OPENMATES_STATE_DIR = state;
const { OpenMatesClient } = await import('../src/client.ts');
const { encryptBytesWithAesGcm, encryptWithAesGcmCombined } = await import('../src/crypto.ts');
const { saveSyncCache, loadSyncCache } = await import('../src/storage.ts');
const chatId = '22222222-2222-4222-8222-222222222222';
const unrelatedId = '33333333-3333-4333-8333-333333333333';

beforeEach(() => {
  rmSync(join(state, 'sync_cache.json'), {force:true});
  writeFileSync(join(state, 'session.json'), JSON.stringify({
    apiUrl:'https://api.dev.openmates.org',sessionId:'fake-session',wsToken:'fake-token',
    cookies:{auth_refresh_token:'fake-refresh'},masterKeyExportedB64:Buffer.alloc(32).toString('base64'),
    emailEncryptionKeyB64:Buffer.alloc(32).toString('base64'),hashedEmail:'fake-owner',userEmailSalt:'fake-salt',
    masterKeyStorage:'plaintext',emailEncryptionKeyStorage:'plaintext',createdAt:1710000000000,
  }), {mode:0o600});
});
after(() => {
  if (originalState === undefined) delete process.env.OPENMATES_STATE_DIR;
  else process.env.OPENMATES_STATE_DIR = originalState;
  rmSync(state, {recursive:true,force:true});
});

describe('foreground chat recovery', () => {
  // contract-test: supporting surface=cli assertions=chats.completion.independent-metadata,storage.background.complete-sealed-recovery
  it('awaits active-chat outputs and leaves unrelated outputs pending', async () => {
    const client = OpenMatesClient.load();
    const active = {record_id:'active',root_chat_id:chatId,target_chat_id:chatId};
    const child = {record_id:'child',root_chat_id:unrelatedId,target_chat_id:chatId};
    const unrelated = {record_id:'unrelated',root_chat_id:unrelatedId,target_chat_id:unrelatedId};
    const calls: unknown[] = [];
    (client as any).replayRecoveryOutputPages = async (...args: unknown[]) => {
      calls.push(args[2]);
      assert.deepEqual(args[2], [[active,child]]);
    };
    await (client as any).replayCurrentTurnRecoveryOutputPages({},'owner',[[active,unrelated,child]],
      {chats:[],embeds:[],embedKeys:[]},null,chatId);
    assert.equal(calls.length,1);
  });

  // contract-test: supporting surface=cli assertions=storage.background.complete-sealed-recovery
  it('does not hide a required current-chat replay failure', async () => {
    const client = OpenMatesClient.load();
    (client as any).replayRecoveryOutputPages = async () => {throw new Error('required ACK failed');};
    await assert.rejects((client as any).replayCurrentTurnRecoveryOutputPages({},'owner',[[
      {record_id:'active',root_chat_id:chatId,target_chat_id:chatId},
    ]],{chats:[],embeds:[],embedKeys:[]},null,chatId),/required ACK failed/);
  });

  // contract-test: supporting surface=cli assertions=message-input.privacy-context,storage.background.complete-sealed-recovery
  for (const staleTarget of [false,true]) it(`reads fresh current-chat ciphertext and PII mappings without account sync (stale target: ${staleTarget})`, async () => {
    const client = OpenMatesClient.load();
    const key = new Uint8Array(32).fill(8);
    const encryptedKey = await encryptBytesWithAesGcm(key,new Uint8Array(32));
    const mappings = [{placeholder:'[PERSON_1]',original:'Private test name',type:'PERSON'}];
    const content = await encryptWithAesGcmCombined('Hello [PERSON_1]',key);
    const pii = await encryptWithAesGcmCombined(JSON.stringify(mappings),key);
    const staleKey = await encryptBytesWithAesGcm(new Uint8Array(32).fill(2),new Uint8Array(32));
    const oldTarget = {details:{id:chatId,messages_v:1,encrypted_chat_key:staleKey},messages:[]};
    saveSyncCache({syncedAt:0,totalChatCount:1,loadedChatCount:1,chats:[{
      details:{id:unrelatedId,messages_v:1},messages:['unrelated ciphertext'],
    },...(staleTarget ? [oldTarget] : [])],embeds:[],embedKeys:[]},null);
    const wrappers = [{id:'fresh-wrapper',encrypted_key:'synthetic cipher'}];
    const requests: unknown[] = [];
    (client as any).ensureSynced = async () => {throw new Error('account sync entered Send');};
    (client as any).http.post = async (url: string, body: unknown) => {
      requests.push({url,body});
      return {ok:true,data:{chats:[{id:chatId,encrypted_chat_key:encryptedKey,messages_v:2,chat_key_wrappers:wrappers}]}};
    };
    (client as any).http.get = async (url: string) => {
      requests.push({url});
      assert.ok(url.startsWith(`/v1/chats/${chatId}/messages/window?`));
      return {ok:true,data:{messages:[JSON.stringify({message_id:'message-1',role:'user',chat_id:chatId,
        encrypted_content:content,encrypted_pii_mappings:pii,created_at:1780000000})],has_more_before:false}};
    };
    const result = await client.getChatMessages(chatId,{personal:true,freshChatOnly:true});
    assert.equal(result.messages[0]?.content,'Hello [PERSON_1]');
    assert.deepEqual(result.messages[0]?.piiMappings,mappings);
    assert.deepEqual(requests[0],{url:'/v1/chats/metadata/batch',body:{chat_ids:[chatId]}});
    assert.equal(requests.length,2);
    const handoff = (client as any).scopedChatHistory.get(result);
    assert.equal(handoff.chats.find((chat: any) => chat.details.id === chatId).details.messages_v,2);
    assert.equal(handoff.chats.find((chat: any) => chat.details.id === chatId).details.encrypted_chat_key,encryptedKey);
    assert.deepEqual(handoff.chatKeyWrappers,wrappers);
    assert.ok(loadSyncCache(null)?.chats.some(chat => chat.details.id === unrelatedId));
    if (staleTarget) assert.equal(loadSyncCache(null)?.chats.find(chat => chat.details.id === chatId)?.details.messages_v,1);
    assert.equal(JSON.stringify(requests).includes('Private test name'),false);
    assert.equal(readFileSync(join(state,'sync_cache.json'),'utf8').includes('Private test name'),false);
  });

  // contract-test: supporting surface=cli assertions=auth.session.isolation,message-input.privacy-context
  it('rejects denied metadata without falling back to cached or account history', async () => {
    const client = OpenMatesClient.load();
    (client as any).http.post = async () => ({ok:false,status:403});
    (client as any).http.get = async () => {throw new Error('history read after denial');};
    (client as any).ensureSynced = async () => {throw new Error('account fallback after denial');};
    await assert.rejects(client.getChatMessages(chatId,{personal:true,freshChatOnly:true}),/HTTP 403/);
  });

  // contract-test: supporting surface=cli assertions=auth.session.isolation
  it('fences logout during the fresh metadata read', async () => {
    const client = OpenMatesClient.load();
    (client as any).http.post = async () => {
      (client as any).session = null;
      return {ok:true,data:{chats:[{id:chatId,messages_v:0}]}};
    };
    await assert.rejects(client.getChatMessages(chatId,{personal:true,freshChatOnly:true}),/workspace changed/);
  });

  // contract-test: supporting surface=cli assertions=auth.session.isolation
  it('requires an exact chat identity for a scoped history request', async () => {
    const client = OpenMatesClient.load();
    (client as any).http.post = async () => {throw new Error('ambiguous lookup performed');};
    await assert.rejects(client.getChatMessages('22222222',{personal:true,freshChatOnly:true}),/full chat UUID/);
  });
});


describe('bounded Task discovery transport', () => {
  // contract-test: supporting surface=cli assertions=chats.direction.context-assessment
  it('reads exactly one authorized page without following the exhaustive cursor', async () => {
    const client = OpenMatesClient.load(); const calls: string[] = [];
    const rows = Array.from({length:100}, (_,i) => ({task_id:`record-${i}`,version:1,source:i===0?'workflow_run':null}));
    (client as any).http.get = async (url: string) => { calls.push(url); return {ok:true,data:{tasks:rows,complete:false,next_cursor:'more'}}; };
    const result = await client.listUserTaskDiscoveryPage({personal:true});
    assert.equal(calls.length,1); assert.equal(result.length,99);
    const query = new URL(calls[0],'https://example.invalid').searchParams;
    assert.equal(query.get('limit'),'100'); assert.equal(query.get('paginate'),'true'); assert.equal(query.has('cursor'),false);
  });
  // contract-test: supporting surface=cli assertions=auth.session.isolation
  it('rejects authorization failure without presenting cached discovery', async () => {
    const client=OpenMatesClient.load(); (client as any).http.get=async()=>({ok:false,status:403,data:{}});
    await assert.rejects(client.listUserTaskDiscoveryPage({personal:true}),/HTTP 403/);
  });
  // contract-test: supporting surface=cli assertions=auth.session.isolation
  for (const change of ['logout','owner','team']) it(`fences ${change} during discovery`, async () => {
    const client=OpenMatesClient.load();
    (client as any).http.get=async()=>{
      if(change==='logout')(client as any).session=null;
      else if(change==='owner')(client as any).session.hashedEmail='another-owner';
      else client.setActiveTeamId('other-team');
      return {ok:true,data:{tasks:[]}};
    };
    await assert.rejects(client.listUserTaskDiscoveryPage({personal:true}),/workspace changed/);
  });
  // contract-test: supporting surface=cli assertions=chats.direction.context-assessment
  it('rejects oversized discovery rather than draining or trusting an invalid page', async () => {
    const client=OpenMatesClient.load(); (client as any).http.get=async()=>({ok:true,data:{tasks:Array.from({length:101},(_,i)=>({task_id:`record-${i}`}))}});
    await assert.rejects(client.listUserTaskDiscoveryPage({personal:true}),/Invalid bounded/);
  });
});
