// contract-test-file: tooling
import { describe, expect, it, vi } from 'vitest';
import {
  claimDraftChatForSend,
  createSendClaimSet,
  createSendStepTrail,
  discardEmptyClaimedChatsAfterFailedSend,
  isDraftChatClaimedForSend,
  isFirstSendStopped,
  markFirstSendStopped,
  shouldDiscardChatAfterFailedSend,
} from '../draftSendClaims';

describe('draft send claims', () => {
  it('reports an unclaimed or empty chat id as not claimed', () => {
    expect(isDraftChatClaimedForSend('never-claimed')).toBe(false);
    expect(isDraftChatClaimedForSend(null)).toBe(false);
    expect(isDraftChatClaimedForSend(undefined)).toBe(false);
  });

  it('holds the claim until released and release is idempotent', () => {
    const release = claimDraftChatForSend('chat-a');
    expect(isDraftChatClaimedForSend('chat-a')).toBe(true);
    release();
    expect(isDraftChatClaimedForSend('chat-a')).toBe(false);
    release();
    expect(isDraftChatClaimedForSend('chat-a')).toBe(false);
  });

  it('ref-counts two concurrent sends on one chat', () => {
    const first = claimDraftChatForSend('chat-b');
    const second = claimDraftChatForSend('chat-b');
    first();
    first();
    expect(isDraftChatClaimedForSend('chat-b')).toBe(true);
    second();
    expect(isDraftChatClaimedForSend('chat-b')).toBe(false);
  });

  it('claim set claims each chat once and releases all', () => {
    const set = createSendClaimSet();
    set.claim('chat-c');
    set.claim('chat-c');
    set.claim(null);
    expect(set.claimedChatIds()).toEqual(['chat-c']);
    set.releaseAll();
    expect(isDraftChatClaimedForSend('chat-c')).toBe(false);
  });

  it('step trail is bounded and resettable', () => {
    const trail = createSendStepTrail(2);
    ['a', 'b', 'c'].forEach(trail.record);
    expect(trail.snapshot()).toEqual(['b', 'c']);
    trail.reset();
    expect(trail.snapshot()).toEqual([]);
  });
});

describe('failed-send cleanup decision', () => {
  it('discards only an empty chat the composer does not hold', () => {
    expect(shouldDiscardChatAfterFailedSend({ messages_v: 0 }, 0, false)).toBe(true);
    expect(shouldDiscardChatAfterFailedSend({ messages_v: 0 }, 0, true)).toBe(false);
    expect(shouldDiscardChatAfterFailedSend({ messages_v: 1 }, 0, false)).toBe(false);
    expect(shouldDiscardChatAfterFailedSend({ messages_v: 0 }, 1, false)).toBe(false);
    expect(shouldDiscardChatAfterFailedSend(undefined, 0, false)).toBe(false);
  });

  it('deletes and announces empty chats, keeps restored-draft chats, logs failures', async () => {
    const onDeleted = vi.fn();
    const deleteDraftOnlyChat = vi.fn().mockResolvedValue({ deleted: true, deletedEmbedIds: ['e1'] });
    const deps = {
      getChat: vi.fn().mockResolvedValue({ messages_v: 0 }),
      getMessagesForChat: vi.fn().mockResolvedValue([]),
      deleteDraftOnlyChat,
      onDeleted,
    };
    const deleted = await discardEmptyClaimedChatsAfterFailedSend(['gone', 'kept'], (id) => id === 'kept', deps);
    expect(deleted).toEqual(['gone']);
    expect(deleteDraftOnlyChat).toHaveBeenCalledTimes(1);
    expect(onDeleted).toHaveBeenCalledWith('gone', ['e1']);

    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    deleteDraftOnlyChat.mockRejectedValueOnce(new Error('db down'));
    expect(await discardEmptyClaimedChatsAfterFailedSend(['x'], () => false, deps)).toEqual([]);
    expect(error).toHaveBeenCalled();
    error.mockRestore();
  });
});

describe('stopped first send marker', () => {
  it('blocks generated metadata for a stopped chat until a new send claims it', () => {
    expect(isFirstSendStopped('stopped-chat')).toBe(false);
    markFirstSendStopped('stopped-chat');
    expect(isFirstSendStopped('stopped-chat')).toBe(true);
    claimDraftChatForSend('stopped-chat')();
    expect(isFirstSendStopped('stopped-chat')).toBe(false);
  });

  it('ignores empty chat ids', () => {
    markFirstSendStopped(null);
    expect(isFirstSendStopped(null)).toBe(false);
  });
});

