// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { DecryptedEmbed } from '../src/client.js';
import { renderTuiEmbedPreview } from '../src/tuiEmbedPreviews.js';
import { cells, lineText } from '../src/tuiText.js';

const root: DecryptedEmbed = {
  id: 'search', embedId: 'search', type: 'app_skill_use', appId: 'fitness', skillId: 'search_classes',
  textPreview: null, createdAt: null,
  content: {
    status: 'finished', provider: 'Urban Sports Club', query: 'yoga near Sorauer Str. 12',
    summary: 'Found 2 Urban Sports classes in onsite mode. Searched all Urban Sports plans.',
    filters: { address: 'Sorauer Str. 12, Berlin', radius_km: 3, plan: 'all', attendance_mode: 'onsite' },
    result_count: 2,
    results: [
      { name: 'Morning Yoga Flow', venue_name: 'Yoga Studio Kreuzberg', date: '2026-07-10' },
      { name: 'HIIT Strength', venue_name: 'BEAT81 - Paul-Lincke-Ufer', date: '2026-07-10' },
    ],
  },
};
const child: DecryptedEmbed = {
  ...root, id: 'class', embedId: 'class', type: 'fitness-class',
  content: {
    name: 'Morning Yoga Flow', date: '2026-07-10', time_range: '07:30 - 08:30',
    venue_name: 'Yoga Studio Kreuzberg', venue_address: 'Oranienstr. 1, 10997 Berlin',
    distance_km: 0.9, spots_display: '5 spots left', plans_required: ['Classic', 'Premium', 'Max'],
    image_url: 'https://example.test/class.jpg',
  },
};
const rendered = (embed: DecryptedEmbed, alias = 'fit-s_c-1', width = 62) =>
  renderTuiEmbedPreview(embed, width, alias).map(lineText);

function inOrder(text: string, values: string[]) {
  let previous = -1;
  for (const value of values) {
    const index = text.indexOf(value, previous + 1);
    assert.ok(index > previous, `${value} must follow ${values[Math.max(0, values.indexOf(value) - 1)]}`);
    previous = index;
  }
}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test('Fitness search details follow the rendered web preview and footer stays at the bottom', () => {
  const lines = rendered(root);
  const text = lines.join('\n');
  inOrder(text, ['Urban Sports Club', 'Search classes', 'Sorauer Str. 12, Berlin', '2 classes',
    'Found 2 Urban Sports classes', 'Morning Yoga Flow', 'Yoga Studio Kreuzberg',
    'HIIT Strength', 'BEAT81 - Paul-Lincke-Ufer', '3 km · Plan: all · onsite',
    'Fitness · Search classes', '/embed fit-s_c-1']);
  assert.match(lines.at(-4) ?? '', /^├/);
  assert.match(lines.at(-1) ?? '', /^╰/);
  assert.ok(renderTuiEmbedPreview(root, 62, 'fit-s_c-1').slice(1, -4).every(line =>
    typeof line === 'string' || !line.spans?.some(span => span.background)));
  assert.ok(renderTuiEmbedPreview(root, 62, 'fit-s_c-1').slice(-3, -1).every(line =>
    typeof line !== 'string' && line.spans?.every(span => span.background)));
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test('Fitness statuses and empty results use the web wording without stale counts or result snippets', () => {
  for (const [status, expected] of [
    ['processing', 'Searching Urban Sports Club...'], ['error', 'Search failed.'],
    ['cancelled', 'Search cancelled.'],
  ]) {
    const text = rendered({ ...root, content: { ...root.content, status } }).join('\n');
    assert.ok(text.includes(expected), status);
    assert.ok(!text.includes('2 classes') && !text.includes('Morning Yoga Flow'), status);
  }
  const empty = rendered({ ...root, content: { status: 'finished', results: [], filters: { city: 'Berlin' } } }).join('\n');
  assert.match(empty, /Berlin[\s\S]*0 classes/);
  assert.ok(!empty.includes('No classes found'));
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test('Fitness location search uses location count and address', () => {
  const location = { ...root, skillId: 'search_locations', content: {
    status: 'finished', provider: 'Urban Sports Club', filters: { city: 'Berlin', radius_km: 2 },
    result_count: 1, results: [{ name: 'BEAT81 - Paul-Lincke-Ufer' }],
  } } satisfies DecryptedEmbed;
  const text = rendered(location, 'fit-s_l-1').join('\n');
  inOrder(text, ['Search locations', 'Berlin', '1 locations', 'BEAT81 - Paul-Lincke-Ufer', '2 km',
    'Fitness · Search locations', '/embed fit-s_l-1']);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test('Fitness child uses schedule and metadata above the title in its bottom bar', () => {
  const lines = rendered(child, 'fit-s_c-1-1');
  const text = lines.join('\n');
  inOrder(text, ['2026-07-10 · 07:30 - 08:30 · Yoga Studio Kreuzberg',
    '0.90 km · 5 spots left · Classic, Premium, Max', 'Fitness · Morning Yoga Flow', '/embed fit-s_c-1-1']);
  assert.equal(text.match(/Morning Yoga Flow/g)?.length, 1);
  assert.ok(!text.includes('image_url') && !text.includes('https://example.test'));
  const location = { ...child, skillId: 'search_locations', content: {
    name: 'Yoga Studio Kreuzberg', address: 'Oranienstr. 1, 10997 Berlin',
    disciplines: 'Yoga|Pilates', distance_km: 0.9,
  } } satisfies DecryptedEmbed;
  inOrder(rendered(location).join('\n'), ['Oranienstr. 1, 10997 Berlin', '0.90 km · Yoga, Pilates',
    'Fitness · Yoga Studio Kreuzberg']);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test('offline child and generic fallback keep only known values in the same bottom bar', () => {
  const unavailable = rendered({ ...child, content: { ...child.content, _tuiUnavailable: true } }).join('\n');
  assert.match(unavailable, /Class details unavailable/);
  assert.ok(!unavailable.includes('0.90 km') && !unavailable.includes('Morning Yoga Flow'));
  const generic: DecryptedEmbed = { ...root, appId: 'maps', skillId: 'search', type: 'app_skill_use',
    textPreview: null, content: { query: 'Yoga near me' } };
  const genericText = rendered(generic, 'map-s-1').join('\n');
  inOrder(genericText, ['Yoga near me', 'Maps · Search', '/embed map-s-1']);
  assert.ok(!genericText.includes('Processing') && !genericText.includes('0 results'));
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test('card geometry and terminal sanitization hold across narrow widths', () => {
  const embed = { ...root, content: { ...root.content, summary: '🧪 漢字 \x1b[31mred\x1b[0m' } };
  for (const width of [1, 5, 20, 32, 62, 80]) {
    const lines = rendered(embed, 'fit-s_c-1', width);
    assert.ok(lines.every(line => cells(line) <= Math.min(width, 62)), width.toString());
    assert.ok(lines.every(line => !line.includes('\x1b')), width.toString());
  }
});
