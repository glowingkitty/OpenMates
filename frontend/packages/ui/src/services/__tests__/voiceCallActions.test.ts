import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ChatSynchronizationService } from '../chatSyncService';
const mocks = vi.hoisted(() => ({
  token: 'a'.repeat(64) + ':expiry:signature',
  profile: vi.fn(async () => ({ user_id: 'user-owner-uuid' })),
  chat: vi.fn(async () => ({ user_id: 'user-owner-uuid', team_id: null } as Record<string, unknown> | null)),
  key: vi.fn(async () => new Uint8Array(32)),
  keyReady: vi.fn((_listener: (chatId: string) => void) => () => {}),
  artifact: vi.fn(async (_event: unknown) => ({ revision: 2, ciphertext: 'encrypted-committed-artifact' })),
  send: vi.fn(async (_type: string, _payload: unknown) => {}),
}));
vi.mock('../userDB', () => ({ userDB: { getUserProfile: mocks.profile } }));
vi.mock('../db', () => ({ chatDB: { getChat: mocks.chat } }));
vi.mock('../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKey: mocks.key, onKeyReady: mocks.keyReady } }));
vi.mock('../../stores/userProfile', () => ({ userProfile: { subscribe: (run: () => void) => { run(); return () => {}; } } }));
vi.mock('../../utils/cookies', () => ({ getWebSocketToken: () => mocks.token }));
vi.mock('../voiceCallMessages', () => ({ upsertCallArtifact: mocks.artifact }));
vi.mock('../websocketService', () => ({ webSocketService: { sendMessage: mocks.send } }));
import { handleVoiceActionCompleted } from '../voiceCallActions';

const receipt = (id = 'receipt-one:0') => ({ request_id: id, call_id: 'call-id-one', chat_id: 'chat-id-one',
  assistant_message_id: 'assistant-one', user_message_id: 'user-turn-one',
  initiator_session_id: 'a'.repeat(64), user_id: 'user-owner-uuid', embed_refs: ['artifact-one'], created_at: 100 });
function service() {
  return Object.assign(new EventTarget(), { requestChatContentBatch_FOR_HANDLERS_ONLY: vi.fn(async () => {}) }) as unknown as ChatSynchronizationService;
}
beforeEach(() => {
  vi.clearAllMocks(); vi.stubGlobal('crypto', webcrypto);
  mocks.token = 'a'.repeat(64) + ':expiry:signature';
  mocks.profile.mockResolvedValue({ user_id: 'user-owner-uuid' });
  mocks.chat.mockResolvedValue({ user_id: 'user-owner-uuid', team_id: null });
  mocks.artifact.mockResolvedValue({ revision: 2, ciphertext: 'encrypted-committed-artifact' });
});
afterEach(() => vi.unstubAllGlobals());

describe('committed voice action recovery', () => {
  // contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.lifecycle.recovery-and-billing
  it('retains a post-hangup receipt until its encrypted embed journal delivery completes', async () => {
    const owner = service();
    mocks.artifact.mockRejectedValueOnce(new Error('Call artifact is awaiting encrypted embed delivery'));
    await expect(handleVoiceActionCompleted(owner, receipt('late-embed:0'))).rejects.toThrow('awaiting encrypted embed delivery');
    expect(mocks.send).not.toHaveBeenCalled();
    owner.dispatchEvent(new CustomEvent('embedUpdated', { detail: { embed_id: 'unrelated-embed' } }));
    expect(mocks.artifact).toHaveBeenCalledOnce();
    owner.dispatchEvent(new CustomEvent('embedUpdated', { detail: { embed_id: 'artifact-one' } }));
    await vi.waitFor(() => expect(mocks.send).toHaveBeenCalledOnce());
    expect(mocks.artifact).toHaveBeenCalledTimes(2);
  });
  // contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.lifecycle.recovery-and-billing,video-call.privacy
  it('finalizes the issued encrypted response after Live ends and ACKs its exact ciphertext revision', async () => {
    const source = receipt();
    const owner = service();
    let finish!: (proof: { revision: number; ciphertext: string }) => void;
    mocks.artifact.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const recovery = handleVoiceActionCompleted(owner, source);
    await vi.waitFor(() => expect(mocks.artifact).toHaveBeenCalledOnce());
    expect(mocks.send).not.toHaveBeenCalled();
    finish({ revision: 2, ciphertext: 'encrypted-committed-artifact' });
    await recovery;
    expect(mocks.artifact).toHaveBeenCalledWith({ callId: source.call_id, chatId: source.chat_id,
      messageId: source.assistant_message_id, userMessageId: source.user_message_id,
      createdAt: source.created_at, embedRefs: source.embed_refs });
    const hash = Buffer.from(await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode('encrypted-committed-artifact'))).toString('hex');
    expect(mocks.send).toHaveBeenCalledExactlyOnceWith('voice_action_completed_confirmed', {
      request_id: source.request_id, call_id: source.call_id, chat_id: source.chat_id,
      assistant_message_id: source.assistant_message_id, revision: 2, ciphertext_hash: hash,
    });
  });

  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.privacy
  it('ignores receipts belonging to another authenticated session or owner', async () => {
    await handleVoiceActionCompleted(service(), { ...receipt('foreign-session:0'), initiator_session_id: 'b'.repeat(64) });
    await handleVoiceActionCompleted(service(), { ...receipt('foreign-owner:0'), user_id: 'another-user' });
    expect(mocks.artifact).not.toHaveBeenCalled(); expect(mocks.send).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.chat.transcripts
  it('waits for normal chat/key hydration and retries after the chat becomes available', async () => {
    const owner = service();
    mocks.chat.mockResolvedValue(null);
    await handleVoiceActionCompleted(owner, receipt('cold-chat-receipt:0'));
    expect(owner.requestChatContentBatch_FOR_HANDLERS_ONLY).toHaveBeenCalledExactlyOnceWith(['chat-id-one']);
    expect(mocks.artifact).not.toHaveBeenCalled();
    mocks.chat.mockResolvedValue({ user_id: 'user-owner-uuid', team_id: null });
    owner.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id: 'chat-id-one' } }));
    await vi.waitFor(() => expect(mocks.send).toHaveBeenCalledOnce());
    expect(mocks.artifact).toHaveBeenCalledOnce();
  });
});
