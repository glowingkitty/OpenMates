// contract-test-file: infrastructure
import { describe, expect, it } from 'vitest';
import { headerBubbleFocusChildEmbedId, headerPreviewBubbleKey } from '../headerImageBubbleKey';

describe('header image bubble keys', () => {
  it('never hands a preview-row bubble key to fullscreen as a child embed id', () => {
    // Opening such a key used to request a non-existent embed ("Embed not found").
    expect(headerBubbleFocusChildEmbedId(headerPreviewBubbleKey('parent-embed', 2))).toBeNull();
  });

  it('keeps a stored child embed id as the fullscreen focus', () => {
    expect(headerBubbleFocusChildEmbedId('child-embed')).toBe('child-embed');
    expect(headerBubbleFocusChildEmbedId('')).toBeNull();
  });
});
