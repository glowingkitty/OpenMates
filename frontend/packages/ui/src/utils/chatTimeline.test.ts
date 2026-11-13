import { expect, it } from 'vitest';
import type { Message } from '../types/chat';
import { timelinePreviewText, bookmarkedTimelineExchanges, buildTimelineExchangeIndex } from './chatTimeline';

const row = (id: string, role: Message['role'], content = '', userId?: string): Message => ({
  message_id: id, chat_id: 'test-chat', created_at: 100, status: 'synced', role, content, user_message_id: userId,
});

// contract-test: supporting surface=gui.web assertions=chat-message-timeline.bookmarks
it('highlights explicit reply associations across human turns and legacy replies without body loading', () => {
  const entries = [row('first', 'user'), row('second', 'user'), row('answer', 'assistant', '', 'first'),
    row('legacy', 'assistant'), row('system', 'system'), row('foreign', 'assistant', '', 'missing')];
  expect([...bookmarkedTimelineExchanges(entries, new Set(['answer', 'system', 'foreign']))]).toEqual(['first']);
  expect([...bookmarkedTimelineExchanges(entries, new Set(['second', 'legacy']))]).toEqual(['second']);
  expect([...bookmarkedTimelineExchanges(entries, new Set(['answer', 'legacy']))]).toEqual(['first', 'second']);
  expect(bookmarkedTimelineExchanges(entries, new Set()).size).toBe(0);
});

// contract-test: supporting surface=gui.web assertions=chat-message-timeline.preview-and-activate,chat-message-timeline.access-and-lifecycle
it('extracts readable authored text without attachment metadata or markup', () => {
  expect(timelinePreviewText(row('user', 'user', '**Budget** and [train tickets](https://example.org/private-token).'))).toContain('Budget');
  expect(timelinePreviewText(row('user', 'user', '**Budget** and [train tickets](https://example.org/private-token).'))).not.toContain('private-token');
  const message = row('attachment', 'user');
  message.content = { type: 'doc', content: [
    { type: 'paragraph', content: [{ type: 'text', text: 'A readable question' }] },
    { type: 'embed', attrs: { embed_id: 'private-embed', url: 'private-url' } },
  ] } as unknown as string;
  expect(timelinePreviewText(message)).toBe('A readable question');
});

// contract-test: supporting surface=gui.web assertions=chat-message-timeline.visibility-and-spacing,chat-message-timeline.bookmarks
it('counts answered questions once and maps legacy question bookmarks to the canonical assistant', () => {
  const entries = [row('q1', 'user'), row('tool', 'system'), row('a1', 'assistant', '', 'q1'),
    row('a2', 'assistant', '', 'q1'), row('q2', 'user')];
  const index = buildTimelineExchangeIndex(entries, new Set(['q1']));
  expect(index.answeredCount).toBe(1);
  expect([...index.assistantBookmarks]).toEqual(['a1']);
  expect(index.legacyAliases.get('a1')).toEqual(['q1']);
  expect(index.entries[0].response_id).toBe('a1');
  expect(buildTimelineExchangeIndex([...entries, row('a3', 'assistant', '', 'q2')], new Set()).answeredCount).toBe(2);
});
