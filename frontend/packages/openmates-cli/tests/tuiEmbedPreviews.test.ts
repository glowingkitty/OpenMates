// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { DecryptedEmbed } from '../src/client.js';
import { APP_GRADIENTS, PRIMARY_GRADIENT } from '../../appGradientTheme.js';
import { renderTuiEmbedPreview } from '../src/tuiEmbedPreviews.js';
import { renderWorkspaceFrame } from '../src/tuiLayout.js';
import { createInitialTuiState } from '../src/tuiRenderer.js';
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

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test('each app uses its own solid web color in the bottom bar with readable foreground', () => {
  const luminance = (hex: string) => {
    const [r, g, b] = [1, 3, 5].map(index => {
      const value = parseInt(hex.slice(index, index + 2), 16) / 255;
      return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  for (const [appId, gradient] of Object.entries({ ...APP_GRADIENTS, unknown: PRIMARY_GRADIENT })) {
    const lines = renderTuiEmbedPreview({ ...root, appId, skillId: 'view', content: { title: 'Known title' } }, 62, 'app-v-1');
    for (const line of lines.slice(-3, -1)) {
      assert.ok(typeof line !== 'string' && line.spans);
      assert.ok(line.spans.every(span => span.background === gradient.start), appId);
      const content = line.spans[1];
      const a = luminance(content.color!), b = luminance(content.background!);
      assert.ok((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) >= 4.5, appId);
    }
  }
  assert.notEqual(APP_GRADIENTS.audio.start, APP_GRADIENTS.weather.start);
});

const recording: DecryptedEmbed = { ...root, type: 'audio-recording', appId: 'audio', skillId: 'transcribe',
  content: { type: 'audio-recording', title: 'Weather in Berlin', status: 'finished' } };

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test('frame painting preserves contrasting app bar text and plain terminal geometry', () => {
  const state = createInitialTuiState();
  state.screen = 'chat';
  const weather: DecryptedEmbed = { ...root, appId: 'weather', skillId: 'forecast', content: { title: 'Berlin forecast' } };
  const body = [...renderTuiEmbedPreview(recording, 62, 'aud-t-1'), ...renderTuiEmbedPreview(weather, 62, 'wea-f-1')];
  const frame = renderWorkspaceFrame(state, 100, 30, body, { colorMode: 'truecolor' });
  assert.ok(frame.includes('\x1b[38;2;0;0;0m\x1b[48;2;0;199;160m'));
  assert.ok(frame.includes('\x1b[38;2;255;255;255m\x1b[48;2;0;91;165m'));
  const plain = renderWorkspaceFrame(state, 100, 30, body, { colorMode: 'none' });
  assert.ok(!plain.includes('\x1b'));
  assert.ok(plain.split('\n').every(line => cells(line) === 100));
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,cli.output.actionable-readable
test('recording preview shows the shortened active transcript above the app and skill bar', () => {
  const transcript = 'Please tell me the weather in Berlin. '.repeat(8) + 'PRIVATE TAIL';
  const lines = rendered({ ...recording, content: { ...recording.content, transcript } }, 'aud-t-1');
  const text = lines.join('\n');
  inOrder(text, ['Weather in Berlin', 'Please tell me the weather in Berlin.', '…', 'Audio · Transcribe', '/embed aud-t-1']);
  assert.ok(!text.includes('PRIVATE TAIL'));
  const snippet = lines.slice(2, -4).map(line => line.slice(2, -2).trimEnd()).join('');
  assert.equal(snippet, transcript.slice(0, 119) + '…');
  assert.ok(lines.every(line => cells(line) === 62));
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test('recording transcript selection follows the web original/corrected preference and flat fallbacks', () => {
  for (const [fields, expected] of [
    [{ transcript: 'fallback', transcript_original: 'original', transcript_corrected: 'corrected' }, 'corrected'],
    [{ transcript: 'fallback', transcript_original: 'original', transcript_corrected: 'corrected', use_corrected: false }, 'original'],
    [{ transcript: 'fallback', transcript_corrected: 'corrected' }, 'fallback'],
    [{ transcript_corrected: 'corrected' }, 'corrected'],
    [{ transcript_original: 'original' }, 'original'],
    [{ text: 'skill transcript' }, 'skill transcript'],
    [{ transcript: { text: 'invented nested content' } }, 'No transcript available.'],
  ] as const) {
    const text = rendered({ ...recording, content: { ...recording.content, ...fields } }).join('\n');
    assert.ok(text.includes(expected));
  }
  const legacy = { ...recording, type: 'recording', appId: null, skillId: null,
    content: { transcript: 'Legacy recording transcript' } };
  assert.match(rendered(legacy, 'aud-t-1').join('\n'), /Legacy recording transcript[\s\S]*Audio · Transcribe/);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test('recording states never present failed transcription as a completed transcript', () => {
  for (const [status, expected] of [['error', 'Recording failed.'], ['cancelled', 'Recording cancelled.'],
    ['transcribing', 'Transcribing…'], ['finished', 'No transcript available.']]) {
    const content = { ...recording.content, status, ...(status === 'error' || status === 'cancelled' ? { transcript: 'stale result' } : {}) };
    const text = rendered({ ...recording, content }).join('\n');
    assert.ok(text.includes(expected));
    assert.ok(!text.includes('stale result'));
  }
  const sanitized = rendered({ ...recording, content: { ...recording.content,
    transcript: '🧪 漢字\n\x1b[31mweather\x1b[0m '.repeat(20) } }, 'aud-t-1', 20);
  assert.ok(sanitized.every(line => cells(line) <= 20 && !line.includes('\x1b')));
  assert.ok(sanitized.join('\n').includes('…'));
});
