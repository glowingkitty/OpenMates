import assert from 'node:assert/strict';
import test from 'node:test';
import { parseMessageSegments, streamingContentStart } from '../src/messageSegments.js';

// contract-test: supporting surface=cli assertions=brand-naming.activation,brand-naming.flow
test('focus activation followed by a shorter intake keeps the visible question exactly once', () => {
  const activation = '```json\n{"embed_id":"focus-activation","focus_id":"business-find_brand_name"}\n```';
  const question = 'What product are you creating, and who is it for?';
  let previous = '';
  let output = '';
  const embeds = new Set<string>();
  for (const raw of [activation, question.slice(0, 12), question, question]) {
    const start = streamingContentStart(previous, raw);
    let offset = 0;
    for (const segment of parseMessageSegments(raw)) {
      if (segment.type === 'embed') embeds.add(segment.value);
      else output += segment.value.slice(Math.max(0, start - offset));
      offset += segment.rawLength;
    }
    previous = raw;
  }
  assert.equal(output, question);
  assert.deepEqual([...embeds], ['focus-activation']);
});
