import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { OpenMatesClient } from '../src/client.js';
import type { TuiModelSelectorShell } from '../src/tuiModelSelectorShell.js';
import { renderWorkspaceFrame } from '../src/tuiLayout.js';
import { createTuiMentionShell, renderTuiMentions, type TuiMentionData } from '../src/tuiMentions.js';
import { pointerTargetAt } from '../src/tuiPointer.js';
import { createInitialTuiState } from '../src/tuiRenderer.js';
import type { TuiModelEntry } from '../src/tuiModelSelector.js';
import { cells, stripAnsi } from '../src/tuiText.js';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => { resolve = yes; });
  return { promise, resolve };
}
const tick = () => new Promise<void>(resolve => setImmediate(resolve));
const models: TuiModelEntry[] = [
  { id: 'openai/gpt-6-astra', name: 'GPT-6 Astra', providerId: 'openai', providerName: 'OpenAI', available: true },
  { id: 'qwen/qwen3-235b-a22b-2507', name: 'Qwen 3', providerId: 'qwen', providerName: 'Qwen', available: true },
];
const data: TuiMentionData = {
  context: { models: [], mates: { software_development: 'Sophia' }, apps: [
    { id: 'web', name: 'Web', skills: [{ id: 'search', name: 'Search' }] },
  ], memoryEntries: [] },
  projects: [{ id: 'p1', name: 'Alpha Project', accessMode: 'read_write' }],
};
function setup(fetchData: (() => Promise<TuiMentionData>) | null = async () => data) {
  const state = createInitialTuiState();
  state.signedIn = true; state.workspace = 'chats'; state.screen = 'chat'; state.focus = 'composer';
  state.activeChatId = 'chat-one'; state.modelSelector = { models } as typeof state.modelSelector;
  let session = { apiUrl: 'https://session.example.test', hashedEmail: 'owner-1', activeTeamId: null as string | null,
    createdAt: 1, masterKeyExportedB64: Buffer.alloc(32, 1).toString('base64') };
  // Deliberately different API URL disables disk cache while preserving the real owner fence.
  const client = { apiUrl: 'https://no-cache.example.test', hasSession: () => true, getSession: () => session } as OpenMatesClient;
  const consumed: string[] = [];
  let consume: (message: string) => Promise<{ message: string; blocked: boolean }> = async message =>
    ({ message: message.replace(/@(?:ai-model|best-model):[^\s]+\s?/, ''), blocked: false });
  const modelShell = { consumeMention: (message: string) => { consumed.push(message); return consume(message); } } as TuiModelSelectorShell;
  let renders = 0;
  const shell = createTuiMentionShell({ state, client, modelShell, ...(fetchData?{fetchData}:{}), render: () => { renders++; shell?.sync(); } });
  const input = (value: string, cursor = value.length) => { state.input = value; state.inputCursor = cursor; shell.sync(); };
  return { state, shell, client, input, consumed, renders: () => renders,
    switchOwner: () => { session = { ...session, hashedEmail: 'owner-2' }; shell.sync(); },
    switchTeam: () => { session = { ...session, activeTeamId: 'team-2' }; state.activeTeamId = 'team-2'; shell.sync(); },
    setConsume: (next: typeof consume) => { consume = next; } };
}
async function ready() { await tick(); await tick(); }
function find(state: ReturnType<typeof createInitialTuiState>, type: string) {
  const picker = state.mentionPicker;
  assert.ok(picker);
  const index = picker.items.findIndex(item => item.type === type);
  assert.ok(index >= 0, `missing ${type}`);
  return `${picker.generation}:${index}`;
}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,terminal-ui.offline.cache-first
test('Project selection resolves only its current access mode and cannot overwrite a newer draft', async () => {
  const ctx = setup(); let calls = 0;
  ctx.client.getProjectSettings = async id => { calls++; assert.equal(id, 'p1'); return { write_mode: 'always_ask' } as Awaited<ReturnType<OpenMatesClient['getProjectSettings']>>; };
  ctx.input('@alpha'); await ready(); assert.equal(calls, 0);
  await ctx.shell.select(find(ctx.state, 'project'));
  assert.equal(calls, 1); assert.equal(ctx.state.input, '@project:p1:read ');
  const pending = deferred<Awaited<ReturnType<OpenMatesClient['getProjectSettings']>>>();
  ctx.client.getProjectSettings = () => pending.promise;
  ctx.input('@alpha'); const selecting = ctx.shell.select(find(ctx.state, 'project'));
  ctx.input('Newer draft'); pending.resolve({ write_mode: 'apply_and_show' } as Awaited<ReturnType<OpenMatesClient['getProjectSettings']>>);
  await selecting; assert.equal(ctx.state.input, 'Newer draft'); ctx.shell.dispose();
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test('Enter on loading or empty suggestions never falls through to send', async () => {
  const pending = deferred<TuiMentionData>(), ctx = setup(() => pending.promise);
  ctx.input('@no-matching-option');
  assert.equal(await ctx.shell.key('', { name: 'return' }), true);
  assert.equal(ctx.state.input, '@no-matching-option'); assert.equal(ctx.state.messages.length, 0);
  pending.resolve(data); await ready();
  assert.equal(await ctx.shell.key('', { name: 'tab' }), true);
  assert.equal(ctx.state.messages.length, 0); ctx.shell.dispose();
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,terminal-ui.offline.cache-first
test('one unavailable source preserves app suggestions and changed workspace metadata can refresh the catalog', async () => {
  const ctx = setup(null); let calls = 0;
  ctx.client.getAppsWorkspaceCatalog = async () => { calls++; return { apps: [{id:'web',name:'Web',skills:[{id:'search',name:'Search'}]}] }; };
  ctx.client.listMemories = async () => { throw Error('Unavailable'); };
  ctx.client.listProjects = async () => [];
  ctx.client.getActiveTeamId = () => null;
  ctx.input('@search'); await ready();
  assert.ok(ctx.state.mentionPicker?.items.some(item => item.type==='skill')); assert.equal(calls,1);
  ctx.shell.sync(); assert.equal(calls,1);
  ctx.state.projects = []; ctx.shell.sync(); await ready(); assert.equal(calls,2);
  ctx.shell.refresh(); ctx.shell.sync(); await ready(); assert.equal(calls,3);
  ctx.shell.dispose();
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test('Wikipedia suggestions pass an explicit language separately from the article query', async () => {
  const ctx = setup(); const queries: unknown[][] = [];
  ctx.client.searchWikipediaTitles = async (...query) => { queries.push(query); return [{page_id:1,key:'Berlin',title:'Berlin',language:'de',disambiguation:false}]; };
  ctx.input('@wiki:de:Berlin'); await new Promise(resolve=>setTimeout(resolve,230)); await ready();
  assert.deepEqual(queries,[['Berlin','de',5]]);
  await ctx.shell.select(find(ctx.state,'wikipedia')); assert.equal(ctx.state.input,'@wikipedia:de:Berlin ');
  ctx.shell.dispose();
});

// contract-test: supporting surface=cli assertions=terminal-ui.offline.cache-first,cli.surface.semantic-parity
test('loads one mention catalog lazily across typing and navigation', async () => {
  let calls = 0;
  const ctx = setup(async () => { calls++; return data; });
  ctx.shell.sync(); assert.equal(calls, 0);
  ctx.input('@'); ctx.input('@w'); ctx.input('@we');
  await ctx.shell.key('', { name: 'down' });
  await ready(); ctx.shell.sync();
  assert.equal(calls, 1);
  assert.ok(ctx.state.mentionPicker?.items.some(item => item.type === 'skill'));
  ctx.shell.dispose();
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test('Enter, Tab and click selection insert canonical skill, Mate and Project tokens at caret without sending', async () => {
  const ctx = setup();
  ctx.input('Ask @web later', 8); await ready();
  assert.equal(await ctx.shell.key('', { name: 'return' }), true);
  assert.equal(ctx.state.input, 'Ask @skill:web:search  later');
  assert.equal(ctx.state.drafts['chat-one'], ctx.state.input);
  ctx.input('Ping @sophia done', 12);
  assert.equal(await ctx.shell.key('', { name: 'tab' }), true);
  assert.equal(ctx.state.input, 'Ping @mate:software_development  done');
  ctx.input('Use @alpha now', 10);
  await ctx.shell.select(find(ctx.state, 'project'));
  assert.equal(ctx.state.input, 'Use @project:p1:read_write  now');
  assert.equal(ctx.state.messages.length, 0);
  ctx.shell.dispose();
});

// contract-test: supporting surface=cli assertions=ai-model-routing.surface.semantic-parity
test('model choice is consumed by model shell and leaves the rest of the draft intact', async () => {
  const ctx = setup();
  ctx.input('Use @gpt answer', 8); await ready();
  await ctx.shell.select(find(ctx.state, 'model'));
  assert.deepEqual(ctx.consumed, ['Use @ai-model:gpt-6-astra:openai  answer']);
  assert.equal(ctx.state.input, 'Use  answer');
  assert.equal(ctx.state.messages.length, 0);
  ctx.shell.dispose();
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test('Esc preserves draft and suppresses the same mention until the user edits', async () => {
  const ctx = setup(); ctx.input('@web'); await ready();
  assert.equal(await ctx.shell.key('', { name: 'escape' }), true);
  assert.equal(ctx.state.input, '@web'); assert.equal(ctx.state.activeChatId, 'chat-one');
  ctx.shell.sync(); assert.equal(ctx.state.mentionPicker, null);
  ctx.input('@we'); assert.ok(ctx.state.mentionPicker);
  ctx.shell.dispose();
});

// contract-test: supporting surface=cli assertions=terminal-ui.offline.cache-first,cli.surface.semantic-parity
test('late account, Team and route data cannot show a stale private catalog', async () => {
  for (const change of ['owner', 'team', 'chat'] as const) {
    const pending = deferred<TuiMentionData>(), fresh = deferred<TuiMentionData>();
    let calls = 0;
    const ctx = setup(() => ++calls === 1 ? pending.promise : fresh.promise);
    ctx.input('@web');
    if (change === 'owner') ctx.switchOwner();
    if (change === 'team') ctx.switchTeam();
    if (change === 'chat') { ctx.state.activeChatId = 'chat-two'; ctx.state.routeVersion++; ctx.state.input = ''; ctx.shell.sync(); }
    pending.resolve(data); await ready();
    if (change === 'chat') assert.equal(ctx.state.mentionPicker, null);
    else assert.ok(!ctx.state.mentionPicker?.items.some(item => item.type === 'skill'));
    assert.equal(ctx.state.input, change === 'chat' ? '' : '@web');
    ctx.shell.dispose();
  }
});

// contract-test: supporting surface=cli assertions=terminal-ui.offline.cache-first,cli.surface.semantic-parity
test('late Wikipedia result and delayed model choice cannot mutate a switched context', async () => {
  const wiki = deferred<Array<{ language: string; key: string; title: string; description: string; disambiguation: boolean }>>();
  const ctx = setup();
  (ctx.client as unknown as { searchWikipediaTitles: () => typeof wiki.promise }).searchWikipediaTitles = () => wiki.promise;
  ctx.input('@wiki:Comet'); await ready();
  await new Promise<void>(resolve => setTimeout(resolve, 230));
  ctx.switchTeam();
  wiki.resolve([{ language: 'en', key: 'Comet', title: 'Comet', description: 'Article', disambiguation: false }]);
  await ready();
  assert.ok(!ctx.state.mentionPicker?.items.some(item => item.type === 'wikipedia'));
  assert.equal(ctx.state.input, '@wiki:Comet');

  ctx.input('@gpt'); await ready();
  const selection = deferred<{ message: string; blocked: boolean }>();
  ctx.setConsume(() => selection.promise);
  const choosing = ctx.shell.select(find(ctx.state, 'model'));
  ctx.switchOwner();
  selection.resolve({ message: '', blocked: false }); await choosing;
  assert.equal(ctx.state.input, '@gpt');
  assert.equal(ctx.state.drafts['chat-one'], undefined);
  ctx.shell.dispose();
});

// contract-test: supporting surface=cli assertions=terminal-pointer.viewport-coherent,terminal-pointer.visible-action-parity
test('visible suggestion rows own pointer targets; resized frames invalidate them', async () => {
  const ctx = setup(); ctx.input('@'); await ready();
  const picker = ctx.state.mentionPicker; assert.ok(picker);
  const rows = renderTuiMentions(picker);
  assert.equal((rows[1] as { action: { command: string } }).action.command, `/mention-select ${picker.generation}:0`);
  const width = 44, height = 18;
  const frame = stripAnsi(renderWorkspaceFrame(ctx.state, width, height, ['underlying body action']));
  assert.ok(frame.split('\n').every(row => cells(row) === width));
  const row = frame.split('\n').findIndex(line => line.includes('@Wiki'));
  assert.ok(row >= 0);
  const col = frame.split('\n')[row].indexOf('@Wiki');
  assert.deepEqual(pointerTargetAt(ctx.state, col, row, width, height), { kind: 'command', command: `/mention-select ${picker.generation}:0` });
  assert.equal(pointerTargetAt(ctx.state, 1, row, width, height), null);
  assert.equal(pointerTargetAt(ctx.state, col, row, width + 1, height), null);
  picker.selectedIndex = 1;
  assert.equal(pointerTargetAt(ctx.state, col, row, width, height), null);
  const selectedFrame = stripAnsi(renderWorkspaceFrame(ctx.state, width, height, []));
  const selectedRow = selectedFrame.split('\n').findIndex(line => line.includes('@Best'));
  assert.ok(selectedRow >= 0);
  const selectedCol = selectedFrame.split('\n')[selectedRow].indexOf('@Best');
  assert.deepEqual(pointerTargetAt(ctx.state, selectedCol, selectedRow, width, height),
    { kind: 'command', command: `/mention-select ${picker.generation}:1` });
  ctx.shell.dispose();
});
