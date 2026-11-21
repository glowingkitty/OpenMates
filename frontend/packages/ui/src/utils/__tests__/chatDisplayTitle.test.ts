// Display-only chat title rule (TASK-6864): generated title, else the first
// user message, never "Untitled chat".
import { describe, expect, it } from 'vitest';
import { FIRST_MESSAGE_TITLE_MAX_LENGTH, firstMessageDisplayTitle, resolveChatDisplayTitle } from '../chatDisplayTitle';

describe('firstMessageDisplayTitle', () => {
  // contract-test: direct surface=gui.web assertions=chats.titles.first-message-fallback
  it('uses the first user message, not a later one or an assistant reply', () => {
    expect(firstMessageDisplayTitle([
      { role: 'system', content: 'Notice' },
      { role: 'user', content: 'Plan a weekend in Lisbon' },
      { role: 'assistant', content: 'Sure!' },
      { role: 'user', content: 'Add a museum' },
    ])).toBe('Plan a weekend in Lisbon');
  });

  // contract-test: direct surface=gui.web assertions=chats.titles.first-message-fallback
  it('collapses whitespace, labels embeds and caps the length', () => {
    expect(firstMessageDisplayTitle([{ role: 'user', content: 'Look  at\nthis ```json\n{"type":"image","embed_id":"e1"}\n```' }]))
      .toBe('Look at this [Image]');
    const long = firstMessageDisplayTitle([{ role: 'user', content: 'word '.repeat(60) }]);
    expect(long.length).toBeLessThanOrEqual(FIRST_MESSAGE_TITLE_MAX_LENGTH);
    expect(long.startsWith('word word')).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=chats.titles.first-message-fallback
  it('is empty without a readable user message', () => {
    expect(firstMessageDisplayTitle([])).toBe('');
    expect(firstMessageDisplayTitle(null)).toBe('');
    expect(firstMessageDisplayTitle([{ role: 'assistant', content: 'Hello' }])).toBe('');
    expect(firstMessageDisplayTitle([{ role: 'user', content: undefined }])).toBe('');
  });
});

describe('resolveChatDisplayTitle', () => {
  // contract-test: direct surface=gui.web assertions=chats.titles.first-message-fallback
  it('prefers the generated title once it arrives', () => {
    expect(resolveChatDisplayTitle('Lisbon weekend', 'Plan a weekend in Lisbon')).toBe('Lisbon weekend');
  });

  // contract-test: direct surface=gui.web assertions=chats.titles.first-message-fallback
  it('falls back to the first message while the title is pending', () => {
    expect(resolveChatDisplayTitle('', 'Plan a weekend in Lisbon')).toBe('Plan a weekend in Lisbon');
    expect(resolveChatDisplayTitle(null, 'Plan a weekend in Lisbon')).toBe('Plan a weekend in Lisbon');
    expect(resolveChatDisplayTitle('   ', 'Plan a weekend in Lisbon')).toBe('Plan a weekend in Lisbon');
  });

  // contract-test: direct surface=gui.web assertions=chats.titles.first-message-fallback
  it('returns null for an empty chat so callers can hide it instead of saying Untitled chat', () => {
    expect(resolveChatDisplayTitle(undefined, '')).toBeNull();
  });
});
