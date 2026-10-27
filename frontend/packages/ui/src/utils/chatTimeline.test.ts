import { describe, expect, it } from 'vitest';
import type { Message } from '../types/chat';
import { mergeTimelineEntries, pairTimelineExchange, timelinePreviewText, timelineResponseId, bookmarkedTimelineExchanges, buildTimelineExchangeIndex } from './chatTimeline';

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

// contract-test: supporting surface=gui.web assertions=chat-message-timeline.preview-and-activate,chat-message-timeline.full-history-loading
it('identifies an answer beyond a bounded question window using only the catalogue', () => {
  const entries = [row('question', 'user'), ...Array.from({ length: 30 }, (_, i) => row(`system-${i}`, 'system')),
    row('answer', 'assistant', 'An answer outside the question window', 'question')];
  expect(timelineResponseId(mergeTimelineEntries(entries), 'question')).toBe('answer');
  expect(pairTimelineExchange(entries.slice(0, 20), 'question').assistant).toBeNull();
  expect(pairTimelineExchange(entries, 'question').assistant?.message_id).toBe('answer');
});

// contract-test: supporting surface=gui.web assertions=chat-message-timeline.preview-and-activate
describe('timeline exchange pairing', () => {
  it('uses the explicit turn association across consecutive human messages', () => {
    const first = row('first', 'user', 'First question');
    const second = row('second', 'user', 'Another participant');
    const answer = row('answer', 'assistant', 'Reply to the first question', 'first');
    expect(pairTimelineExchange([first, second, answer], 'first').assistant).toEqual(answer);
    expect(pairTimelineExchange([first, second, answer], 'second').assistant).toBeNull();
  });
  // contract-test: supporting surface=gui.web assertions=chat-message-timeline.preview-and-activate
  it('pairs legacy answers only before the next user and keeps pending distinct from absent', () => {
    const rows = [row('first', 'user'), row('system', 'system'), row('answer', 'assistant'), row('second', 'user')];
    expect(pairTimelineExchange(rows, 'first').assistant?.message_id).toBe('answer');
    expect(pairTimelineExchange(rows, 'second').pending).toBe(false);
    expect(pairTimelineExchange(rows, 'second', 'second').pending).toBe(true);
    expect(() => pairTimelineExchange(rows, 'missing')).toThrow();
  });
});

// contract-test: supporting surface=gui.web assertions=chat-message-timeline.full-history-loading,chat-message-timeline.access-and-lifecycle
it('keeps ten thousand stable identities without copying private bodies into the catalogue', () => {
  const rows = Array.from({ length: 10000 }, (_, i) => ({ ...row(String(i).padStart(5, '0'), 'user', 'Private text'), created_at: i }));
  const catalogue = mergeTimelineEntries(rows.slice(0, 6000), rows.slice(4000));
  expect(catalogue).toHaveLength(10000);
  expect(catalogue[0].message_id).toBe('00000');
  expect(catalogue[catalogue.length - 1]?.message_id).toBe('09999');
  expect(catalogue.every(entry => !('content' in entry))).toBe(true);
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
