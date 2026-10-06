// Minimal sidebar metadata preserves hidden-key privacy without loading transcripts.
// These tests exercise real encryption/decoding and publication fences locally.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { OpenMatesClient } from '../src/client.js';
import { encryptBytesWithAesGcm, encryptWithAesGcmCombined } from '../src/crypto.js';
import { loadSyncCache, saveSyncCache } from '../src/storage.js';

function fixture() {
  let master = Buffer.alloc(32, 1);
  const client = Object.create(OpenMatesClient.prototype) as OpenMatesClient;
  Object.assign(client, { requireSession: () => {}, hasSession: () => true,
    resolveTeamContext: () => null, getMasterKeyBytes: () => master,
    getChatWrappingKey: async () => master, getCliRequestHeaders: () => ({}), appendTeamQuery: (path: string) => path });
  return { client, master, changeAccount: () => { master = Buffer.alloc(32, 2); } };
}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,chat-navigation.open.local-first-coherent
test('cached history decrypts stale local chats without network access and retains account fences', async () => {
  const previousStateDir = process.env.OPENMATES_STATE_DIR;
  const stateDir = mkdtempSync(join(tmpdir(), 'openmates-local-chat-list-'));
  process.env.OPENMATES_STATE_DIR = stateDir;
  try {
    const {client,master,changeAccount}=fixture(),key=Buffer.alloc(32,3);
    saveSyncCache({syncedAt:0,totalChatCount:1,loadedChatCount:1,chats:[{details:{id:'cached',
      encrypted_chat_key:await encryptBytesWithAesGcm(key,master),
      encrypted_title:await encryptWithAesGcmCombined('Saved conversation',key)},messages:[]}],embeds:[],embedKeys:[]});
    Object.assign(client,{ensureSynced:async()=>{throw new Error('Network must not be called');},
      getChatWrappingKey:async()=>{throw new Error('Remote key lookup must not be called');}});
    const page=await client.listCachedChats(Number.MAX_SAFE_INTEGER,1);
    assert.equal(page?.chats[0].title,'Saved conversation');assert.equal(page?.total,1);
    let forced=false;
    Object.assign(client,{getChatWrappingKey:async()=>master,ensureSynced:async(force:boolean)=>{
      forced=force;return loadSyncCache();
    }});
    await client.listChats(10,1,{forceRefresh:true});assert.equal(forced,true);
    Object.assign(client,{decryptChatListItem:async()=>{changeAccount();return {};}});
    await assert.rejects(client.listCachedChats(),/workspace changed/);
  } finally {
    if(previousStateDir===undefined)delete process.env.OPENMATES_STATE_DIR;
    else process.env.OPENMATES_STATE_DIR=previousStateDir;
    rmSync(stateDir,{recursive:true,force:true});
  }
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,chat-navigation.open.local-first-coherent
test('missing team cache or local team key never falls back to personal chats or fetches a key', async () => {
  const previousStateDir=process.env.OPENMATES_STATE_DIR;
  const stateDir=mkdtempSync(join(tmpdir(),'openmates-local-team-chat-list-'));
  process.env.OPENMATES_STATE_DIR=stateDir;
  try {
    const {client}=fixture();
    const cache={syncedAt:0,totalChatCount:1,loadedChatCount:1,chats:[{details:{id:'private'},messages:[]}],embeds:[],embedKeys:[]};
    saveSyncCache(cache);
    Object.assign(client,{resolveTeamContext:()=> 'team',requireSession:()=>({hashedEmail:'fixture'}),
      getTeam:async()=>{throw new Error('Remote team lookup must not be called');}});
    assert.equal(await client.listCachedChats(),null);
    saveSyncCache(cache,'team');
    assert.equal(await client.listCachedChats(),null);
  } finally {
    if(previousStateDir===undefined)delete process.env.OPENMATES_STATE_DIR;
    else process.env.OPENMATES_STATE_DIR=previousStateDir;
    rmSync(stateDir,{recursive:true,force:true});
  }
});

// contract-test: supporting surface=cli assertions=chat-navigation.projects.organize
test('project naming sends structured titles through the naming route', async () => {
  const { client } = fixture();
  let request: unknown;
  Object.assign(client, { http: { post: async (route: string, body: unknown) => {
    assert.equal(route, '/v1/projects/ask/plan'); request = body;
    return { ok: true, data: { proposed_project: { name: 'Website launch' } } };
  } } });
  const result = await client.planProjectAsk({ instruction: 'Name a new project from chat titles.', chatTitles: ['Launch copy'] });
  assert.deepEqual(request, { instruction: 'Name a new project from chat titles.', chat_titles: ['Launch copy'] });
  assert.deepEqual(result.proposed_project, { name: 'Website launch' });
});

// contract-test: supporting surface=cli assertions=chat-navigation.activity.global-running,chat-navigation.projects.nested-readable
test('sidebar metadata distinguishes a readable untitled chat from a locked hidden key', async () => {
  const { client, master } = fixture(), key = Buffer.alloc(32, 3);
  let path = '', body: unknown;
  Object.assign(client, { http: { post: async (route: string, payload: unknown) => {
    path = route; body = payload;
    return { ok: true, data: { chats: [
      { id: 'normal', encrypted_chat_key: await encryptBytesWithAesGcm(key, master), updated_at: '1700000100' },
      { id: 'locked', encrypted_chat_key: await encryptBytesWithAesGcm(key, Buffer.alloc(32, 9)), encrypted_title: await encryptWithAesGcmCombined('Private topic', key), parent_id: 'normal' },
    ] } };
  } } });
  const result = await client.getSidebarChats(['normal', 'locked']);
  assert.equal(path, '/v1/chats/metadata/batch'); assert.deepEqual(body, { chat_ids: ['normal', 'locked'] });
  assert.equal(result[0].isHiddenCandidate, false); assert.equal(result[0].title, null);
  assert.equal(result[0].updatedAt, 1700000100);
  assert.equal(result[1].isHiddenCandidate, true); assert.equal(result[1].title, null);
  assert.equal(result[1].parentId, 'normal');
});

// contract-test: supporting surface=cli assertions=chat-navigation.activity.global-running
test('sidebar metadata cannot return plaintext after an account change during the request', async () => {
  const { client, master, changeAccount } = fixture(), key = Buffer.alloc(32, 3);
  const row = { id: 'normal', encrypted_chat_key: await encryptBytesWithAesGcm(key, master), encrypted_title: await encryptWithAesGcmCombined('Previous account', key) };
  Object.assign(client, { http: { post: async () => { changeAccount(); return { ok: true, data: { chats: [row] } }; } } });
  await assert.rejects(client.getSidebarChats(['normal']), /workspace changed/);
});

// contract-test: supporting surface=cli assertions=chat-navigation.activity.global-running
test('activity census cannot cross accounts before metadata hydration starts', async () => {
  const { client, changeAccount } = fixture();
  let hydrated = false;
  Object.assign(client, { http: { get: async () => {
    changeAccount(); return { ok: true, data: { active_tasks: [{ chat_id: 'previous-chat' }], chats: [{ chat_id: 'previous-chat' }] } };
  } }, getSidebarChats: async () => { hydrated = true; return []; } });
  await assert.rejects(client.getChatActivity(), /workspace changed/);
  assert.equal(hydrated, false);
});

// contract-test: supporting surface=cli assertions=chat-navigation.draft-only.addressable,chat-navigation.order.sidebar-header-match
test('saved keyless drafts retain their preview and ordering metadata without revealing locked chats', async () => {
  const {client, master} = fixture(), key = Buffer.alloc(32, 3);
  const draft = await encryptWithAesGcmCombined('Plan the release', master);
  Object.assign(client, {ensureSynced: async () => ({chats: [
    {details: {id: 'draft', encrypted_draft_md: draft, encrypted_draft_preview: draft, pinned: true, last_edited_overall_timestamp: 100}, messages: []},
    {details: {id: 'locked', encrypted_chat_key: await encryptBytesWithAesGcm(key, Buffer.alloc(32, 9)), encrypted_draft_md: draft, encrypted_draft_preview: draft}, messages: []},
    {details: {id: 'empty'}, messages: []},
  ]})});
  const {chats} = await client.listChats();
  assert.equal(chats[0].isHiddenCandidate, false); assert.equal(chats[0].draftPreview, 'Plan the release');
  assert.equal(chats[0].hasDraft, true); assert.equal(chats[0].pinned, true); assert.equal(chats[0].updatedAt, 100);
  assert.equal(chats[1].isHiddenCandidate, true); assert.equal(chats[1].draftPreview, null);
  assert.equal(chats[2].isHiddenCandidate, true);
});

// contract-test: supporting surface=cli assertions=chat-navigation.projects.nested-readable,chat-navigation.order.sidebar-header-match
test('linked metadata uses message time rather than a later metadata edit', async () => {
  const {client, master} = fixture(), key = Buffer.alloc(32, 3);
  Object.assign(client, {http: {post: async () => ({ok: true, data: {chats: [{id:'linked',
    encrypted_chat_key: await encryptBytesWithAesGcm(key,master), updated_at:'1700000300', last_message_at:'1700000100', pinned:true}]}})}});
  const [chat] = await client.getSidebarChats(['linked']);
  assert.equal(chat.updatedAt,1700000100); assert.equal(chat.pinned,true); assert.equal(chat.metadataUpdatedAt,1700000300);
});

// contract-test: supporting surface=cli assertions=chat-navigation.open.local-first-coherent
test('a list response cannot publish after the account changes while syncing', async () => {
  const {client,changeAccount} = fixture();
  Object.assign(client,{ensureSynced:async()=>{changeAccount();return {chats:[]};}});
  await assert.rejects(client.listChats(),/workspace changed/);
});

// contract-test: supporting surface=cli assertions=chat-navigation.draft-only.addressable,chat-navigation.open.local-first-coherent
test('saving a draft before the first list still syncs the complete chat census', async () => {
  const previousStateDir = process.env.OPENMATES_STATE_DIR;
  const stateDir = mkdtempSync(join(tmpdir(), 'openmates-sidebar-draft-'));
  process.env.OPENMATES_STATE_DIR = stateDir;
  try {
    const { client, master } = fixture(), key = Buffer.alloc(32, 3);
    let connections = 0;
    const serverChat = { id: 'server-chat', encrypted_chat_key: await encryptBytesWithAesGcm(key, master),
      encrypted_title: await encryptWithAesGcmCombined('Existing conversation', key) };
    Object.assign(client, {
      openWsClient: async () => { connections++; return { ws: {
        waitForMessage: async () => ({ payload: { chat_id: 'draft', draft_v: 1 } }),
        sendAsync: async () => {}, send: () => {}, close: () => {},
        collectMessages: async () => [{ type: 'phase_2_last_20_chats_ready', payload: {
          chats: [{ chat_details: serverChat }], total_chat_count: 2,
        } }], drainPassiveTaskUpdateJobs: () => [],
        waitForRecoveryOutputDiscovery: async () => {}, drainAvailableRecoveryOutputPages: () => [],
      } }; },
      persistPendingAIResponsesFromSync: async () => {},
      persistPendingTaskUpdateJobs: async () => new Set(),
    });
    await client.saveDraft({ chatId: 'draft', markdown: 'Finish the release' });
    assert.equal((await client.getDraft('draft'))?.markdown, 'Finish the release');
    assert.equal(connections, 1, 'A recent targeted draft read needs no complete sync');
    const { chats } = await client.listChats();
    assert.equal(connections, 2, 'The draft connection cannot substitute for the full sync');
    assert.deepEqual(new Set(chats.map(chat => chat.id)), new Set(['draft', 'server-chat']));
    assert.equal(chats.find(chat => chat.id === 'server-chat')?.title, 'Existing conversation');
  } finally {
    if (previousStateDir === undefined) delete process.env.OPENMATES_STATE_DIR;
    else process.env.OPENMATES_STATE_DIR = previousStateDir;
    rmSync(stateDir, { recursive: true, force: true });
  }
});

// contract-test: supporting surface=cli assertions=chat-navigation.open.local-first-coherent
test('editing a draft does not extend the freshness of an existing chat census', async () => {
  const previousStateDir = process.env.OPENMATES_STATE_DIR;
  const stateDir = mkdtempSync(join(tmpdir(), 'openmates-sidebar-freshness-'));
  process.env.OPENMATES_STATE_DIR = stateDir;
  try {
    const { client } = fixture();
    const syncedAt = Date.now() - 600_000;
    saveSyncCache({ syncedAt, totalChatCount: 1, loadedChatCount: 1,
      chats: [{ details: { id: 'existing' }, messages: [] }], embeds: [], embedKeys: [] });
    Object.assign(client, { openWsClient: async () => ({ ws: {
      waitForMessage: async () => ({ payload: { chat_id: 'existing', draft_v: 2 } }),
      sendAsync: async () => {}, close: () => {},
    } }) });
    await client.saveDraft({ chatId: 'existing', markdown: 'Updated plan' });
    assert.equal(loadSyncCache()?.syncedAt, syncedAt);
    Object.assign(client, { openWsClient: async () => { throw new Error('full census sync requested'); } });
    assert.equal((await client.getDraft('existing'))?.markdown, 'Updated plan');
    await assert.rejects(client.listChats(), /full census sync requested/);
    const cache = loadSyncCache();
    assert.ok(cache);
    cache.draftSyncedAt = { existing: Date.now() - 600_000 };
    saveSyncCache(cache);
    await assert.rejects(client.getDraft('existing'), /full census sync requested/);
  } finally {
    if (previousStateDir === undefined) delete process.env.OPENMATES_STATE_DIR;
    else process.env.OPENMATES_STATE_DIR = previousStateDir;
    rmSync(stateDir, { recursive: true, force: true });
  }
});

// contract-test: supporting surface=cli assertions=chat-navigation.draft-only.addressable,chat-navigation.open.local-first-coherent
test('clearing a new draft remembers its deletion without marking the chat census fresh', async () => {
  const previousStateDir = process.env.OPENMATES_STATE_DIR;
  const stateDir = mkdtempSync(join(tmpdir(), 'openmates-sidebar-draft-delete-'));
  process.env.OPENMATES_STATE_DIR = stateDir;
  try {
    const { client } = fixture();
    Object.assign(client, { openWsClient: async () => ({ ws: {
      waitForMessage: async () => ({ payload: { chat_id: 'draft', draft_v: 1 } }),
      sendAsync: async () => {}, close: () => {},
    } }) });
    await client.saveDraft({ chatId: 'draft', markdown: 'Private draft' });
    await client.clearDraft('draft');
    assert.equal(loadSyncCache()?.syncedAt, 0);
    assert.equal(loadSyncCache()?.chats.length, 0, 'The empty draft shell is removed');
    Object.assign(client, { openWsClient: async () => { throw new Error('full census sync requested'); } });
    assert.equal(await client.getDraft('draft'), null);
    await assert.rejects(client.getDraft('another-chat'), /full census sync requested/);
    await assert.rejects(client.listChats(), /full census sync requested/);
  } finally {
    if (previousStateDir === undefined) delete process.env.OPENMATES_STATE_DIR;
    else process.env.OPENMATES_STATE_DIR = previousStateDir;
    rmSync(stateDir, { recursive: true, force: true });
  }
});

// contract-test: supporting surface=cli assertions=chat-navigation.open.local-first-coherent,chats.completion.recovery-takeover,chats.persistence.client-encrypted
test('verified synced history is published and retained on disk before slow recovery finishes', async () => {
  const previous=process.env.OPENMATES_STATE_DIR,stateDir=mkdtempSync(join(tmpdir(),'tui-metadata-recovery-'));
  process.env.OPENMATES_STATE_DIR=stateDir;
  try {
    const {client,master}=fixture(),key=Buffer.alloc(32,3);
    const details={id:'saved',encrypted_chat_key:await encryptBytesWithAesGcm(key,master),encrypted_title:await encryptWithAesGcmCombined('Saved conversation',key)};
    let release!:()=>void, published!:(page:unknown)=>void;
    const metadata=new Promise(done=>{published=done;});
    const recovery=new Promise<void>(done=>{release=done;});
    Object.assign(client,{
      openWsClient:async()=>({ownerId:'owner',ws:{
        collectMessages:async()=>[{type:'phase_2_last_20_chats_ready',payload:{chats:[{chat_details:details}],total_chat_count:1}}],
        send:()=>{},close:()=>{},drainPassiveTaskUpdateJobs:()=>[],
        waitForRecoveryOutputDiscovery:async()=>{},drainAvailableRecoveryOutputPages:()=>[[{record_id:'pending',root_chat_id:'saved'}]],
      }}),
      persistPendingAIResponsesFromSync:async()=>{},persistPendingWorkflowChatDeliveries:async()=>0,
      persistPendingTaskUpdateJobs:async()=>new Set(),
      persistAvailableRecoveryOutputs:async()=>{await recovery;throw new Error('Recovery unavailable');},
    });
    const listing=client.listChats(10,1,{forceRefresh:true,onSyncedChats:published});
    const page=await metadata as {chats:{id:string}[]};
    assert.equal(page.chats[0].id,'saved');assert.equal(loadSyncCache()?.syncedAt,0);
    assert.equal((await client.listCachedChats())?.chats[0].title,'Saved conversation');
    release();assert.equal((await listing).pendingRecoveryOutputs,1);
    assert.equal((await client.listCachedChats())?.chats[0].id,'saved');
    // A recovery failure outside the browsing observer also retains the encrypted history.
    const replay=client as unknown as {replayAvailableRecoveryOutputs:(...args:unknown[])=>Promise<number>};
    await assert.rejects(replay.replayAvailableRecoveryOutputs({},'owner',[{root_chat_id:'saved'}],loadSyncCache(),null),/Recovery unavailable/);
    assert.equal(loadSyncCache()?.syncedAt,0);assert.equal((await client.listCachedChats())?.chats[0].id,'saved');
  } finally {
    if(previous===undefined)delete process.env.OPENMATES_STATE_DIR;else process.env.OPENMATES_STATE_DIR=previous;
    rmSync(stateDir,{recursive:true,force:true});
  }
});

// contract-test: supporting surface=cli assertions=chat-navigation.open.local-first-coherent,chats.completion.recovery-takeover
test('cancelling background chat sync closes its socket and stops recovery without removing saved history', async () => {
  const previous=process.env.OPENMATES_STATE_DIR,stateDir=mkdtempSync(join(tmpdir(),'tui-cancel-sync-'));
  process.env.OPENMATES_STATE_DIR=stateDir;
  try {
    const {client,master}=fixture(),key=Buffer.alloc(32,3),controller=new AbortController();
    let entered!:()=>void,rejectRecovery!:(error:Error)=>void,closed=0;
    const recovering=new Promise<void>(done=>{entered=done;});
    const pending=new Promise<number>((_done,reject)=>{rejectRecovery=reject;});
    Object.assign(client,{
      openWsClient:async()=>({ownerId:'owner',ws:{
        collectMessages:async()=>[{type:'phase_2_last_20_chats_ready',payload:{chats:[{chat_details:{id:'saved',
          encrypted_chat_key:await encryptBytesWithAesGcm(key,master),encrypted_title:await encryptWithAesGcmCombined('Saved conversation',key)}}],total_chat_count:1}}],
        send:()=>{},close:()=>{closed++;rejectRecovery(new Error('Socket closed'));},drainPassiveTaskUpdateJobs:()=>[],
        waitForRecoveryOutputDiscovery:async()=>{},drainAvailableRecoveryOutputPages:()=>[[{record_id:'pending',root_chat_id:'saved'}]],
      }}),
      persistPendingAIResponsesFromSync:async()=>{},persistPendingWorkflowChatDeliveries:async()=>0,
      persistPendingTaskUpdateJobs:async()=>new Set(),
      persistAvailableRecoveryOutputs:()=>{entered();return pending;},
    });
    const listing=client.listChats(10,1,{forceRefresh:true,signal:controller.signal,onSyncedChats:()=>{}});
    await recovering;controller.abort();
    await assert.rejects(listing,{name:'AbortError'});assert.ok(closed>0);
    assert.equal((await client.listCachedChats())?.chats[0].id,'saved');
  } finally {
    if(previous===undefined)delete process.env.OPENMATES_STATE_DIR;else process.env.OPENMATES_STATE_DIR=previous;
    rmSync(stateDir,{recursive:true,force:true});
  }
});

// contract-test: supporting surface=cli assertions=chat-navigation.open.local-first-coherent
test('an incomplete metadata sync cannot replace the saved chat cache or publish an empty list', async () => {
  const previous=process.env.OPENMATES_STATE_DIR,stateDir=mkdtempSync(join(tmpdir(),'tui-incomplete-sync-'));
  process.env.OPENMATES_STATE_DIR=stateDir;
  try {
    const {client,master}=fixture(),key=Buffer.alloc(32,3);let published=false;
    saveSyncCache({syncedAt:1,totalChatCount:1,loadedChatCount:1,embeds:[],embedKeys:[],chats:[{messages:[],details:{
      id:'saved',encrypted_chat_key:await encryptBytesWithAesGcm(key,master),encrypted_title:await encryptWithAesGcmCombined('Saved conversation',key),
    }}]});
    Object.assign(client,{openWsClient:async()=>({ws:{collectMessages:async()=>[],send:()=>{},close:()=>{}}})});
    await assert.rejects(client.listChats(10,1,{forceRefresh:true,onSyncedChats:()=>{published=true;}}),/before history arrived/);
    assert.equal(published,false);assert.equal(loadSyncCache()?.syncedAt,1);
    assert.equal((await client.listCachedChats())?.chats[0].title,'Saved conversation');
  } finally {
    if(previous===undefined)delete process.env.OPENMATES_STATE_DIR;else process.env.OPENMATES_STATE_DIR=previous;
    rmSync(stateDir,{recursive:true,force:true});
  }
});
