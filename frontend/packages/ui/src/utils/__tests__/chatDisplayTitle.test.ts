// Display-only chat title rule (TASK-6864): generated title, else the first
// user message, never "Untitled chat".
import { describe, expect, it } from 'vitest';
import {
  FIRST_MESSAGE_TITLE_MAX_LENGTH,
  firstMessageDisplayTitle,
  mentionedProjectIds,
  readableTitleText,
  resolveChatDisplayTitle,
} from '../chatDisplayTitle';

const PROJECT_ID = '6b0c2f4e-3a91-4d2b-9c57-1f8e2a7d4c10';
const UUID_PATTERN = /[0-9a-f]{8}-[0-9a-f]{4}-/i;

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

describe('readableTitleText', () => {
  const projectName = (projectId: string) => (projectId === PROJECT_ID ? 'Garden planner' : undefined);

  // contract-test: direct surface=gui.web assertions=chats.titles.first-message-fallback
  it('shows a mentioned Project by its name, never its id', () => {
    const title = firstMessageDisplayTitle(
      [{ role: 'user', content: `@project:${PROJECT_ID}:read Add a harvest log to the planner.` }],
      projectName,
    );
    expect(title).toBe('@Garden planner Add a harvest log to the planner.');
    expect(title).not.toMatch(UUID_PATTERN);
  });

  // contract-test: direct surface=gui.web assertions=chats.titles.first-message-fallback
  it('falls back to a generic Project label while the name is unknown', () => {
    expect(readableTitleText(`@project:${PROJECT_ID}:read_write Plan the beds`)).toBe('@Project Plan the beds');
  });

  // contract-test: direct surface=gui.web assertions=chats.titles.first-message-fallback
  it('shows Focus and skill mentions by readable names', () => {
    expect(readableTitleText('@focus:example_app:write_specification Draft the harvest log'))
      .toBe('@Write specification Draft the harvest log');
    expect(readableTitleText('@skill:example_app:get_docs Check this')).toBe('@Get docs Check this');
  });

  // contract-test: direct surface=gui.web assertions=chats.titles.first-message-fallback
  it('uses folder and file names, memory and Wikipedia labels', () => {
    expect(readableTitleText(`@project-file:${PROJECT_ID}:notes%2Fharvest%20log.md:read Summarize`))
      .toBe('@harvest log.md Summarize');
    expect(readableTitleText(`@project-folder:${PROJECT_ID}:src-1:docs%2Fbeds:read List files`))
      .toBe('@beds List files');
    expect(readableTitleText(`@memory-entry:openmates:memories:${PROJECT_ID} Use my notes`)).toBe('@Memory Use my notes');
    expect(readableTitleText('@wikipedia:en:Crop_rotation Explain')).toBe('@Crop rotation Explain');
  });

  // contract-test: direct surface=gui.web assertions=chats.titles.first-message-fallback
  it('strips leftover mention syntax and bare ids', () => {
    expect(readableTitleText(`@mate:unknown_mate_id Hello ${PROJECT_ID} @unknown-kind:abc:def there`)).toBe('Hello there');
  });

  // contract-test: supporting surface=gui.web assertions=chats.titles.first-message-fallback
  it('lists the mentioned Project ids once each', () => {
    expect(mentionedProjectIds(`@project:${PROJECT_ID}:read and @project-file:${PROJECT_ID}:a.md:read`))
      .toEqual([PROJECT_ID]);
    expect(mentionedProjectIds('no mentions')).toEqual([]);
  });

  // contract-test: direct surface=gui.web assertions=chats.titles.first-message-fallback
  it('shows privacy placeholders by their short alias, never with the nonce', () => {
    expect(
      readableTitleText('Hello, my name is [PERSON_NAME_1_56b5ce76693a4a01] [PERSON_NAME_2_56b5ce76693a4a01]'),
    ).toBe('Hello, my name is [PERSON_NAME_1] [PERSON_NAME_2]');
  });
});
