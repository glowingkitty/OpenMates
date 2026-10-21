import { describe, expect, it, vi } from 'vitest';
import { loadExpandedMessageMarkdown } from '../chatMessageExpansion';

describe('full user-message expansion', () => {
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('expands complete optimistic content without depending on a pending or missing disk row', async () => {
    const content = 'Original result context '.repeat(80) + 'Synthetic Practice alpha';
    const loadSaved = vi.fn(async () => null);
    for (const status of ['sending', 'processing', 'synced']) {
      expect(await loadExpandedMessageMarkdown({ message_id: 'user', chat_id: 'chat', content, ...{ status } }, loadSaved)).toBe(content);
    }
    expect(loadSaved).not.toHaveBeenCalled();
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('falls back to disk only when the existing message has no decoded source', async () => {
    const loadSaved = vi.fn(async () => ({ content: 'Full saved text' }));
    expect(await loadExpandedMessageMarkdown({ message_id: 'user', chat_id: 'chat' }, loadSaved)).toBe('Full saved text');
    expect(loadSaved).toHaveBeenCalledWith('user');
    expect(await loadExpandedMessageMarkdown({}, loadSaved)).toBeNull();
  });
});
