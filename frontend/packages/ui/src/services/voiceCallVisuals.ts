/** Persist only the exact source frame selected by a call skill, as a normal image. */
import { encode } from '@toon-format/toon';
import { uploadFileToServer, type UploadFileResponse } from '../components/enter_message/services/uploadService';
import { chatDB } from './db';
import { chatKeyManager } from './encryption/ChatKeyManager';
import { ensureChatKeySafeForWrite } from './chatKeyWriteGuard';
import { deriveEmbedKeyFromChatKey, encryptWithEmbedKey, wrapEmbedKeyWithMasterKey,
  wrapEmbedKeyWithChatKey } from './encryption/MetadataEncryptor';
import { embedStore, type EmbedKeyEntry } from './embedStore';
import { sendStoreEmbedImpl, sendStoreEmbedKeysImpl } from './embedSenders';
import { chatSyncService } from './chatSyncService';
import { userDB } from './userDB';
import { computeSHA256 } from '../message_parsing/utils';
import { getWorkspaceCacheIdentity } from './workspaceQueryCache';
import { getWorkspaceCacheEpoch, registerWorkspaceCacheClear } from './workspaceCacheLifecycle';
import { upsertCallUserArtifact } from './voiceCallMessages';
import type { VoiceArtifactReference } from './voiceCallArtifactReferences';

export interface CallSourceFrame {
  callId: string; chatId: string; messageId: string; frameId: string;
  data: string; capturedAt: number; createdAt: number;
}

const sourceQueues = new Map<string, Promise<VoiceArtifactReference>>();

export async function persistCallSourceFrame(frame: CallSourceFrame): Promise<VoiceArtifactReference> {
  const identity = getWorkspaceCacheIdentity();
  const epoch = getWorkspaceCacheEpoch();
  const assertCurrent = () => {
    if (!identity || identity !== getWorkspaceCacheIdentity() || epoch !== getWorkspaceCacheEpoch()) {
      throw new Error('Call source account changed');
    }
  };
  assertCurrent();
  const sourceKey = `${identity}:${epoch}:${await computeSHA256(frame.data)}`;
  assertCurrent();
  const previous = sourceQueues.get(sourceKey) ?? Promise.resolve();
  const pending = previous.catch(() => {}).then(() => persistSource(frame, assertCurrent));
  sourceQueues.set(sourceKey, pending);
  const release = () => { if (sourceQueues.get(sourceKey) === pending) sourceQueues.delete(sourceKey); };
  void pending.then(release, release);
  return pending;
}

async function persistSource(frame: CallSourceFrame, assertCurrent: () => void): Promise<VoiceArtifactReference> {
  assertCurrent();
  if (!frame.callId || !frame.chatId || !frame.messageId || !/^[A-Za-z0-9_-]{1,240}$/.test(frame.frameId)
      || !Number.isFinite(frame.capturedAt) || !Number.isSafeInteger(frame.createdAt)
      || !frame.data || frame.data.length > 6_000_000 || !/^[A-Za-z0-9+/]+={0,2}$/.test(frame.data)) {
    throw new Error('Invalid call source frame');
  }
  const chat = await chatDB.getChat(frame.chatId);
  const profile = await userDB.getUserProfile();
  const chatKey = await chatKeyManager.getKey(frame.chatId);
  assertCurrent();
  if (!profile?.user_id || !chat || chat.team_id || chat.chat_visibility === 'direct' || !chatKey
      || !await ensureChatKeySafeForWrite(frame.chatId, chatKey, 'call source image')) {
    throw new Error('Call source chat unavailable');
  }
  const bytes = Uint8Array.from(atob(frame.data), (character) => character.charCodeAt(0));
  if (bytes[0] !== 0xff || bytes[1] !== 0xd8 || bytes[2] !== 0xff) throw new Error('Call source must be JPEG');
  const filename = `call-source-${frame.frameId}.jpg`;
  const file = new File([bytes], filename, { type: 'image/jpeg' });
  assertCurrent();
  const controller = new AbortController();
  const unregister = registerWorkspaceCacheClear(() => controller.abort());
  let upload: UploadFileResponse;
  try {
    assertCurrent();
    upload = await uploadFileToServer(file, controller.signal);
  } finally {
    unregister();
  }
  assertCurrent();
  const reference: VoiceArtifactReference = { type: 'image', embed_id: upload.embed_id };
  // Upload deduplication can return an image already owned by another chat.
  // Confirm its existing ciphertext in its original scope rather than rotating
  // its key or replacing metadata beneath earlier source references.
  const previous = upload.deduplicated ? await embedStore.getPersistencePayload(upload.embed_id) : null;
  if (previous) {
    assertCurrent();
    const confirmed = await sendStoreEmbedImpl(chatSyncService, previous);
    if (!confirmed) throw new Error('Call source awaiting encrypted sync');
    assertCurrent();
    const existingKey = await embedStore.getEmbedKey(upload.embed_id, previous.hashed_chat_id);
    if (!existingKey) throw new Error('Existing call source key unavailable');
    const newChatHash = await computeSHA256(frame.chatId);
    const chatWrapper: EmbedKeyEntry = { hashed_embed_id: await computeSHA256(upload.embed_id),
      key_type: 'chat', hashed_chat_id: newChatHash,
      encrypted_embed_key: await wrapEmbedKeyWithChatKey(existingKey, chatKey),
      hashed_user_id: await computeSHA256(profile.user_id), created_at: Math.floor(Date.now() / 1000) };
    assertCurrent();
    await sendStoreEmbedKeysImpl(chatSyncService, { keys: [{ ...chatWrapper }] });
    assertCurrent();
    await embedStore.storeEmbedKeys([chatWrapper], assertCurrent);
    embedStore.setEmbedKeyInCache(upload.embed_id, existingKey, newChatHash);
    await upsertCallUserArtifact({ callId: frame.callId, chatId: frame.chatId, messageId: frame.messageId,
      createdAt: frame.createdAt, embedReferences: [reference] }, assertCurrent);
    assertCurrent();
    return reference;
  }
  if (upload.deduplicated) throw new Error('Existing call source metadata unavailable');
  const content = encode({ app_id: 'images', skill_id: 'upload', type: 'image', status: 'finished',
    filename, file_size: bytes.length, file_type: 'image/jpeg', content_hash: upload.content_hash,
    s3_base_url: upload.s3_base_url, files: upload.files, aes_key: upload.aes_key,
    aes_nonce: upload.aes_nonce, vault_wrapped_aes_key: upload.vault_wrapped_aes_key,
    ai_detection: upload.ai_detection, source_frame_id: frame.frameId, captured_at: frame.capturedAt });
  const key = await deriveEmbedKeyFromChatKey(chatKey, upload.embed_id);
  const hashedChatId = await computeSHA256(frame.chatId);
  const hashedUserId = await computeSHA256(profile.user_id);
  const hashedEmbedId = await computeSHA256(upload.embed_id);
  const now = Math.floor(Date.now() / 1000);
  const master = await wrapEmbedKeyWithMasterKey(key);
  const wrappedChat = await wrapEmbedKeyWithChatKey(key, chatKey);
  if (!master || !wrappedChat) throw new Error('Call source key unavailable');
  const keys: EmbedKeyEntry[] = [
    { hashed_embed_id: hashedEmbedId, key_type: 'master', hashed_chat_id: null,
      encrypted_embed_key: master, hashed_user_id: hashedUserId, created_at: now },
    { hashed_embed_id: hashedEmbedId, key_type: 'chat', hashed_chat_id: hashedChatId,
      encrypted_embed_key: wrappedChat, hashed_user_id: hashedUserId, created_at: now },
  ];
  const payload = { embed_id: upload.embed_id, chat_id: frame.chatId,
    encrypted_type: await encryptWithEmbedKey('images-image', key),
    encrypted_content: await encryptWithEmbedKey(content, key),
    encrypted_text_preview: await encryptWithEmbedKey(filename, key), status: 'finished',
    hashed_chat_id: hashedChatId, hashed_message_id: await computeSHA256(frame.messageId),
    hashed_user_id: hashedUserId, content_hash: upload.content_hash,
    is_private: true, is_shared: false, created_at: now, updated_at: now };
  assertCurrent();
  embedStore.setEmbedKeyInCache(upload.embed_id, key, hashedChatId);
  await embedStore.storeEmbedKeys(keys, assertCurrent);
  await embedStore.putEncrypted(`embed:${upload.embed_id}`, {
    ...payload, createdAt: now * 1000, updatedAt: now * 1000,
  }, 'images-image', content, { app_id: 'images', skill_id: 'upload' }, { writeGuard: assertCurrent });
  assertCurrent();
  if (!await sendStoreEmbedImpl(chatSyncService, payload, { keys: keys.map((entry) => ({ ...entry })) })) throw new Error('Call source awaiting encrypted sync');
  assertCurrent();
  await upsertCallUserArtifact({ callId: frame.callId, chatId: frame.chatId, messageId: frame.messageId,
    createdAt: frame.createdAt, embedReferences: [reference] }, assertCurrent);
  assertCurrent();
  return reference;
}
