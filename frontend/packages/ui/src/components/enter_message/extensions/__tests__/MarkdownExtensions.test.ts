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
  Reflect.deleteProperty(window, 'dispatchEvent');
});

describe('MarkdownLink', () => {
  it('prefills the current composer for message fallback links without navigating', () => {
    const dispatchEvent = vi.fn((_event: Event) => true);
    Object.defineProperty(window, 'dispatchEvent', {
      configurable: true,
      value: dispatchEvent,
    });

    expect(isMarkdownInternalHashLink('#message=Save%20place')).toBe(true);
    expect(dispatchMessagePrefillFromHref('#message=Save%20place')).toBe(true);

    const event = dispatchEvent.mock.calls[0][0] as CustomEvent;
    expect(dispatchEvent).toHaveBeenCalledTimes(1);
    expect(event).toBeInstanceOf(CustomEvent);
    expect(event.type).toBe('docsMessagePrefill');
    expect(event.detail).toEqual({
      text: 'Save place',
      autoSend: false,
    });
  });
});
