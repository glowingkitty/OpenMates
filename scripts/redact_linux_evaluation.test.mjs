/** Engineering tooling tests; no SDK import, network requests or inference. */
// contract-test-file: tooling
import test from 'node:test';
import assert from 'node:assert/strict';
import { validatedSpans, score, evidenceJSON, loadSynthetic, boundaryFixtures, percentile } from './redact_linux_evaluation.mjs';

const text = '👋 Amina Okafor';
const fixture = { id: 'unicode', text, expected: [['private_person', 'Amina Okafor']] };
const span = (original, start, end) => ({ label: 'GIVEN_NAME', original, start, end });

test('converts UTF-16 emoji offsets to Unicode code points without shifting', () => {
  const [actual] = validatedSpans(text, [span('Amina', 3, 8)]);
  assert.deepEqual([actual.start_utf16, actual.end_utf16, actual.start, actual.end], [3, 8, 2, 7]);
  assert.throws(() => validatedSpans(text, [span('Amina', 2, 7)]), /integrity/);
  assert.throws(() => validatedSpans(text, [span(text.slice(0, 1), 0, 1)]), /integrity/);
  assert.throws(() => validatedSpans(text, [span('Amina', 3.5, 8)]), /integrity/);
});

test('strict coverage includes intervening spaces and credential punctuation', () => {
  const split = validatedSpans(text, [span('Amina', 3, 8), span('Okafor', 9, 15)]);
  const partial = score([fixture], [{ id: fixture.id, spans: split }]);
  assert.equal(partial.fully_hidden, 0);
  assert.equal(partial.letters_digits_hidden, 1);
  assert.equal(partial.values[0].partial, true);
  const complete = score([fixture], [{ id: fixture.id, spans: validatedSpans(text, [span('Amina Okafor', 3, 15)]) }]);
  assert.equal(complete.fully_hidden, 1);
  const secret = { id: 'secret', text: 'my-key', expected: [['secret', 'my-key']] };
  assert.equal(score([secret], [{ id: 'secret', spans: [{ start: 0, end: 2 }, { start: 3, end: 6 }] }]).fully_hidden, 0);
});

test('counts false positives on negative cases and does not require label equivalence', () => {
  const negative = { id: 'code', text: '3.14.159', expected: [] };
  const result = score([negative], [{ id: 'code', spans: [{ start: 0, end: 8, label: 'IP_ADDRESS' }] }]);
  assert.equal(result.negative_cases, 1);
  assert.equal(result.false_positive_cases.length, 1);
  assert.equal(result.expected_values, 0);
});

test('splits persisted synthetic originals while preserving byte-for-byte recovery', () => {
  const source = { text: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ\n👋', nested: { original: 'abcdefghijklmnopqrst', value: '' },
    expected: [['secret', 'abcdefghijklmnopqrst']], custom: ['abcdefghijklmnopqrst'] };
  const encoded = evidenceJSON(source);
  assert.ok(!encoded.includes(source.text));
  assert.ok(!encoded.includes(source.custom[0]));
  const decoded = JSON.parse(encoded, (_key, value) => value && Object.keys(value).length === 1 && Array.isArray(value.synthetic_parts) ? value.synthetic_parts.join('') : value);
  assert.deepEqual(decoded, source);
});

test('existing fixtures stay assembled locally; long-tail fixtures keep annotated text', () => {
  const fixtures = loadSynthetic(new URL('./fixtures/privacy-filter-synthetic.json', import.meta.url));
  assert.equal(fixtures.length, 56);
  assert.equal(fixtures.reduce((sum, item) => sum + item.expected.length, 0), 50);
  for (const fixture of [...fixtures, ...boundaryFixtures()]) {
    for (const [, expected] of fixture.expected) assert.ok(fixture.text.includes(expected), fixture.id);
  }
  assert.ok(boundaryFixtures().at(-1).text.length > 65000);
});

test('nearest rank p95 reports tail sample instead of claiming interpolated precision', () => {
  assert.equal(percentile([7, 1, 4, 2, 3, 6, 5], 0.5), 4);
  assert.equal(percentile([7, 1, 4, 2, 3, 6, 5], 0.95), 7);
});
