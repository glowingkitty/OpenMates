// A Project chip restored with the generic "Project" label (the Project's name
// was not loaded yet) is relabelled with the Project's name once it is known;
// the serialized mention syntax never changes and no id is ever shown.
import { afterEach, describe, expect, it } from 'vitest';
import { Editor } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import { GenericMentionNode } from '../GenericMentionNode';
import {
  registerMentionProjectNameLookup,
  registerMentionProjectNameResolver,
} from '../../../../utils/mentionProjectNames';

const PROJECT_ID = 'be6bc80f-1b59-43e7-b800-c4575b021ade';
const SYNTAX = `@project:${PROJECT_ID}:read`;
const editors: Editor[] = [];

function chipAttrs(editor: Editor): Record<string, unknown> {
  let attrs: Record<string, unknown> = {};
  editor.state.doc.descendants((node) => {
    if (node.type.name === 'genericMention') attrs = node.attrs;
  });
  return attrs;
}

afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
  registerMentionProjectNameLookup(null);
  registerMentionProjectNameResolver(null);
});

describe('Project chip names', () => {
  // contract-test: direct surface=gui.web assertions=message-input.drafts.preview-persistence
  it('relabels a generic Project chip with the Project name once it is fetched', async () => {
    const names = new Map<string, string>();
    registerMentionProjectNameLookup((id) => names.get(id));
    let resolved: () => void = () => undefined;
    const fetched = new Promise<void>((resolve) => (resolved = resolve));
    registerMentionProjectNameResolver(async (ids) => {
      expect(ids).toEqual([PROJECT_ID]);
      names.set(PROJECT_ID, 'Garden planner');
      resolved();
    });

    const editor = new Editor({
      element: document.createElement('div'),
      extensions: [StarterKit, GenericMentionNode],
      content: {
        type: 'doc',
        content: [{
          type: 'paragraph',
          content: [
            { type: 'genericMention', attrs: { mentionType: 'project', displayName: 'Project', mentionSyntax: SYNTAX, projectId: PROJECT_ID, projectAccessMode: 'read' } },
            { type: 'text', text: ' Plan the beds' },
          ],
        }],
      },
    });
    editors.push(editor);

    await fetched;
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(chipAttrs(editor)).toMatchObject({ displayName: 'Garden planner', mentionSyntax: SYNTAX });
    expect(editor.getText()).toContain('@Garden planner');
    expect(editor.getText()).not.toContain(PROJECT_ID);
  });

  // contract-test: direct surface=gui.web assertions=message-input.drafts.preview-persistence
  it('keeps the generic label when the Project cannot be read, and asks only once', async () => {
    let calls = 0;
    registerMentionProjectNameResolver(async () => {
      calls += 1;
    });
    const editor = new Editor({
      element: document.createElement('div'),
      extensions: [StarterKit, GenericMentionNode],
      content: '<p></p>',
    });
    editors.push(editor);
    editor.commands.setGenericMention({ mentionType: 'project', displayName: 'Project', mentionSyntax: SYNTAX, projectId: PROJECT_ID, projectAccessMode: 'read' });
    editor.commands.insertContent(' more text');
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(chipAttrs(editor).displayName).toBe('Project');
    expect(calls).toBe(1);
  });
});
