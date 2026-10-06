// contract-test-file: infrastructure
import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { DecryptedEmbed } from '../src/client.js';
import { buildTuiResultsViewData, parseTuiResultsViewBlock, renderTuiResultsViewLines, tuiResultsSourceChildren } from '../src/tuiResultsViews.js';

function embed(id: string, type: string, content: Record<string, unknown>): DecryptedEmbed {
  return { id, embedId: id, type, content, appId: null, skillId: null, textPreview: null, createdAt: null };
}

test('results descriptor keeps only web fields, stable comma refs and Unicode title', () => {
  assert.deepEqual(parseTuiResultsViewBlock(`title: Zürich 🗺️\nembeds: a, b, a\nsources: s, s\nhighlight: b\nprovider: ignored\n# comment`), {
    title: 'Zürich 🗺️', embeds: ['a', 'b'], sources: ['s'], highlight: ['b'],
  });
  assert.deepEqual(parseTuiResultsViewBlock('title: Invalid\nfilters: city=Paris'), {
    title: 'Invalid', embeds: [], sources: [], highlight: [],
  });
});

test('direct children precede one-level source children, dedupe, and preserve selected result aliases', () => {
  const source = embed('source', 'app_skill_use', { embed_ids: 'embed:berlin|munich', child_embed_ids: ['zurich', 'berlin'] });
  const embeds = new Map([
    ['source', source],
    ['berlin', embed('berlin', 'place', { title: 'Berlin Hauptbahnhof', address: 'Europaplatz 1', lat: 52.525, lon: 13.369, provider: 'Maps' })],
    ['munich', embed('munich', 'event', { title: 'München concert', date: '2026-10-12', venue_name: 'Arena' })],
    ['zurich', embed('zurich', 'place', { title: 'Zürich Lake', location: { latitude: 47.36, longitude: 8.54 } })],
  ]);
  const data = buildTuiResultsViewData({ title: 'Mapped results', embeds: ['berlin'], sources: ['source'], highlight: ['munich'] }, embeds);
  assert.deepEqual(data.entries.map(entry => entry.ref), ['berlin', 'munich', 'zurich']);
  assert.deepEqual(data.availableModes, ['map', 'calendar', 'list']);
  const map = renderTuiResultsViewLines(data, { mode: 'map', viewKey: 2, selectedRefs: ['berlin'], aliasForEmbed: ref => `short-${ref}` }).join('\n');
  assert.match(map, /Mapped results · Map/);
  assert.match(map, /\/view 2 map\|calendar\|list/);
  assert.match(map, /▶ 1\. Berlin Hauptbahnhof/);
  assert.match(map, /★ 2\. München concert/);
  assert.match(map, /Europaplatz 1/);
  assert.match(map, /52\.52500, 13\.36900/);
  assert.match(map, /\/embed short-zurich/);
  const calendar = renderTuiResultsViewLines(data, { mode: 'calendar' }).join('\n');
  assert.match(calendar, /2026-10-12\n★ 2\. München concert/);
  assert.doesNotMatch(calendar, /Berlin Hauptbahnhof/);
  assert.match(renderTuiResultsViewLines(data, { mode: 'list' }).join('\n'), /Berlin Hauptbahnhof[\s\S]*München concert[\s\S]*Zürich Lake/);
});

test('dates use source day and time without timezone shifting or invented schedules', () => {
  const data = buildTuiResultsViewData({ title: 'Calendar', embeds: ['late', 'all-day', 'invalid'], sources: [], highlight: [] }, {
    late: embed('late', 'event', { title: 'Late local', start_time: '2026-10-10T23:30:00-07:00' }),
    'all-day': embed('all-day', 'event', { title: 'All day', date: '2026-10-10' }),
    invalid: embed('invalid', 'event', { title: 'Invalid', date: '2026-02-30' }),
  });
  assert.deepEqual(data.entries.map(entry => [entry.ref, entry.date, entry.time]), [['late', '2026-10-10', '23:30'], ['all-day', '2026-10-10', undefined]]);
  assert.deepEqual(data.availableModes, ['calendar', 'list']);
  const lines = renderTuiResultsViewLines(data, { mode: 'map' }).join('\n');
  assert.match(lines, /Calendar · Calendar/);
  assert.match(lines, /All day[\s\S]*Late local/);
  assert.doesNotMatch(lines, /2026-10-11|Invalid/);
});

test('missing, invalid and online locations do not become map points or expose empty protocol', () => {
  const data = buildTuiResultsViewData({ title: 'Locations', embeds: ['bad', 'online', 'gone'], sources: ['source'], highlight: [] }, {
    bad: embed('bad', 'place', { title: 'Bad', lat: 100, lon: 200 }),
    online: embed('online', 'event', { title: 'Online', event_type: 'online', lat: 50, lon: 10, date: '2026-10-11' }),
    source: embed('source', 'search', { embed_ids: ['gone'] }),
  });
  assert.deepEqual(data.entries.map(entry => entry.ref), ['online']);
  assert.deepEqual(data.availableModes, ['calendar', 'list']);
  assert.deepEqual(data.missingRefs, ['gone']);
  const output = renderTuiResultsViewLines(data, { mode: 'map' }).join('\n');
  assert.doesNotMatch(output, /50\.00000|Bad|```|source/);
  assert.match(output, /1 referenced result unavailable/);
  assert.match(renderTuiResultsViewLines(buildTuiResultsViewData(parseTuiResultsViewBlock('title: Empty'), {})).join('\n'), /No results with a valid location or date/);
});

test('route points make a mappable result without inventing a point address or date', () => {
  const data = buildTuiResultsViewData({ title: 'Connections', embeds: ['route'], sources: [], highlight: [] }, {
    route: embed('route', 'travel-connection', { origin: 'München', destination: 'Zürich', route_points: [
      { lat: 48.14, lon: 11.56, label: 'München' }, { lat: 47.38, lon: 8.54, label: 'Zürich' },
    ] }),
  });
  assert.deepEqual(data.availableModes, ['map', 'list']);
  const output = renderTuiResultsViewLines(data, { mode: 'map' }).join('\n');
  assert.match(output, /München → Zürich/);
  assert.match(output, /München → Zürich\n {3}\/embed/);
  assert.doesNotMatch(output, /2026-|Address:/);
});

test('unhydrated and failed source roots have distinct honest fallbacks', () => {
  const descriptor = { title: 'Source results', embeds: [], sources: ['source'], highlight: [] };
  const pending = buildTuiResultsViewData(descriptor, {});
  assert.deepEqual(pending.missingRefs, ['source']);
  assert.match(renderTuiResultsViewLines(pending).join('\n'), /Referenced results are not available yet/);
  const failed = buildTuiResultsViewData(descriptor, { source: embed('source', 'search', { status: 'error' }) });
  assert.equal(failed.failedSources, 1);
  assert.match(renderTuiResultsViewLines(failed).join('\n'), /Source results\nReferenced source failed\. No verified results/);
});

test('source child extraction accepts arrays, JSON strings and delimiters, while failed sources cannot expose stale children', () => {
  const source = embed('source', 'search', {
    embed_ids: '["embed:one", "two", "one"]', child_embed_ids: ['two', 'three'],
  });
  assert.deepEqual(tuiResultsSourceChildren(source), ['one', 'two', 'three']);
  assert.deepEqual(tuiResultsSourceChildren(embed('source', 'search', { embed_ids: 'one|two, three four' })), ['one', 'two', 'three', 'four']);
  assert.deepEqual(tuiResultsSourceChildren({ ...source, content: { ...source.content, status: 'error' } }), []);
  assert.deepEqual(tuiResultsSourceChildren({ ...source, content: { ...source.content, status: 'cancelled' } }), []);
  assert.equal(tuiResultsSourceChildren(embed('source', 'search', { embed_ids: Array.from({ length: 45 }, (_, index) => `child-${index}`) })).length, 40);
});
