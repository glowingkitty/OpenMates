import assert from 'node:assert/strict';
import test from 'node:test';
import { parseMessageSegments, streamingTextDelta } from '../src/messageSegments.js';

// contract-test: supporting surface=cli assertions=brand-naming.activation,brand-naming.flow
test('focus activation followed by a shorter intake keeps the visible question exactly once', () => {
  const activation = '```json\n{"embed_id":"focus-activation","focus_id":"business-find_brand_name"}\n```';
  const question = 'What product are you creating, and who is it for?';
  let previous = '';
  let output = '';
  const embeds = new Set<string>();
  for (const raw of [activation, question.slice(0, 12), activation + '\n\n' + question,
    '\n\n\n' + question + '\n\n' + activation, question, question]) {
    for (const segment of parseMessageSegments(raw)) {
      if (segment.type === 'embed') embeds.add(segment.value);
    }
    const text = parseMessageSegments(raw).filter(segment => segment.type === 'text')
      .map(segment => segment.value).join('').replace(/\n{3,}/g, '\n\n').trim();
    output += streamingTextDelta(previous, text);
    if (text) previous = text;
  }
  assert.equal(output.trim(), question);
  assert.deepEqual([...embeds], ['focus-activation']);
});
