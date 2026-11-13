// The composer's sensitive-data preview scans what the user typed, not the
// labels of mention chips, and its offsets stay aligned with editor positions.
import { afterEach, describe, expect, it } from 'vitest';
import { Editor } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import { GenericMentionNode } from '../../extensions/GenericMentionNode';
import { MateNode } from '../../extensions/MateNode';
import { detectPII } from '../piiDetectionService';
import { MENTION_SCAN_PLACEHOLDER, piiScanText } from '../piiScanText';

const editors: Editor[] = [];

function createEditor(): Editor {
  const editor = new Editor({
    element: document.createElement('div'),
    extensions: [StarterKit, GenericMentionNode, MateNode],
    content: '<p></p>',
  });
  editors.push(editor);
  editor.commands.focus('end');
  return editor;
}

function insertProjectMention(editor: Editor, displayName: string) {
  editor.commands.setGenericMention({
    mentionType: 'project',
    displayName,
    mentionSyntax: '@project:example-project-id:read_write',
    projectId: 'example-project-id',
    projectAccessMode: 'read_write',
  });
}

afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

describe('piiScanText', () => {
  // contract-test: direct surface=gui.web assertions=pii.composer.mention-labels-not-scanned
  it('does not scan a Project chip label that contains a phone-like number', () => {
    const editor = createEditor();
    const projectName = 'Garden plan 0151 2345 678';
    insertProjectMention(editor, projectName);
    editor.commands.insertContent(' what should I plant first?');

    // The visible text still carries the label (suggestions and caching use it).
    expect(editor.getText()).toContain(`@${projectName}`);
    // Scanning that visible text is what flagged the chip before.
    expect(detectPII(editor.getText()).some((match) => match.type === 'PHONE')).toBe(true);
    const scanned = piiScanText(editor);
    expect(scanned).toBe(`${MENTION_SCAN_PLACEHOLDER} what should I plant first?`);
    expect(detectPII(scanned)).toEqual([]);
  });

  // contract-test: direct surface=gui.web assertions=pii.composer.mention-labels-not-scanned
  it('keeps offsets of typed sensitive data after a chip aligned with editor positions', () => {
    const editor = createEditor();
    insertProjectMention(editor, 'Garden plan');
    editor.commands.insertContent(' write to anna.schmidt@example.org please');

    const scanned = piiScanText(editor);
    const matches = detectPII(scanned).filter((match) => match.type === 'EMAIL');
    expect(matches).toHaveLength(1);
    const [email] = matches;
    // The preview maps text offset n to editor position n + 1 (inside the paragraph).
    expect(editor.state.doc.textBetween(email.startIndex + 1, email.endIndex + 1)).toBe('anna.schmidt@example.org');
  });

  // contract-test: direct surface=gui.web assertions=pii.composer.mention-labels-not-scanned
  it('does not join digits typed on both sides of a chip into one number', () => {
    const editor = createEditor();
    editor.commands.insertContent('0151');
    insertProjectMention(editor, 'Garden plan');
    editor.commands.insertContent('2345678');

    expect(piiScanText(editor)).toBe(`0151${MENTION_SCAN_PLACEHOLDER}2345678`);
    expect(detectPII(piiScanText(editor)).filter((match) => match.type === 'PHONE')).toEqual([]);
  });

  // contract-test: direct surface=gui.web assertions=pii.composer.mention-labels-not-scanned
  it('replaces mate chips too and leaves plain text unchanged', () => {
    const editor = createEditor();
    editor.commands.insertContent('Hello ');
    editor.commands.insertContent({ type: 'mate', attrs: { name: 'sophia', displayName: 'Sophia 2026' } });
    editor.commands.insertContent(' there');
    expect(piiScanText(editor)).toBe(`Hello ${MENTION_SCAN_PLACEHOLDER} there`);
  });
});
