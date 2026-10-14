import { describe, expect, it } from 'vitest';
import { preserveUserBlankLines } from '../userReadSpacing';

describe('user read spacing', () => {
  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it('creates one empty paragraph for each user-authored blank line', () => {
    expect(preserveUserBlankLines('First **bold** line\nsecond line\n\n\nThird line')).toBe(
      'First **bold** line\nsecond line\n\n<!-- EMPTY_PARAGRAPH -->\n\n<!-- EMPTY_PARAGRAPH -->\n\nThird line',
    );
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it('leaves consecutive blank lines inside fenced code untouched', () => {
    expect(preserveUserBlankLines('Before\n\n```text\nfirst\n\n\nsecond\n```\n\nAfter')).toBe(
      'Before\n\n<!-- EMPTY_PARAGRAPH -->\n\n```text\nfirst\n\n\nsecond\n```\n\n<!-- EMPTY_PARAGRAPH -->\n\nAfter',
    );
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it('preserves tilde fences and shorter backtick fences inside a longer code block', () => {
    for (const code of [
      '~~~text\nfirst\n\nsecond\n~~~',
      '````markdown\n```text\nfirst\n\nsecond\n```\n\nlast\n````',
    ]) {
      expect(preserveUserBlankLines(`${code}\n\nAfter`)).toBe(
        `${code}\n\n<!-- EMPTY_PARAGRAPH -->\n\nAfter`,
      );
    }
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it('renders Windows line endings with the same authored blank lines', () => {
    expect(preserveUserBlankLines('First\r\nsecond\r\n\r\nThird')).toBe(
      'First\nsecond\n\n<!-- EMPTY_PARAGRAPH -->\n\nThird',
    );
  });
  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it('treats whitespace-only user lines as authored blank lines', () => {
    expect(preserveUserBlankLines('First\n \n\t\nLast')).toBe(
      'First\n\n<!-- EMPTY_PARAGRAPH -->\n\n<!-- EMPTY_PARAGRAPH -->\n\nLast',
    );
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it('preserves nested list code and its enclosing Markdown structure', () => {
    const code = '- Saved code:\n\n  ```js\n  first\n\n  second\n  ```';
    expect(preserveUserBlankLines(`${code}\n\nAfter`)).toBe(
      `${code}\n\n<!-- EMPTY_PARAGRAPH -->\n\nAfter`,
    );
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it('preserves blank lines in indented code', () => {
    const code = '    first\n\n    second';
    expect(preserveUserBlankLines(`${code}\n\nAfter`)).toBe(
      `${code}\n\n<!-- EMPTY_PARAGRAPH -->\n\nAfter`,
    );
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it.each([
    '1. **First**\n\n1. Second',
    '- **First**\n\n- Second',
    '1. **First**\n\n   Still first.\n\n2. Second',
    '> **First**\n>\n> Second',
  ])('preserves ordinary list and quote containers without code: %s', (container) => {
    expect(preserveUserBlankLines(`${container}\n\nAfter`)).toBe(
      `${container}\n\n<!-- EMPTY_PARAGRAPH -->\n\nAfter`,
    );
  });

});
