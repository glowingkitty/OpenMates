import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
vi.mock('../teamStore', async () => ({ activeTeamId: (await import('svelte/store')).writable(null) }));
import { ActiveAITaskMap, activityChats, runningChatIds, activeChatCount } from '../chatActivityStore';
import { aiTypingStore, aiTypingByChatStore } from '../aiTypingStore';
import type { Chat } from '../../types/chat';
const tasks = new ActiveAITaskMap();
beforeEach(() => { tasks.clear(); aiTypingStore.reset(); activityChats.set([]); });
describe('activity independent of sidebar mounting', () => {
  // contract-test: supporting surface=gui.web assertions=chat-navigation.activity.global-running
  it('tracks multiple tasks and preserves the other task on completion', () => {
    tasks.set('one', { taskId: 'first', userMessageId: 'u1' });
    tasks.set('two', { taskId: 'second', userMessageId: 'u2' });
    expect([...get(runningChatIds)]).toEqual(['one', 'two']);
    tasks.delete('one'); expect([...get(runningChatIds)]).toEqual(['two']);
    tasks.clear(); expect(get(runningChatIds).size).toBe(0);
  });
  // contract-test: supporting surface=gui.web assertions=chat-navigation.activity.global-running
  it('keeps simultaneous typing and rejects an old response ending a newer turn', () => {
    aiTypingStore.setTyping('one', 'u1', 'a1', 'travel');
    aiTypingStore.setTyping('two', 'u2', 'a2', 'travel');
    aiTypingStore.setTyping('one', 'u3', 'a3', 'travel');
    aiTypingStore.clearTyping('one', 'a1');
    expect(Object.keys(get(aiTypingByChatStore))).toEqual(['one', 'two']);
    aiTypingStore.clearTyping('two', 'a2'); expect([...get(runningChatIds)]).toEqual(['one']);
    aiTypingStore.reset(); expect(get(runningChatIds).size).toBe(0);
  });
  // contract-test: supporting surface=gui.web assertions=chat-navigation.activity.global-running
  it('counts parent entries rather than children while the sidebar is closed', () => {
    activityChats.set([{ chat_id: 'trip' }, { chat_id: 'hotels', parent_id: 'trip' }, { chat_id: 'flights', parent_id: 'trip' }] as Chat[]);
    tasks.set('hotels', { taskId: 'h', userMessageId: 'u1' }); tasks.set('flights', { taskId: 'f', userMessageId: 'u2' });
    expect(get(activeChatCount)).toBe(1);
    tasks.clear(); expect(get(activeChatCount)).toBe(0);
  });
});
