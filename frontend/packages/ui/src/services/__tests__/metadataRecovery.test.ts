// contract-test-file: infrastructure
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
const m = vi.hoisted(() => ({
  chat: { chat_id: 'chat', user_id: 'owner', encrypted_chat_key: 'wrapped', title_v: 0, metadata_v: 0 },
  getChat: vi.fn(), getKey: vi.fn(), getProfile: vi.fn(), encrypt: vi.fn(), open: vi.fn(),
  db: null as IDBDatabase | null, derive: vi.fn(), save: vi.fn(), send: vi.fn(), on: vi.fn(), off: vi.fn(), invalidate: vi.fn(), epoch: 0,
}));
vi.mock('../db', () => ({ chatDB: { getChat: m.getChat, get db() { return m.db; }, CHATS_STORE_NAME: 'chats' } }));
vi.mock('../userDB', () => ({ userDB: { getUserProfile: m.getProfile } }));
vi.mock('../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKey: m.getKey },
  computeKeyFingerprint: (key: Uint8Array) => key.join(',') }));
vi.mock('../chatKeyWriteGuard', () => ({ ensureChatKeySafeForWrite: async () => true }));
vi.mock('../websocketService', () => ({ webSocketService: { sendMessage: m.send, on: m.on, off: m.off } }));
vi.mock('../../utils/chatCompletionRecovery', () => ({ deriveChatCompletionRecoveryKeypair: m.derive,
  openChatMetadataRecoveryEnvelope: m.open }));
vi.mock('../encryption/MessageEncryptor', () => ({ encryptWithChatKey: m.encrypt }));
vi.mock('../generatedChatMetadataPersistence', () => ({ persistGeneratedChatMetadata: m.save }));
vi.mock('../chatMetadataCache', () => ({ chatMetadataCache: { invalidateChat: m.invalidate } }));
vi.mock('../workspaceQueryCache', () => ({ getWorkspaceCacheIdentity: () => 'owner' }));
vi.mock('../workspaceCacheLifecycle', () => ({ getWorkspaceCacheEpoch: () => m.epoch, registerWorkspaceCacheClear: vi.fn() }));
vi.mock('../../stores/notificationStore', () => ({ notificationStore: { chatMessage: vi.fn() } }));
vi.mock('../../stores/unreadMessagesStore', () => ({ unreadMessagesStore: { incrementUnread: vi.fn() } }));
vi.mock('../chatNotificationVisibility', () => ({ isChatVisiblyActive: () => true }));
vi.mock('../embedDiffStore', () => ({ reconstructEncryptedVersionRows: vi.fn() }));
vi.mock('../recoveryEmbedSource', () => ({ historySourceFromSealedEmbed: vi.fn() }));
import { handleMetadataJobsAvailableImpl, resetRecoveryLifecycleImpl } from '../chatSyncServiceHandlersRecovery';
const job = { job_id: 'job', chat_id: 'chat', task_id: 'task', chat_key_version: 1, stage: 'initial' as const };
let handlers: Map<string, (payload: unknown) => void>;
let receipt: Record<string, unknown>;
let availableJob: Omit<typeof job, 'stage'> & { stage: 'initial' | 'postprocessing' } = job;
let service: any;
beforeEach(() => {
  vi.clearAllMocks(); m.epoch = 0; handlers = new Map(); availableJob = job;
  vi.spyOn(document, 'hasFocus').mockReturnValue(true);
  m.on.mockImplementation((type, callback) => handlers.set(type, callback));
  m.off.mockImplementation((type) => handlers.delete(type));
  m.getChat.mockResolvedValue(m.chat); m.getKey.mockResolvedValue(new Uint8Array(32).fill(1));
  m.getProfile.mockResolvedValue({ user_id: 'owner' }); m.derive.mockResolvedValue({ privateKey: 'private' });
  m.open.mockResolvedValue({ title: 'Early title', summary: 'Early summary' });
  m.encrypt.mockImplementation(async text => `encrypted:${text}`);
  m.save.mockImplementation(async (_db, baseline, patch) => ({ ...baseline, ...patch }));
  receipt = { ...job, state: 'TERMINAL', versions: { metadata_v: 1, title_v: 1 },
    encrypted_metadata: { encrypted_title: 'accepted-title', encrypted_chat_summary: 'accepted-summary' } };
  m.send.mockImplementation(async (type, payload) => {
    const response = type === 'metadata_job_claim' ? {
      ...availableJob, state: 'AVAILABLE', sealed_payload: '{}', encrypted_fields: ['encrypted_title', 'encrypted_chat_summary'],
    } : receipt;
    queueMicrotask(() => handlers.get(type === 'metadata_job_claim' ? 'metadata_job_claimed' : 'metadata_job_persisted')
      ?.({ ...response, request_id: payload.request_id }));
  });
  service = { hasCompletedInitialSync_FOR_HANDLERS_ONLY: true,
    requestChatContentBatch_FOR_HANDLERS_ONLY: vi.fn().mockResolvedValue(undefined), dispatchEvent: vi.fn() };
});
afterEach(() => { resetRecoveryLifecycleImpl(); vi.restoreAllMocks(); });
it('persists early metadata before completion and applies only accepted fields and versions', async () => {
  receipt.encrypted_metadata = { encrypted_chat_summary: 'accepted-summary' };
  await handleMetadataJobsAvailableImpl(service, { jobs: [job] });
  expect(m.send).toHaveBeenCalledWith('metadata_job_persist', expect.objectContaining({
    wrapped_chat_key: 'wrapped', encrypted_metadata: {
      encrypted_title: 'encrypted:Early title', encrypted_chat_summary: 'encrypted:Early summary',
    },
  }));
  expect(m.save).toHaveBeenCalledWith(expect.anything(), m.chat, {
    encrypted_chat_summary: 'accepted-summary', metadata_v: 1, title_v: 1,
  }, expect.any(Function));
  expect(m.invalidate).toHaveBeenCalledWith('chat');
  expect(service.dispatchEvent.mock.calls[0][0].type).toBe('chatUpdated');
});
it('ignores a superseded job after manual edits or a newer turn', async () => {
  receipt.state = 'SUPERSEDED'; receipt.encrypted_metadata = {};
  await handleMetadataJobsAvailableImpl(service, { jobs: [job] });
  expect(m.save).not.toHaveBeenCalled();
});
it('deduplicates concurrent discovery', async () => {
  await Promise.all([handleMetadataJobsAvailableImpl(service, { jobs: [job] }),
    handleMetadataJobsAvailableImpl(service, { jobs: [job] })]);
  expect(m.send.mock.calls.filter(([type]) => type === 'metadata_job_persist')).toHaveLength(1);
  expect(m.save).toHaveBeenCalledTimes(1);
});
it('fences a key rotation during decrypt', async () => {
  m.open.mockImplementation(async () => {
    m.getKey.mockResolvedValue(new Uint8Array(32).fill(2));
    return { title: 'Early title', summary: 'Early summary' };
  });
  await handleMetadataJobsAvailableImpl(service, { jobs: [job] });
  expect(m.send.mock.calls.map(([type]) => type)).toEqual(['metadata_job_claim']);
  expect(m.save).not.toHaveBeenCalled();
});
it('fences an account reset during encryption', async () => {
  m.encrypt.mockImplementation(async () => { m.epoch += 1; return 'ciphertext'; });
  await handleMetadataJobsAvailableImpl(service, { jobs: [job] });
  expect(m.send.mock.calls.map(([type]) => type)).toEqual(['metadata_job_claim']);
  expect(m.save).not.toHaveBeenCalled();
});
it('rejects mismatched sealed field declarations and receipt identity', async () => {
  m.open.mockResolvedValue({ title: 'Early title' });
  await handleMetadataJobsAvailableImpl(service, { jobs: [job] });
  expect(m.send.mock.calls.map(([type]) => type)).toEqual(['metadata_job_claim']);
  m.open.mockResolvedValue({ title: 'Early title', summary: 'Early summary' }); receipt.task_id = 'other-task';
  await handleMetadataJobsAvailableImpl(service, { jobs: [job] });
  expect(m.save).not.toHaveBeenCalled();
});

it('accepts final refinement after the initial header without inventing source versions', async () => {
  await handleMetadataJobsAvailableImpl(service, { jobs: [job] });
  availableJob = { ...job, job_id: 'final-job', stage: 'postprocessing' };
  receipt = { ...receipt, ...availableJob, versions: { metadata_v: 2, title_v: 2 },
    encrypted_metadata: { encrypted_title: 'final-title', encrypted_chat_summary: 'final-summary' } };
  await handleMetadataJobsAvailableImpl(service, { jobs: [availableJob] });
  expect(m.save).toHaveBeenLastCalledWith(expect.anything(), m.chat, {
    encrypted_title: 'final-title', encrypted_chat_summary: 'final-summary', metadata_v: 2, title_v: 2,
  }, expect.any(Function));
  expect(m.send.mock.calls.filter(([type]) => type === 'metadata_job_persist')
    .every(([, payload]) => payload.versions === undefined)).toBe(true);
});

it.each([false, true])('serializes separate discovery callbacks through the actual IDB guard (manual edit: %s)', async manualEdit => {
  const { persistGeneratedChatMetadata } = await vi.importActual<typeof import('../generatedChatMetadataPersistence')>(
    '../generatedChatMetadataPersistence');
  let row: any = { ...m.chat };
  m.db = { transaction: () => {
    const transaction: any = { objectStore: () => ({ put: (value: any) => { row = { ...value }; },
      get: () => {
        const request: any = {};
        queueMicrotask(() => { request.result = { ...row }; request.onsuccess(); transaction.oncomplete(); });
        return request;
      },
    }) };
    return transaction;
  } } as unknown as IDBDatabase;
  m.getChat.mockImplementation(async () => ({ ...row }));
  m.save.mockImplementation(async (database, baseline, patch, current) => {
    if (manualEdit && patch.metadata_v === 2) row = { ...row, title_v: 3, encrypted_title: 'manual-title' };
    return persistGeneratedChatMetadata(database, baseline, patch, current);
  });
  const responseHandlers = new Map<string, Set<(payload: unknown) => void>>();
  m.on.mockImplementation((type, callback) => {
    if (!responseHandlers.has(type)) responseHandlers.set(type, new Set());
    responseHandlers.get(type)!.add(callback);
  });
  m.off.mockImplementation((type, callback) => responseHandlers.get(type)?.delete(callback));
  const finalJob = { ...job, job_id: 'final-job', stage: 'postprocessing' as const };
  m.open.mockImplementation(async envelope => envelope);
  m.send.mockImplementation(async (type, payload) => {
    const final = payload.job_id === finalJob.job_id;
    const identity = final ? finalJob : job;
    const response = type === 'metadata_job_claim' ? { ...identity, state: 'AVAILABLE',
      sealed_payload: JSON.stringify({ title: final ? 'Final title' : 'Early title', summary: final ? 'Final summary' : 'Early summary' }),
      encrypted_fields: ['encrypted_title', 'encrypted_chat_summary'],
    } : { ...identity, state: 'TERMINAL', encrypted_metadata: payload.encrypted_metadata,
      versions: { title_v: final ? 2 : 1, metadata_v: final ? 2 : 1 } };
    queueMicrotask(() => {
      for (const callback of [...responseHandlers.get(type === 'metadata_job_claim' ? 'metadata_job_claimed' : 'metadata_job_persisted') ?? []]) {
        callback({ ...response, request_id: payload.request_id });
      }
    });
  });
  await Promise.all([handleMetadataJobsAvailableImpl(service, { jobs: [job] }),
    handleMetadataJobsAvailableImpl(service, { jobs: [finalJob] })]);
  expect(m.save).toHaveBeenCalledTimes(2);
  expect(m.save.mock.calls[1][1]).toMatchObject({ encrypted_title: 'encrypted:Early title', title_v: 1,
    encrypted_chat_summary: 'encrypted:Early summary', metadata_v: 1 });
  expect(row).toMatchObject({ encrypted_title: manualEdit ? 'manual-title' : 'encrypted:Final title',
    encrypted_chat_summary: 'encrypted:Final summary', title_v: manualEdit ? 3 : 2, metadata_v: 2 });
});
