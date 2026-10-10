// contract-test-file: infrastructure
import assert from 'node:assert/strict';
import {test} from 'node:test';
import terminalFrame from '../../../apps/web_app/tests/helpers/terminal-frame.ts';

const {terminalRowsAtCheckpoint} = terminalFrame;

const enter = '\x1b[?1049h\x1b[2J\x1b[H';
const paint = (body: string) => `\x1b[?2026h\x1b[?25l${body}\x1b[?2026l`;
const row = (number: number, content: string) => `\x1b[${number};1H\x1b[2K${content}`;

test('unchanged rows survive incremental paints and blank row positions remain indexed', () => {
  const transcript = enter + paint(row(1, 'header') + row(2, '') + row(3, 'footer'))
    + paint(row(3, 'updated footer'));
  assert.deepEqual(terminalRowsAtCheckpoint(transcript), ['header', '', 'updated footer']);
});

test('style-only updates replace styled rows without borrowing cursor controls', () => {
  const transcript = enter + paint(row(1, 'header') + row(2, '\x1b[31mvalue\x1b[0m'))
    + paint(row(2, '\x1b[32mvalue\x1b[0m') + '\x1b[4;8H\x1b[?25h');
  assert.deepEqual(terminalRowsAtCheckpoint(transcript), ['header', 'value']);
});

test('erase-to-end removes old lower rows and later writes preserve blank gaps', () => {
  const transcript = enter + paint(row(1, 'one') + row(2, 'two') + row(3, 'three'))
    + paint('\x1b[2;1H\x1b[J')
    + paint(row(3, 'new third'));
  assert.deepEqual(terminalRowsAtCheckpoint(transcript), ['one', '', 'new third']);
});

test('alternate-screen reentry and screen reset discard earlier frames', () => {
  const old = enter + paint(row(1, 'old') + row(2, 'stale'));
  assert.deepEqual(terminalRowsAtCheckpoint(old + '\x1b[?1049l' + enter + paint(row(1, 'new'))), ['new']);
  assert.deepEqual(terminalRowsAtCheckpoint(old + '\x1b[2J\x1b[H' + paint(row(1, 'reset'))), ['reset']);
});

test('a resized full repaint keeps Unicode wide cells intact and clears its shorter tail', () => {
  const transcript = enter + paint(row(1, '🧭 東京') + row(2, 'middle') + row(3, 'old bottom'))
    + paint(row(1, '🧭 東京') + row(2, 'new middle') + '\x1b[3;1H\x1b[J');
  assert.deepEqual(terminalRowsAtCheckpoint(transcript), ['🧭 東京', 'new middle']);
});

test('a full repaint screen clear bounds a shorter screen without losing its final row', () => {
  const transcript = enter + paint(row(1, 'old first') + row(2, 'old second') + row(3, 'old third'))
    + paint('\x1b[2J' + row(1, 'new first') + row(2, 'new final'));
  assert.deepEqual(terminalRowsAtCheckpoint(transcript), ['new first', 'new final']);
});

test('incomplete paints cannot replace the last completed screen', () => {
  const transcript = enter + paint(row(1, 'complete')) + '\x1b[?2026h' + row(1, 'partial');
  assert.deepEqual(terminalRowsAtCheckpoint(transcript), ['complete']);
  assert.throws(() => terminalRowsAtCheckpoint(enter + '\x1b[?2026h' + row(1, 'partial')), /No complete terminal frame/);
});
