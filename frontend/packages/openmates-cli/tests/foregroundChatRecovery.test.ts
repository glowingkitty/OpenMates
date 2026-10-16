/** Foreground sends must retain scoped privacy/durability without account replay. */
import { after, beforeEach, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createServer, type ServerResponse } from 'node:http';

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

describe('same-send fresh history preparation', () => {
  function deferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (error: Error) => void;
    const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
    return { promise, resolve, reject };
  }
  function fixture() {
    const client = OpenMatesClient.load();
    // This send fixture mocks network discovery as well as its socket/history.
    for (const method of ['listUserPlans', 'listUserTaskDiscoveryPage', 'listUserTasks']) (client as any)[method] = async () => [];
    (client as any).getActiveProjectFocus = async () => null;
    const calls: string[] = [];
    let closed = 0;
    const ws = {
      isOpen: () => true,
      waitForServerCapability: async (capability: string) => capability === 'personal_memory_snapshot_v1',
      requestPersonalMemorySnapshot: async () => { calls.push('snapshot'); return { encrypted_settings: null, memories: [] }; },
      close: () => { closed++; },
    };
    (client as any).openWsClient = async () => {
      calls.push('socket'); return { ws, session: client.getSession(), ownerId: 'owner' };
    };
    return { client, calls, ws, closed: () => closed };
  }
  // contract-test: supporting surface=cli assertions=auth.session.isolation,chats.direction.context-assessment
  it('reads canonical followup history while socket preparation is pending and joins before privacy', async () => {
    const { client, calls, ws } = fixture();
    const history = deferred<any>();
    const socket = deferred<any>();
    const socketStarted = deferred<void>();
    const snapshotStarted = deferred<void>();
    ws.requestPersonalMemorySnapshot = async () => {
      calls.push('snapshot'); snapshotStarted.resolve(); return { encrypted_settings: null, memories: [] };
    };
    let historySignal: AbortSignal | undefined;
    let privacy = false;
    (client as any).getChatMessages = (_id: string, options: any) => {
      assert.equal(_id, chatId); assert.equal(options.freshChatOnly, true);
      assert.equal(options.personal, true); historySignal = options.signal;
      calls.push('history'); return history.promise;
    };
    (client as any).openWsClient = () => { calls.push('socket'); socketStarted.resolve(); return socket.promise; };
    const send = client.sendMessage({ chatId, message: 'And France?', piiDetection: false,
      onPrivacyPrepared: () => { privacy = true; throw new Error('stop before admission'); } });
    const rejected = assert.rejects(send, /stop before admission/);
    await socketStarted.promise;
    assert.deepEqual(calls, ['history', 'socket']);
    assert.equal(privacy, false);
    socket.resolve({ ws, session: client.getSession(), ownerId: 'owner' });
    await snapshotStarted.promise;
    assert.ok(calls.includes('snapshot'));
    assert.equal(privacy, false, 'fresh canonical PII history must still gate privacy');
    history.resolve({ chat: {}, messages: [] });
    await rejected;
    assert.equal(privacy, true); assert.equal(historySignal?.aborted, true);
  });
  // contract-test: supporting surface=cli assertions=auth.session.isolation,chats.direction.context-assessment
  it('starts fresh followup discovery before the independent Memory snapshot completes', async () => {
    const { client, ws } = fixture();
    const memory = deferred<any>(); const snapshotStarted = deferred<void>();
    let discoveries = 0, privacy = false;
    (client as any).getChatMessages = async () => ({ chat: {}, messages: [] });
    (client as any).listUserTaskDiscoveryPage = async () => { discoveries++; return []; };
    ws.requestPersonalMemorySnapshot = () => { snapshotStarted.resolve(); return memory.promise; };
    const send = client.sendMessage({ chatId, message: 'And France?', piiDetection: false,
      onPrivacyPrepared: () => { privacy = true; throw new Error('stop before admission'); } });
    const rejected = assert.rejects(send, /stop before admission/);
    await snapshotStarted.promise;
    assert.equal(discoveries, 1); assert.equal(privacy, false);
    memory.resolve({ encrypted_settings: null, memories: [] });
    await rejected;
  });
  // contract-test: supporting surface=cli assertions=auth.session.isolation
  for (const change of ['account', 'team']) it(`fences ${change} after canonical history finishes while socket preparation remains pending`, async () => {
    const { client, ws } = fixture();
    const socket = deferred<any>();
    let privacy = false;
    (client as any).getChatMessages = async () => ({ chat: {}, messages: [] });
    (client as any).openWsClient = () => socket.promise;
    const send = client.sendMessage({ chatId, message: 'And France?', piiDetection: false,
      onPrivacyPrepared: () => { privacy = true; } });
    const rejected = assert.rejects(send, /workspace changed/);
    await new Promise(resolve => setImmediate(resolve));
    if (change === 'account') client.getSession()!.hashedEmail = 'different-owner';
    else client.setActiveTeamId('different-team');
    socket.resolve({ ws, session: client.getSession(), ownerId: 'new-owner' });
    await rejected;
    assert.equal(privacy, false);
  });
  // contract-test: supporting surface=cli assertions=auth.session.isolation
  it('does not proceed to privacy when the concurrent canonical read rejects authorization', async () => {
    const { client, closed } = fixture();
    (client as any).getChatMessages = async () => { throw new Error('Chat metadata failed with HTTP 403'); };
    let privacy = false;
    await assert.rejects(client.sendMessage({ chatId, message: 'And France?', piiDetection: false,
      onPrivacyPrepared: () => { privacy = true; } }), /HTTP 403/);
    assert.equal(privacy, false); assert.ok(closed() > 0);
  });
  // contract-test: supporting surface=cli assertions=auth.session.isolation
  it('aborts unfinished canonical reads when fresh Memory preparation fails', async () => {
    const { client, ws } = fixture();
    let aborted = false;
    (client as any).getChatMessages = (_id: string, options: any) => new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => { aborted = true; reject(new Error('history cancelled')); });
    });
    ws.requestPersonalMemorySnapshot = async () => { throw new Error('Memory authority unavailable'); };
    await assert.rejects(client.sendMessage({ chatId, message: 'And France?', piiDetection: false }), /Memory authority unavailable/);
    assert.equal(aborted, true);
  });
  // contract-test: supporting surface=cli assertions=auth.session.isolation,chats.direction.context-assessment
  it('joins one canonical snapshot for remember references and privacy but refreshes the next turn', async () => {
    const { client, calls } = fixture();
    let histories = 0;
    (client as any).getChatMessages = async () => {
      histories++; calls.push('history');
      return { chat: {}, messages: [{ id: 'earlier-message', content: `Fresh revision ${histories}` }] };
    };
    const prepared: string[] = [];
    for (let turn = 0; turn < 2; turn++) {
      await assert.rejects(client.sendMessage({ chatId, message: 'Remember my message @earlier-message', piiDetection: false,
        onPrivacyPrepared: message => { prepared.push(message); throw new Error('stop before admission'); } }), /stop before admission/);
    }
    assert.equal(histories, 2, 'one fresh history read per send, never a cross-turn cache');
    assert.match(prepared[0], /Fresh revision 1/); assert.match(prepared[1], /Fresh revision 2/);
  });
});

describe('post-reply viewer cancellation', () => {
  // contract-test: supporting surface=cli assertions=auth.session.isolation,auth.session.lifecycle
  for (const phase of ['before headers', 'after rotated headers'] as const) {
    it(`releases viewer auth before foreground validation ${phase} without saving late credentials`, async () => {
      let first!: ServerResponse;
      let firstSeen!: () => void;
      const firstReceived = new Promise<void>(resolve => { firstSeen = resolve; });
      let headersCaptured!: () => void;
      const rotatedHeaders = new Promise<void>(resolve => { headersCaptured = resolve; });
      let authCalls = 0, upgrades = 0;
      const sentCookies: Array<string | undefined> = [];
      const server = createServer((request, response) => {
        assert.equal(request.url, '/v1/auth/session');
        authCalls++; sentCookies.push(request.headers.cookie);
        response.setHeader('content-type', 'application/json');
        if (authCalls === 1) {
          first = response;
          if (phase === 'after rotated headers') {
            response.setHeader('set-cookie', 'auth_refresh_token=viewer-rotated-cookie; Path=/; HttpOnly');
            response.writeHead(200); response.flushHeaders();
          }
          firstSeen(); return;
        }
        response.setHeader('set-cookie', 'auth_refresh_token=foreground-cookie; Path=/; HttpOnly');
        response.end(JSON.stringify({ success: true, ws_token: 'foreground-token', user: { id: 'owner' } }));
      });
      server.on('upgrade', (_request, socket) => { upgrades++; socket.destroy(); });
      await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
      const address = server.address(); assert.ok(address && typeof address === 'object');
      const apiUrl = `http://127.0.0.1:${address.port}`;
      const stored = JSON.parse(readFileSync(join(state, 'session.json'), 'utf8'));
      writeFileSync(join(state, 'session.json'), JSON.stringify({ ...stored, apiUrl }), { mode: 0o600 });
      const client = OpenMatesClient.load({ apiUrl });
      const internal = client as any;
      const stdinTty = process.stdin.isTTY, stdoutTty = process.stdout.isTTY;
      Object.defineProperty(process.stdin, 'isTTY', { configurable: true, value: true });
      Object.defineProperty(process.stdout, 'isTTY', { configurable: true, value: true });
      internal.interactiveViewerAllowed = true;
      const privacyOwner = internal.preparedPrivacyOwnerKey(null);
      internal.preparedPrivacy.set(privacyOwner, '{}', 'generation:1', []);
      const privacyBundle = internal.preparedPrivacy.get(privacyOwner, '{}');
      const epoch = internal.preparedPrivacyEpoch;
      const capture = internal.http.captureCookies.bind(internal.http);
      internal.http.captureCookies = async (...args: unknown[]) => {
        await capture(...args);
        if (internal.http.getCookieMap().auth_refresh_token === 'viewer-rotated-cookie') headersCaptured();
      };
      const nativeFetch = globalThis.fetch;
      const fetchErrors: Array<{ name?: string; code?: string }> = [];
      globalThis.fetch = async (...args) => {
        try { return await nativeFetch(...args); }
        catch (error) { fetchErrors.push(error as { name?: string; code?: string }); throw error; }
      };
      let deadline: ReturnType<typeof setTimeout> | null = null;
      try {
        const viewer = client.setInteractiveChatViewer(chatId);
        await firstReceived;
        if (phase === 'after rotated headers') await rotatedHeaders;
        client.clearInteractiveChatViewer();
        const foreground = internal.refreshWsToken();
        const owner = await Promise.race([foreground, new Promise<never>((_resolve, reject) => {
          deadline = setTimeout(() => reject(new Error('Cancelled viewer retained the session-refresh lock')), 1_000);
        })]);
        await viewer;
        assert.equal(owner, 'owner'); assert.equal(authCalls, 2); assert.equal(upgrades, 0);
        if (phase === 'before headers') assert.deepEqual(fetchErrors.map(error => [error.name, error.code]),
          [['OpenMatesViewerSupersededError', 'OPENMATES_VIEWER_SUPERSEDED']],
          'native fetch must expose the owned cancellation brand to the observer');
        assert.equal(sentCookies[1], `auth_refresh_token=${stored.cookies.auth_refresh_token}`);
        if (phase === 'before headers') first.setHeader('set-cookie', 'auth_refresh_token=late-viewer-cookie; Path=/; HttpOnly');
        first.end(JSON.stringify({ success: true, ws_token: 'late-viewer-token', user: { id: 'wrong-owner' } }));
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(client.getSession()!.wsToken, 'foreground-token');
        assert.equal(client.getSession()!.cookies.auth_refresh_token, 'foreground-cookie');
        assert.equal(JSON.parse(readFileSync(join(state, 'session.json'), 'utf8')).cookies.auth_refresh_token, 'foreground-cookie');
        assert.equal(internal.http.getCookieMap().auth_refresh_token, 'foreground-cookie');
        assert.equal(internal.preparedPrivacyEpoch, epoch);
        assert.equal(internal.preparedPrivacy.get(internal.preparedPrivacyOwnerKey(null), '{}'), privacyBundle,
          'cancelled viewer/ordinary rotation must not discard an owner-bound privacy bundle');
      } finally {
        globalThis.fetch = nativeFetch;
        if (deadline) clearTimeout(deadline);
        client.endInteractiveViewerSession();
        Object.defineProperty(process.stdin, 'isTTY', { configurable: true, value: stdinTty });
        Object.defineProperty(process.stdout, 'isTTY', { configurable: true, value: stdoutTty });
        first?.end(); server.closeAllConnections();
        await new Promise<void>(resolve => server.close(() => resolve()));
      }
    });
  }
  // contract-test: supporting surface=cli assertions=auth.session.isolation,auth.session.lifecycle
  it('does not let a cancelled viewer clear a newer pending viewer controller or retain its late socket', async () => {
    const client = OpenMatesClient.load(); const internal = client as any;
    const stdinTty = process.stdin.isTTY, stdoutTty = process.stdout.isTTY;
    Object.defineProperty(process.stdin, 'isTTY', { configurable: true, value: true });
    Object.defineProperty(process.stdout, 'isTTY', { configurable: true, value: true });
    internal.interactiveViewerAllowed = true;
    const opens: Array<{ resolve: (value: unknown) => void; signal: AbortSignal }> = [];
    const closed: string[] = [];
    internal.openWsClient = (options: { signal: AbortSignal }) => new Promise(resolve => { opens.push({ resolve, signal: options.signal }); });
    const ws = (name: string) => ({ close: () => { closed.push(name); }, onClose: () => () => {}, send: () => {} });
    try {
      const first = client.setInteractiveChatViewer(chatId);
      const second = client.setInteractiveChatViewer(unrelatedId);
      assert.equal(opens[0].signal.aborted, true);
      assert.equal(opens[0].signal.reason?.name, 'OpenMatesViewerSupersededError');
      assert.equal(opens[0].signal.reason?.code, 'OPENMATES_VIEWER_SUPERSEDED');
      const current = internal.interactiveViewerOpenController;
      opens[0].resolve({ ws: ws('cancelled') }); await first;
      assert.deepEqual(closed, ['cancelled']);
      assert.equal(internal.interactiveViewerOpenController, current);
      client.clearInteractiveChatViewer(); assert.equal(opens[1].signal.aborted, true);
      opens[1].resolve({ ws: ws('newer') }); await second;
      assert.deepEqual(closed, ['cancelled', 'newer']);
      assert.equal(internal.interactiveViewerOpenController, null);
    } finally {
      client.endInteractiveViewerSession();
      Object.defineProperty(process.stdin, 'isTTY', { configurable: true, value: stdinTty });
      Object.defineProperty(process.stdout, 'isTTY', { configurable: true, value: stdoutTty });
    }
  });
});
