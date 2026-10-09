/** Complete, owner-scoped CLI Task inventory over the encrypted paginated route. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { OpenMatesClient, type UserTaskRecord } from '../src/client.js';

type Page = { tasks?: UserTaskRecord[]; complete?: boolean; next_cursor?: string | null };

function task(index: number): UserTaskRecord {
  return { task_id: `task-${String(index).padStart(3, '0')}` } as UserTaskRecord;
}

function clientForPages(teamId: string | null, respond: (url: URL) => Page | Promise<Page>) {
  const client = Object.create(OpenMatesClient.prototype) as OpenMatesClient;
  const session = { apiUrl: 'http://localhost', hashedEmail: 'synthetic-owner', sessionId: 'synthetic-session',
    createdAt: 1, masterKeyExportedB64: 'synthetic-key', activeTeamId: teamId };
  const seen: URL[] = [];
  const internals = client as unknown as {
    session: typeof session;
    requireSession: () => typeof session;
    resolveTeamContext: (options: { teamId?: string | null; personal?: boolean }) => string | null;
    getCliRequestHeaders: () => Record<string, string>;
    http: { get: (url: string, headers: Record<string, string>) => Promise<{ ok: boolean; status: number; data: Page }> };
  };
  internals.session = session;
  internals.requireSession = () => internals.session;
  internals.resolveTeamContext = options => options.personal ? null : options.teamId ?? internals.session.activeTeamId;
  internals.getCliRequestHeaders = () => ({ unchanged: 'auth' });
  internals.http = { get: async (path, headers) => {
    assert.deepEqual(headers, { unchanged: 'auth' });
    const url = new URL(path, 'http://localhost');
    seen.push(url);
    return { ok: true, status: 200, data: await respond(url) };
  } };
  return { client, session, seen };
}

// contract-test: supporting surface=cli assertions=tasks.surface.semantic-parity,tasks.external-chat.encrypted-context
test('Task discovery follows bounded cursor pages and publishes cumulative validated batches', async () => {
  const all = Array.from({ length: 615 }, (_, index) => task(index));
  const { client, seen } = clientForPages('team', url => {
    const cursor = url.searchParams.get('cursor');
    const start = cursor ? all.findIndex(entry => entry.task_id === cursor) + 1 : 0;
    const page = all.slice(start, start + 100);
    return { tasks: page, complete: start + page.length === all.length,
      next_cursor: start + page.length === all.length ? null : page.at(-1)!.task_id };
  });
  const batches: Array<[number, boolean]> = [];
  const result = await client.listUserTasks({ teamId: 'team', externalChatProvider: 'codex',
    externalChatLookupHash: 'a'.repeat(64), limit: 1000 }, {
    onPage: async (tasks, complete) => { batches.push([tasks.length, complete]); },
  });
  assert.deepEqual(result.map(entry => entry.task_id), all.map(entry => entry.task_id));
  assert.deepEqual(batches, [[100, false], [200, false], [300, false], [400, false], [500, false], [600, false], [615, true]]);
  assert.equal(seen.length, 7);
  for (const url of seen) {
    assert.equal(url.searchParams.get('paginate'), 'true');
    assert.equal(url.searchParams.get('limit'), '100');
    assert.equal(url.searchParams.get('external_chat_provider'), 'codex');
    assert.equal(url.searchParams.get('external_chat_lookup_hash'), 'a'.repeat(64));
    assert.equal(url.searchParams.get('team_id'), 'team');
  }
  assert.deepEqual(seen.map(url => url.searchParams.get('cursor')),
    [null, 'task-099', 'task-199', 'task-299', 'task-399', 'task-499', 'task-599']);
});

// contract-test: supporting surface=cli assertions=tasks.surface.semantic-parity
test('personal inventory pages more than 500 workflow Tasks inside the same wire batch limit', async () => {
  const canonical = Array.from({ length: 101 }, (_, index) => task(index));
  const projections = Array.from({ length: 615 }, (_, index) =>
    ({ task_id: `workflow-run:${String(index).padStart(4, '0')}`, source: 'workflow_run', read_only: true }) as UserTaskRecord);
  const prefix = 'workflow-tasks:';
  const wireSizes: number[] = [];
  const { client, seen } = clientForPages(null, url => {
    const cursor = url.searchParams.get('cursor');
    let rows: UserTaskRecord[];
    if (!cursor) rows = canonical;
    else if (cursor === canonical[99]!.task_id) rows = [canonical[100]!, ...projections];
    else rows = projections.slice(projections.findIndex(row => row.task_id === cursor.slice(prefix.length)) + 1);
    const page = rows.slice(0, 100);
    wireSizes.push(page.length);
    const complete = rows.length <= 100;
    const last = page.at(-1)!;
    return { tasks: page, complete, next_cursor: complete ? null
      : last.task_id.startsWith('workflow-') ? prefix + last.task_id : last.task_id };
  });
  const batches: number[] = [];
  const result = await client.listUserTasks({ personal: true }, { onPage: tasks => { batches.push(tasks.length); } });
  assert.deepEqual(batches, [100, 200, 300, 400, 500, 600, 700, 716]);
  assert.deepEqual(wireSizes, [100, 100, 100, 100, 100, 100, 100, 16]);
  assert.deepEqual(result.map(row => row.task_id), [...canonical, ...projections].map(row => row.task_id));
  assert.equal(seen[1]?.searchParams.get('cursor'), 'task-099');
  assert.equal(seen[2]?.searchParams.get('cursor'), prefix + projections[98]!.task_id);
  assert.ok(seen.every(url => !url.searchParams.has('team_id')));
});

// contract-test: supporting surface=cli assertions=tasks.surface.semantic-parity
test('a full canonical tail transitions once into workflow Tasks without exceeding the limit', async () => {
  const canonical = Array.from({ length: 100 }, (_, index) => task(index));
  const projection = { task_id: 'workflow-run:one', source: 'workflow_run', read_only: true } as UserTaskRecord;
  const { client, seen } = clientForPages(null, url => url.searchParams.has('cursor')
    ? { tasks: [projection], complete: true, next_cursor: null }
    : { tasks: canonical, complete: false, next_cursor: 'workflow-tasks:' });
  assert.equal((await client.listUserTasks()).length, 101);
  assert.equal(seen[1]?.searchParams.get('cursor'), 'workflow-tasks:');
});

// contract-test: supporting surface=cli assertions=tasks.surface.semantic-parity,tasks.external-chat.encrypted-context
test('workflow phase cursors reject filtered scope, malformed progress, oversized and unordered pages', async () => {
  const canonical = Array.from({ length: 100 }, (_, index) => task(index));
  for (const filters of [{ teamId: 'team' }, { projectId: 'project' }]) {
    const { client } = clientForPages(null, () => ({ tasks: canonical, complete: false, next_cursor: 'workflow-tasks:' }));
    await assert.rejects(client.listUserTasks(filters), /TASK_LIST_INCOMPLETE/);
  }
  const projections = Array.from({ length: 100 }, (_, index) =>
    ({ task_id: `workflow-run:${String(index).padStart(3, '0')}`, source: 'workflow_run', read_only: true }) as UserTaskRecord);
  for (const page of [
    { tasks: projections, complete: false, next_cursor: 'workflow-tasks:wrong' },
    { tasks: [...canonical, ...projections], complete: false, next_cursor: 'task-099' },
    { tasks: [...projections].reverse(), complete: true, next_cursor: null },
  ]) {
    const { client } = clientForPages(null, () => page);
    await assert.rejects(client.listUserTasks(), /TASK_LIST_INCOMPLETE/);
  }
  const canonicalInPhase = clientForPages(null, url => url.searchParams.has('cursor')
    ? { tasks: [task(100)], complete: true, next_cursor: null }
    : { tasks: canonical, complete: false, next_cursor: 'workflow-tasks:' });
  await assert.rejects(canonicalInPhase.client.listUserTasks(), /TASK_LIST_INCOMPLETE/);
});

// contract-test: supporting surface=cli assertions=tasks.surface.semantic-parity
test('underfilled legacy responses remain usable, but saturated or malformed inventories fail closed', async () => {
  const legacy = clientForPages('team', () => ({ tasks: [task(0)] }));
  assert.deepEqual((await legacy.client.listUserTasks()).map(entry => entry.task_id), ['task-000']);
  for (const page of [
    { tasks: Array.from({ length: 100 }, (_, index) => task(index)) },
    { tasks: [task(0)], complete: false, next_cursor: null },
    { tasks: [task(0)], complete: true, next_cursor: 'task-000' },
    { tasks: [task(0)], complete: true },
    { tasks: [], complete: false, next_cursor: 'task-000' },
  ]) {
    const { client } = clientForPages('team', () => page);
    await assert.rejects(client.listUserTasks(), /TASK_LIST_INCOMPLETE/);
  }
});

// contract-test: supporting surface=cli assertions=tasks.surface.semantic-parity
test('rejects a cyclic cursor before publishing a second page', async () => {
  const hundred = Array.from({ length: 100 }, (_, index) => task(index));
  const { client } = clientForPages('team', url => ({ tasks: hundred, complete: false,
    next_cursor: url.searchParams.get('cursor') ?? 'task-099' }));
  const batches: number[] = [];
  await assert.rejects(client.listUserTasks({}, { onPage: tasks => { batches.push(tasks.length); } }), /TASK_LIST_INCOMPLETE/);
  assert.deepEqual(batches, [100]);
});

// contract-test: supporting surface=cli assertions=tasks.surface.semantic-parity
test('fences account and Team changes before a deferred page or callback can continue paging', async () => {
  let release!: (page: Page) => void;
  const deferred = clientForPages('team', () => new Promise(resolve => { release = resolve; }));
  const pending = deferred.client.listUserTasks();
  deferred.session.hashedEmail = 'different-owner';
  release({ tasks: [task(0)], complete: true, next_cursor: null });
  await assert.rejects(pending, /Task workspace changed/);

  const hundred = Array.from({ length: 100 }, (_, index) => task(index));
  const switched = clientForPages('team', () => ({ tasks: hundred, complete: false, next_cursor: 'task-099' }));
  await assert.rejects(switched.client.listUserTasks({}, { onPage: () => { switched.session.activeTeamId = 'other-team'; } }),
    /Task workspace changed/);
  assert.equal(switched.seen.length, 1);
});
