import { describe, expect, it } from 'vitest';

import { hasAnswerText, shouldShowEmbedErrorBanner } from '../embedErrorBanner';

const skillRef = '```json\n{"type":"app_skill_use","embed_id":"0b8f6a52-1c2d-4e5f-8a9b-0c1d2e3f4a5b"}\n```';
const base = { role: 'assistant', hasEmbedErrors: true, responseActive: false, status: 'synced' };

// contract-test: direct surface=gui.web assertions=chats.rendering.skill-failure-banner
describe('embed error banner visibility', () => {
  // contract-test: direct surface=gui.web assertions=chats.rendering.skill-failure-banner
  it('stays hidden while the assistant turn is still working', () => {
    expect(shouldShowEmbedErrorBanner({ ...base, responseActive: true, status: 'synced', content: skillRef })).toBe(false);
    expect(shouldShowEmbedErrorBanner({ ...base, status: 'streaming', content: skillRef })).toBe(false);
    expect(shouldShowEmbedErrorBanner({ ...base, status: 'processing', content: '' })).toBe(false);
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.skill-failure-banner
  it('stays hidden when one of several skills failed and the finished answer has text', () => {
    const content = `${skillRef}\n\n${skillRef}\n\nIt will be sunny in Berlin and two trains leave on Friday.`;
    expect(shouldShowEmbedErrorBanner({ ...base, content })).toBe(false);
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.skill-failure-banner
  it('shows when the finished turn has no answer text because its skills failed', () => {
    expect(shouldShowEmbedErrorBanner({ ...base, content: `${skillRef}\n\n${skillRef}\n` })).toBe(true);
    expect(shouldShowEmbedErrorBanner({ ...base, content: '' })).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.skill-failure-banner
  it('never shows without a failed embed or on non-assistant messages', () => {
    expect(shouldShowEmbedErrorBanner({ ...base, hasEmbedErrors: false, content: '' })).toBe(false);
    expect(shouldShowEmbedErrorBanner({ ...base, role: 'user', content: '' })).toBe(false);
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.skill-failure-banner
  it('reads answer text from saved assistant documents', () => {
    const embedOnly = { type: 'doc', content: [{ type: 'embedPreviewLarge', attrs: { id: 'e1' } }] };
    const withText = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Sunny.' }] }] };
    expect(hasAnswerText(embedOnly)).toBe(false);
    expect(hasAnswerText(withText)).toBe(true);
    expect(hasAnswerText(null)).toBe(false);
  });
});
