import { describe, expect, it } from 'vitest';
import type { Chat } from '../../types/chat';
import { aggregateRunningChats, processingAncestorIds } from '../chatActivity';
const chat = (id: string, parent?: string, extra: Partial<Chat> = {}) => ({ chat_id: id, parent_id: parent, ...extra }) as Chat;

describe('running chat groups', () => {
  // contract-test: supporting surface=gui.web assertions=chat-navigation.activity.global-running
  it('groups two running children beneath one idle parent', () => {
    const groups = aggregateRunningChats([chat('trip'), chat('hotels', 'trip'), chat('flights', 'trip')], new Set(['hotels', 'flights']));
    expect(groups.map(group => [group.chat.chat_id, group.activeSubChatCount])).toEqual([['trip', 2]]);
  });
  // contract-test: supporting surface=gui.web assertions=chat-navigation.activity.global-running
  it('counts a running parent once and includes deeper active descendants', () => {
    const groups = aggregateRunningChats([chat('trip'), chat('hotels', 'trip'), chat('reviews', 'hotels')], new Set(['trip', 'reviews']));
    expect(groups).toHaveLength(1);
    expect(groups[0].activeSubChatCount).toBe(1);
  });
  // contract-test: supporting surface=gui.web assertions=chat-navigation.activity.global-running
  it('keeps independent running chats and removes completed groups immediately', () => {
    const chats = [chat('trip'), chat('launch')];
    expect(aggregateRunningChats(chats, new Set(['trip', 'launch']))).toHaveLength(2);
    expect(aggregateRunningChats(chats, new Set(['launch']))[0].chat.chat_id).toBe('launch');
    expect(aggregateRunningChats(chats, new Set())).toEqual([]);
  });
  // contract-test: supporting surface=gui.web assertions=chat-navigation.activity.global-running
  it('does not expose locked or hidden parent groups', () => {
    expect(aggregateRunningChats([chat('private', undefined, { is_hidden_candidate: true }), chat('child', 'private')], new Set(['child']))).toEqual([]);
    const chats = [chat('parent'), chat('private-child', 'parent', { is_hidden_candidate: true })];
    expect(aggregateRunningChats(chats, new Set(['private-child']))).toEqual([]);
    expect(processingAncestorIds(chats, new Set(['private-child'])).size).toBe(0);
  });
  // contract-test: supporting surface=gui.web assertions=chat-navigation.activity.global-running
  it('handles incomplete ancestry without losing an available running child', () => {
    expect(aggregateRunningChats([chat('child', 'missing')], new Set(['child']))[0].chat.chat_id).toBe('child');
  });
  // contract-test: supporting surface=gui.web assertions=chat-navigation.activity.global-running
  it('marks every ancestor for folders containing an intermediate parent', () => {
    const chats = [chat('launch'), chat('research', 'launch'), chat('analysis', 'research')];
    expect([...processingAncestorIds(chats, new Set(['analysis']))]).toEqual(['analysis', 'research', 'launch']);
    expect(processingAncestorIds([chat('launch', undefined, { is_hidden_candidate: true }), ...chats.slice(1)], new Set(['analysis'])).size).toBe(0);
  });
});
