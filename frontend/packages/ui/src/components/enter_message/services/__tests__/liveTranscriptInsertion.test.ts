// Live dictation insertion into the composer editor: caret-targeted streaming,
// correction reconciliation and cancellation cleanup on a real TipTap editor.
import { afterEach, describe, expect, it } from 'vitest';
import { Editor } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import { createLiveTranscriptController } from '../liveTranscriptInsertion';
import { RecordingTranscriptProcessing, recordingTranscriptProcessingKey } from '../../extensions/RecordingTranscriptProcessing';

const editors: Editor[] = [];

function createEditor(text = ''): Editor {
  const editor = new Editor({
    element: document.createElement('div'),
    extensions: [StarterKit, RecordingTranscriptProcessing],
    content: text ? `<p>${text}</p>` : '<p></p>',
  });
  editors.push(editor);
  editor.commands.focus('end');
  return editor;
}

afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

describe('live transcript insertion', () => {
  // contract-test: supporting surface=gui.web assertions=message-input.audio.live-editor-transcript
  it('streams only the new suffix of the cumulative transcript at the caret', () => {
    const editor = createEditor('Existing notes.');
    const live = createLiveTranscriptController(editor);
    expect(live.apply('please')).toBe(true);
    expect(live.apply('please schedule')).toBe(true);
    expect(live.apply('please schedule')).toBe(false);
    expect(live.apply('please schedule the review')).toBe(true);
    expect(editor.getText()).toBe('Existing notes. please schedule the review');
    expect(editor.state.selection.from).toBe(editor.state.doc.content.size - 1);
    expect(live.hasText()).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.audio.live-editor-transcript
  it('continues dictation at a moved caret and keeps the arranged text on correction', () => {
    const editor = createEditor();
    const live = createLiveTranscriptController(editor);
    live.apply('meet on Monday');
    // User moves the caret before "Monday" and keeps speaking.
    const mondayStart = editor.getText().indexOf('Monday') + 1;
    editor.commands.setTextSelection(mondayStart);
    live.apply('meet on Monday next');
    expect(editor.getText()).toBe('meet on next Monday');
    expect(live.ranges()).toHaveLength(2);
    expect(live.applyCorrection('Meet on Monday next.')).toBe('kept');
    expect(editor.getText()).toBe('meet on next Monday');
  });

  // contract-test: supporting surface=gui.web assertions=message-input.audio.live-editor-transcript
  it('replaces one untouched segment with the corrected transcript', () => {
    const editor = createEditor('Notes:');
    const live = createLiveTranscriptController(editor);
    live.apply('um please schedule the the review');
    expect(editor.getText()).toBe('Notes: um please schedule the the review');
    expect(live.applyCorrection('Please schedule the review.')).toBe('replaced');
    expect(editor.getText()).toBe('Notes: Please schedule the review.');
  });

  // contract-test: supporting surface=gui.web assertions=message-input.audio.live-editor-transcript
  it('keeps user edits inside dictated text instead of overwriting them', () => {
    const editor = createEditor();
    const live = createLiveTranscriptController(editor);
    live.apply('call Anna tomorrow');
    editor.commands.setTextSelection({ from: 6, to: 10 });
    editor.commands.insertContent('Bob');
    expect(editor.getText()).toBe('call Bob tomorrow');
    expect(live.applyCorrection('Call Anna tomorrow.')).toBe('kept');
    expect(editor.getText()).toBe('call Bob tomorrow');
  });

  // contract-test: supporting surface=gui.web assertions=message-input.audio.live-editor-transcript
  it('inserts the corrected transcript when no live text arrived', () => {
    const editor = createEditor('Hello');
    const live = createLiveTranscriptController(editor);
    expect(live.applyCorrection('World.')).toBe('inserted');
    expect(editor.getText()).toBe('Hello World.');
  });

  // contract-test: supporting surface=gui.web assertions=message-input.audio.live-editor-transcript
  it('separates dictation inserted mid-sentence from neighbouring words', () => {
    const editor = createEditor('before after');
    editor.commands.setTextSelection(7);
    const live = createLiveTranscriptController(editor);
    live.apply('middle');
    expect(editor.getText()).toBe('before middle after');
    live.discard();
    expect(editor.getText()).toBe('before after');
  });

  // contract-test: supporting surface=gui.web assertions=message-input.audio.live-editor-transcript
  it('discards only untouched dictated text on cancel', () => {
    const editor = createEditor('Keep this.');
    const live = createLiveTranscriptController(editor);
    live.apply('drop this');
    live.discard();
    expect(editor.getText()).toBe('Keep this.');
    expect(live.hasText()).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.audio.live-editor-transcript
  it('marks dictated ranges while correction is processing and clears them afterwards', () => {
    const editor = createEditor('Notes:');
    const live = createLiveTranscriptController(editor);
    live.apply('first point');
    live.setProcessing(true);
    const decorations = recordingTranscriptProcessingKey.getState(editor.state)!.find();
    expect(decorations).toHaveLength(1);
    expect(editor.state.doc.textBetween(decorations[0].from, decorations[0].to)).toBe('first point');
    expect(editor.view.dom.querySelector('.recording-transcript-processing')?.textContent).toBe('first point');
    live.setProcessing(false);
    expect(recordingTranscriptProcessingKey.getState(editor.state)!.find()).toHaveLength(0);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.audio.live-editor-transcript
  it('renders dictated line breaks as hard breaks', () => {
    const editor = createEditor();
    const live = createLiveTranscriptController(editor);
    live.apply('line one\nline two');
    expect(editor.getJSON().content?.[0].content?.map((node) => node.type)).toEqual(['text', 'hardBreak', 'text']);
    expect(live.applyCorrection('Line one.\nLine two.')).toBe('replaced');
    expect(editor.state.doc.textBetween(0, editor.state.doc.content.size, '\n', '\n')).toBe('Line one.\nLine two.');
  });
});
