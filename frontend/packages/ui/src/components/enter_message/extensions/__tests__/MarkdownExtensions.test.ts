// @vitest-environment jsdom
// frontend/packages/ui/src/components/enter_message/extensions/__tests__/MarkdownExtensions.test.ts
//
// Covers the chat markdown link extension behavior that is not visible from
// parser-only tests. Internal message-prefill links must act on the mounted
// composer via the existing prefill event instead of navigating the page or
// opening a browser tab.

import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  dispatchMessagePrefillFromHref,
  isMarkdownInternalHashLink,
} from '../MarkdownExtensions';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('MarkdownLink', () => {
  it('prefills the current composer for message fallback links without navigating', () => {
    const prefillHandler = vi.fn();
    window.addEventListener('docsMessagePrefill', prefillHandler);

    expect(isMarkdownInternalHashLink('#message=Save%20place')).toBe(true);
    expect(dispatchMessagePrefillFromHref('#message=Save%20place')).toBe(true);

    expect(prefillHandler).toHaveBeenCalledTimes(1);
    expect(prefillHandler.mock.calls[0][0].detail).toEqual({
      text: 'Save place',
      autoSend: false,
    });

    window.removeEventListener('docsMessagePrefill', prefillHandler);
  });
});
