/** Built SDK + synthetic first-party protocol fixture. No account or inference. */
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { resolve, dirname, join } from 'node:path';
import { tmpdir } from 'node:os';
import { webcrypto } from 'node:crypto';
import assert from 'node:assert/strict';
const cli = resolve(process.argv[2]);
const require = createRequire(pathToFileURL(cli));
const { WebSocketServer } = require('ws');
const { OpenMatesClient } = await import(pathToFileURL(join(dirname(cli), 'index.js')).href);
if (!resolve(process.env.OPENMATES_STATE_DIR ?? '').startsWith(join(tmpdir(), 'cli-privacy-e2e-'))) throw Error('Disposable CLI privacy fixture directory required.');
const key = await webcrypto.subtle.importKey('raw', new Uint8Array(32), { name: 'AES-GCM' }, false, ['encrypt']);
const iv = webcrypto.getRandomValues(new Uint8Array(12));
const encrypted = await webcrypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(JSON.stringify({ enabled: true, textToHide: 'Prepared Fixture Private', replaceWith: 'PERSON' })));
const ciphertext = Buffer.concat([Buffer.from(iv), Buffer.from(encrypted)]).toString('base64');
const chatId = '77777777-7777-4777-8777-777777777777';
const chatKeyIv = webcrypto.getRandomValues(new Uint8Array(12));
const wrapped = await webcrypto.subtle.encrypt({name:'AES-GCM',iv:chatKeyIv},key,new Uint8Array(32).fill(8));
const encryptedChatKey = Buffer.concat([Buffer.from(chatKeyIv),Buffer.from(wrapped)]).toString('base64');
let generation = 'fixture-epoch:1';
let prepared = 0, unchanged = 0, full = 0, redacted = 0;
let scopedMetadata = 0, scopedWindows = 0, taskDiscovery = 0, linkedTaskDiscovery = 0;
const wss = new WebSocketServer({ noServer: true });
const api = createServer((request, response) => {
  response.setHeader('content-type', 'application/json');
  if (request.method === 'POST' && request.url === '/v1/auth/session') response.end(JSON.stringify({ success: true, ws_token: 'fixture-token', user: { id: '11111111-1111-4111-8111-111111111111' } }));
  else if (request.method === 'POST' && request.url === '/v1/chats/metadata/batch') {
    scopedMetadata++;
    response.end(JSON.stringify({chats:[{id:chatId,messages_v:0,encrypted_chat_key:encryptedChatKey}]}));
  } else if (request.method === 'GET' && request.url.startsWith(`/v1/chats/${chatId}/messages/window?`)) {
    scopedWindows++;
    response.end(JSON.stringify({messages:[],has_more_before:false}));
  }
  else if (request.method === 'GET' && request.url.startsWith('/v1/user-tasks?')) {
    const query = new URL(request.url, 'http://fixture.invalid').searchParams;
    assert.equal(query.get('limit'),'100'); assert.equal(query.get('paginate'),'true'); assert.equal(query.has('cursor'),false);
    if (query.has('chat_id')) {
      linkedTaskDiscovery++;
      assert.equal(query.get('chat_id'), chatId, 'linked Task discovery must remain scoped to this saved chat');
      response.end(JSON.stringify({tasks:[],complete:true,next_cursor:null}));
    } else {
      taskDiscovery++;
      response.end(JSON.stringify({tasks:Array.from({length:100},(_,i)=>({task_id:`fixture-task-${i}`,version:1})),complete:false,next_cursor:'must-not-follow'}));
    }
  }
  else { response.statusCode = 404; response.end('{}'); }
});
api.on('upgrade', (request, socket, head) => wss.handleUpgrade(request, socket, head, peer => {
  peer.send(JSON.stringify({ type: 'server_capabilities', payload: { capabilities: ['personal_send_context_snapshot_v2'] } }));
  peer.on('message', raw => {
    const frame = JSON.parse(raw.toString());
    assert.ok(!['phased_sync_request','recovery_output_get'].includes(frame.type),
      'Privacy preparation must not enter account-wide sync/recovery');
    if (frame.type !== 'personal_send_context_snapshot') return;
    const equal = !!generation && frame.payload.known_generation === generation;
    if (frame.payload.purpose === 'prepare') prepared++;
    else if (equal) unchanged++; else full++;
    peer.send(JSON.stringify({ type: 'personal_send_context_snapshot_result', payload: {
      request_id: frame.payload.request_id, success: true, turn_id: frame.payload.turn_id,
      receipt_id: frame.payload.purpose === 'send' ? '22222222-2222-4222-8222-222222222222' : null,
      privacy_generation: generation, unchanged: equal, project_candidates: [],
      ...(!equal ? { personal_memories: { encrypted_settings: null, memories: [{ id: 'fixture-private-entry', app_id: 'privacy', item_type: 'personal_data_entry', encrypted_item_json: ciphertext }] } } : {}),
    } }));
  });
}));
await new Promise(resolve => api.listen(0, '127.0.0.1', resolve));
const apiUrl = `http://127.0.0.1:${api.address().port}`;
const client = new OpenMatesClient({ apiUrl, session: { apiUrl, sessionId: 'fixture-session', cookies: { auth_refresh_token: 'fixture-refresh' },
  wsToken: 'fixture-token', masterKeyExportedB64: Buffer.alloc(32).toString('base64'), emailEncryptionKeyB64: Buffer.alloc(32).toString('base64'),
  hashedEmail: 'fixture-owner', userEmailSalt: 'fixture-salt', createdAt: 1, autoLogoutMinutes: null, authorizerDeviceName: 'Fixture device' } });
let stopActivity;
try {
  // Seed the disposable profile through the public client persistence path.
  // Auth refresh uses the authoritative stored session to reject writes after
  // logout; an in-memory session alone cannot stand in for a paired profile.
  client.setActiveTeamId(null);
  assert.equal((await client.listUserTaskDiscoveryPage({personal:true})).length,100);
  assert.equal(taskDiscovery,1);
  // The fixture supplies authenticated terminal intent; startup warming itself
  // follows the production activity subscription and built client path.
  client.interactiveViewerAllowed = true;
  stopActivity = await client.observeChatActivity(() => {});
  await client.preparedPrivacyWarmPending;
  const send = async (savedChatId) => {
    await assert.rejects(client.sendMessage({ message: 'Hello Prepared Fixture Private', personal: true,
      ...(savedChatId ? {chatId:savedChatId} : {}),
      onPrivacyPrepared: safe => { assert.equal(safe.includes('Prepared Fixture Private'), false); redacted++; throw Error('fixture privacy boundary'); } }), /fixture privacy boundary/);
  };
  await send(); await send(chatId); await send(chatId);
  generation = 'fixture-epoch:2'; await send();
  client.invalidatePreparedPrivacy(); await send();
  generation = null; await send(); await send();
  // One standalone bounded probe, plus one directory and one chat-linked
  // Task read for each of the two saved-chat preparation attempts.
  assert.deepEqual({ prepared, unchanged, full, redacted,scopedMetadata,scopedWindows,taskDiscovery,linkedTaskDiscovery },
    { prepared: 1, unchanged: 3, full: 4, redacted: 7,scopedMetadata:2,scopedWindows:2,taskDiscovery:3,linkedTaskDiscovery:2 });
  process.stdout.write(JSON.stringify({ prepared, unchanged, full, redacted,scopedMetadata,scopedWindows,taskDiscovery,linkedTaskDiscovery }) + '\n');
} finally {
  client.endInteractiveViewerSession(); stopActivity?.();
  for (const peer of wss.clients) peer.terminate();
  wss.close(); api.closeAllConnections(); await new Promise(resolve => api.close(resolve));
}
