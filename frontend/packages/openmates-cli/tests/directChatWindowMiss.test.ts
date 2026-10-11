// contract-test-file: cli
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash, randomBytes, randomUUID } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { generateIdentity, sealDirectChatKey } from '@repo/pairing-crypto/direct-chat';
import { createAccountChatIdentity } from '../src/directChats.ts';
import { OpenMatesClient } from '../src/client.ts';
import { bytesToBase64, encryptWithAesGcmCombined } from '../src/crypto.ts';
import { saveLocalTeamKey, saveSyncCache, loadSyncCache, saveTrustedAccountId, saveCachedDirectChatAccountKey, type OpenMatesSession } from '../src/storage.ts';

const stateDir = mkdtempSync(join(tmpdir(), 'openmates-direct-window-'));
process.env.OPENMATES_STATE_DIR = stateDir;
process.once('exit', () => rmSync(stateDir, { recursive: true, force: true }));

// contract-test: supporting surface=cli assertions=teams.direct-chat.participant-isolation,teams.direct-chat.account-key-exchange
test('an exact newly web-created direct UUID can open despite a fresh older Team census', async () => {
  const teamId = randomUUID(), chatId = randomUUID();
  const userId = randomUUID(), ownHash = createHash('sha256').update(userId).digest('hex');
  const peerHash = createHash('sha256').update(randomUUID()).digest('hex');
  const identity = await generateIdentity(), chatKey = randomBytes(32), teamKey = randomBytes(32);
  const session: OpenMatesSession = { apiUrl: 'https://example.invalid', sessionId: randomUUID(), wsToken: null,
    cookies: {}, masterKeyExportedB64: bytesToBase64(randomBytes(32)), hashedEmail: randomUUID(),
    userEmailSalt: 'salt', createdAt: Date.now(), authorizerDeviceName: null, autoLogoutMinutes: null,
    activeTeamId: teamId };
  const encryptedChatKey = await sealDirectChatKey(chatKey,
    { teamId, chatId, recipientHash: ownHash, keyId: identity.keyId }, identity.publicKey);
  const details = { id: chatId, team_id: teamId, hashed_team_id: createHash('sha256').update(teamId).digest('hex'),
    chat_visibility: 'direct', participant_user_hashes: [ownHash, peerHash], encrypted_chat_key: encryptedChatKey,
    encrypted_title: await encryptWithAesGcmCombined('Private Team message', chatKey), messages_v: 1 };
  const message = { id: randomUUID(), chat_id: chatId, role: 'user', created_at: 1,
    encrypted_content: await encryptWithAesGcmCombined('Web-created private note', chatKey) };
  const staleCache = { syncedAt: Date.now(), totalChatCount: 1, loadedChatCount: 1,
    chats: [{ details: { id: randomUUID() }, messages: [] }], embeds: [], embedKeys: [] };
  const makeClient = () => {
    const client = new OpenMatesClient({ apiUrl: session.apiUrl, session }) as any;
    client.ensureSynced = async () => staleCache;
    client.getChatWrappingKey = async () => teamKey;
    client.ownDirectChatHash = async () => ownHash;
    client.ensureDirectChatIdentity = async () => identity;
    return client;
  };
  const client = makeClient();
  const calls: string[] = [];
  client.http.post = async (path: string, body: { chat_ids: string[] }) => {
    calls.push(path);
    assert.deepEqual(body.chat_ids, [chatId]);
    return { ok: true, status: 200, data: { chats: [details] } };
  };
  client.http.get = async (path: string) => {
    calls.push(path);
    return { ok: true, status: 200, data: { messages: [message] } };
  };
  const read = await client.getChatMessagesWindow(chatId, { teamId });
  assert.equal(read.chat.id, chatId);
  assert.equal(read.chat.chatVisibility, 'direct');
  assert.equal(read.messages[0]?.content, 'Web-created private note');
  assert.match(calls[0] ?? '', /\/v1\/chats\/metadata\/batch\?team_id=/);
  assert.match(calls[1] ?? '', /\/messages\/window\?/);

  const outsider = makeClient();
  let windowCalled = false;
  outsider.http.post = async () => ({ ok: false, status: 403, data: { chats: [] } });
  outsider.http.get = async () => { windowCalled = true; throw new Error('window must stay closed'); };
  await assert.rejects(outsider.getChatMessagesWindow(chatId, { teamId }), /metadata failed with HTTP 403/);
  assert.equal(windowCalled, false);
  const hidden = makeClient();
  hidden.http.post = async () => ({ ok: true, status: 200, data: { chats: [] } });
  hidden.http.get = async () => { windowCalled = true; throw new Error('window must stay closed'); };
  await assert.rejects(hidden.getChatMessagesWindow(chatId, { teamId }), /not found/);
  assert.equal(windowCalled, false);

  saveLocalTeamKey(session.hashedEmail, teamId, bytesToBase64(teamKey));
  saveSyncCache(staleCache, teamId);
  const offline = makeClient();
  offline.http.post = async () => { throw new Error('offline metadata request forbidden'); };
  offline.http.get = async () => { throw new Error('offline window request forbidden'); };
  await assert.rejects(offline.getChatMessagesWindow(chatId, { teamId, preferCache: true }), /not found/);
});

// contract-test: supporting surface=cli assertions=teams.direct-chat.account-key-exchange,teams.direct-chat.participant-isolation
test('an online window saves a newly discovered encrypted direct chat for a cold offline process', async () => {
  const teamId = randomUUID(), chatId = randomUUID(), accountId = randomUUID();
  const ownHash = createHash('sha256').update(accountId).digest('hex');
  const peerHash = createHash('sha256').update(randomUUID()).digest('hex');
  const masterKey = randomBytes(32), teamKey = randomBytes(32), chatKey = randomBytes(32);
  const { identity, record } = await createAccountChatIdentity(masterKey);
  const session: OpenMatesSession = { apiUrl: 'https://offline-window.example.invalid', sessionId: randomUUID(),
    wsToken: null, cookies: {}, masterKeyExportedB64: bytesToBase64(masterKey), hashedEmail: randomUUID(),
    userEmailSalt: 'salt', createdAt: Date.now(), authorizerDeviceName: null, autoLogoutMinutes: null,
    activeTeamId: teamId };
  writeFileSync(join(stateDir, 'session.json'), JSON.stringify(session), { mode: 0o600 });
  saveTrustedAccountId(accountId);
  saveCachedDirectChatAccountKey(session, session.apiUrl, accountId, record);
  saveLocalTeamKey(session.hashedEmail, teamId, bytesToBase64(teamKey));
  const encryptedChatKey = await sealDirectChatKey(chatKey,
    { teamId, chatId, recipientHash: ownHash, keyId: identity.keyId }, identity.publicKey);
  const details = { id: chatId, team_id: teamId, hashed_team_id: createHash('sha256').update(teamId).digest('hex'),
    chat_visibility: 'direct', participant_user_hashes: [ownHash, peerHash], encrypted_chat_key: encryptedChatKey,
    encrypted_title: await encryptWithAesGcmCombined('Cold offline chat', chatKey), messages_v: 1 };
  const encryptedContent = await encryptWithAesGcmCombined('Offline ciphertext-backed note', chatKey);
  const message = { id: randomUUID(), chat_id: chatId, role: 'user', created_at: 1,
    encrypted_content: encryptedContent };
  const staleCache = { syncedAt: Date.now(), totalChatCount: 0, loadedChatCount: 0,
    chats: [], embeds: [], embedKeys: [] };
  saveSyncCache(staleCache, teamId);
  const denied = new OpenMatesClient({ apiUrl: session.apiUrl, session }) as any;
  denied.ensureSynced = async () => staleCache;
  denied.getChatWrappingKey = async () => teamKey;
  denied.http.post = async () => ({ ok: false, status: 403, data: { chats: [] } });
  denied.http.get = async () => { throw new Error('denied window must not open'); };
  await assert.rejects(denied.getChatMessagesWindow(chatId, { teamId }), /metadata failed with HTTP 403/);
  assert.equal(loadSyncCache(teamId)?.chats.some(row => row.details.id === chatId), false);
  const online = new OpenMatesClient({ apiUrl: session.apiUrl, session }) as any;
  online.ensureSynced = async () => staleCache;
  online.getChatWrappingKey = async () => teamKey;
  online.http.post = async () => ({ ok: true, status: 200, data: { chats: [details] } });
  online.http.get = async () => ({ ok: true, status: 200, data: { messages: [message] } });
  assert.equal((await online.getChatMessagesWindow(chatId, { teamId })).messages[0]?.content,
    'Offline ciphertext-backed note');
  const cached = loadSyncCache(teamId);
  assert.equal(cached?.chats.find(row => row.details.id === chatId)?.messages.length, 1);
  const disk = readFileSync(join(stateDir,
    `sync_cache.team.${createHash('sha256').update(teamId).digest('hex').slice(0, 32)}.json`), 'utf8');
  assert.equal(disk.includes('Offline ciphertext-backed note'), false);
  assert.equal(disk.includes(encryptedContent), true);
  const child = `import {OpenMatesClient} from './src/client.ts';
    const session=${JSON.stringify(session)};
    const c=new OpenMatesClient({apiUrl:session.apiUrl,session});
    let networkCalls=0;
    globalThis.fetch=async()=>{networkCalls++;throw new Error('offline fetch forbidden')};
    c.http.get=async()=>{networkCalls++;throw new Error('offline GET forbidden')};
    c.http.post=async()=>{networkCalls++;throw new Error('offline POST forbidden')};
    const result=await c.getChatMessages('${chatId}',{teamId:'${teamId}',preferCache:true,maxHistoryPages:0});
    process.stdout.write(JSON.stringify({content:result.messages[0]?.content,networkCalls}));`;
  const output = execFileSync(process.execPath,
    ['--experimental-strip-types', '--loader', './tests/loader.mjs', '--input-type=module', '-e', child],
    { cwd: process.cwd(), env: { ...process.env, OPENMATES_STATE_DIR: stateDir }, encoding: 'utf8' });
  assert.deepEqual(JSON.parse(output), { content: 'Offline ciphertext-backed note', networkCalls: 0 });
  saveSyncCache(staleCache, teamId);
  online.http.get = async () => {
    saveSyncCache({ ...staleCache, syncedAt: staleCache.syncedAt + 1 }, teamId);
    return { ok: true, status: 200, data: { messages: [message] } };
  };
  assert.equal((await online.getChatMessagesWindow(chatId, { teamId })).messages[0]?.content,
    'Offline ciphertext-backed note');
  assert.equal(loadSyncCache(teamId)?.chats.some(row => row.details.id === chatId), false,
    'a newer sync must not be overwritten by the older window');
});
