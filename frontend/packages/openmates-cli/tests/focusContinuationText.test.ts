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

// contract-test: supporting surface=cli assertions=brand-naming.flow
test('final source-link cleanup does not duplicate a finalist comparison', () => {
  const streamed = 'A preliminary [ExampleTrademarks search](https://example.com/fixture) returned similar marks.\nA [ExampleTrademarks trademark query](https://example.com/fixture) was truncated.';
  const finalized = 'A preliminary ExampleTrademarks search returned similar marks.\nA ExampleTrademarks trademark query was truncated.';
  assert.equal(streamingTextDelta(streamed, finalized), '');
  assert.equal(streamingTextDelta(finalized, streamed), '');
});

// contract-test: supporting surface=cli assertions=brand-naming.flow
test('source-link revisions preserve a genuinely appended Markdown suffix once', () => {
  const previous = 'See [the register](https://example.org/old).';
  const current = 'See the register.\nThen [check the source](https://example.org/new).';
  assert.equal(streamingTextDelta(previous, current), '\nThen [check the source](https://example.org/new).');
  assert.equal(streamingTextDelta('See the register.', previous + ' More evidence.'), ' More evidence.');
});

// contract-test: supporting surface=cli assertions=brand-naming.activation,brand-naming.flow
test('changed and shorter phases still print while non-link edits stay visible', () => {
  assert.equal(streamingTextDelta('I will activate the brand naming focus now.', 'What does your product do?'), 'What does your product do?');
  assert.equal(streamingTextDelta('Domain is available.', 'Domain is unavailable.'), 'Domain is unavailable.');
  assert.equal(streamingTextDelta('An unfinished [source](', 'An unfinished source'), 'An unfinished source');
});
