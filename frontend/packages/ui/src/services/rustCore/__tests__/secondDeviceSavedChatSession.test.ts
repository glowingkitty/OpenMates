// Engineering unit check: a failed saved read closes the Worker host fail-closed and must
// end the whole second-device session, so the web surface re-admits a fresh Worker instead
// of retrying a closed host (which only ever answers session_expired).
import { describe, expect, it, vi } from 'vitest';
import { admitSecondDeviceSavedChatSession } from '../secondDeviceSavedChatSession';
import { PriorProfileLifecycle } from '../platformLifecycle';
import { DrainedSelectedColdReadCancellation } from '../protocol';
import { assertLocalReadAfterFirstSession, type OriginalFirstSessionWorker } from '../originalFirstSessionSource';
import type { BrowserCoreWorkerHost } from '../workerHost';

const owner = 'owner-1';
const chatId = '11111111-1111-1111-1111-111111111111';

function fixture(readFailure: Error | ((signal: AbortSignal) => Promise<never>), admitReply?: unknown, cachedReply?: unknown) {
  const lifecycle = new PriorProfileLifecycle();
  let witnessCurrent = true;
  const calls = { workerClosed: 0, restores: 0, reads: 0, lastSelector: undefined as unknown };
  const key = {} as CryptoKey;
  const status = { principal: owner, persistence: 'memory_only', localReadOnly: false, handle: 1, generation: 1 };
  const consumeFirstSessionAdmission = vi.fn<() => unknown>(() => ({ ok: true, status }));
  const host = {
    consumeFirstSessionAdmission,
    async request(body: { operation: string; selector?: unknown }, signal: AbortSignal) {
      if (body.operation === 'restore_existing') { calls.restores++; return { ok: true, status }; }
      if (body.operation === 'admit_chat' && admitReply) return admitReply;
      if (body.operation === 'read_online_cached_saved_chat' && cachedReply) return cachedReply;
      calls.lastSelector = body.selector;
      calls.reads++;
      if (typeof readFailure === 'function') return readFailure(signal);
      throw readFailure;
    },
    close() {},
  } as unknown as BrowserCoreWorkerHost;
  const sources = {
    async capture(generation: number) {
      return { generation, key, profile: { principal: owner, hashedEmail: null, userEmailSalt: null }, persistence: 'persisted' as const };
    },
    async assertCurrent() { if (!witnessCurrent) throw new Error('invalidated_snapshot'); },
    async executeLocalReadPlan() { return '{}'; },
  };
  const listeners = { addEventListener() {}, removeEventListener() {} };
  const owned = { host, close() { calls.workerClosed++; } };
  const original = async (): Promise<OriginalFirstSessionWorker> => ({
    ...owned, witness: await sources.capture(lifecycle.current()), confirmHandover: vi.fn(),
  });
  const admit = (first?: OriginalFirstSessionWorker) => admitSecondDeviceSavedChatSession({
    expectedPrincipal: owner, signal: new AbortController().signal, sources, lifecycle,
    currentSelection: () => ({ ownerId: owner, chatId, teamId: null, workspaceEpoch: 1, selectionGeneration: 1, revision: 0 }),
    page: listeners, createChannel: () => ({ ...listeners, close() {} }),
    createWorker: async () => first ?? owned,
  }, first);
  return { calls, admit, lifecycle, original, consumeFirstSessionAdmission, invalidateWitness() { witnessCurrent = false; } };
}

describe('second-device saved chat session', () => {
  // contract-test: supporting surface=gui.web assertions=auth.session.authoritative-enforcement
  it('fences local reads only for a definitive denial in the exact original scope', () => {
    const scope = { owner, sessionId: 'tab-session', scope: 'personal-snapshot', loginGeneration: 3 };
    const denied = { ...scope, failure: 'session_expired' as const };
    expect(() => assertLocalReadAfterFirstSession(denied, scope)).toThrow('session_expired');
    expect(() => assertLocalReadAfterFirstSession({ ...denied, failure: 'unavailable' }, scope)).not.toThrow();
    expect(() => assertLocalReadAfterFirstSession(denied, { ...scope, loginGeneration: 4 })).not.toThrow();
    expect(() => assertLocalReadAfterFirstSession(denied, { ...scope, owner: 'other-owner' })).not.toThrow();
    expect(() => assertLocalReadAfterFirstSession(denied, { ...scope, sessionId: 'other-tab' })).not.toThrow();
    expect(() => assertLocalReadAfterFirstSession(denied, { ...scope, scope: 'different-workspace' })).not.toThrow();
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.authoritative-enforcement
  it('adopts the actual page Worker once using its exact profile and skips a second restore', async () => {
    const f = fixture(new Error('unused'));
    const original = await f.original();
    const session = await f.admit(original);
    expect(session.status.principal).toBe(owner);
    expect(f.consumeFirstSessionAdmission).toHaveBeenCalledTimes(1);
    expect(original.confirmHandover).toHaveBeenCalledOnce();
    expect(f.calls.restores).toBe(0);
    session.close();
    expect(f.calls.workerClosed).toBe(1);
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.authoritative-enforcement
  it.each(['opaque key', 'lifecycle generation', 'owner', 'invalid profile', 'missing genuine reply'])(
    'fails closed before admitting a page Worker with %s', async reason => {
      const f = fixture(new Error('unused'));
      const genuine = await f.original();
      const witness = { ...genuine.witness, profile: { ...genuine.witness.profile } };
      if (reason === 'opaque key') witness.key = {} as CryptoKey;
      if (reason === 'lifecycle generation') f.lifecycle.invalidate();
      if (reason === 'owner') witness.profile.principal = 'another-owner';
      const original = { ...genuine, witness };
      if (reason === 'invalid profile') f.invalidateWitness();
      if (reason === 'missing genuine reply') f.consumeFirstSessionAdmission.mockReturnValue(null);
      await expect(f.admit(original)).rejects.toThrow(reason === 'invalid profile' ? 'invalidated_snapshot' : 'session_expired');
      expect(f.consumeFirstSessionAdmission).toHaveBeenCalledTimes(reason === 'missing genuine reply' ? 1 : 0);
      expect(original.confirmHandover).not.toHaveBeenCalled();
      expect(f.calls.restores).toBe(0);
      expect(f.calls.workerClosed).toBe(1);
    },
  );

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('forwards an explicitly shaped latest page to the Rust reader', async () => {
    const f = fixture(new Error('read intercepted'));
    const session = await f.admit();
    const selector = { direction: 'latest' as const, limit: 5, respectCompressionBoundary: false };
    await expect(session.publishPage(selector, () => {})).rejects.toThrow('read intercepted');
    expect(f.calls.lastSelector).toEqual(selector);
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('a failed saved read ends the session instead of leaving a closed host behind', async () => {
    const f = fixture(new Error('unavailable'));
    const session = await f.admit();
    expect(session.signal.aborted).toBe(false);
    await expect(session.publishPage({ direction: 'latest' }, () => { throw new Error('no page may publish'); })).rejects.toThrow(/unavailable/);
    expect(f.calls.reads).toBe(1);
    expect(session.signal.aborted, 'callers must see the session as ended and re-admit').toBe(true);
    expect(f.calls.workerClosed).toBe(1);
    expect(() => session.assertCurrent()).toThrow(/invalidated_snapshot/);
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.authoritative-enforcement
  it.each(['session_expired', 'unavailable'])('keeps the exact Worker failure for an online cache read: %s', async error => {
    const f = fixture(new Error('unused'), undefined, { ok: false, error });
    const session = await f.admit();
    await expect(session.publishCachedPage({ direction: 'latest' }, () => {
      throw new Error('no page may publish');
    })).rejects.toThrow(error);
    expect(session.signal.aborted).toBe(true);
    expect(f.calls.workerClosed).toBe(1);
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent,auth.session.authoritative-enforcement
  it.each([
    ['owned stop', new DrainedSelectedColdReadCancellation(), true, null],
    ['unproven stop', new Error('cancelled'), false, null],
    ['authority denial', new Error('session_expired'), false, null],
    ['unrelated failure', new Error('unavailable'), false, null],
    ['profile witness refused', new DrainedSelectedColdReadCancellation(), false, 'witness'],
    ['revoked lifetime', new DrainedSelectedColdReadCancellation(), false, 'lifetime'],
  ] as const)('handles a superseded cold read with %s', async (_label, failure, keep, invalidate) => {
    vi.stubGlobal('indexedDB', {});
    try {
      let finish!: () => void;
      let requestSignal!: AbortSignal;
      const f = fixture(signal => {
        requestSignal = signal;
        return new Promise<never>((_, reject) => { finish = () => reject(failure); });
      });
      const session = await f.admit();
      const selection = new AbortController();
      const publish = vi.fn();
      const result = session.publishColdPage(publish, undefined, undefined, selection.signal).catch(error => error);
      await vi.waitFor(() => expect(requestSignal).toBeDefined());
      selection.abort();
      expect(requestSignal.aborted).toBe(true);
      expect(session.signal.aborted).toBe(false);
      expect(f.calls.workerClosed).toBe(0);
      if (invalidate === 'witness') f.invalidateWitness();
      if (invalidate === 'lifetime') {
        f.lifecycle.invalidate();
        expect(session.signal.aborted).toBe(true);
      }
      finish();
      const terminal = await result;
      expect(terminal).toBeInstanceOf(Error);
      expect(terminal.message).toBe(invalidate === 'witness' ? 'invalidated_snapshot' : failure.message);
      expect(publish).not.toHaveBeenCalled();
      expect(session.signal.aborted).toBe(!keep);
      expect(f.calls.workerClosed).toBe(keep ? 0 : 1);
      if (keep) {
        session.assertCurrent();
        session.close();
      }
    } finally { vi.unstubAllGlobals(); }
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.launch-and-provider
  it('a chat admission the core rejects as session_expired ends the session so the owner re-admits', async () => {
    const f = fixture(new Error('unused'), { ok: false, error: 'session_expired' });
    const session = await f.admit();
    await expect(session.admitChat(chatId, null)).rejects.toThrow(/session_expired/);
    expect(session.signal.aborted, 'a stale session must not be reused for the retry').toBe(true);
    expect(f.calls.workerClosed).toBe(1);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.launch-and-provider
  it('a non-session admission failure keeps the session', async () => {
    const f = fixture(new Error('unused'), { ok: false, error: 'chat_unavailable' });
    const session = await f.admit();
    await expect(session.admitChat(chatId, null)).rejects.toThrow(/chat_unavailable/);
    expect(session.signal.aborted).toBe(false);
    expect(f.calls.workerClosed).toBe(0);
  });
});
