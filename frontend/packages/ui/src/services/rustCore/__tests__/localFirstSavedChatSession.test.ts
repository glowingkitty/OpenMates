// Local-only Rust admission (no server call) that renders the retained cache
// before the server check, then upgrades on the same Worker via restore_existing.
import { describe, expect, it } from 'vitest';
import { admitLocalSavedChatSession } from '../secondDeviceSavedChatSession';
import { PriorProfileLifecycle } from '../platformLifecycle';
import type { BrowserCoreWorkerHost } from '../workerHost';

const owner = 'owner-1';
const chatId = '11111111-1111-1111-1111-111111111111';

function fixture(restoreExisting: 'ok' | 'revoked') {
  const lifecycle = new PriorProfileLifecycle();
  const calls = { workerClosed: 0, workersCreated: 0, operations: [] as string[] };
  const localStatus = { principal: owner, persistence: 'memory_only', localReadOnly: true, handle: 'local', generation: 1 };
  const onlineStatus = { ...localStatus, localReadOnly: false, handle: 'online' };
  const host = {
    async request(body: { operation: string }) {
      calls.operations.push(body.operation);
      if (body.operation === 'restore_local') return { ok: true, status: localStatus };
      // A revoked session: Rust's server check fails and the Worker refuses.
      if (body.operation === 'restore_existing') return restoreExisting === 'ok' ? { ok: true, status: onlineStatus } : { ok: false, error: 'unavailable' };
      if (body.operation === 'read_local_saved_chat_cursor') return { ok: false, error: 'chat_unavailable' };
      throw new Error('unexpected operation');
    },
    close() {},
  } as unknown as BrowserCoreWorkerHost;
  const sources = {
    async capture(generation: number) {
      return { generation, key: {} as CryptoKey, profile: { principal: owner, hashedEmail: null, userEmailSalt: null }, persistence: 'memory_only' as const };
    },
    async assertCurrent() {},
    async executeLocalReadPlan() { return '{}'; },
  };
  const listeners = { addEventListener() {}, removeEventListener() {} };
  const common = {
    expectedPrincipal: owner, signal: new AbortController().signal, sources, lifecycle,
    currentSelection: () => ({ ownerId: owner, chatId, teamId: null, workspaceEpoch: 1, selectionGeneration: 1, revision: 0 }),
    page: listeners, createChannel: () => ({ ...listeners, close() {} }),
  };
  const admit = () => admitLocalSavedChatSession({ ...common,
    createWorker: async () => { calls.workersCreated++; return { host, close() { calls.workerClosed++; } }; } });
  return { calls, admit, common };
}

describe('local-first saved chat session', () => {
  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('admits local-only without a server call; a cache miss keeps the session', async () => {
    const f = fixture('ok');
    const local = await f.admit();
    expect(local.status.localReadOnly).toBe(true);
    expect(f.calls.operations).toEqual(['restore_local']);
    await expect(local.publishCachedPage({ direction: 'latest' }, () => { throw new Error('no page'); })).rejects.toThrow(/chat_unavailable/);
    expect(local.signal.aborted).toBe(false);
    expect(f.calls.workerClosed).toBe(0);
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('upgrades on the SAME Worker with the normal server check', async () => {
    const f = fixture('ok');
    const local = await f.admit();
    const online = await local.upgrade(f.common);
    expect(f.calls.workersCreated).toBe(1);
    expect(f.calls.operations).toEqual(['restore_local', 'restore_existing']);
    expect(online.status.localReadOnly).toBe(false);
    expect(local.signal.aborted, 'the local session ends at handover').toBe(true);
    await expect(local.publishCachedPage({ direction: 'latest' }, () => undefined)).rejects.toThrow();
    expect(f.calls.workerClosed, 'the online session now owns the Worker').toBe(0);
    online.close();
    expect(f.calls.workerClosed).toBe(1);
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('a revoked session (failed restore_existing) tears down all local state', async () => {
    const f = fixture('revoked');
    const local = await f.admit();
    await expect(local.upgrade(f.common)).rejects.toThrow(/session_expired/);
    expect(local.signal.aborted).toBe(true);
    expect(f.calls.workerClosed, 'the Worker holding the key is closed').toBeGreaterThanOrEqual(1);
    await expect(local.publishCachedPage({ direction: 'latest' }, () => undefined)).rejects.toThrow();
    expect(f.calls.operations).toEqual(['restore_local', 'restore_existing']);
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('the upgrade handover keeps the caller\'s prepared platform snapshot (no self-inflicted cancel)', async () => {
    const f = fixture('ok');
    const local = await f.admit();
    // Like createBrowserSavedChatPlatform: the server-checked platform is prepared
    // BEFORE upgrade(), pins the lifecycle generation and closes on any advance.
    const prepared = f.common.lifecycle.current();
    let platformClosed = false;
    const stopObserving = f.common.lifecycle.observe(() => { platformClosed = true; });
    const active = () => {
      if (platformClosed) throw new Error('cancelled');
      if (f.common.lifecycle.current() !== prepared) throw new Error('invalidated_snapshot');
    };
    const sources = {
      async capture(generation: number) { active(); return f.common.sources.capture(generation); },
      async assertCurrent() { active(); },
      executeLocalReadPlan: f.common.sources.executeLocalReadPlan,
    };
    const online = await local.upgrade({ ...f.common, sources });
    expect(platformClosed, 'handover must not advance the shared profile lifecycle').toBe(false);
    expect(f.common.lifecycle.current()).toBe(prepared);
    expect(online.status.localReadOnly).toBe(false);
    expect(f.calls.workersCreated, 'no second Worker / re-admission').toBe(1);
    // A real teardown still revokes: closing the online session advances the lifecycle.
    online.close();
    expect(platformClosed, 'teardown revokes every observer').toBe(true);
    expect(f.calls.workerClosed).toBe(1);
    stopObserving();
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('closing a local session without handover still revokes the shared lifecycle', async () => {
    const f = fixture('ok');
    const local = await f.admit();
    const before = f.common.lifecycle.current();
    local.close();
    expect(f.common.lifecycle.current()).toBeGreaterThan(before);
    expect(f.calls.workerClosed).toBe(1);
  });
});
