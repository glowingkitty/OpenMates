// contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
import { beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import {
  chatRecommendationItems, clearAllChatRecommendations, emptyChatRecommendationsState,
  getChatRecommendations, parseChatRecommendationsState, setChatRecommendations,
  withRecommendationRemoved,
} from '../chatRecommendationsStore';
import type { ChatRecommendationsState } from '../../types/recommendations';

const memory = {
  id: 'rec-1', kind: 'memory' as const, action: 'create' as const, target_id: null,
  title: 'Conference preferences', summary: 'Prefers open source events.',
};
const workflow = {
  id: 'rec-2', kind: 'workflow' as const, action: 'update' as const, target_id: 'wf-1',
  title: 'Weekly digest', summary: 'Every Monday.',
};
const state: ChatRecommendationsState = {
  schema_version: 1, items: [memory, workflow], dismissed: [], resolved: [], updated_at: 10,
};

describe('chatRecommendationsStore', () => {
  beforeEach(() => clearAllChatRecommendations());

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('round-trips a schema_version 1 state and rejects other shapes', () => {
    expect(parseChatRecommendationsState(JSON.stringify(state))).toEqual(state);
    expect(parseChatRecommendationsState('not json')).toBeNull();
    expect(parseChatRecommendationsState(JSON.stringify({ ...state, schema_version: 2 }))).toBeNull();
    expect(parseChatRecommendationsState(JSON.stringify({ ...state, items: [{ ...memory, kind: 'tip' }] }))).toBeNull();
    expect(parseChatRecommendationsState(JSON.stringify({ ...state, dismissed: [1] }))).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('keeps one state per chat and forgets it on null', () => {
    setChatRecommendations('chat-1', state);
    setChatRecommendations('chat-2', emptyChatRecommendationsState(5));
    expect(get(chatRecommendationItems('chat-1'))).toEqual([memory, workflow]);
    expect(get(chatRecommendationItems('chat-2'))).toEqual([]);
    setChatRecommendations('chat-1', null);
    expect(getChatRecommendations('chat-1')).toBeNull();
    expect(getChatRecommendations('chat-2')?.updated_at).toBe(5);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('removes a dismissed or saved item and records its title once', () => {
    const dismissed = withRecommendationRemoved(state, 'rec-1', 'dismissed', 20);
    expect(dismissed).toEqual({ ...state, items: [workflow], dismissed: ['Conference preferences'], updated_at: 20 });
    const resolved = withRecommendationRemoved(dismissed!, 'rec-2', 'resolved', 30);
    expect(resolved).toMatchObject({ items: [], dismissed: ['Conference preferences'], resolved: ['Weekly digest'] });
    expect(withRecommendationRemoved(state, 'unknown', 'dismissed')).toBeNull();
    const again = withRecommendationRemoved({ ...state, dismissed: ['Conference preferences'] }, 'rec-1', 'dismissed', 40);
    expect(again?.dismissed).toEqual(['Conference preferences']);
  });
});
