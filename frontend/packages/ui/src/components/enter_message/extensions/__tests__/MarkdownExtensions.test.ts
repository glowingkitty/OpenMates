// @vitest-environment jsdom
// frontend/packages/ui/src/components/enter_message/extensions/__tests__/MarkdownExtensions.test.ts
//
// Covers the chat markdown link extension behavior that is not visible from
// parser-only tests. Internal message-prefill links must act on the mounted
// composer via the existing prefill event instead of navigating the page or
// opening a browser tab.

import { Editor } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { MarkdownLink } from '../MarkdownExtensions';

let editor: Editor | null = null;

afterEach(() => {
  editor?.destroy();
  editor = null;
  document.body.innerHTML = '';
  history.replaceState(null, '', '/');
});

describe('MarkdownLink', () => {
  it('prefills the current composer for message fallback links without navigating', () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    history.replaceState(null, '', '/#chat-id=current-chat');

    editor = new Editor({
      element: host,
      extensions: [
        StarterKit.configure({ link: false }),
        MarkdownLink,
      ],
      content: '<p><a href="#message=Save%20place">Save place</a></p>',
    });

    const prefillHandler = vi.fn();
    window.addEventListener('docsMessagePrefill', prefillHandler);
    const link = host.querySelector('a');

    expect(link).not.toBeNull();
    expect(link?.getAttribute('target')).toBeNull();
    expect(link?.getAttribute('data-internal')).toBe('true');

    link?.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));

    expect(prefillHandler).toHaveBeenCalledTimes(1);
    expect(prefillHandler.mock.calls[0][0].detail).toEqual({
      text: 'Save place',
      autoSend: false,
    });
    expect(window.location.hash).toBe('#chat-id=current-chat');

    window.removeEventListener('docsMessagePrefill', prefillHandler);
  });
});
