// Wall-time comparison of the Rust (wasm, nodejs target) search exports against
// verbatim copies of the TypeScript functions in searchService.ts.
// Usage: node searchSnippetBench.cjs <path-to-wasm-bindgen-nodejs-package>/openmates_browser.js
'use strict';
const SNIPPET_CONTEXT_CHARS = 50;

function findMatchRanges(text, query) {
  const ranges = [];
  const lowerText = text.toLowerCase();
  const lowerQuery = query.toLowerCase();
  let searchFrom = 0;
  while (searchFrom < lowerText.length) {
    const idx = lowerText.indexOf(lowerQuery, searchFrom);
    if (idx === -1) break;
    ranges.push({ start: idx, length: lowerQuery.length });
    searchFrom = idx + lowerQuery.length;
  }
  return ranges;
}

function buildSnippet(content, matchStart, matchLength) {
  const contextStart = Math.max(0, matchStart - SNIPPET_CONTEXT_CHARS);
  const contextEnd = Math.min(content.length, matchStart + matchLength + SNIPPET_CONTEXT_CHARS);
  let snippet = content.slice(contextStart, contextEnd);
  let snippetMatchStart = matchStart - contextStart;
  if (contextStart > 0) {
    const firstSpace = snippet.indexOf(' ');
    if (firstSpace > 0 && firstSpace < snippetMatchStart) {
      snippet = snippet.slice(firstSpace + 1);
      snippetMatchStart -= firstSpace + 1;
    }
    snippet = '... ' + snippet;
    snippetMatchStart += 4;
  }
  if (contextEnd < content.length) {
    const lastSpace = snippet.lastIndexOf(' ');
    if (lastSpace > snippetMatchStart + matchLength) snippet = snippet.slice(0, lastSpace);
    snippet = snippet + ' ...';
  }
  return { snippet, snippetMatchStart, snippetMatchLength: matchLength };
}

const long = 'The quick brown fox jumps over the lazy dog. '.repeat(8) +
  'Needle in a haystack with \u{1F600} emoji and Straße, İstanbul. ' + 'tail words follow here '.repeat(6);

// Search runs over many chats: a batch of message bodies, each snippeted at its first match.
const corpus = Array.from({ length: 500 }, (_, i) =>
  (i % 3 === 0 ? 'ascii filler text number ' + i + ' ' : 'Gespräch Nr. ' + i + ' \u{1F600} ')
    .repeat(12) + 'needle ' + 'more words after the hit '.repeat(6));

function time(fn, rounds = 7) {
  const samples = [];
  for (let r = 0; r < rounds; r++) {
    const t = process.hrtime.bigint();
    fn();
    samples.push(Number(process.hrtime.bigint() - t) / 1e6);
  }
  samples.sort((a, b) => a - b);
  return samples[Math.floor(samples.length / 2)];
}

let sink = 0;
const text = long.repeat(200);
const tsRanges = () => { for (let i = 0; i < 200; i++) sink += findMatchRanges(text, 'needle').length; };
const tsSnippet = () => { for (let i = 0; i < 20000; i++) sink += buildSnippet(long, 400, 6).snippet.length; };
const tsBatch = () => {
  for (let rep = 0; rep < 20; rep++) {
    for (const body of corpus) {
      const r = findMatchRanges(body, 'needle');
      if (r.length) sink += buildSnippet(body, r[0].start, r[0].length).snippet.length;
    }
  }
};


// Verbatim JavaScript of embedSuggestionSearch.ts (types removed).
const stringValue = (value) => (typeof value === 'string' ? value.trim() : '');
function buildIndex(entriesByApp) {
  const byId = new Map();
  for (const [appId, groups] of Array.from(entriesByApp)) {
    for (const [groupName, entries] of Object.entries(groups)) {
      for (const entry of entries) {
        const value = entry.item_value;
        const embedId = stringValue(value?.embed_id);
        if (!embedId) continue;
        const title = stringValue(value.title) || stringValue(value.name) || groupName.replace(/_/g, ' ');
        const subtitle = [value.location, value.address, value.where, value.origin, value.destination, value.provider, value.date_start]
          .map(stringValue).filter(Boolean).join(' \u00b7 ').slice(0, 160);
        const metadata = Object.entries(value)
          .filter(([key]) => !['embed_id', 'url', 'booking_url', 'link'].includes(key))
          .map(([, field]) => stringValue(field).slice(0, 120))
          .filter(Boolean).join(' ').slice(0, 500);
        const searchText = [title, metadata].join(' ').toLowerCase();
        const settingsPath = entry.id ? `apps/${appId}/settings_memories/${groupName}/entry/${entry.id}` : undefined;
        const candidate = { embedId, settingsPath, title, subtitle, appId, updatedAt: entry.updated_at ?? 0, searchText };
        if (!byId.has(embedId) || byId.get(embedId).updatedAt < candidate.updatedAt) byId.set(embedId, candidate);
      }
    }
  }
  return Array.from(byId.values()).sort((a, b) => b.updatedAt - a.updatedAt);
}
const indexByEntries = new WeakMap();
function searchSavedEmbedMemories(state, query, limit = 6) {
  const normalized = query.trim().toLowerCase();
  if (!normalized || limit <= 0) return [];
  let index = indexByEntries.get(state.entriesByApp);
  if (!index) { index = buildIndex(state.entriesByApp); indexByEntries.set(state.entriesByApp, index); }
  const matches = [];
  for (const entry of index) { if (entry.searchText.includes(normalized)) matches.push(entry); }
  matches.sort((a, b) => {
    const aTitle = a.title.toLowerCase().includes(normalized) ? 1 : 0;
    const bTitle = b.title.toLowerCase().includes(normalized) ? 1 : 0;
    return bTitle - aTitle || b.updatedAt - a.updatedAt;
  });
  return matches.slice(0, limit).map(({ searchText: _s, ...result }) => result);
}
const memItems = Array.from({ length: 2000 }, (_, i) => ({ id: String(i), item_value: { embed_id: `e${i}`, title: `Design item ${i}`, location: 'Berlin' }, updated_at: i }));
const memState = () => ({ entriesByApp: new Map([['app', { g: memItems }]]) });
const orderedMem = JSON.stringify([['app', [['g', memItems.map((e) => ({ id: e.id, item_value: Object.entries(e.item_value), updated_at: e.updated_at }))]]]]);
const tsMemBuild = () => { for (let i = 0; i < 20; i++) sink += searchSavedEmbedMemories(memState(), 'design').length; };
const resident = memState();
const tsMemQuery = () => { for (let i = 0; i < 2000; i++) sink += searchSavedEmbedMemories(resident, 'item 1' + (i % 10)).length; };

// Verbatim hot loop of searchMessagesInChat: normalizedContent cached, first indexOf, 5 snippets.
const normalized = corpus.map((body) => body.toLowerCase());
function tsChatSearch(query) {
  const snippets = [];
  const lowerQuery = query.toLowerCase();
  for (let i = 0; i < corpus.length; i++) {
    if (snippets.length >= 5) break;
    const idx = normalized[i].indexOf(lowerQuery);
    if (idx === -1) continue;
    const { snippet, snippetMatchStart, snippetMatchLength } = buildSnippet(corpus[i], idx, query.length);
    snippets.push({ messageId: 'm' + i, snippet, matchStart: snippetMatchStart, matchLength: snippetMatchLength });
  }
  return snippets;
}
const tsChatMany = () => { for (let i = 0; i < 2000; i++) sink += tsChatSearch('needle').length; };
const tsChatRare = () => { for (let i = 0; i < 2000; i++) sink += tsChatSearch('Nr. 499').length; };

const rows = [['ranges x200 (112 KB)', tsRanges], ['snippet x20000', tsSnippet], ['chat search x2000, common query (5 hits)', tsChatMany], ['chat search x2000, rare query (full scan)', tsChatRare], ['per-item calls 500 bodies x20 (TS = direct)', tsBatch], ['memories build+query x20 (2000 items)', tsMemBuild], ['memories query x2000 (index cached)', tsMemQuery]];
const results = rows.map(([name, fn]) => ({ name, ts: time(fn) }));

if (process.argv[2]) {
  const wasm = require(process.argv[2]);
  const rustRanges = () => { for (let i = 0; i < 200; i++) sink += JSON.parse(wasm.search_find_match_ranges(text, 'needle')).length; };
  const rustSnippet = () => { for (let i = 0; i < 20000; i++) sink += JSON.parse(wasm.search_build_snippet(long, 400, 6)).snippet.length; };
  const rustPerItem = () => {
    for (let rep = 0; rep < 20; rep++) {
      for (const body of corpus) {
        const r = JSON.parse(wasm.search_find_match_ranges(body, 'needle'));
        if (r.length) sink += JSON.parse(wasm.search_build_snippet(body, r[0].start, r[0].length)).snippet.length;
      }
    }
  };
  const corpusHandle = new wasm.SearchCorpus();
  corpusHandle.set_texts_json(JSON.stringify(corpus.map((body, i) => ['m' + i, body])));
  const rustCorpus = () => {
    for (let rep = 0; rep < 20; rep++) sink += JSON.parse(corpusHandle.search('needle', 1)).length;
  };
  const rustMemBuild = () => { for (let i = 0; i < 20; i++) sink += JSON.parse(wasm.search_saved_embed_memories(orderedMem, 'design', 6)).length; };
  const memIndex = new wasm.SavedMemoriesIndex();
  memIndex.set_entries_json(orderedMem);
  const rustMemQuery = () => { for (let i = 0; i < 2000; i++) sink += JSON.parse(memIndex.search('item 1' + (i % 10), 6)).length; };
  const hitsCorpus = new wasm.SearchCorpus();
  hitsCorpus.set_texts_json(JSON.stringify(corpus.map((body, i) => ['m' + i, body])));
  const rustChatMany = () => { for (let i = 0; i < 2000; i++) sink += JSON.parse(hitsCorpus.first_hits('needle', 5)).length; };
  const rustChatRare = () => { for (let i = 0; i < 2000; i++) sink += JSON.parse(hitsCorpus.first_hits('Nr. 499', 5)).length; };
  const rust = [rustRanges, rustSnippet, rustChatMany, rustChatRare, rustPerItem, rustMemBuild, rustMemQuery];
  rust.forEach((fn, i) => { results[i].rust = time(fn); });
  results.push({ name: 'resident corpus 500 bodies x20 queries', ts: results[4].ts, rust: time(rustCorpus) });
  const t = process.hrtime.bigint();
  const loader = new wasm.SearchCorpus();
  loader.set_texts_json(JSON.stringify(corpus.map((body, i) => ['m' + i, body])));
  console.log(`corpus load 500 bodies: ${(Number(process.hrtime.bigint() - t) / 1e6).toFixed(2)} ms (once per ingest)`);
}
console.log('| case | TS ms | Rust wasm ms | ratio |\n|---|---:|---:|---:|');
for (const r of results) {
  console.log(`| ${r.name} | ${r.ts.toFixed(2)} | ${r.rust === undefined ? '-' : r.rust.toFixed(2)} | ${r.rust === undefined ? '-' : (r.rust / r.ts).toFixed(2)} |`);
}
if (sink === -1) console.log(sink);
