/**
 * Unit tests for OpenMates Teams V1 CLI client routes.
 *
 * Purpose: lock the CLI-side team context, membership, billing, and workspace
 * move HTTP contracts before the dev-server CLI verification scripts use them.
 * Security: uses a local HTTP server and synthetic session only; no production
 * credentials or real team data are involved.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/teams-permissions.test.ts
 */

import { after, before, describe, it } from "node:test";
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { OpenMatesClient, type ProjectRecord, type UserPlanRecord, type UserTaskRecord, type WorkflowDetail } from "../src/client.ts";
import { buildCreateUserPlanInput } from "../src/plansCli.ts";
import { loadLocalTeamKey, loadSyncCache, saveLocalTeamKey, saveSyncCache, type OpenMatesSession } from "../src/storage.ts";
import { buildCreateUserTaskInput } from "../src/tasksCli.ts";
import { bytesToBase64, encryptBytesWithAesGcm, encryptWithAesGcmCombined } from "../src/crypto.ts";
import { buildEncryptedObjectSlugMetadata } from "../src/objectSlugs.ts";

type SeenRequest = { method: string | undefined; url: string | undefined; body: unknown };

const originalHome = process.env.HOME;
const tempHome = mkdtempSync(join(tmpdir(), "openmates-teams-permissions-"));
process.env.HOME = tempHome;

before(() => {
  process.env.HOME = tempHome;
});

function fakeActivitySocket() {
  const handlers = new Map<string, Set<() => void>>();
  const closeHandlers = new Set<() => void>();
  let closed = false;
  return {
    onMessageType(type: string, handler: () => void) {
      const listeners = handlers.get(type) ?? new Set<() => void>();
      listeners.add(handler); handlers.set(type, listeners);
      return () => { listeners.delete(handler); };
    },
    onClose(handler: () => void) { closeHandlers.add(handler); return () => { closeHandlers.delete(handler); }; },
    emit(type: string) { if (!closed) for (const handler of handlers.get(type) ?? []) handler(); },
    close() { if (closed) return; closed = true; for (const handler of [...closeHandlers]) handler(); },
    get closed() { return closed; },
  };
}

async function waitFor(check: () => boolean): Promise<void> {
  const deadline = Date.now() + 1_000;
  while (!check()) {
    if (Date.now() >= deadline) throw new Error('Timed out waiting for activity observer reconnect');
    await new Promise(resolve => setTimeout(resolve, 20));
  }
}

// contract-test: supporting surface=cli assertions=teams.workspace.surface-parity
it('reconnects activity observation after socket loss while retaining Team switch routing', async () => {
  const client = new OpenMatesClient({ apiUrl: 'http://127.0.0.1', session: testSession('team-a') });
  const sockets: ReturnType<typeof fakeActivitySocket>[] = [];
  (client as unknown as { openWsClient: () => Promise<unknown> }).openWsClient = async () => {
    const ws = fakeActivitySocket(); sockets.push(ws);
    return { ws, session: client.getSession(), ownerId: null };
  };
  let changes = 0;
  const stop = await client.observeChatActivity(() => { changes++; });
  sockets[0]!.emit('team_chat_message_created');
  client.setActiveTeamId('team-b');
  sockets[0]!.emit('team_chat_message_created');
  assert.equal(changes, 2);
  sockets[0]!.close();
  await waitFor(() => sockets.length === 2);
  sockets[1]!.emit('team_chat_message_created');
  assert.equal(changes, 3);
  stop();
  assert.equal(sockets[1]!.closed, true);
  sockets[1]!.emit('team_chat_message_created');
  assert.equal(changes, 3);
});

// contract-test: supporting surface=cli assertions=teams.workspace.surface-parity
it('does not reconnect an activity socket after account replacement or cleanup', async () => {
  const session = testSession('team-a');
  const client = new OpenMatesClient({ apiUrl: 'http://127.0.0.1', session });
  const sockets: ReturnType<typeof fakeActivitySocket>[] = [];
  const internals = client as unknown as { session: OpenMatesSession | null; openWsClient: () => Promise<unknown> };
  internals.openWsClient = async () => {
    const ws = fakeActivitySocket(); sockets.push(ws);
    return { ws, session: client.getSession(), ownerId: null };
  };
  let changes = 0;
  const stop = await client.observeChatActivity(() => { changes++; });
  internals.session = { ...testSession('team-b'), hashedEmail: 'different-account' };
  sockets[0]!.emit('team_chat_message_created');
  assert.equal(changes, 0);
  assert.equal(sockets[0]!.closed, true);
  await new Promise(resolve => setTimeout(resolve, 300));
  assert.equal(sockets.length, 1);
  stop();

  const stopCurrent = await client.observeChatActivity(() => { changes++; });
  sockets[1]!.close();
  stopCurrent();
  await new Promise(resolve => setTimeout(resolve, 300));
  assert.equal(sockets.length, 2);
});

// contract-test: supporting surface=cli assertions=teams.workspace.surface-parity
it('refreshes a stale cached Team chat through its bounded encrypted message window', async () => {
  const suffix = randomBytes(5).toString('hex');
  const teamId = `team-${suffix}`, chatId = `chat-${suffix}`;
  const session = testSession(teamId);
  const teamKey = randomBytes(32), chatKey = randomBytes(32);
  saveLocalTeamKey(session.hashedEmail, teamId, bytesToBase64(teamKey));
  saveSyncCache({ syncedAt: 1, totalChatCount: 1, loadedChatCount: 1,
    chats: [{ details: { id: chatId, encrypted_chat_key: await encryptBytesWithAesGcm(chatKey, teamKey),
      messages_v: 1, title_v: 0, draft_v: 0 }, messages: [JSON.stringify({id:'older-message',role:'user',created_at:1,
        encrypted_content:await encryptWithAesGcmCombined('Older Team message',chatKey)})] }], embeds: [], embedKeys: [] }, teamId);
  const client = new OpenMatesClient({ apiUrl: 'http://127.0.0.1', session });
  const internals = client as unknown as {
    ensureSynced: () => Promise<never>;
    http: { get: (url: string) => Promise<unknown> };
    session: OpenMatesSession;
  };
  internals.ensureSynced = async () => { throw new Error('Full sync must not run for a cached Team window'); };
  const seen: string[] = [];
  internals.http.get = async (url) => {
    seen.push(url);
    return { ok: true, status: 200, data: { messages: [{ id: 'remote-message', chat_id: chatId,
      role: 'user', created_at: 2, encrypted_content: await encryptWithAesGcmCombined('Encrypted Team reply', chatKey) }],
      server_message_count: 2, has_more_before: true } };
  };
  const result = await client.getChatMessagesWindow(chatId, { teamId, direction: 'latest', limit: 100, preferCache: true });
  assert.equal(result.messages[0]?.content, 'Encrypted Team reply');
  assert.equal(result.serverMessageCount, 2);
  assert.equal(result.hasMoreBefore, true);
  assert.match(seen[0] ?? '', new RegExp(`/v1/chats/${chatId}/messages/window\\?`));
  assert.match(seen[0] ?? '', new RegExp(`team_id=${teamId}`));
  const cached=loadSyncCache(teamId)!;
  assert.equal(cached.chats[0]?.messages.length,2);
  assert.deepEqual(cached.chats[0]?.messages.map(raw=>JSON.parse(raw).id),['older-message','remote-message']);
  assert.doesNotMatch(JSON.stringify(cached),/Older Team message|Encrypted Team reply/);
  const offline=await client.getChatMessages(chatId,{teamId,preferCache:true});
  assert.deepEqual(offline.messages.map(message=>message.content),['Older Team message','Encrypted Team reply']);
  internals.http.get = async () => ({ok:true,status:200,data:{messages:[JSON.parse(cached.chats[0]!.messages[0]!)],
    has_more_before:true,server_message_count:1}});
  await client.getChatMessagesWindow(chatId,{teamId,preferCache:true});
  assert.deepEqual(loadSyncCache(teamId)!.chats[0]!.messages.map(raw=>JSON.parse(raw).id),['older-message'],
    'a deleted confirmed tail must also be removed from the offline cache');

  let release!: (response: unknown) => void;
  internals.http.get = () => new Promise(resolve => { release = resolve; });
  const staleRefresh = client.getChatMessagesWindow(chatId, { teamId, preferCache: true });
  await waitFor(() => !!release);
  client.setActiveTeamId(`other-${suffix}`);
  release({ ok: true, status: 200, data: { messages: [] } });
  await assert.rejects(staleRefresh, /Chat workspace changed/);

  client.setActiveTeamId(teamId);
  release = undefined as unknown as (response: unknown) => void;
  const staleAccountRefresh = client.getChatMessagesWindow(chatId, { teamId, preferCache: true });
  await waitFor(() => !!release);
  internals.session.hashedEmail = `changed-${suffix}`;
  release({ ok: true, status: 200, data: { messages: [] } });
  await assert.rejects(staleAccountRefresh, /Chat workspace changed/);
});

// contract-test: supporting surface=cli assertions=teams.chat.encrypted-until-invoked,teams.collaboration.realtime-team-sync
it('keeps encrypted Team chat metadata for bounded cross-member reads after an ordinary confirmed send', async () => {
  const teamId = 'team-retained-cache';
  const chatId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  const session = testSession(teamId);
  const teamKey = randomBytes(32), chatKey = randomBytes(32);
  const ownerRow = { id: 'durable-owner', client_message_id: 'owner-client-id', chat_id: chatId,
    role: 'user', created_at: 1, encrypted_content: await encryptWithAesGcmCombined('Owner phrase', chatKey),
    encrypted_sender_name: await encryptWithAesGcmCombined('Owner', chatKey) };
  saveLocalTeamKey(session.hashedEmail, teamId, bytesToBase64(teamKey));
  saveSyncCache({ syncedAt: Date.now(), totalChatCount: 1, loadedChatCount: 1,
    chats: [{ details: { id: chatId, encrypted_chat_key: await encryptBytesWithAesGcm(chatKey, teamKey),
      messages_v: 1, title_v: 0, draft_v: 0 }, messages: [JSON.stringify(ownerRow)] }],
    embeds: [], embedKeys: [] }, teamId);
  const client = new OpenMatesClient({ apiUrl: 'http://127.0.0.1', session });
  const originalGetMessages = client.getChatMessages.bind(client);
  let sentEnvelope: Record<string, unknown> | null = null;
  const waiters = new Map<string, Array<{ match: (value: unknown) => boolean; resolve: (frame: unknown) => void }>>();
  const emit = (type: string, payload: Record<string, unknown>) => {
    const pending = waiters.get(type) ?? [];
    for (const waiter of pending) if (waiter.match(payload)) waiter.resolve({ type, payload });
    waiters.delete(type);
  };
  const ws = {
    waitForRecoveryOutputDiscovery: async () => {},
    waitForMessage: (type: string, match: (value: unknown) => boolean = () => true) =>
      new Promise(resolve => { const pending = waiters.get(type) ?? [];pending.push({ match, resolve });waiters.set(type, pending); }),
    send: () => {},
    sendAsync: async (type: string, payload: Record<string, unknown>) => {
      if (type === 'team_notification_preview_capabilities')
        emit('team_notification_preview_capabilities_result', { request_id: payload.request_id, recipient_count: 0 });
      if (type === 'chat_turn_preflight')
        emit('chat_turn_preflight_ack', { turn_id: payload.turn_id, preflight_id: 'durable-preflight', committed_messages_v: 2 });
      if (type === 'chat_message_added') {
        sentEnvelope = payload.message as Record<string, unknown>;
        emit('chat_message_confirmed', { chat_id: chatId, message_id: sentEnvelope.message_id });
      }
    },
    onMessageType: () => () => {},
    onClose: () => () => {},
    close: () => {},
  };
  const internals = client as unknown as {
    ownTeamSenderName: () => Promise<string>;
    getChatMessages: typeof client.getChatMessages;
    openWsClient: () => Promise<unknown>;
    http: { get: (url: string) => Promise<unknown> };
  };
  internals.ownTeamSenderName = async () => 'Maya';
  internals.getChatMessages = (query, options) => originalGetMessages(query, { ...options, preferCache: true });
  internals.openWsClient = async () => ({ ws, session, ownerId: 'member-user-id' });
  internals.http.get = async (url) => {
    assert.match(url, /\/messages\/window\?/);
    assert.ok(sentEnvelope);
    return { ok: true, status: 200, data: { messages: [ownerRow, {
      id: 'durable-member', client_message_id: sentEnvelope.client_message_id, chat_id: chatId,
      role: 'user', created_at: 2, encrypted_content: sentEnvelope.encrypted_content,
      encrypted_sender_name: sentEnvelope.encrypted_sender_name,
    }], server_message_count: 2, has_more_before: false } };
  };

  const sent = await client.sendMessage({ chatId, message: 'Member phrase', piiDetection: false, memorySnapshot: [] });
  assert.ok(sent.userMessageId);
  assert.equal(loadSyncCache(teamId)?.chats[0]?.messages.length, 1);
  const refreshed = await client.getChatMessagesWindow(chatId, { teamId, preferCache: true });
  assert.deepEqual(refreshed.messages.map(message => message.content), ['Owner phrase', 'Member phrase']);
  assert.equal(refreshed.messages[1]?.clientMessageId, sent.userMessageId);
});

// contract-test: supporting surface=cli assertions=teams.lifecycle.encrypted-profiled
it("loads Team member profiles locally and writes only ciphertext for own profile", async () => {
  const key = randomBytes(32);
  const session = testSession("team-profile");
  const encrypted = await encryptWithAesGcmCombined(JSON.stringify({ display_name: "Alice", avatar: "flower" }), key);
  saveLocalTeamKey(session.hashedEmail, "team-profile", bytesToBase64(key));
  await withServer((request, body) => {
    if (request.url === "/v1/teams/team-profile/members" && request.method === "GET")
      return { members: [{ user_id: "alice-id", hashed_user_id: "alice-hash", role: "owner", encrypted_member_profile: encrypted }] };
    if (request.url === "/v1/teams/team-profile/members/alice-id" && request.method === "GET")
      return { member: { user_id: "alice-id", role: "owner", encrypted_member_profile: encrypted } };
    if (request.url === "/v1/teams/team-profile/members/me/profile" && request.method === "PATCH")
      return { member: { user_id: "alice-id", role: "owner", encrypted_member_profile: (body as Record<string, unknown>).encrypted_member_profile } };
    return {};
  }, async (apiUrl, seen) => {
    const client = new OpenMatesClient({ apiUrl, session });
    assert.equal((await client.listTeamMembers("team-profile"))[0]?.profile?.display_name, "Alice");
    assert.equal((await client.getTeamMember("team-profile", "alice-id")).profile?.avatar, "flower");
    const updated = await client.updateOwnTeamMemberProfile("team-profile", { display_name: "Alice B", avatar: "star" });
    assert.equal(updated.profile?.display_name, "Alice B");
    const patch = seen.find((row) => row.method === "PATCH")?.body as Record<string, unknown>;
    assert.deepEqual(Object.keys(patch), ["encrypted_member_profile"]);
    assert.equal(typeof patch.encrypted_member_profile, "string");
    assert.doesNotMatch(JSON.stringify(patch), /Alice B|star|display_name|avatar/);
  });
});

// contract-test: supporting surface=cli assertions=teams.security.join-policy
it("reads and updates only the supported Team security policy fields", async () => {
  await withServer((request, body) => {
    if (request.method === "GET") return { security_policy: {
      restrict_email_domains: true, allowed_email_domains: ["example.org"],
      require_invite_link_approval: true, require_strong_auth: true,
    } };
    return { security_policy: body };
  }, async (apiUrl, seen) => {
    const client = new OpenMatesClient({ apiUrl, session: testSession("team-1") });
    const policy = await client.getTeamSecurity("team-1");
    assert.deepEqual(policy.allowed_email_domains, ["example.org"]);
    await client.updateTeamSecurity("team-1", { ...policy, require_strong_auth: false });
    assert.deepEqual(seen.map((row) => [row.method, row.url]), [
      ["GET", "/v1/teams/team-1/security"], ["PATCH", "/v1/teams/team-1/security"],
    ]);
    assert.deepEqual(Object.keys(seen[1]!.body as Record<string, unknown>).sort(),
      ["restrict_email_domains", "allowed_email_domains", "require_invite_link_approval", "require_strong_auth"].sort());
  });
});

// contract-test: supporting surface=cli assertions=teams.lifecycle.encrypted-profiled
it("does not send a profile mutation after Team context changes during key loading", async () => {
  await withServer(() => ({}), async (apiUrl, seen) => {
    const client = new OpenMatesClient({ apiUrl, session: testSession("team-1") });
    let releaseKey!: (key: Uint8Array) => void;
    (client as unknown as { loadTeamKeyBytes: () => Promise<Uint8Array> }).loadTeamKeyBytes =
      () => new Promise((resolve) => { releaseKey = resolve; });
    const pending = client.updateOwnTeamMemberProfile("team-1", { display_name: "Alice" });
    client.setActiveTeamId("team-2");
    releaseKey(randomBytes(32));
    await assert.rejects(pending, /Account or Team changed/);
    assert.ok(!seen.some((row) => row.method === "PATCH"));
  });
});

// contract-test: supporting surface=cli assertions=teams.workspace.surface-parity
it("discards a deferred Team list from an old account before pruning the new owner's artifacts", async () => {
  const suffix = randomBytes(6).toString("hex"), oldTeam = `old-${suffix}`, newTeam = `new-${suffix}`;
  const oldSession = { ...testSession(oldTeam), hashedEmail: `old-account-${suffix}`, sessionId: `old-session-${suffix}` };
  const newSession = { ...testSession(newTeam), hashedEmail: `new-account-${suffix}`, sessionId: `new-session-${suffix}`, masterKeyExportedB64: Buffer.alloc(32, 4).toString("base64") };
  const key = bytesToBase64(randomBytes(32));
  saveLocalTeamKey(newSession.hashedEmail, newTeam, key);
  saveSyncCache({ syncedAt: 123, totalChatCount: 0, loadedChatCount: 0, chats: [], embeds: [], embedKeys: [] }, newTeam);
  const client = new OpenMatesClient({ apiUrl: "http://127.0.0.1", session: oldSession });
  let release!: (value: unknown) => void;
  const internals = client as unknown as { session: OpenMatesSession; http: { get: () => Promise<unknown> } };
  internals.http.get = () => new Promise((resolve) => { release = resolve; });
  const pending = client.listTeams();
  internals.session = newSession;
  release({ ok: true, status: 200, data: { teams: [{ team_id: oldTeam }] } });
  await assert.rejects(pending, /Account changed while loading Teams/);
  assert.equal(loadLocalTeamKey(newSession.hashedEmail, newTeam), key);
  assert.equal(loadSyncCache(newTeam)?.syncedAt, 123);
  assert.equal(client.getActiveTeamId(), newTeam);
});

// contract-test: supporting surface=cli assertions=teams.workspace.surface-parity
it("accepts a Team switch within the same owner while a Team list is pending", async () => {
  const suffix = randomBytes(6).toString("hex"), selectedTeam = `selected-${suffix}`;
  const client = new OpenMatesClient({ apiUrl: "http://127.0.0.1", session: testSession(null) });
  let release!: (value: unknown) => void;
  const internals = client as unknown as { http: { get: () => Promise<unknown> } };
  internals.http.get = () => new Promise((resolve) => { release = resolve; });
  const pending = client.listTeams();
  client.setActiveTeamId(selectedTeam);
  release({ ok: true, status: 200, data: { teams: [{ team_id: selectedTeam }] } });
  assert.equal((await pending)[0]?.team_id, selectedTeam);
  assert.equal(client.getActiveTeamId(), selectedTeam);
});

// contract-test: supporting surface=cli assertions=teams.workspace.surface-parity
it("rejects a Team selection when the account switches during cached key loading", async () => {
  const suffix = randomBytes(6).toString("hex"), oldTeam = `old-${suffix}`, newTeam = `new-${suffix}`;
  const oldSession = { ...testSession(oldTeam), hashedEmail: `old-account-${suffix}`, sessionId: `old-session-${suffix}` };
  const newSession = { ...testSession(newTeam), hashedEmail: `new-account-${suffix}`, sessionId: `new-session-${suffix}` };
  const client = new OpenMatesClient({ apiUrl: "http://127.0.0.1", session: oldSession });
  const internals = client as unknown as {
    session: OpenMatesSession;
    http: { get: () => Promise<unknown> };
    cacheTeamKeyFromRecord: () => Promise<void>;
  };
  internals.http.get = async () => ({ ok: true, status: 200, data: { team: { team_id: oldTeam } } });
  internals.cacheTeamKeyFromRecord = async () => {
    // A cache hit still yields before getTeam resumes and Settings applies the selection.
    queueMicrotask(() => { internals.session = newSession; });
  };
  const pendingSelection = (async () => {
    const team = await client.getTeam(oldTeam);
    client.setActiveTeamId(team.team_id);
  })();
  await assert.rejects(pendingSelection, /Account changed while loading Team/);
  assert.equal(client.getActiveTeamId(), newTeam);
});

after(() => {
  if (originalHome === undefined) delete process.env.HOME;
  else process.env.HOME = originalHome;
  rmSync(tempHome, { recursive: true, force: true });
});

function testSession(activeTeamId: string | null = null): OpenMatesSession {
  return {
    apiUrl: "http://127.0.0.1",
    sessionId: "session-1",
    wsToken: "x",
    cookies: { auth_refresh_token: "x" },
    masterKeyExportedB64: Buffer.alloc(32).toString("base64"),
    hashedEmail: "hashed-email",
    userEmailSalt: "salt",
    emailEncryptionKeyB64: Buffer.alloc(32).toString("base64"),
    createdAt: Date.now(),
    authorizerDeviceName: "test-device",
    autoLogoutMinutes: null,
    activeTeamId,
  };
}

async function withServer(
  handler: (request: IncomingMessage, body: unknown) => unknown,
  run: (apiUrl: string, seen: SeenRequest[]) => Promise<void>,
): Promise<void> {
  const seen: SeenRequest[] = [];
  const server = createServer((request: IncomingMessage, response: ServerResponse) => {
    let raw = "";
    request.setEncoding("utf8");
    request.on("data", (chunk) => { raw += chunk; });
    request.on("end", () => {
      const body = raw ? JSON.parse(raw) : undefined;
      seen.push({ method: request.method, url: request.url, body });
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify(handler(request, body)));
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    await run(`http://127.0.0.1:${address.port}`, seen);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
}

async function buildProjectRecord(masterKey: Uint8Array, projectId: string, slug: string): Promise<ProjectRecord> {
  const projectKey = randomBytes(32);
  const slugMetadata = await buildEncryptedObjectSlugMetadata({ value: slug, encryptionKey: projectKey, lookupKey: masterKey });
  return {
    project_id: projectId,
    encrypted_project_key: await encryptBytesWithAesGcm(projectKey, masterKey),
    encrypted_slug: slugMetadata.encrypted_slug,
    slug_lookup_hash: slugMetadata.slug_lookup_hash,
    encrypted_name: await encryptWithAesGcmCombined(slug, projectKey),
    version: 1,
  };
}

async function buildWorkflowRecord(masterKey: Uint8Array, workflowId: string, slug: string): Promise<WorkflowDetail> {
  const slugMetadata = await buildEncryptedObjectSlugMetadata({ value: slug, encryptionKey: masterKey, lookupKey: masterKey });
  return {
    id: workflowId,
    slug,
    encrypted_slug: slugMetadata.encrypted_slug,
    slug_lookup_hash: slugMetadata.slug_lookup_hash,
    title: slug,
    status: "draft",
    enabled: false,
    current_version_id: "version-1",
    created_at: 1,
    updated_at: 1,
    graph: { version: 1, trigger_node_id: "trigger", nodes: [{ id: "trigger", type: "manual_trigger" }] },
  };
}

describe("OpenMatesClient Teams V1", () => {
  // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
  it("resolves active, override, and personal team context", () => {
    const client = new OpenMatesClient({ apiUrl: "http://127.0.0.1", session: testSession("team-active") });

    assert.equal(client.resolveTeamContext(), "team-active");
    assert.equal(client.resolveTeamContext({ teamId: "team-override" }), "team-override");
    assert.equal(client.resolveTeamContext({ personal: true }), null);
  });

  // contract-test: direct surface=cli assertions=cli.surface.semantic-parity
  it("adds team context to team-aware resource list routes", async () => {
    await withServer(
      () => ({ tasks: [], workflows: [] }),
      async (apiUrl, seen) => {
        const client = new OpenMatesClient({ apiUrl, session: testSession("team-active") });

        await client.listUserTasks();
        await client.listUserTasks({ personal: true });
        await client.listWorkflows({ teamId: "team-override" });

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["GET", "/v1/user-tasks?limit=100&paginate=true&team_id=team-active"],
          ["GET", "/v1/user-tasks?limit=100&paginate=true"],
          ["GET", "/v1/workflows?team_id=team-override"],
        ]);
      },
    );
  });

  // contract-test: direct surface=cli assertions=cli.surface.semantic-parity,teams.name.transient-policy,teams.billing.context-parity
  it("calls team lifecycle, membership, and billing endpoints", async () => {
    await withServer(
      (request, body) => {
        if (request.url === "/v1/teams" && request.method === "GET") return { teams: [{ team_id: "team-1" }] };
        if (request.url === "/v1/teams/name-approval" && request.method === "POST") {
          assert.deepEqual(body, { name: 'acme' });
          return { approval_token: 'approved-acme', expires_at: 1000 };
        }
        if (request.url === "/v1/teams" && request.method === "POST") return { team: { team_id: (body as Record<string, unknown>).team_id, ...(body as Record<string, unknown>) } };
        if (request.url === "/v1/teams/team-1/invites") return { invite: { invite_id: "invite-1", ...(body as Record<string, unknown>) } };
        if (request.url === "/v1/teams/invites/invite-1/accept") return { access_request: { access_request_id: "access-1", status: "pending_access_approval" }, status_label: "Waiting for team access approval" };
        if (request.url === "/v1/teams/team-1/access-requests") return { access_requests: [{ access_request_id: "access-1" }] };
        if (request.url === "/v1/teams/team-1/access-requests/access-1/approve") return { membership: { role: "member", ...(body as Record<string, unknown>) } };
        if (request.url === "/v1/teams/team-1/access-requests/access-1/reject") return { success: true };
        if (request.url === "/v1/teams/invites/invite-1/decline") return { success: true };
        if (request.url === "/v1/teams/team-1/export") return { artifact: { schema: "openmates.team_export.v1" }, artifact_hash: "hash-1" };
        if (request.url === "/v1/teams/import") return { success: true, imported_rows: 1, ...(body as Record<string, unknown>) };
        if (request.url === "/v1/teams/team-1/members/user-1") return { membership: { user_id: "user-1", ...(body as Record<string, unknown>) } };
        if (request.url === "/v1/teams/team-1/billing") return { billing: { balance_credits: 10 } };
        if (request.url === "/v1/teams/team-1/billing/bank-transfer-orders") return { order_id: "bt_1", reference: "OMT-team-bt1" };
        return { success: true };
      },
      async (apiUrl, seen) => {
        const client = new OpenMatesClient({ apiUrl, session: testSession() });

        assert.equal((await client.listTeams())[0]?.team_id, "team-1");
        assert.equal(typeof (await client.createTeam({ teamId: "team-1", name: "Acme" })).team_id, "string");
        assert.equal(typeof (await client.createTeamInvite("team-1", { role: "viewer", recipient_email: "bob@example.com" })).invite_id, "string");
        assert.equal(((await client.acceptTeamInvite("invite-1")).access_request as Record<string, unknown>).status, "pending_access_approval");
        assert.equal((await client.listTeamAccessRequests("team-1"))[0]?.access_request_id, "access-1");
        assert.equal((await client.approveTeamAccessRequest("team-1", "access-1", "cipher-team-key")).role, "member");
        assert.equal((await client.rejectTeamAccessRequest("team-1", "access-1")).success, true);
        assert.equal((await client.declineTeamInvite("invite-1", "Bob@Example.com")).success, true);
        assert.equal((await client.exportTeamData("team-1")).artifact_hash, "hash-1");
        assert.equal((await client.importTeamData("team-1", { schema: "openmates.team_export.v1", rewrapped_with_destination_team_key: true })).success, true);
        assert.equal((await client.updateTeamMemberRole("team-1", "user-1", "admin")).role, "admin");
        assert.equal((await client.getTeamBilling("team-1")).balance_credits, 10);
        assert.equal((await client.createTeamBankTransferOrder("team-1", 110000)).order_id, "bt_1");

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["GET", "/v1/teams"],
          ["POST", "/v1/teams/name-approval"],
          ["POST", "/v1/teams"],
          ["POST", "/v1/teams/team-1/invites"],
          ["POST", "/v1/teams/invites/invite-1/accept"],
          ["GET", "/v1/teams/team-1/access-requests"],
          ["POST", "/v1/teams/team-1/access-requests/access-1/approve"],
          ["POST", "/v1/teams/team-1/access-requests/access-1/reject"],
          ["POST", "/v1/teams/invites/invite-1/decline"],
          ["POST", "/v1/teams/team-1/export"],
          ["POST", "/v1/teams/import"],
          ["PATCH", "/v1/teams/team-1/members/user-1"],
          ["GET", "/v1/teams/team-1/billing"],
          ["POST", "/v1/teams/team-1/billing/bank-transfer-orders"],
        ]);
        // contract-test: direct surface=cli assertions=teams.name.transient-policy
        const createBody = seen[2]?.body as Record<string, unknown>;
        assert.equal(createBody.name_approval_token, 'approved-acme');
        assert.equal('name' in createBody, false);
        assert.equal(typeof createBody.team_id, "string");
        assert.equal(typeof createBody.encrypted_name, "string");
        assert.equal(typeof createBody.encrypted_team_key, "string");
        assert.equal(typeof createBody.encrypted_zero_balance, "string");
        assert.equal(typeof createBody.created_at, "number");
        assert.equal(typeof (seen[3]?.body as Record<string, unknown>).invite_id, "string");
        assert.equal(typeof (seen[3]?.body as Record<string, unknown>).created_at, "number");
        assert.equal((seen[3]?.body as Record<string, unknown>).recipient_email, "bob@example.com");
        assert.equal(typeof (seen[3]?.body as Record<string, unknown>).encrypted_invite_team_key, "string");
        assert.equal(typeof (seen[3]?.body as Record<string, unknown>).invite_key_kdf_context, "object");
        assert.equal((seen[6]?.body as Record<string, unknown>).encrypted_team_key, "cipher-team-key");
        assert.equal((seen[8]?.body as Record<string, unknown>).verified_email, "bob@example.com");
        assert.equal((seen[13]?.body as Record<string, unknown>).credits_amount, 110000);
        assert.equal(typeof (seen[13]?.body as Record<string, unknown>).email_encryption_key, "string");
      },
    );
  });

  // contract-test: direct surface=cli assertions=cli.surface.semantic-parity,teams.name.transient-policy,teams.invites.fragment-key-web-flow
  it("encrypts invite team keys and uploads recipient wrappers on accept", async () => {
    let encryptedInviteTeamKey = "";
    let inviteKeyKdfContext: Record<string, unknown> | undefined;

    await withServer(
      (request, body) => {
        if (request.url === "/v1/teams/name-approval" && request.method === "POST") {
          assert.deepEqual(body, { name: 'secret team' });
          return { approval_token: 'approved-secret-team', expires_at: 1000 };
        }
        if (request.url === "/v1/teams" && request.method === "POST") return { team: { team_id: (body as Record<string, unknown>).team_id, ...(body as Record<string, unknown>) } };
        if (request.url === "/v1/teams/team-secret/invites") {
          const payload = body as Record<string, unknown>;
          encryptedInviteTeamKey = String(payload.encrypted_invite_team_key ?? "");
          inviteKeyKdfContext = payload.invite_key_kdf_context as Record<string, unknown> | undefined;
          return { invite: { invite_id: payload.invite_id, encrypted_invite_team_key: encryptedInviteTeamKey, invite_key_kdf_context: inviteKeyKdfContext } };
        }
        if (request.url === "/v1/teams/invites/invite-secret/preview") {
          assert.deepEqual(body, { verified_email: 'bob@example.com' });
          return { invite: { invite_id: "invite-secret", encrypted_invite_team_key: encryptedInviteTeamKey, invite_key_kdf_context: inviteKeyKdfContext, hashed_recipient_email: 'synthetic-hash' } };
        }
        if (request.url === "/v1/teams/invites/invite-secret/accept") return { access_request: { access_request_id: "access-secret", status: "pending_access_approval", ...(body as Record<string, unknown>) }, status_label: "Waiting for team access approval" };
        if (request.url === "/v1/teams/team-secret/access-requests/access-secret/approve") return { membership: { status: "active", role: "member" } };
        return { success: true };
      },
      async (apiUrl, seen) => {
        const client = new OpenMatesClient({ apiUrl, session: testSession() });

        await client.createTeam({ teamId: "team-secret", name: "Secret Team" });
        const invite = await client.createTeamInvite("team-secret", { invite_id: "invite-secret", role: "member", recipient_email: "bob@example.com" });
        assert.equal(typeof invite.invite_secret, "string");
        assert.match(String(invite.invite_url), /#key=/);
        const accept = await client.acceptTeamInvite("invite-secret", { inviteSecret: String(invite.invite_secret), recipientEmail: "bob@example.com" });
        const accessRequest = accept.access_request as Record<string, unknown>;
        const approved = await client.approveTeamAccessRequest("team-secret", String(accessRequest.access_request_id));

        assert.equal(accessRequest.status, "pending_access_approval");
        assert.equal(approved.status, "active");
        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["POST", "/v1/teams/name-approval"],
          ["POST", "/v1/teams"],
          ["POST", "/v1/teams/team-secret/invites"],
          ["POST", "/v1/teams/invites/invite-secret/preview"],
          ["POST", "/v1/teams/invites/invite-secret/accept"],
          ["POST", "/v1/teams/team-secret/access-requests/access-secret/approve"],
        ]);
        assert.equal((seen[1]?.body as Record<string, unknown>).name_approval_token, 'approved-secret-team');
        assert.equal(typeof (seen[2]?.body as Record<string, unknown>).encrypted_invite_team_key, "string");
        assert.equal(typeof (seen[2]?.body as Record<string, unknown>).invite_key_kdf_context, "object");
        assert.equal(typeof (seen[4]?.body as Record<string, unknown>).encrypted_team_key, "string");
        assert.equal((seen[4]?.body as Record<string, unknown>).verified_email, 'bob@example.com');
        assert.equal((seen[5]?.body as Record<string, unknown>).encrypted_team_key, undefined);
      },
    );
  });

  // contract-test: direct surface=cli assertions=teams.invites.fragment-key-web-flow,teams.name.transient-policy
  it("encrypts a link invite without a recipient and requires verified email to accept", async () => {
    const inviteState: { payload?: Record<string, unknown> } = {};
    await withServer(
      (request, body) => {
        if (request.url === '/v1/teams/name-approval') return { approval_token: 'approved-link-team', expires_at: 1000 };
        if (request.url === '/v1/teams' && request.method === 'POST') return { team: { team_id: 'team-link', ...(body as Record<string, unknown>) } };
        if (request.url === '/v1/teams/team-link/invites') {
          inviteState.payload = body as Record<string, unknown>;
          return { invite: { invite_id: 'invite-link' } };
        }
        if (request.url === '/v1/teams/invites/invite-link/preview') {
          assert.deepEqual(body, { verified_email: 'joiner@example.com' });
          return { invite: {
            invite_id: 'invite-link', kind: 'link',
            encrypted_invite_team_key: inviteState.payload?.encrypted_invite_team_key,
            invite_key_kdf_context: inviteState.payload?.invite_key_kdf_context,
          } };
        }
        if (request.url === '/v1/teams/invites/invite-link/accept') {
          const payload = body as Record<string, unknown>;
          assert.equal(payload.verified_email, 'joiner@example.com');
          assert.equal(typeof payload.encrypted_team_key, 'string');
          return { access_request: { access_request_id: 'link-access', status: 'pending_access_approval' } };
        }
        throw new Error(`Unexpected request ${request.method} ${request.url}`);
      },
      async (apiUrl, seen) => {
        const client = new OpenMatesClient({ apiUrl, session: testSession() });
        await client.createTeam({ teamId: 'team-link', name: 'Link Team' });
        const invite = await client.createTeamInvite('team-link', { invite_id: 'invite-link', role: 'member' });
        assert.equal(typeof invite.invite_secret, 'string');
        assert.match(String(invite.invite_url), /#key=/);
        assert.equal(typeof inviteState.payload?.encrypted_invite_team_key, 'string');
        assert.equal(typeof inviteState.payload?.invite_key_kdf_context, 'object');
        assert.equal('invite_secret' in (inviteState.payload ?? {}), false);
        const accepted = await client.acceptTeamInvite('invite-link', {
          inviteSecret: String(invite.invite_secret), recipientEmail: 'Joiner@Example.com',
        });
        assert.equal((accepted.access_request as Record<string, unknown>).status, 'pending_access_approval');
        assert.deepEqual(seen.map(request => [request.method, request.url]), [
          ['POST', '/v1/teams/name-approval'],
          ['POST', '/v1/teams'],
          ['POST', '/v1/teams/team-link/invites'],
          ['POST', '/v1/teams/invites/invite-link/preview'],
          ['POST', '/v1/teams/invites/invite-link/accept'],
        ]);
      },
    );
  });

  // contract-test: direct surface=cli assertions=cli.slugs.encrypted-stable,cli.slugs.local-resolution-id-transport,cli.surface.semantic-parity
  it("moves supported workspace resources to a team with confirmation metadata", async () => {
    const session = testSession();
    const masterKey = Buffer.from(session.masterKeyExportedB64, "base64");
    const teamKey = randomBytes(32);
    const chatKey = randomBytes(32);
    const chatSlugMetadata = await buildEncryptedObjectSlugMetadata({ value: "chat slug", encryptionKey: chatKey, lookupKey: masterKey });
    const project = await buildProjectRecord(masterKey, "project-canonical", "project slug");
    const task = await buildCreateUserTaskInput(masterKey, { title: "Task title", slug: "task slug" }) as UserTaskRecord;
    task.task_id = "task-canonical";
    const planProjectKey = randomBytes(32);
    const plan = await buildCreateUserPlanInput(masterKey, {
      title: "Plan title",
      goal: "Move the plan",
      slug: "plan slug",
      linkedProjectIds: [project.project_id],
      linkedProjectKeys: [{ projectId: project.project_id, projectKey: planProjectKey }],
    }) as UserPlanRecord;
    plan.plan_id = "plan-canonical";
    const workflow = await buildWorkflowRecord(masterKey, "workflow-canonical", "workflow slug");
    saveLocalTeamKey(session.hashedEmail, "team-1", bytesToBase64(teamKey));
    saveSyncCache({
      syncedAt: Date.now(),
      totalChatCount: 1,
      loadedChatCount: 1,
      chats: [{
        details: {
          id: "chat-canonical",
          encrypted_chat_key: await encryptBytesWithAesGcm(chatKey, masterKey),
          encrypted_slug: chatSlugMetadata.encrypted_slug,
          title_v: 1,
          draft_v: 1,
          messages_v: 0,
        },
        messages: [],
      }],
      embeds: [],
      embedKeys: [],
    });

    await withServer(
      (request, body) => {
        if (request.url === "/v1/projects?include_archived=true") return { projects: [project] };
        if (request.url === "/v1/projects/project-canonical") return { project, folders: [], items: [] };
        if (request.url === "/v1/user-tasks?limit=100&paginate=true") return { tasks: [task] };
        if (request.url === "/v1/user-plans?active_only=false") return { plans: [plan] };
        if (request.url === "/v1/workflows") return { workflows: [workflow] };
        if (request.url === "/v1/workflows/workflow-canonical") return { workflow };
        return { moved: true, ...(body as Record<string, unknown>) };
      },
      async (apiUrl, seen) => {
        const client = new OpenMatesClient({ apiUrl, session });

        await client.moveWorkspaceToTeam("chat", "chat slug", "team-1");
        await client.moveWorkspaceToTeam("project", "project slug", "team-1");
        await client.moveWorkspaceToTeam("task", "task slug", "team-1");
        await client.moveWorkspaceToTeam("plan", "plan slug", "team-1");
        const workflowResult = await client.moveWorkspaceToTeam("workflow", "workflow slug", "team-1");

        assert.equal(workflowResult.team_id, "team-1");
        assert.equal(workflowResult.confirmed, true);
        const moveRequests = seen.filter((request) => request.method === "POST" && request.url?.endsWith("/move"));
        assert.deepEqual(moveRequests.map((request) => [request.method, request.url]), [
          ["POST", "/v1/chats/chat-canonical/move"],
          ["POST", "/v1/projects/project-canonical/move"],
          ["POST", "/v1/user-tasks/task-canonical/move"],
          ["POST", "/v1/user-plans/plan-canonical/move"],
          ["POST", "/v1/workflows/workflow-canonical/move"],
        ]);
        for (const request of moveRequests) {
          const payload = request.body as Record<string, unknown>;
          assert.equal(payload.team_id, "team-1");
          assert.equal(payload.confirmed, true);
          assert.equal(typeof payload.moved_at, "number");
          assert.equal(typeof payload.encrypted_slug, "string");
          assert.equal(typeof payload.slug_lookup_hash, "string");
          assert.equal("slug" in payload, false);
        }
        assert.equal(typeof (moveRequests[1]?.body as Record<string, unknown>).team_project_key_wrapper, "object");
      },
    );
  });
});
