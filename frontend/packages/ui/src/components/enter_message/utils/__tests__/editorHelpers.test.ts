// frontend/packages/ui/src/components/enter_message/utils/__tests__/editorHelpers.test.ts
//
// Unit tests for the message composer empty-content helpers.
// These helpers control send-button visibility, so stale false positives can
// let users send an empty draft after deleting the final local-only file preview.
// The editor is mocked to cover TipTap states that are awkward to reproduce
// without a DOM-backed ProseMirror instance.

import type { Editor } from '@tiptap/core';
import { describe, expect, it } from 'vitest';
import { isContentEmptyExceptMention } from '../editorHelpers';

type MockNode = {
  isText?: boolean;
  text?: string;
  type: { name: string };
};

function createEditorMock(isEmpty: boolean, nodes: MockNode[]): Editor {
  return {
    isEmpty,
    state: {
      doc: {
        descendants(callback: (node: MockNode) => boolean | void) {
          for (const node of nodes) {
            if (callback(node) === false) break;
          }
        },
      },
    },
  } as unknown as Editor;
}

describe('isContentEmptyExceptMention', () => {
  it('treats an empty paragraph as empty even when editor.isEmpty is stale', () => {
    const editor = createEditorMock(false, [
      { type: { name: 'doc' } },
      { type: { name: 'paragraph' } },
    ]);

    expect(isContentEmptyExceptMention(editor)).toBe(true);
  });

  it('treats text as sendable content', () => {
    const editor = createEditorMock(false, [
      { type: { name: 'paragraph' } },
      { isText: true, text: 'hello', type: { name: 'text' } },
    ]);

    expect(isContentEmptyExceptMention(editor)).toBe(false);
  });

  it('treats embeds as sendable content', () => {
    const editor = createEditorMock(false, [
      { type: { name: 'paragraph' } },
      { type: { name: 'embed' } },
    ]);

    expect(isContentEmptyExceptMention(editor)).toBe(false);
  });
});
