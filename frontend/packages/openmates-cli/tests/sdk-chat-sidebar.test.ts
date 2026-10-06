// Minimal sidebar metadata preserves hidden-key privacy without loading transcripts.
// These tests exercise real encryption/decoding and publication fences locally.
import { createHash } from 'node:crypto';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { OpenMatesClient, mergeConcurrentChatMessages } from '../src/client.js';
import { encryptBytesWithAesGcm, encryptWithAesGcmCombined } from '../src/crypto.js';
import { loadSyncCache, saveSyncCache } from '../src/storage.js';

function fixture() {
  let master = Buffer.alloc(32, 1);
  const client = Object.create(OpenMatesClient.prototype) as OpenMatesClient;
  Object.assign(client, { requireSession: () => ({hashedEmail:'fixture-account'}), hasSession: () => true,
    resolveTeamContext: () => null, getMasterKeyBytes: () => master,
    getChatWrappingKey: async () => master, getCliRequestHeaders: () => ({}), appendTeamQuery: (path: string) => path });
  return { client, master, changeAccount: () => { master = Buffer.alloc(32, 2); } };
}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,chat-navigation.open.local-first-coherent
test('cached chat opening and drafts bypass full sync while preserving account fences', async () => {
  const previousStateDir = process.env.OPENMATES_STATE_DIR;
  const stateDir = mkdtempSync(join(tmpdir(), 'openmates-cached-chat-open-'));
  process.env.OPENMATES_STATE_DIR = stateDir;
  try {
    const {client,master,changeAccount}=fixture(),key=Buffer.alloc(32,3);
    saveSyncCache({syncedAt:0,totalChatCount:1,loadedChatCount:1,chats:[{details:{id:'cached',messages_v:1,
      encrypted_chat_key:await encryptBytesWithAesGcm(key,master),
      encrypted_title:await encryptWithAesGcmCombined('Saved conversation',key),
      encrypted_draft_md:await encryptWithAesGcmCombined('Continue the plan',master)},
      messages:[JSON.stringify({message_id:'message',role:'user',encrypted_content:await encryptWithAesGcmCombined('A cached message',key)})]}],embeds:[],embedKeys:[]});
    Object.assign(client,{ensureSynced:async()=>{throw new Error('Full sync must not block opening');},
      http:{get:async()=>{throw new Error('Cached messages must not fetch history');}}});
    const opened=await client.getChatMessages('cached',{preferCache:true});
    assert.equal(opened.chat.title,'Saved conversation');
    assert.equal(opened.messages[0].content,'A cached message');
    assert.equal((await client.getCachedDraft('cached'))?.markdown,'Continue the plan');
    await assert.rejects(client.getChatMessages('cached'),/Full sync must not block opening/);
    Object.assign(client,{decryptRawChatMessages:async()=>{changeAccount();return [];}});
    await assert.rejects(client.getChatMessages('cached',{preferCache:true}),/workspace changed/);
  } finally {
    if(previousStateDir===undefined)delete process.env.OPENMATES_STATE_DIR;
    else process.env.OPENMATES_STATE_DIR=previousStateDir;
    rmSync(stateDir,{recursive:true,force:true});
  }
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,chat-navigation.open.local-first-coherent
test('metadata-only chat opening reads canonical history without saved-output recovery', async () => {
  const previousStateDir=process.env.OPENMATES_STATE_DIR;
  const stateDir=mkdtempSync(join(tmpdir(),'openmates-metadata-chat-open-'));
  process.env.OPENMATES_STATE_DIR=stateDir;
  try {
    const {client,master}=fixture(),key=Buffer.alloc(32,3);
    saveSyncCache({syncedAt:0,totalChatCount:1,loadedChatCount:1,chats:[{details:{id:'older',messages_v:2,
      encrypted_chat_key:await encryptBytesWithAesGcm(key,master)},messages:[]}],embeds:[],embedKeys:[]});
    let requests=0;
    Object.assign(client,{ensureSynced:async()=>{throw new Error('Recovery must not block history');},
      http:{get:async(route:string)=>{
        requests++;assert.match(route,/\/v1\/chats\/older\/messages\/window\?/);
        return {ok:true,data:{messages:[{message_id:'archived',role:'assistant',
          encrypted_content:await encryptWithAesGcmCombined('Canonical history',key)}],has_more_before:false}};
      }}});
    const opened=await client.getChatMessages('older',{preferCache:true});
    assert.equal(opened.messages[0].content,'Canonical history');
    assert.equal(loadSyncCache()?.chats[0].messages.length,1);
    Object.assign(client,{http:{get:async()=>{throw new Error('Offline');}}});
    assert.equal((await client.getChatMessages('older',{preferCache:true})).messages[0].content,'Canonical history');assert.equal(requests,1);
  } finally {
    if(previousStateDir===undefined)delete process.env.OPENMATES_STATE_DIR;
    else process.env.OPENMATES_STATE_DIR=previousStateDir;
    rmSync(stateDir,{recursive:true,force:true});
  }
});

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

// contract-test: supporting surface=cli assertions=chat-navigation.open.local-first-coherent,chats.persistence.client-encrypted
test('first history window is usable and encrypted on disk while older history is unavailable', async()=>{
  const previous=process.env.OPENMATES_STATE_DIR,stateDir=mkdtempSync(join(tmpdir(),'tui-window-offline-'));
  process.env.OPENMATES_STATE_DIR=stateDir;
  try {
    const {client,master}=fixture(),key=Buffer.alloc(32,3);let reads=0,published=false;
    const id='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';
    Object.assign(client,{ensureSynced:async()=>{throw Error('Recovery must not block');},http:{
      post:async(_route:string,body:unknown)=>{assert.deepEqual(body,{chat_ids:[id]});return {ok:true,data:{chats:[{id,encrypted_chat_key:await encryptBytesWithAesGcm(key,master)}]}};},
      get:async()=>{if(reads++) {assert.equal(published,true);throw Error('Offline');}
        return {ok:true,data:{messages:[{message_id:'recent',role:'user',encrypted_content:await encryptWithAesGcmCombined('Private window content',key)}],has_more_before:true,start_cursor:{message_id:'recent',created_at:1}}};},
    }});
    const opened=await client.getChatMessages(id,{preferCache:true,onMessages:page=>{
      published=true;assert.equal(page.messages[0].content,'Private window content');
      assert.equal(loadSyncCache()?.chats[0].messages.length,1);
      assert.equal(JSON.stringify(loadSyncCache()).includes('Private window content'),false);
    }});
    assert.equal(opened.historyIncomplete,true);assert.equal(opened.messages.length,1);
    assert.equal((await client.getChatMessages(id,{preferCache:true})).messages[0].content,'Private window content');
    await assert.rejects(client.getChatMessages('uncached-secret-title',{preferCache:true}),/not found/);
  } finally {if(previous===undefined)delete process.env.OPENMATES_STATE_DIR;else process.env.OPENMATES_STATE_DIR=previous;rmSync(stateDir,{recursive:true,force:true});}
});

// contract-test: supporting surface=cli assertions=chat-navigation.open.local-first-coherent,chats.persistence.client-encrypted
test('background sync retains concurrent windows without reviving deleted or newer chats',()=>{
  const chat={details:{id:'saved',messages_v:2,encrypted_chat_key:'key'},messages:[]};
  const cache={syncedAt:0,totalChatCount:1,loadedChatCount:1,chats:[chat],embeds:[],embedKeys:[]};
  const latest={...cache,chats:[{...chat,messages:['ciphertext']}]};
  assert.deepEqual(mergeConcurrentChatMessages(cache,latest).chats[0].messages,['ciphertext']);
  assert.equal(mergeConcurrentChatMessages({...cache,chats:[]},latest).chats.length,0);
  assert.equal(mergeConcurrentChatMessages({...cache,chats:[{...chat,details:{...chat.details,messages_v:3}}]},latest).chats[0].messages.length,0);
});

// contract-test: supporting surface=cli assertions=chat-navigation.open.local-first-coherent,chats.persistence.client-encrypted
test('idle recent history warming is bounded and cancellation stops subsequent reads',async()=>{
  const previous=process.env.OPENMATES_STATE_DIR,stateDir=mkdtempSync(join(tmpdir(),'tui-warm-recent-'));
  process.env.OPENMATES_STATE_DIR=stateDir;
  try {
    const {client}=fixture(),controller=new AbortController();let reads=0;
    saveSyncCache({syncedAt:0,totalChatCount:30,loadedChatCount:30,chats:Array.from({length:30},(_,i)=>({details:{id:String(i),messages_v:1,last_edited_overall_timestamp:30-i},messages:[]})),embeds:[],embedKeys:[]});
    Object.assign(client,{getChatMessages:async(id:string,options:{preferCache:boolean;maxHistoryPages:number})=>{
      assert.ok(Number(id)<20);assert.equal(options.preferCache,true);assert.equal(options.maxHistoryPages,1);reads++;
      return {chat:{id},messages:[]};
    }});
    await client.cacheRecentChatMessages();assert.equal(reads,20);
    Object.assign(client,{getChatMessages:async()=>{reads++;controller.abort();return {chat:{},messages:[]};}});
    await assert.rejects(client.cacheRecentChatMessages({signal:controller.signal}),{name:'AbortError'});
    assert.ok(reads<=23);
  } finally {if(previous===undefined)delete process.env.OPENMATES_STATE_DIR;else process.env.OPENMATES_STATE_DIR=previous;rmSync(stateDir,{recursive:true,force:true});}
});

// contract-test: supporting surface=cli assertions=app-memories.privacy.client-encrypted,app-memories.access.owner-scoped,cli.surface.semantic-parity
test('remembered home data remains encrypted offline and cannot cross accounts or Teams',async()=>{
  const previous=process.env.OPENMATES_STATE_DIR,stateDir=mkdtempSync(join(tmpdir(),'tui-remembered-cache-'));
  process.env.OPENMATES_STATE_DIR=stateDir;
  try {
    const {client,changeAccount}=fixture();
    Object.assign(client,{listMemories:async()=>[{id:'saved',data:{embed_id:'event',title:'Private remembered title'},app_id:'events',item_type:'saved_events'}],
      settingsGet:async()=>({success:true,reminders:[{target_embed_id:'event',prompt_preview:'Private reminder'}]})});
    const result=await client.getContinueItems();assert.equal(result.memories.length,1);
    assert.equal(JSON.stringify(loadSyncCache()).includes('Private remembered'),false);
    assert.equal(JSON.stringify(loadSyncCache()).includes('Private reminder'),false);
    assert.equal((await client.getCachedContinueItems())?.memories[0].data.title,'Private remembered title');
    Object.assign(client,{resolveTeamContext:()=> 'team'});assert.equal(await client.getCachedContinueItems(),null);
    Object.assign(client,{resolveTeamContext:()=>null,listMemories:async()=>{changeAccount();return result.memories;}});
    await assert.rejects(client.getContinueItems(),/workspace changed/);
  } finally {if(previous===undefined)delete process.env.OPENMATES_STATE_DIR;else process.env.OPENMATES_STATE_DIR=previous;rmSync(stateDir,{recursive:true,force:true});}
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,chats.persistence.client-encrypted
test('saved embeds open from encrypted cache and targeted reads without a full recovery sync',async()=>{
  const previous=process.env.OPENMATES_STATE_DIR,stateDir=mkdtempSync(join(tmpdir(),'tui-embed-cache-'));
  process.env.OPENMATES_STATE_DIR=stateDir;
  try {
    const {client,master,changeAccount}=fixture(),key=Buffer.alloc(32,3),id='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';let requested=0,closed=0;
    const wrapper={hashed_embed_id:createHash('sha256').update(id).digest('hex'),key_type:'master',encrypted_embed_key:await encryptBytesWithAesGcm(key,master)};
    const content=await encryptWithAesGcmCombined(JSON.stringify({title:'Private saved event',description:'Full details'}),key),type=await encryptWithAesGcmCombined('events-event',key);
    Object.assign(client,{ensureSynced:async()=>{throw Error('Full recovery must not block embed opening');},openWsClient:async()=>({ws:{
      sendAsync:async(name:string,payload:{embed_id:string})=>{requested++;assert.equal(name,'request_embed');assert.equal(payload.embed_id,id);},
      waitForMessage:async()=>({payload:{embed_id:id,type,content,already_encrypted:true,embed_keys:[wrapper]}}),close:()=>{closed++;},
    }})});
    const embed=await client.getEmbed(id,{preferCache:true});assert.equal(embed.content?.title,'Private saved event');assert.equal(requested,1);assert.equal(closed,1);
    assert.equal(JSON.stringify(loadSyncCache()).includes('Private saved event'),false);
    Object.assign(client,{openWsClient:async()=>{throw Error('Offline');}});
    assert.equal((await client.getEmbed(id,{preferCache:true})).content?.description,'Full details');
    Object.assign(client,{resolveEmbedKey:async()=>{changeAccount();return key;}});
    await assert.rejects(client.getEmbed(id,{preferCache:true}),/workspace changed/);
  } finally {if(previous===undefined)delete process.env.OPENMATES_STATE_DIR;else process.env.OPENMATES_STATE_DIR=previous;rmSync(stateDir,{recursive:true,force:true});}
});

// contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted,chats.rendering.inline-entity-interaction
test('cached child embed repairs its missing inherited parent and stays readable offline',async()=>{
  const previous=process.env.OPENMATES_STATE_DIR,stateDir=mkdtempSync(join(tmpdir(),'tui-parent-repair-'));
  process.env.OPENMATES_STATE_DIR=stateDir;
  try {
    const {client,master}=fixture(),key=Buffer.alloc(32,3),id='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',parent='bbbbbbbb-cccc-4ddd-8eee-ffffffffffff';
    const content=await encryptWithAesGcmCombined(JSON.stringify({title:'Inherited event'}),key),type=await encryptWithAesGcmCombined('events-event',key);
    saveSyncCache({syncedAt:0,totalChatCount:0,loadedChatCount:0,chats:[],embedKeys:[],embeds:[{embed_id:id,parent_embed_id:parent,encrypted_type:type,encrypted_content:content}]});
    let requests=0;
    Object.assign(client,{openWsClient:async()=>({ws:{sendAsync:async()=>{requests++;},waitForMessage:async()=>({payload:{
      embed_id:requests===0?id:parent,type,content,already_encrypted:true,...(requests===0?{parent_embed_id:parent}:{}),
      embed_keys:requests===0?[]:[{hashed_embed_id:createHash('sha256').update(parent).digest('hex'),key_type:'master',encrypted_embed_key:await encryptBytesWithAesGcm(key,master)}],
    }}),close:()=>{}}})});
    assert.equal((await client.getEmbed(id,{preferCache:true})).content?.title,'Inherited event');assert.equal(requests,2);
    Object.assign(client,{openWsClient:async()=>{throw Error('Offline');}});
    assert.equal((await client.getEmbed(id,{preferCache:true})).content?.title,'Inherited event');
    assert.equal(JSON.stringify(loadSyncCache()).includes('Inherited event'),false);
  } finally {if(previous===undefined)delete process.env.OPENMATES_STATE_DIR;else process.env.OPENMATES_STATE_DIR=previous;rmSync(stateDir,{recursive:true,force:true});}
});
