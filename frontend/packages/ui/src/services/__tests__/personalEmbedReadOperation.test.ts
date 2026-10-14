/**
 * Verifies actual Personal resolver and child-repair interleavings.
 * Network and persistence gates model key-arrival reactivity without live data.
 * Strict child acceptance independently checks lineage and parent wrappers.
 * Scope/deadline cases prove stale operations cannot write or suppress new owners.
 * Browser coverage retains the real authenticated REST and reload proof.
 */
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { embedStore } from '../embedStore';
import { requestEmbedFromServerOnce, resolveEmbed } from '../embedResolver';
import { capturePersonalEmbedReadScope, runPersonalEmbedReadOperation } from '../personalEmbedReadOperation';
import { authStore } from '../../stores/authState';
import { userProfile } from '../../stores/userProfile';
import { activeChatStore } from '../../stores/activeChatStore';
import { beginAuthBootstrapReadiness, settleAuthBootstrapReadiness, failAuthBootstrapReadiness,
  observeAuthBootstrapFailure, recoverAuthBootstrapAfterConfirmedSession } from '../../stores/authBootstrapReadiness';
import { setActiveTeamContext } from '../../stores/teamStore';
import { chatDB } from '../db';
import * as parsingUtils from '../../message_parsing/utils';

const send = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
vi.mock('../websocketService', () => ({ webSocketService: { sendMessage: send } }));
vi.mock('../chatSyncService', () => ({ chatSyncService: { dispatchEvent: vi.fn() } }));
vi.mock('../../stores/teamStore', async () => {
  const { writable } = await import('svelte/store');
  const activeTeamId = writable<string | null>(null);
  return { activeTeamId, activeTeam: writable(null), activeTeamContext: writable({ team: null, teamId: null, epoch: 0 }),
    teamEnabled: writable(true), TEAMS_UPDATED_EVENT: 'test:teams-updated', TEAM_CONTEXT_CHANGED_EVENT: 'test:team-context',
    getActiveTeamContextSnapshot: () => ({ team: null, teamId: null, epoch: 0 }),
    isActiveTeamContext: () => true, notifyTeamsUpdated: () => {},
    setActiveTeamContext: () => activeTeamId.set(null) };
});
const deferred = () => { let release!: () => void; const promise = new Promise<void>(resolve => { release = resolve; }); return { promise, release }; };
const chat = '11111111-1111-1111-1111-111111111111';
const parent = '22222222-2222-2222-2222-222222222222';
let sequence = 0, child: string, rows: Map<string, any>, parentKeys: any[], fetchRead: ReturnType<typeof vi.fn>;
const recover = () => (embedStore as any).recoverMissingSourceChildren(parent,
  { content: JSON.stringify({ embed_ids: [child] }) }, chat, `hash-${chat}`, new Set());
const scope = (chatId = chat, embedId = child) => capturePersonalEmbedReadScope(chatId, embedId)!;
beforeEach(() => {
  settleAuthBootstrapReadiness(beginAuthBootstrapReadiness());
  vi.restoreAllMocks(); send.mockClear();
  child = `33333333-3333-3333-3333-${String(++sequence).padStart(12, '0')}`;
  authStore.set({ isAuthenticated: true, isInitialized: true });
  userProfile.update(p => ({ ...p, user_id: 'owner', account_id: 'account' }));
  setActiveTeamContext(null); activeChatStore.setActiveChat(chat);
  rows = new Map([[`embed:${parent}`, { embed_id: parent, hashed_chat_id: `hash-${chat}`,
    hashed_user_id: 'hash-owner', status: 'finished', encrypted_content: 'parent-cipher' }]]);
  parentKeys = [{ hashed_embed_id: `hash-${parent}`, hashed_user_id: 'hash-owner', key_type: 'master',
    hashed_chat_id: null, encrypted_embed_key: 'wrapped', created_at: 1 }];
  vi.spyOn(parsingUtils, 'computeSHA256').mockImplementation(async v => `hash-${v}`);
  vi.spyOn(chatDB, 'getChat').mockImplementation(async chat_id => ({ chat_id, team_id: null }) as any);
  vi.spyOn(embedStore, 'getRawEntry').mockImplementation(async ref => rows.get(ref) ?? null);
  vi.spyOn(embedStore, 'getEmbedKeyEntries').mockImplementation(async hash => hash === `hash-${parent}` ? parentKeys : []);
  vi.spyOn(embedStore, 'get').mockImplementation(async ref => rows.has(ref) ? { content: JSON.stringify({
    embed_ref: 'exact-ref', app_id: 'images', ...(ref === `embed:${parent}` ? { embed_ids: [child] } : {}),
  }) } : undefined);
  vi.spyOn(embedStore, 'storeEmbedKeys').mockImplementation(async (_keys, guard) => { guard?.(); });
  vi.spyOn(embedStore, 'putEncrypted').mockImplementation(async (ref, row, _type, _a, _b, options) => {
    options?.writeGuard?.(); rows.set(ref, row);
  });
  fetchRead = vi.fn().mockImplementation(async () => ({ ok: true, status: 200, json: async () => ({
    embed: { embed_id: child, parent_embed_id: parent, hashed_chat_id: `hash-${chat}`,
      hashed_user_id: 'hash-owner', status: 'finished', encrypted_content: 'cipher' }, embed_keys: parentKeys,
  }) }));
  vi.stubGlobal('fetch', fetchRead);
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('Personal recovery ownership through persistence', () => {
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery,chats.rendering.assistant-document-convergence
  it('waits through cached bootstrap and rejects optimistic auth before any ciphertext GET', async () => {
    const token = beginAuthBootstrapReadiness();
    const optimistic = recover();
    await vi.waitFor(() => expect(chatDB.getChat).toHaveBeenCalledTimes(1));
    expect(fetchRead).not.toHaveBeenCalled();
    authStore.set({ isAuthenticated: true, isInitialized: true });
    settleAuthBootstrapReadiness(token);
    await expect(optimistic).resolves.toEqual([]);
    expect(embedStore.putEncrypted).not.toHaveBeenCalled();
    await expect(recover()).resolves.toEqual([child]);
    expect(fetchRead).toHaveBeenCalledTimes(1);
    expect(embedStore.putEncrypted).toHaveBeenCalledTimes(1);
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it('keeps helper and resolver behind bootstrap without a WS escape on revoked auth', async () => {
    const token = beginAuthBootstrapReadiness();
    const helper = recover(), resolver = requestEmbedFromServerOnce(child, 'bootstrap', { chatId: chat });
    await vi.waitFor(() => expect(chatDB.getChat).toHaveBeenCalledTimes(2));
    authStore.set({ isAuthenticated: false, isInitialized: true });
    settleAuthBootstrapReadiness(token);
    await expect(helper).resolves.toEqual([]); await expect(resolver).resolves.toBe(false);
    expect(fetchRead).not.toHaveBeenCalled(); expect(embedStore.putEncrypted).not.toHaveBeenCalled();
    expect(send).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it('fails early bootstrap errors closed for helper and resolver without changing settled state', async () => {
    const token = beginAuthBootstrapReadiness();
    const helper = recover();
    await vi.waitFor(() => expect(chatDB.getChat).toHaveBeenCalledTimes(1));
    const failure = new Error('crypto initialization failed');
    await expect(observeAuthBootstrapFailure(token, async () => { throw failure; })).rejects.toBe(failure);
    await expect(helper).resolves.toEqual([]);
    await expect(requestEmbedFromServerOnce(child, 'failed-bootstrap', { chatId: chat })).resolves.toBe(false);
    expect(fetchRead).not.toHaveBeenCalled(); expect(send).not.toHaveBeenCalled();
    // A completed check is not revoked by later unrelated onMount failure observation.
    const settled = beginAuthBootstrapReadiness(); settleAuthBootstrapReadiness(settled);
    await expect(observeAuthBootstrapFailure(settled, async () => { throw failure; })).rejects.toBe(failure);
    await expect(requestEmbedFromServerOnce(child, 'settled', { chatId: chat })).resolves.toBe(true);
    expect(fetchRead).toHaveBeenCalledTimes(1);
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it('bounds bootstrap waits with the existing deadline and prevents late work after settlement', async () => {
    vi.useFakeTimers(); const token = beginAuthBootstrapReadiness(), operation = vi.fn();
    const waiting = runPersonalEmbedReadOperation(scope(), operation);
    const rejection = expect(waiting).rejects.toThrow('timed out');
    await vi.advanceTimersByTimeAsync(8000); await rejection;
    expect(operation).not.toHaveBeenCalled();
    settleAuthBootstrapReadiness(token); await vi.advanceTimersByTimeAsync(0);
    expect(operation).not.toHaveBeenCalled();
    await expect(runPersonalEmbedReadOperation(scope(), operation)).resolves.toBeUndefined();
    expect(operation).toHaveBeenCalledTimes(1);
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it('does not let an old page settle or fail a newer bootstrap token', async () => {
    const old = beginAuthBootstrapReadiness(), current = beginAuthBootstrapReadiness(), operation = vi.fn();
    const waiting = runPersonalEmbedReadOperation(scope(), operation);
    settleAuthBootstrapReadiness(old); failAuthBootstrapReadiness(old);
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(operation).not.toHaveBeenCalled();
    settleAuthBootstrapReadiness(current); await waiting;
    expect(operation).toHaveBeenCalledTimes(1);
    failAuthBootstrapReadiness(current);
    await expect(runPersonalEmbedReadOperation(scope(), operation)).resolves.toBeUndefined();
    expect(operation).toHaveBeenCalledTimes(2);
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it.each(['confirmed-login', 'confirmed-session-check'])('recovers a failed same-page bootstrap after %s without equating old auth', async () => {
    const token = beginAuthBootstrapReadiness(); failAuthBootstrapReadiness(token);
    const old = scope();
    await expect(runPersonalEmbedReadOperation(old, vi.fn())).rejects.toThrow('did not settle');
    authStore.set({ isAuthenticated: true, isInitialized: true });
    recoverAuthBootstrapAfterConfirmedSession();
    expect(() => runPersonalEmbedReadOperation(old, vi.fn())).toThrow('scope changed');
    await expect(recover()).resolves.toEqual([child]);
    expect(fetchRead).toHaveBeenCalledTimes(1); expect(embedStore.putEncrypted).toHaveBeenCalledTimes(1);
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it('does not infer bootstrap recovery from revoked or offline optimistic auth snapshots', async () => {
    const token = beginAuthBootstrapReadiness(); failAuthBootstrapReadiness(token);
    authStore.set({ isAuthenticated: false, isInitialized: true });
    await expect(recover()).resolves.toEqual([]);
    // Existing offline fallback may restore local authentication, without a confirmed-success notification.
    authStore.set({ isAuthenticated: true, isInitialized: true });
    await expect(recover()).resolves.toEqual([]);
    expect(fetchRead).not.toHaveBeenCalled(); expect(send).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it('never lets a confirmed session notification release a newer pending mount', async () => {
    const old = beginAuthBootstrapReadiness(); failAuthBootstrapReadiness(old);
    const current = beginAuthBootstrapReadiness(), operation = vi.fn();
    const waiting = runPersonalEmbedReadOperation(scope(), operation);
    recoverAuthBootstrapAfterConfirmedSession();
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(operation).not.toHaveBeenCalled();
    settleAuthBootstrapReadiness(current); await waiting;
    expect(operation).toHaveBeenCalledTimes(1);
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it('retains the settled Personal REST miss WebSocket policy', async () => {
    fetchRead.mockResolvedValue({ ok: false, status: 404 });
    await expect(requestEmbedFromServerOnce(child, 'settled-rest-miss', { chatId: chat })).resolves.toBe(true);
    expect(fetchRead).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith('request_embed', { embed_id: child, chat_id: chat, team_id: null });
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery,chats.rendering.assistant-document-convergence
  it.each(['helper-first', 'resolver-first'])('coalesces %s while parent keys persist', async ordering => {
    const entered = deferred(), released = deferred();
    vi.mocked(embedStore.storeEmbedKeys).mockImplementation(async (_keys, guard) => {
      guard?.(); entered.release(); await released.promise; guard?.();
    });
    const first = ordering === 'helper-first' ? recover() : requestEmbedFromServerOnce(child, 'first', { chatId: chat });
    await entered.promise;
    const second = ordering === 'helper-first' ? requestEmbedFromServerOnce(child, 'second', { chatId: chat }) : recover();
    await vi.waitFor(() => expect(chatDB.getChat).toHaveBeenCalledTimes(2));
    expect(fetchRead).toHaveBeenCalledTimes(1);
    released.release(); const results = await Promise.all([first, second]);
    expect(results).toContainEqual([child]); expect(results).toContain(true);
    expect(fetchRead).toHaveBeenCalledTimes(1); expect(embedStore.putEncrypted).toHaveBeenCalledTimes(1);
    expect(send).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery,chats.rendering.assistant-document-convergence
  it('retries a boot read after the same-owner authoritative auth snapshot replaces optimistic auth', async () => {
    const entered = deferred(), responseReady = deferred();
    const realResponse = fetchRead.getMockImplementation()!;
    fetchRead.mockImplementationOnce(async (...args) => {
      entered.release(); await responseReady.promise; return realResponse(...args);
    });
    const optimistic = recover(); await entered.promise;
    // Mirrors +page's cached login followed by performAuthCheck's successful snapshot update.
    authStore.set({ isAuthenticated: true, isInitialized: true });
    responseReady.release();
    await expect(optimistic).resolves.toEqual([]);
    expect(embedStore.putEncrypted).not.toHaveBeenCalled();
    expect(rows.has(`embed:${child}`)).toBe(false);
    await expect(recover()).resolves.toEqual([child]);
    expect(fetchRead).toHaveBeenCalledTimes(2);
    expect(embedStore.putEncrypted).toHaveBeenCalledTimes(1);
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it('allows a fresh auth generation through the public resolver while old persistence is pending', async () => {
    const entered = deferred(), released = deferred();
    vi.mocked(embedStore.storeEmbedKeys).mockImplementation(async (_keys, guard) => {
      guard?.(); entered.release(); await released.promise; guard?.();
    });
    const first = requestEmbedFromServerOnce(child, 'old-auth', { chatId: chat }); await entered.promise;
    authStore.set({ isAuthenticated: true, isInitialized: true });
    const second = requestEmbedFromServerOnce(child, 'fresh-auth', { chatId: chat });
    await vi.waitFor(() => expect(fetchRead).toHaveBeenCalledTimes(2));
    released.release(); await expect(first).resolves.toBe(false); await expect(second).resolves.toBe(true);
    expect(embedStore.putEncrypted).toHaveBeenCalledTimes(1); expect(send).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it('expires settled Personal cooldown and refetches instead of retaining a response', async () => {
    vi.useFakeTimers();
    await expect(requestEmbedFromServerOnce(child, 'first', { chatId: chat })).resolves.toBe(true);
    rows.delete(`embed:${child}`);
    await expect(requestEmbedFromServerOnce(child, 'cooldown', { chatId: chat })).resolves.toBe(false);
    expect(fetchRead).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(10_000);
    await expect(requestEmbedFromServerOnce(child, 'expired', { chatId: chat })).resolves.toBe(true);
    expect(fetchRead).toHaveBeenCalledTimes(2);
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it('rechecks a stale resolver miss after context capture instead of refetching', async () => {
    rows.set(`embed:${child}`, { embed_id: child, encrypted_content: 'cipher' });
    vi.mocked(embedStore.get).mockResolvedValueOnce(undefined);
    await expect(resolveEmbed(child, { chatId: chat })).resolves.toBeNull();
    await vi.waitFor(() => expect(vi.mocked(embedStore.get).mock.calls.length).toBeGreaterThanOrEqual(2));
    expect(fetchRead).not.toHaveBeenCalled(); expect(send).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it.each(['lineage', 'owner', 'source', 'wrapper'])('does not accept a generic-first child with invalid %s', async invalid => {
    const entered = deferred(), released = deferred();
    vi.mocked(embedStore.storeEmbedKeys).mockImplementation(async (_keys, guard) => {
      guard?.(); entered.release(); await released.promise; guard?.();
    });
    fetchRead.mockImplementation(async () => ({ ok: true, status: 200, json: async () => ({
      embed: { embed_id: child, parent_embed_id: invalid === 'lineage' ? 'wrong-parent' : parent,
        hashed_chat_id: invalid === 'source' ? 'wrong-source' : `hash-${chat}`,
        hashed_user_id: invalid === 'owner' ? 'wrong-owner' : 'hash-owner', status: 'finished', encrypted_content: 'cipher' },
      embed_keys: parentKeys,
    }) }));
    if (invalid === 'wrapper') parentKeys[0].hashed_user_id = 'wrong-owner';
    const generic = requestEmbedFromServerOnce(child, 'first', { chatId: chat }); await entered.promise;
    const strict = recover(); await vi.waitFor(() => expect(chatDB.getChat).toHaveBeenCalledTimes(2));
    released.release(); await generic; await expect(strict).resolves.toEqual([]);
    expect(fetchRead).toHaveBeenCalledTimes(1); expect(embedStore.putEncrypted).toHaveBeenCalledTimes(1);
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it.each(['auth', 'account', 'chat'])('guards Personal resolver persistence when captured %s changes', async change => {
    const entered = deferred(), released = deferred();
    vi.mocked(embedStore.storeEmbedKeys).mockImplementation(async (_keys, guard) => {
      guard?.(); entered.release(); await released.promise; guard?.();
    });
    const generic = requestEmbedFromServerOnce(child, 'first', { chatId: chat }); await entered.promise;
    if (change === 'auth') authStore.set({ isAuthenticated: true, isInitialized: true });
    if (change === 'account') userProfile.update(p => ({ ...p, account_id: 'other-account' }));
    if (change === 'chat') activeChatStore.setActiveChat(parent);
    released.release(); await expect(generic).resolves.toBe(false);
    expect(embedStore.putEncrypted).not.toHaveBeenCalled(); expect(send).not.toHaveBeenCalled();
  });
});

describe('Personal pending scope and deadline', () => {
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it('bounds a hung joined operation and rejects late persistence before allowing retry', async () => {
    vi.useFakeTimers(); const blocked = deferred(); let lateGuard!: () => void; let signal!: AbortSignal;
    const first = runPersonalEmbedReadOperation(scope(), async (guard, activeSignal) => {
      lateGuard = guard; signal = activeSignal; await blocked.promise; guard();
    });
    const joined = runPersonalEmbedReadOperation(scope(), async () => { throw new Error('must join'); });
    const observations = Promise.allSettled([first, joined]);
    await vi.advanceTimersByTimeAsync(8000); const results = await observations;
    expect(results.every(r => r.status === 'rejected')).toBe(true); expect(signal.aborted).toBe(true);
    expect(lateGuard).toThrow('expired'); blocked.release();
    const retried = vi.fn(async guard => { guard(); });
    await runPersonalEmbedReadOperation(scope(), retried); expect(retried).toHaveBeenCalledTimes(1);
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it('removes failed reads without caching a 401 or its response', async () => {
    const failed = vi.fn(async () => { throw new Error('HTTP401'); });
    await expect(runPersonalEmbedReadOperation(scope(), failed)).rejects.toThrow('HTTP401');
    const retried = vi.fn(async () => {}); await runPersonalEmbedReadOperation(scope(), retried);
    expect(retried).toHaveBeenCalledTimes(1);
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it.each(['auth', 'owner', 'account'])('does not join pending work from another %s scope', async change => {
    const blocked = deferred(), started = vi.fn();
    const operation = async (guard: () => void) => { started(); await blocked.promise; guard(); };
    const first = runPersonalEmbedReadOperation(scope(), operation);
    const observedFirst = first.catch(error => error);
    await vi.waitFor(() => expect(started).toHaveBeenCalledTimes(1));
    if (change === 'auth') authStore.set({ isAuthenticated: true, isInitialized: true });
    if (change === 'owner') userProfile.update(p => ({ ...p, user_id: 'other-owner' }));
    if (change === 'account') userProfile.update(p => ({ ...p, account_id: 'other-account' }));
    const second = runPersonalEmbedReadOperation(scope(), operation);
    await vi.waitFor(() => expect(started).toHaveBeenCalledTimes(2));
    blocked.release(); expect(await observedFirst).toBeInstanceOf(Error); await second;
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it('isolates actual source chats and children while preserving a different active chat', async () => {
    const blocked = deferred(), started = vi.fn();
    const operation = async (guard: () => void) => { started(); await blocked.promise; guard(); };
    const first = runPersonalEmbedReadOperation(scope(), operation);
    const parentSource = runPersonalEmbedReadOperation(scope(parent), operation);
    const anotherChild = runPersonalEmbedReadOperation(scope(chat, parent), operation);
    await vi.waitFor(() => expect(started).toHaveBeenCalledTimes(3));
    blocked.release(); await Promise.all([first, parentSource, anotherChild]);
  });
});
