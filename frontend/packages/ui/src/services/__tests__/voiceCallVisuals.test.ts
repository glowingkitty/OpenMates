import { beforeEach, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({
  sendKeys: vi.fn(), existingKey: vi.fn(async () => new Uint8Array(32)), clearers: new Set<() => void>(), prepare: vi.fn(), epoch: 1, identity: 'owner', upload: vi.fn(), send: vi.fn(), attach: vi.fn(),
  put: vi.fn(), keys: vi.fn(), raw: vi.fn(),
}));
vi.mock('../../components/enter_message/services/uploadService', () => ({ uploadFileToServer: mocks.upload }));
vi.mock('../db', () => ({ chatDB: { getChat: vi.fn(async () => ({ team_id: null })) } }));
vi.mock('../userDB', () => ({ userDB: { getUserProfile: vi.fn(async () => ({ user_id: 'user' })) } }));
vi.mock('../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKey: vi.fn(async () => new Uint8Array(32)) } }));
vi.mock('../chatKeyWriteGuard', () => ({ ensureChatKeySafeForWrite: vi.fn(async () => true) }));
vi.mock('../encryption/MetadataEncryptor', () => ({
  deriveEmbedKeyFromChatKey: vi.fn(async () => new Uint8Array(32)),
  encryptWithEmbedKey: vi.fn(async (value: string) => `encrypted:${value}`),
  wrapEmbedKeyWithMasterKey: vi.fn(async () => 'master-wrapped'),
  wrapEmbedKeyWithChatKey: vi.fn(async () => 'chat-wrapped'),
}));
vi.mock('../embedStore', () => ({ embedStore: {
  getEmbedKey: mocks.existingKey, getPersistencePayload: mocks.raw, setEmbedKeyInCache: vi.fn(), storeEmbedKeys: mocks.keys, putEncrypted: mocks.put,
} }));
vi.mock('../embedSenders', () => ({ sendStoreEmbedImpl: mocks.send, sendStoreEmbedKeysImpl: mocks.sendKeys }));
vi.mock('../chatSyncService', () => ({ chatSyncService: {} }));
vi.mock('../voiceCallMessages', () => ({ upsertCallUserArtifact: mocks.attach }));
vi.mock('../../message_parsing/utils', () => ({ computeSHA256: vi.fn(async (value: string) => `hash:${value}`) }));
vi.mock('../workspaceQueryCache', () => ({ getWorkspaceCacheIdentity: () => mocks.identity }));
vi.mock('../workspaceCacheLifecycle', () => ({ getWorkspaceCacheEpoch: () => mocks.epoch,
  registerWorkspaceCacheClear: (clear: () => void) => { mocks.clearers.add(clear); return () => mocks.clearers.delete(clear); },
}));
vi.mock('../uploadPrivacy', () => ({ prepareFileForUpload: mocks.prepare }));
vi.mock('../../config/api.js', () => ({ getUploadUrl: () => 'https://upload.example.test' }));
import { persistCallSourceFrame } from '../voiceCallVisuals';
const frame = { callId: 'call', chatId: 'chat', messageId: 'user-turn', frameId: 'frame',
  data: '/9j/2Q==', capturedAt: 1700000000123, createdAt: 1700000000 };
beforeEach(() => {
  vi.clearAllMocks(); mocks.clearers.clear(); mocks.epoch = 1; mocks.identity = 'owner';
  mocks.send.mockResolvedValue(true);
  mocks.upload.mockResolvedValue({ embed_id: 'uploaded-frame', content_hash: 'source-hash',
    files: { preview: { s3_key: 'preview' }, original: { s3_key: 'original' } },
    s3_base_url: 'encrypted-bucket', aes_key: 'private-key', aes_nonce: 'nonce', vault_wrapped_aes_key: 'wrapped' });
});
// contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
it('uploads the exact source JPEG and attaches the same encrypted image to the user turn', async () => {
  const reference = await persistCallSourceFrame(frame);
  const file = mocks.upload.mock.calls[0][0] as File;
  expect(file.type).toBe('image/jpeg');
  expect(file.size).toBe(4);
  const bytes = await new Promise<Uint8Array>((resolve) => {
    const reader = new FileReader(); reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
    reader.readAsArrayBuffer(file);
  });
  expect([...bytes]).toEqual([255, 216, 255, 217]);
  expect(reference).toEqual({ type: 'image', embed_id: 'uploaded-frame', source_frame_id:'frame',
    captured_at:1700000000123,source_call_id:'call',source:'camera' });
  const payload = mocks.send.mock.calls[0][1];
  expect(payload).toMatchObject({ encrypted_type: 'encrypted:images-image', hashed_chat_id: 'hash:chat',
    hashed_message_id: 'hash:user-turn', is_private: true });
  expect(payload).not.toHaveProperty('aes_key');
  expect(mocks.keys.mock.calls[0][0]).toHaveLength(2);
  expect(mocks.attach).not.toHaveBeenCalled();
  expect(mocks.put.mock.calls[0][3]).toContain('source: camera');
});
// contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
it('does not announce a source image while encrypted synchronization is pending', async () => {
  mocks.send.mockResolvedValue(false);
  await expect(persistCallSourceFrame(frame)).rejects.toThrow('awaiting encrypted sync');
  expect(mocks.attach).not.toHaveBeenCalled();
});
// contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
it('fences account/cache changes while the upload is in flight', async () => {
  mocks.upload.mockImplementationOnce(async () => { mocks.epoch += 1; return { embed_id: 'old-source' }; });
  await expect(persistCallSourceFrame(frame)).rejects.toThrow('account changed');
  expect(mocks.put).not.toHaveBeenCalled();
  expect(mocks.send).not.toHaveBeenCalled();
  expect(mocks.attach).not.toHaveBeenCalled();
});

// contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
it('reuses deduplicated source ciphertext in its original chat scope', async () => {
  mocks.upload.mockResolvedValueOnce({ embed_id: 'uploaded-frame', deduplicated: true, content_hash: 'source-hash' });
  mocks.raw.mockResolvedValueOnce({ encrypted_type: 'old-type', encrypted_content: 'old-ciphertext',
    hashed_chat_id: 'old-chat', hashed_message_id: 'old-turn', hashed_user_id: 'hash:user', status: 'finished' });
  await persistCallSourceFrame(frame);
  expect(mocks.put).not.toHaveBeenCalled();
  expect(mocks.send.mock.calls[0][1]).toMatchObject({ encrypted_content: 'old-ciphertext', hashed_chat_id: 'old-chat' });
  expect(mocks.sendKeys).toHaveBeenCalledWith(expect.anything(), { keys: [expect.objectContaining({
    hashed_chat_id: 'hash:chat', key_type: 'chat', encrypted_embed_key: 'chat-wrapped',
  })] });
  expect(mocks.attach).not.toHaveBeenCalled();
});
// contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
it('preserves an existing upload when its canonical metadata is unavailable', async () => {
  mocks.upload.mockResolvedValueOnce({ embed_id: 'uploaded-frame', deduplicated: true });
  mocks.raw.mockResolvedValueOnce(null);
  await expect(persistCallSourceFrame(frame)).rejects.toThrow('metadata unavailable');
  expect(mocks.put).not.toHaveBeenCalled();
  expect(mocks.attach).not.toHaveBeenCalled();
});

// contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
it('aborts before cookie-authenticated XHR when the account changes during file preparation', async () => {
  const actual = await vi.importActual<typeof import('../../components/enter_message/services/uploadService')>(
    '../../components/enter_message/services/uploadService');
  let prepared!: (file: File) => void;
  mocks.prepare.mockImplementationOnce(() => new Promise<File>((resolve) => { prepared = resolve; }));
  mocks.upload.mockImplementationOnce(actual.uploadFileToServer);
  const network = vi.fn();
  vi.stubGlobal('XMLHttpRequest', network);
  try {
    const pending = persistCallSourceFrame(frame);
    const rejected = expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    await vi.waitFor(() => expect(mocks.prepare).toHaveBeenCalled());
    mocks.epoch += 1;
    for (const clear of mocks.clearers) clear();
    prepared(new File(['sanitized source'], 'source.jpg', { type: 'image/jpeg' }));
    await rejected;
    expect(network).not.toHaveBeenCalled();
    expect(mocks.put).not.toHaveBeenCalled();
    expect(mocks.attach).not.toHaveBeenCalled();
    expect(mocks.clearers.size).toBe(0);
  } finally { vi.unstubAllGlobals(); }
});

// contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
it('serializes identical source pixels until the first canonical save completes, retaining both user attachments', async () => {
  let finish!: (confirmed: boolean) => void;
  mocks.send.mockImplementationOnce(() => new Promise<boolean>((resolve) => { finish = resolve; }));
  const first = persistCallSourceFrame(frame);
  await vi.waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(1));
  mocks.upload.mockResolvedValueOnce({ embed_id: 'uploaded-frame', deduplicated: true });
  mocks.raw.mockResolvedValueOnce({ embed_id: 'uploaded-frame', encrypted_type: 'canonical-type',
    encrypted_content: 'canonical-content', hashed_chat_id: 'hash:chat', hashed_message_id: 'hash:user-turn',
    hashed_user_id: 'hash:user', created_at: 1700000000, updated_at: 1700000000, status: 'finished' });
  const second = persistCallSourceFrame({ ...frame, messageId: 'second-user-turn', frameId: 'next-frame' });
  await Promise.resolve();
  expect(mocks.upload).toHaveBeenCalledTimes(1);
  finish(true);
  await expect(first).resolves.toMatchObject({ type: 'image', embed_id: 'uploaded-frame',source_frame_id:'frame' });
  await expect(second).resolves.toMatchObject({ type: 'image', embed_id: 'uploaded-frame',source_frame_id:'next-frame' });
  expect(mocks.attach).not.toHaveBeenCalled();
  expect(mocks.send).toHaveBeenCalledTimes(2);
});
