import { describe, expect, it } from 'vitest';
import { Schema } from '@tiptap/pm/model';
import { appendedTextRanges } from '../streamingTextFade';

const schema = new Schema({
  nodes: {
    doc: { content: 'block+' },
    paragraph: { content: 'inline*', group: 'block' },
    text: { group: 'inline' },
  },
  marks: { strong: {} },
});

const paragraph = (...text: string[]) => schema.nodes.paragraph.create(null, text.map(value => schema.text(value)));
const doc = (...blocks: ReturnType<typeof paragraph>[]) => schema.nodes.doc.create(null, blocks);

describe('streaming text fade boundaries', () => {
  // contract-test: direct surface=gui.web assertions=chats.streaming.web-chunk-fade
  it('targets only appended characters in the last paragraph', () => {
    const oldDoc = doc(paragraph('Earlier text.'));
    const nextDoc = doc(paragraph('Earlier text. New chunk.'));
    const ranges = appendedTextRanges(oldDoc, nextDoc);
    expect(ranges).toHaveLength(1);
    expect(nextDoc.textBetween(ranges[0].from, ranges[0].to)).toBe(' New chunk.');
  });

  // contract-test: direct surface=gui.web assertions=chats.streaming.web-chunk-fade
  it('targets a new paragraph without including the old one', () => {
    const oldDoc = doc(paragraph('Stable.'));
    const nextDoc = doc(paragraph('Stable.'), paragraph('Fresh line.'));
    const ranges = appendedTextRanges(oldDoc, nextDoc);
    expect(ranges.map(range => nextDoc.textBetween(range.from, range.to))).toEqual(['Fresh line.']);
  });

  // contract-test: direct surface=gui.web assertions=chats.streaming.web-chunk-fade
  it('does not fade corrected existing text or markdown marks', () => {
    const oldDoc = doc(paragraph('Prior typo'));
    const correction = doc(paragraph('Prior type'));
    expect(appendedTextRanges(oldDoc, correction)).toEqual([]);
    const marked = doc(schema.nodes.paragraph.create(null, schema.text('Prior typo', [schema.marks.strong.create()])));
    expect(appendedTextRanges(oldDoc, marked)).toEqual([]);
  });
});
