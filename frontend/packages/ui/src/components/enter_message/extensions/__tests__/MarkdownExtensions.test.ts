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
  vi.unstubAllGlobals();
});

describe('MarkdownLink', () => {
  it('prefills the current composer for message fallback links without navigating', () => {
    const dispatchEvent = vi.fn();
    vi.stubGlobal('window', { dispatchEvent });

    expect(isMarkdownInternalHashLink('#message=Save%20place')).toBe(true);
    expect(dispatchMessagePrefillFromHref('#message=Save%20place')).toBe(true);

    expect(dispatchEvent).toHaveBeenCalledTimes(1);
    expect(dispatchEvent.mock.calls[0][0]).toBeInstanceOf(CustomEvent);
    expect(dispatchEvent.mock.calls[0][0].type).toBe('docsMessagePrefill');
    expect(dispatchEvent.mock.calls[0][0].detail).toEqual({
      text: 'Save place',
      autoSend: false,
    });
  });
});
