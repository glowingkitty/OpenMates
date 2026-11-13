// Engineering unit check: a failed saved read closes the Worker host fail-closed and must
// end the whole second-device session, so the web surface re-admits a fresh Worker instead
// of retrying a closed host (which only ever answers session_expired).
import { describe, expect, it } from 'vitest';
import { admitSecondDeviceSavedChatSession } from '../secondDeviceSavedChatSession';
import { PriorProfileLifecycle } from '../platformLifecycle';
import type { BrowserCoreWorkerHost } from '../workerHost';

const owner = 'owner-1';
const chatId = '11111111-1111-1111-1111-111111111111';

function fixture(readFailure: Error) {
  const lifecycle = new PriorProfileLifecycle();
  const calls = { workerClosed: 0, reads: 0 };
  const status = { principal: owner, persistence: 'memory_only', localReadOnly: false, handle: 1, generation: 1 };
  const host = {
    async request(body: { operation: string }) {
      if (body.operation === 'restore_existing') return { ok: true, status };
      calls.reads++;
      throw readFailure;
    },
    close() {},
  } as unknown as BrowserCoreWorkerHost;
  const sources = {
    async capture(generation: number) {
      return { generation, key: {} as CryptoKey, profile: { principal: owner, hashedEmail: null, userEmailSalt: null }, persistence: 'persisted' as const };
    },
    async assertCurrent() {},
  };
  const listeners = { addEventListener() {}, removeEventListener() {} };
  const admit = () => admitSecondDeviceSavedChatSession({
    expectedPrincipal: owner, signal: new AbortController().signal, sources, lifecycle,
    currentSelection: () => ({ ownerId: owner, chatId, teamId: null, workspaceEpoch: 1, selectionGeneration: 1, revision: 0 }),
    page: listeners, createChannel: () => ({ ...listeners, close() {} }),
    createWorker: async () => ({ host, close() { calls.workerClosed++; } }),
  });
  return { calls, admit };
}

describe('second-device saved chat session', () => {
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
});
