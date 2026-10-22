import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({
  connection: {} as object, scope: 'account-a|key-1', session: 'session-a', handlers: new Map<string, (data: any) => void>(),
  listeners: new Map<string, () => void>(), invalidators: [] as Array<() => void>,
  send: vi.fn(), checkAuth: vi.fn(async () => false), serializeRead: vi.fn((read: () => Promise<unknown>) => read()), waitMutations: vi.fn(async () => true), decrypt: vi.fn(async (value: string) => value),
  store: { subscribe(callback: (value: any) => void) { callback({ user_id: 'account-a', isAuthenticated: true }); return () => {}; } },
}));
vi.mock('../workspaceQueryCache', () => ({ getWorkspaceCacheIdentity: () => mocks.scope }));
vi.mock('../workspaceCacheLifecycle', () => ({ registerWorkspaceCacheClear: (fn: () => void) => mocks.invalidators.push(fn) }));
vi.mock('../../stores/authState', () => ({ authStore: mocks.store }));
vi.mock('../../stores/authStore', () => ({ checkAuth: mocks.checkAuth, serializeAuthSessionRead: mocks.serializeRead }));
vi.mock('../../stores/userProfile', () => ({ userProfile: mocks.store }));
vi.mock('../../stores/personalDataStore', () => ({ personalDataStore: { ...mocks.store, settings: mocks.store, hasPendingPrivacyMutations: () => false, waitForPrivacyMutations: mocks.waitMutations, acknowledgePrivacyPersistence: vi.fn() } }));
vi.mock('../../utils/sessionId', () => ({ getSessionId: () => mocks.session }));
vi.mock('../../utils/websocketRoutingId', () => ({ getWebSocketRoutingId: () => 'document-a' }));
vi.mock('../cryptoService', () => ({ decryptWithMasterKey: mocks.decrypt }));
vi.mock('../websocketService', () => ({ webSocketService: {
  on: (type: string, handler: (data: any) => void) => mocks.handlers.set(type, handler),
  off: (type: string) => mocks.handlers.delete(type),
  addEventListener: (type: string, handler: () => void) => mocks.listeners.set(type, handler),
  removeEventListener: (type: string) => mocks.listeners.delete(type),
  sendMessage: mocks.send,
  getConnectionForSend: () => mocks.connection,
} }));
const snapshot = (text = 'Secret Orchard') => ({ encrypted_settings: '{"memories":[{"id":"private-doc","document":"My local document"}]}', memories: [
  { id: 'memory-a', app_id: 'privacy', item_type: 'personal_data_entry', encrypted_item_json: JSON.stringify({ enabled: true, textToHide: text, replaceWith: 'PRIVATE_NAME' }) },
] });
function full(purpose: string, request: any, generation: string | null = 'generation-a') {
  return { request_id: request.request_id, success: true, unchanged: false, personal_memories: snapshot(),
    privacy_generation: generation, receipt_id: purpose === 'send' ? 'receipt-a' : null, turn_id: request.turn_id };
}
describe('prepared Personal privacy', () => {
  afterEach(() => { mocks.invalidators.forEach(fn => fn()); vi.useRealTimers(); vi.unstubAllGlobals(); });
  beforeEach(() => { vi.resetModules(); mocks.handlers.clear(); mocks.listeners.clear(); mocks.invalidators.length = 0;
    mocks.scope = 'account-a|key-1'; mocks.session = 'session-a'; mocks.send.mockReset(); mocks.decrypt.mockImplementation(async (value: string) => value); mocks.decrypt.mockClear(); mocks.waitMutations.mockReset().mockResolvedValue(true); mocks.checkAuth.mockReset().mockResolvedValue(false); mocks.serializeRead.mockClear(); });

  // contract-test: direct surface=gui.web assertions=ai-model-routing.preprocessing.prepared-privacy
  it('decrypts on focus once, checks authority at Send and reuses RAM only on an unchanged generation', async () => {
    const service = await import('../preparedPrivacyForSend');
    mocks.handlers.get('server_capabilities')!({ capabilities: ['personal_send_context_snapshot_v2'] });
    mocks.send.mockImplementation(async (_type: string, request: any) => {
      mocks.handlers.get('personal_send_context_snapshot_result')!(!request.known_generation ? full(request.purpose, request)
        : { request_id: request.request_id, success: true, unchanged: true, privacy_generation: 'generation-a', receipt_id: 'receipt-b', turn_id: request.turn_id });
    });
    service.warmPersonalPrivacyForSend();
    await vi.waitFor(() => expect(mocks.decrypt).toHaveBeenCalledTimes(2));
    // Await the warm compile's microtasks, without using a production timer.
    await new Promise(resolve => setTimeout(resolve, 0));
    const receipt = await service.freshPersonalPrivacyForSend('turn-a');
    expect(mocks.send.mock.calls.map(([, value]) => value.purpose)).toEqual(['prepare', 'send']);
    expect(mocks.send.mock.calls[1][1].known_generation).toBe('generation-a');
    expect(mocks.decrypt).toHaveBeenCalledTimes(2);
    expect(service.filterWithFreshPersonalPrivacy('Visit Secret Orchard', receipt).content).not.toContain('Secret Orchard');
  });

  // contract-test: direct surface=gui.web assertions=ai-model-routing.preprocessing.prepared-privacy
  it('does a full scan for changed or unknown generation and attaches only the exact fresh receipt', async () => {
    const service = await import('../preparedPrivacyForSend');
    mocks.handlers.get('server_capabilities')!({ capabilities: ['personal_send_context_snapshot_v2'] });
    mocks.send.mockImplementation(async (_type: string, request: any) => mocks.handlers.get('personal_send_context_snapshot_result')!(full(request.purpose, request, null)));
    const receipt = await service.freshPersonalPrivacyForSend('turn-a');
    expect(receipt.generation).toBeNull();
    const frame = { turn_id: 'turn-a' } as Record<string, unknown>;
    await service.attachFreshPrivacyReceipt(frame, receipt);
    expect(frame).toMatchObject({ privacy_receipt_id: 'receipt-a', privacy_generation: null });
    await service.freshPersonalPrivacyForSend('turn-b');
    expect(mocks.decrypt).toHaveBeenCalledTimes(4);
    expect(mocks.send.mock.calls[1][1].known_generation).toBeUndefined();
  });

  // contract-test: direct surface=gui.web assertions=ai-model-routing.preprocessing.prepared-privacy
  it('rejects unmatched unchanged proofs and never filters using a former session or key owner', async () => {
    const service = await import('../preparedPrivacyForSend');
    mocks.handlers.get('server_capabilities')!({ capabilities: ['personal_send_context_snapshot_v2'] });
    mocks.send.mockImplementation(async (_type: string, request: any) => mocks.handlers.get('personal_send_context_snapshot_result')!({ ...full('send', request), unchanged: true }));
    await expect(service.freshPersonalPrivacyForSend('turn-a')).rejects.toThrow('unchanged');
    mocks.send.mockImplementation(async (_type: string, request: any) => mocks.handlers.get('personal_send_context_snapshot_result')!(full('send', request)));
    const receipt = await service.freshPersonalPrivacyForSend('turn-b');
    mocks.session = 'session-b';
    expect(() => service.filterWithFreshPersonalPrivacy('Secret Orchard', receipt)).toThrow('owner');
  });

  // contract-test: direct surface=gui.web assertions=ai-model-routing.preprocessing.prepared-privacy
  it('preserves explicit revealed values and embed references while redacting fresh Personal entries', async () => {
    const service = await import('../preparedPrivacyForSend');
    mocks.handlers.get('server_capabilities')!({ capabilities: ['personal_send_context_snapshot_v2'] });
    mocks.send.mockImplementation(async (_type: string, request: any) => mocks.handlers.get('personal_send_context_snapshot_result')!(full('send', request)));
    const receipt = await service.freshPersonalPrivacyForSend('turn-a');
    const message = {};
    service.registerPersonalPrivacyExclusions(message, new Set(['Secret Orchard']));
    const embed = '```json\n{"embed_id":"05143690-1234-4abc-8123-0123456789ab"}\n```';
    expect(service.filterWithFreshPersonalPrivacy('Secret Orchard ' + embed, receipt, message).content).toBe('Secret Orchard ' + embed);
    service.invalidatePreparedPrivacy();
    expect(() => service.filterWithFreshPersonalPrivacy('Secret Orchard', receipt)).toThrow('preferences');
  });
  // contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance,ai-model-routing.preprocessing.prepared-privacy
  it('preserves closed camera provenance while redacting prose and arbitrary JSON notes', async () => {
    const service = await import('../preparedPrivacyForSend');
    mocks.handlers.get('server_capabilities')!({ capabilities: ['personal_send_context_snapshot_v2'] });
    mocks.send.mockImplementation(async (_type: string, request: any) => mocks.handlers.get('personal_send_context_snapshot_result')!(full('send', request)));
    const receipt = await service.freshPersonalPrivacyForSend('turn-camera');
    const reference = { type: 'image', embed_id: '05143690-1234-4abc-8123-0123456789ab',
      source_frame_id: 'fb138791-7451-4cc9-a037-645944986181', source_call_id: '673f1d7523a5487e868e7769ec91804a',
      source: 'camera', captured_at: 1792698555.81 };
    const fence = (value: object) => '```json\n' + JSON.stringify(value) + '\n```';
    const filtered = service.filterWithFreshPersonalPrivacy('Secret Orchard\n\n' + fence(reference), receipt);
    expect(filtered.content).toContain(fence(reference));
    expect(filtered.content).not.toContain('Secret Orchard');
    const untrusted = service.filterWithFreshPersonalPrivacy(fence({ ...reference, note: 'Secret Orchard' }), receipt);
    expect(untrusted.content).not.toContain('Secret Orchard');
    const malformed = service.filterWithFreshPersonalPrivacy(fence({ ...reference, source_call_id: 'Secret Orchard' }), receipt);
    expect(malformed.content).not.toContain('Secret Orchard');
  });

  // contract-test: direct surface=gui.web assertions=ai-model-routing.preprocessing.prepared-privacy
  it('discards a slower focus compile after a newer Send has prepared another generation', async () => {
    const service = await import('../preparedPrivacyForSend');
    mocks.handlers.get('server_capabilities')!({ capabilities: ['personal_send_context_snapshot_v2'] });
    let release: (() => void) | undefined;
    let decryptCalls = 0;
    mocks.decrypt.mockImplementation(async (value: string) => {
      if (decryptCalls++ === 0) await new Promise<void>(resolve => { release = resolve; });
      return value;
    });
    mocks.send.mockImplementation(async (_type: string, request: any) => {
      const response = full(request.purpose, request, request.purpose === 'prepare' ? 'old-generation' : 'new-generation');
      mocks.handlers.get('personal_send_context_snapshot_result')!(response);
    });
    service.warmPersonalPrivacyForSend();
    await vi.waitFor(() => expect(release).toBeTypeOf('function'));
    await service.freshPersonalPrivacyForSend('turn-new');
    release!();
    await new Promise(resolve => setTimeout(resolve, 0));
    await service.freshPersonalPrivacyForSend('turn-next');
    expect(mocks.send.mock.calls.at(-1)![1].known_generation).toBe('new-generation');
  });

  // contract-test: direct surface=gui.web assertions=ai-model-routing.preprocessing.prepared-privacy
  it('actively expires the decrypted bundle after two idle hours and slides on focus', async () => {
    vi.useFakeTimers();
    const service = await import('../preparedPrivacyForSend');
    mocks.handlers.get('server_capabilities')!({ capabilities: ['personal_send_context_snapshot_v2'] });
    mocks.send.mockImplementation(async (_type: string, request: any) => mocks.handlers.get('personal_send_context_snapshot_result')!(full(request.purpose, request)));
    await service.freshPersonalPrivacyForSend('turn-a');
    await vi.advanceTimersByTimeAsync(60 * 60 * 1000);
    service.warmPersonalPrivacyForSend();
    await vi.advanceTimersByTimeAsync(60 * 60 * 1000 + 1);
    await service.freshPersonalPrivacyForSend('turn-b');
    expect(mocks.send.mock.calls.at(-1)![1].known_generation).toBe('generation-a');
    await vi.advanceTimersByTimeAsync(2 * 60 * 60 * 1000 + 1);
    await service.freshPersonalPrivacyForSend('turn-c');
    expect(mocks.send.mock.calls.at(-1)![1].known_generation).toBeUndefined();
  });

  // contract-test: direct surface=gui.web assertions=ai-model-routing.preprocessing.prepared-privacy
  it('waits for an owned privacy write before checking fresh authority and rejects key-scope changes', async () => {
    const service = await import('../preparedPrivacyForSend');
    mocks.handlers.get('server_capabilities')!({ capabilities: ['personal_send_context_snapshot_v2'] });
    let release: ((value: boolean) => void) | undefined;
    mocks.waitMutations.mockImplementationOnce(() => new Promise<boolean>(resolve => { release = resolve; }));
    mocks.send.mockImplementation(async (_type: string, request: any) => mocks.handlers.get('personal_send_context_snapshot_result')!(full('send', request)));
    const ready = service.freshPersonalPrivacyForSend('turn-a');
    expect(mocks.send).not.toHaveBeenCalled();
    release!(true);
    const receipt = await ready;
    mocks.scope = 'account-a|key-2';
    expect(() => service.filterWithFreshPersonalPrivacy('Secret Orchard', receipt)).toThrow('owner');
    await service.freshPersonalPrivacyForSend('turn-b');
    expect(mocks.send.mock.calls.at(-1)![1].known_generation).toBeUndefined();
  });

  // contract-test: direct surface=gui.web assertions=ai-model-routing.preprocessing.prepared-privacy
  it('loads a full first-party snapshot on each unsupported send and refuses missing ciphertext', async () => {
    const service = await import('../preparedPrivacyForSend');
    const fetchSnapshot = vi.fn(async () => ({ ok: true, json: async () => ({ success: true, user: { id: 'account-a' }, personal_memories: snapshot() }) }));
    vi.stubGlobal('fetch', fetchSnapshot);
    const first = await service.freshPersonalPrivacyForSend('turn-a');
    await service.freshPersonalPrivacyForSend('turn-b');
    expect(first.receiptId).toBeNull();
    expect(fetchSnapshot).toHaveBeenCalledTimes(2);
    expect(mocks.decrypt).toHaveBeenCalledTimes(4);
    const request = fetchSnapshot.mock.calls[0] as unknown as [string, { body: string }];
    expect(JSON.parse(request[1].body)).toMatchObject({ include_personal_memories: true, session_id: 'session-a' });
    await expect(service.compilePersonalPrivacy({ encrypted_settings: null, memories: [{
      id: 'broken-memory', app_id: 'privacy', item_type: 'personal_data_entry', encrypted_item_json: null,
    }] })).rejects.toThrow('missing encrypted row content');
  });

  // contract-test: direct surface=gui.web assertions=ai-model-routing.preprocessing.prepared-privacy,auth.session.lifecycle
  it('immediately fences cached privacy and old receipts on 401, then runs coalesced auth recovery without resending', async () => {
    const service = await import('../preparedPrivacyForSend');
    mocks.handlers.get('server_capabilities')!({ capabilities: ['personal_send_context_snapshot_v2'] });
    mocks.send.mockImplementation(async (_type: string, request: any) => mocks.handlers.get('personal_send_context_snapshot_result')!(full('send', request)));
    const receipt = await service.freshPersonalPrivacyForSend('turn-a');
    mocks.handlers.get('server_capabilities')!({ capabilities: [] });
    const fetchSnapshot = vi.fn(async () => ({ ok: false, status: 401 }));
    vi.stubGlobal('fetch', fetchSnapshot);
    let finishRecovery: ((value: boolean) => void) | undefined;
    let lockActive = false;
    mocks.serializeRead.mockImplementationOnce(async read => { lockActive = true; try { return await read(); } finally { lockActive = false; } });
    mocks.checkAuth.mockImplementationOnce(() => { expect(lockActive).toBe(false); return new Promise<boolean>(resolve => { finishRecovery = resolve; }); });
    const rejected = service.freshPersonalPrivacyForSend('expired-turn');
    void rejected.catch(() => {});
    await vi.waitFor(() => expect(mocks.checkAuth).toHaveBeenCalledExactlyOnceWith(undefined, true));
    expect(() => service.filterWithFreshPersonalPrivacy('Secret Orchard', receipt)).toThrow();
    await expect(service.attachFreshPrivacyReceipt({ turn_id: receipt.turnId }, receipt)).rejects.toThrow('session expired');
    expect(fetchSnapshot).toHaveBeenCalledOnce();
    expect(mocks.serializeRead).toHaveBeenCalledOnce();
    finishRecovery!(false);
    await expect(rejected).rejects.toThrow('session expired');
    expect(mocks.send).toHaveBeenCalledOnce();
    mocks.handlers.get('server_capabilities')!({ capabilities: ['personal_send_context_snapshot_v2'] });
    await service.freshPersonalPrivacyForSend('user-retry');
    expect(mocks.send.mock.calls.at(-1)![1].known_generation).toBeUndefined();
  });

  // contract-test: direct surface=gui.web assertions=ai-model-routing.preprocessing.prepared-privacy,auth.session.lifecycle
  it('blocks an unavailable 503 snapshot without initiating logout or discarding the authorized account state', async () => {
    const service = await import('../preparedPrivacyForSend');
    mocks.handlers.get('server_capabilities')!({ capabilities: ['personal_send_context_snapshot_v2'] });
    mocks.send.mockImplementation(async (_type: string, request: any) => mocks.handlers.get('personal_send_context_snapshot_result')!(full('send', request)));
    const receipt = await service.freshPersonalPrivacyForSend('turn-a');
    mocks.handlers.get('server_capabilities')!({ capabilities: [] });
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503 })));
    await expect(service.freshPersonalPrivacyForSend('unavailable-turn')).rejects.toThrow('unavailable');
    expect(mocks.checkAuth).not.toHaveBeenCalled();
    expect(service.filterWithFreshPersonalPrivacy('Secret Orchard', receipt).content).not.toContain('Secret Orchard');
    expect(mocks.send).toHaveBeenCalledOnce();
  });

  // contract-test: direct surface=gui.web assertions=ai-model-routing.preprocessing.prepared-privacy,auth.session.lifecycle
  it('does not let an old-owner 401 force recovery of a newly selected account', async () => {
    const service = await import('../preparedPrivacyForSend');
    vi.stubGlobal('fetch', vi.fn(async () => { mocks.scope = 'account-b|key-b'; return { ok: false, status: 401 }; }));
    await expect(service.freshPersonalPrivacyForSend('old-owner-turn')).rejects.toThrow('session expired');
    expect(mocks.checkAuth).not.toHaveBeenCalled();
    expect(mocks.send).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=ai-model-routing.preprocessing.prepared-privacy
  it('preserves valid reference UUIDs while redacting user JSON notes and malformed JSON', async () => {
    const service = await import('../preparedPrivacyForSend');
    mocks.handlers.get('server_capabilities')!({ capabilities: ['personal_send_context_snapshot_v2'] });
    mocks.send.mockImplementation(async (_type: string, request: any) => mocks.handlers.get('personal_send_context_snapshot_result')!(full('send', request)));
    const receipt = await service.freshPersonalPrivacyForSend('turn-a');
    const id = '05143690-1234-4abc-8123-0123456789ab';
    const text = '```json\n' + JSON.stringify({ embed_id: id, embed_ids: [id], note: 'Contact person@example.com or +49 1512 3456789' }) + '\n```';
    const result = service.filterWithFreshPersonalPrivacy(text, receipt);
    expect(result.content).toContain('"embed_id":"' + id + '"');
    expect(result.content).toContain('"embed_ids":["' + id + '"]');
    expect(result.content).not.toContain('person@example.com');
    expect(result.content).not.toContain('+49 1512 3456789');
    expect(result.mappings).toEqual(expect.arrayContaining([
      expect.objectContaining({ original: 'person@example.com' }),
      expect.objectContaining({ original: '+49 1512 3456789' }),
    ]));
    const malformed = '```json\n{"embed_id":"' + id + '","note":"person@example.com"\n```';
    expect(service.filterWithFreshPersonalPrivacy(malformed, receipt).content).not.toContain('person@example.com');
  });

});
