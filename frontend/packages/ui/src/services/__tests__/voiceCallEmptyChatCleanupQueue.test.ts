import { beforeEach, describe, expect, it, vi } from 'vitest';

const env = vi.hoisted(() => ({
  identity: 'https://api.example/v1|user-1||0|0' as string | null,
  snapshot: vi.fn(),
  remove: vi.fn(async (_input: unknown, _read: unknown) => ({ accepted: true, localEligible: true })),
  record: vi.fn(async (_event: unknown) => {}),
  getChat: vi.fn(async (_chatId: string): Promise<unknown> => ({ chat_id: 'chat-a' })),
}));
vi.mock('../voiceCallEmptyChatCleanup', () => ({
  cleanupEmptyVoiceCallChat: env.remove,
  readEmptyVoiceCallCleanupSnapshot: env.snapshot,
}));
vi.mock('../workspaceQueryCache', () => ({ getWorkspaceCacheIdentity: () => env.identity }));
vi.mock('../workspaceCacheLifecycle', () => ({ getWorkspaceCacheEpoch: () => 0 }));
vi.mock('../personalChatTurnBarrier', () => ({ hasPendingPersonalChatTurn: () => false }));
vi.mock('../voiceCallLifecycle', () => ({ recordCallLifecycle: env.record }));
vi.mock('../db', () => ({ chatDB: { getChat: env.getChat } }));

import {
  markEmptyCallCleanupTerminated, noteEmptyCallCleanupCallId, pendingEmptyCallCleanups,
  rememberEmptyCallCleanup, retryPendingEmptyVoiceCallCleanups, setEmptyCallCleanupLive,
} from '../voiceCallEmptyChatCleanupQueue';

const CALL = 'a'.repeat(32);
const ATTEMPT = '018fabcd-abcd-7abc-8abc-abcdefabcdef';
const lifecycle = (action: 'started' | 'ended') => ({
  message_id: `${action === 'started' ? '00000000' : 'ffffffff'}-voice-call-${CALL}-${action}`,
  chat_id: 'chat-a', role: 'system', status: 'synced',
  content: JSON.stringify({ schema_version: 1, type: 'voice_call', action, call_id: CALL, created_at: 1, active_elapsed_seconds: 0 }),
});
const snapshot = (messages: unknown[], chat: Record<string, unknown> = {}) => ({
  chat: { chat_id: 'chat-a', messages_v: messages.length, ...chat }, messages,
  artifactCount: 0, pendingOperationCount: 0, hasDraft: false, hasOrdinaryText: false, hasPendingTurn: false,
});

describe('durable empty voice-call cleanup', () => {
  beforeEach(() => {
    localStorage.clear();
    env.identity = 'https://api.example/v1|user-1||0|0';
    env.snapshot.mockReset(); env.remove.mockClear(); env.record.mockClear(); env.getChat.mockClear();
    setEmptyCallCleanupLive('chat-a', false);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing
  it('retries an interrupted call after reload and forgets it once the server deletes it', async () => {
    rememberEmptyCallCleanup('chat-a', ATTEMPT);
    noteEmptyCallCleanupCallId('chat-a', CALL);
    markEmptyCallCleanupTerminated('chat-a');
    env.snapshot.mockResolvedValue(snapshot([lifecycle('started'), lifecycle('ended')]));
    await retryPendingEmptyVoiceCallCleanups();
    expect(env.remove).toHaveBeenCalledOnce();
    expect(env.remove.mock.calls[0][0]).toEqual({ chatId: 'chat-a', cleanupAttemptId: ATTEMPT, callId: CALL,
      expectedMessagesVersion: 2 });
    expect(pendingEmptyCallCleanups()).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.call-events
  it('completes an ended lifecycle event the interrupted call never persisted', async () => {
    rememberEmptyCallCleanup('chat-a', ATTEMPT);
    noteEmptyCallCleanupCallId('chat-a', CALL);
    markEmptyCallCleanupTerminated('chat-a');
    env.snapshot.mockResolvedValueOnce(snapshot([lifecycle('started')]))
      .mockResolvedValue(snapshot([lifecycle('started'), lifecycle('ended')]));
    await retryPendingEmptyVoiceCallCleanups();
    expect(env.record).toHaveBeenCalledOnce();
    expect(env.record.mock.calls[0][0]).toMatchObject({ type: 'ended', chatId: 'chat-a', callId: CALL });
    expect(env.remove).toHaveBeenCalledOnce();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing
  it('keeps a call that is live in this tab or was seen recently untouched', async () => {
    rememberEmptyCallCleanup('chat-a', ATTEMPT);
    env.snapshot.mockResolvedValue(snapshot([]));
    await retryPendingEmptyVoiceCallCleanups();
    setEmptyCallCleanupLive('chat-a', true);
    markEmptyCallCleanupTerminated('chat-a');
    await retryPendingEmptyVoiceCallCleanups();
    expect(env.snapshot).not.toHaveBeenCalled();
    expect(env.remove).not.toHaveBeenCalled();
    expect(pendingEmptyCallCleanups()).toHaveLength(1);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it('drops the record without deleting when the chat gained real content', async () => {
    rememberEmptyCallCleanup('chat-a', ATTEMPT);
    noteEmptyCallCleanupCallId('chat-a', CALL);
    markEmptyCallCleanupTerminated('chat-a');
    env.snapshot.mockResolvedValue(snapshot([lifecycle('started'), { ...lifecycle('ended'), message_id: 'user-1', role: 'user' }]));
    await retryPendingEmptyVoiceCallCleanups();
    expect(env.record).not.toHaveBeenCalled();
    expect(env.remove).not.toHaveBeenCalled();
    expect(pendingEmptyCallCleanups()).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing
  it('keeps the record for a later retry when the server does not accept yet', async () => {
    env.remove.mockResolvedValueOnce({ accepted: false, localEligible: false });
    rememberEmptyCallCleanup('chat-a', ATTEMPT);
    markEmptyCallCleanupTerminated('chat-a');
    env.snapshot.mockResolvedValue(snapshot([]));
    await retryPendingEmptyVoiceCallCleanups();
    expect(env.remove).toHaveBeenCalledOnce();
    expect(pendingEmptyCallCleanups()).toHaveLength(1);
    expect(pendingEmptyCallCleanups()[0].attempts).toBe(1);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it('never retries another account or a team workspace', async () => {
    rememberEmptyCallCleanup('chat-a', ATTEMPT);
    markEmptyCallCleanupTerminated('chat-a');
    env.identity = 'https://api.example/v1|user-2||0|0';
    expect(pendingEmptyCallCleanups()).toEqual([]);
    env.identity = 'https://api.example/v1|user-1|team-1|0|0';
    expect(pendingEmptyCallCleanups()).toEqual([]);
    await retryPendingEmptyVoiceCallCleanups();
    expect(env.remove).not.toHaveBeenCalled();
  });
});
