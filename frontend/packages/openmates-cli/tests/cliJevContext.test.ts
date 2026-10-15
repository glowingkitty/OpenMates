import { stringify as stringifyYaml } from "yaml";
/** Metadata discovery and selected-only private Project context. */
// contract-test-file: supporting surface=cli assertions=focus-modes.project-recommendation-full-assessment,focus-modes.project-specialist-composition,chats.direction.context-assessment
import { it } from 'node:test';
import assert from 'node:assert/strict';
import { loadActiveCliProjectContext, discoverCliProjectCandidates, collectRelatedCliTaskContext, prepareCliJevContext, parseFocusAuthoringDocument } from '../src/cliJevContext.ts';
import type { UserTaskRecord } from '../src/client.ts';
import { projectItemRevision, assessCliProjectAuthoring, startCliProjectAuthoring } from '../src/cliProjectAuthoring.ts';
import { encryptWithAesGcmCombined } from '../src/crypto.ts';
const key = new Uint8Array(32).fill(8);

// contract-test: supporting surface=cli assertions=chats.direction.context-assessment,plans.active-context.vault-boundary
it('skips only impossible Focus and Plan reads for an SDK-minted chat while retaining fresh Project and Task candidates', async () => {
  const encryptedName = await encryptWithAesGcmCombined('Project candidate', key);
  const calls = { projects: 0, settings: 0, tasks: 0, focus: 0, plans: 0 };
  const scope = { personal: true, teamId: null };
  const client = {
    async listProjects(options: unknown) { assert.deepEqual(options, scope); calls.projects++; return [{ project_id: 'project', encrypted_name: encryptedName }]; },
    async decryptProjectKey() { return key; },
    async getProjectSettings(_id: string, options: unknown) { assert.deepEqual(options, scope); calls.settings++; return { auto_selection: true }; },
    async listUserTaskDiscoveryPage(options: Record<string, unknown>) { assert.deepEqual(options, scope); calls.tasks++;
      return [{ task_id: 'task', status: 'in_progress', version: 1, updated_at: 10 }]; },
    async listUserTasks(options: Record<string, unknown>) { assert.deepEqual(options, { ...scope, chatId: 'existing-or-caller-id', limit: 100 }); calls.tasks++; return []; },
    async decryptTaskContextRecord(_record: unknown, options: unknown) { assert.deepEqual(options, scope);
      return { title: 'Current work', description: 'Useful summary', linkedProjectIds: ['project'] }; },
    async getActiveProjectFocus() { calls.focus++; return null; },
    async listUserPlans() { calls.plans++; return []; },
  };
  const supplied = { custom_rule_documents: [{ id: 'rule', source: 'project' as const, project_id: 'project', document: 'Private rule' }],
    project_focus_catalog: [{ id: 'focus', title: 'Private', summary: 'Private', revision: '1' }] };
  const fresh = await prepareCliJevContext(client as never, 'fresh-chat', scope, supplied, 'Question', { sdkMintedChatId: true });
  assert.deepEqual(calls, { projects: 1, settings: 1, tasks: 1, focus: 0, plans: 0 });
  assert.deepEqual(fresh.project_focus_candidates?.map(row => row.name), ['Project candidate']);
  assert.deepEqual(fresh.related_task_candidates?.map(row => row.title), ['Current work']);
  assert.deepEqual(fresh.custom_memory_documents, []);
  assert.deepEqual(fresh.project_focus_catalog, []);
  assert.equal(fresh.accepted_plan_context, null);

  await prepareCliJevContext(client as never, 'existing-or-caller-id', scope, supplied, 'Question');
  assert.deepEqual(calls, { projects: 2, settings: 2, tasks: 3, focus: 2, plans: 1 });
});

// contract-test: supporting surface=cli assertions=chats.direction.context-assessment
it('prioritizes older actual chat-linked open Tasks and their owned explicit dependencies ahead of general recent discovery', async () => {
  const now = 10_000, reads: string[] = [];
  const row = (id: string, status: string, updated_at: number, primary_chat_id: string | null = null) =>
    ({ task_id: id, status, updated_at, primary_chat_id, version: 7 } as UserTaskRecord);
  const records = [row('old-unlinked-blocked', 'blocked', 1), row('old-unlinked-todo', 'todo', 1), row('old-unlinked-done', 'done', 1),
    ...Array.from({ length: 65 }, (_, index) => row(`recent-${index}`, 'in_progress', now)),
    row('linked-todo', 'todo', 1, 'chat'), row('linked-backlog', 'backlog', 1, 'chat'), row('linked-blocked', 'blocked', 1, 'chat'),
    row('dependency-old', 'done', 1), row('other-chat-blocked', 'blocked', 1, 'other'), row('bad-version', 'todo', 1, 'chat')];
  records.at(-1)!.version = 0;
  const options = { teamId: 'team' };
  const client = {
    async getTaskDependencies(id: string, context: unknown) {
      assert.deepEqual(context, options);
      return { dependencies: id === 'linked-todo' ? [{ source_ref: 'task:linked-todo', target_ref: 'task:dependency-old' },
        { source_ref: 'task:unrelated', target_ref: 'task:old-unlinked-done' }, { source_ref: 'task:linked-todo', target_ref: 'task:foreign' }] : [], blockers: [] };
    },
    async decryptTaskContextRecord(record: UserTaskRecord, context: unknown) {
      assert.deepEqual(context, options); reads.push(record.task_id);
      return { title: record.task_id, description: 'Actual owned summary', linkedProjectIds: [], status: record.status };
    },
  };
  const candidates = await collectRelatedCliTaskContext(client as never, 'chat', options, records, now);
  assert.equal(candidates.length, 24);
  assert.deepEqual(candidates.slice(0, 4).map(task => task.task_id), ['linked-backlog', 'linked-blocked', 'linked-todo', 'dependency-old']);
  assert.equal(candidates[3].explicit_dependency, true);
  assert.ok(candidates.every(task => task.revision === '7' && task.summary === 'Actual owned summary'));
  assert.ok(!reads.some(id => ['old-unlinked-blocked', 'old-unlinked-todo', 'old-unlinked-done', 'other-chat-blocked', 'bad-version', 'foreign'].includes(id)));
});

// contract-test: supporting surface=cli assertions=chats.direction.context-assessment
it('sends an older linked Task summary through normal context preparation even when optional dependency and Plan reads fail', async () => {
  const task = { task_id: 'linked', status: 'blocked', updated_at: 1, primary_chat_id: 'chat', version: 4 } as UserTaskRecord;
  const client = { async listProjects() { return []; }, async getActiveProjectFocus() { return null; }, async getCustomRuleDocuments() { return []; },
    async listUserTasks() { return [task]; }, async listUserPlans() { throw new Error('Optional Plan unavailable'); },
    async getTaskDependencies() { throw new Error('Optional dependencies unavailable'); },
    async decryptTaskContextRecord() { return { title: 'Current chat work', description: 'Existing goal', linkedProjectIds: [], status: 'blocked' }; } };
  const result = await prepareCliJevContext(client as never, 'chat', {});
  assert.equal(result.accepted_plan_context, null);
  assert.deepEqual(result.related_task_candidates, [{ task_id: 'linked', title: 'Current chat work', summary: 'Existing goal', project_id: null,
    status: 'blocked', changed_at: 1, revision: '4', explicit_dependency: false }]);
});
async function contextFixture() {
  const items = await Promise.all(['selected', 'unselected'].map(async id => ({ project_item_id: id, item_type: 'embed', updated_at: 1,
    target_id_encrypted: await encryptWithAesGcmCombined(id + '-embed', key), encrypted_metadata: await encryptWithAesGcmCombined(JSON.stringify({
      display_path: `.openmates/focuses/${id}/SKILL.md`, focus_title: id, focus_description: 'Private context summary', focus_when_to_use: 'Use this Project' }), key) })));
  let selection = [{ id: 'selected', kind: 'focus', revision: projectItemRevision(items[0]) }];
  let focus = { project_id: 'project', team_id: null, focus_id: 'base', specialist_focus_id: null as string | null };
  const reads: string[] = [];
  const client = {
    async getActiveProjectFocus() { return focus; }, async getProject() { return { project: {}, items, folders: [] }; }, async decryptProjectKey() { return key; },
    async selectProjectContext(_project: string, input: Record<string, unknown>) { assert.doesNotMatch(JSON.stringify(input), /Full private instructions/); return selection; },
    async readEncryptedProjectFile(_project: string, embed: string) { reads.push(embed); return { content: { code: 'Full private instructions' }, revision: 1 }; },
  };
  return { client, items, reads, setSelection(value: typeof selection) { selection = value; }, setFocus(value: typeof focus) { focus = value; } };
}

// contract-test: supporting surface=cli assertions=focus-modes.project-recommendation-full-assessment,focus-modes.project-specialist-composition
it('reads only revision-bound selected private Markdown and leaves other Focus bodies undisclosed', async () => {
  const f = await contextFixture(); const context = await loadActiveCliProjectContext(f.client as never, 'chat', 'Use Project guidance');
  assert.deepEqual(f.reads, ['selected-embed']); assert.equal(context.project_focus_catalog?.length, 2);
  assert.deepEqual(context.project_focus_documents?.map(row => row.item_id), ['selected']);
  const metadataOnly = await contextFixture(); await loadActiveCliProjectContext(metadataOnly.client as never, 'chat'); assert.equal(metadataOnly.reads.length, 0);
});

// contract-test: supporting surface=cli assertions=focus-modes.project-specialist-composition
it('retains only the fresh accepted specialist when metadata relevance does not select it', async () => {
  const f = await contextFixture(); f.setSelection([]); f.setFocus({ project_id: 'project', team_id: null, focus_id: 'base', specialist_focus_id: 'project-focus:project:unselected' });
  const context = await loadActiveCliProjectContext(f.client as never, 'chat', 'Continue');
  assert.deepEqual(f.reads, ['unselected-embed']); assert.deepEqual(context.project_focus_documents?.map(row => row.item_id), ['unselected']);
});

// contract-test: supporting surface=cli assertions=focus-modes.project-specialist-composition
it('omits stale selection revisions before any private read and drops bodies after focus changes', async () => {
  const stale = await contextFixture(); stale.setSelection([{ id: 'selected', kind: 'focus', revision: 'outdated' }]);
  await loadActiveCliProjectContext(stale.client as never, 'chat', 'Use guidance'); assert.equal(stale.reads.length, 0);
  const changed = await contextFixture(); changed.client.readEncryptedProjectFile = async (_project, embed) => { changed.reads.push(embed); changed.setFocus({ project_id: 'other', team_id: null, focus_id: 'other', specialist_focus_id: null }); return { content: { code: 'Full private instructions' }, revision: 1 }; };
  assert.deepEqual(await loadActiveCliProjectContext(changed.client as never, 'chat', 'Use guidance'), {});
});

// contract-test: supporting surface=cli assertions=focus-modes.project-recommendation-full-assessment
it('discovery includes OFF metadata for explicit mentions without loading private settings or files', async () => {
  const encryptedName = await encryptWithAesGcmCombined('Explicit Project', key), encryptedDescription = await encryptWithAesGcmCombined('Small summary', key);
  const candidates = await discoverCliProjectCandidates({ async listProjects() { return [{ project_id: 'project', encrypted_name: encryptedName, encrypted_description: encryptedDescription }]; },
    async decryptProjectKey() { return key; }, async getProjectSettings() { return { auto_selection: false }; },
    async readEncryptedProjectFile() { throw new Error('No private reads during discovery'); } } as never, {});
  assert.deepEqual(candidates, [{ project_id: 'project', name: 'Explicit Project', summary: 'Small summary',
    auto_selection: false, focus_activation_policy: 'delayed' }]);
});

// contract-test: supporting surface=cli assertions=focus-modes.project-recommendation-full-assessment
it('authoring catalogs only Project-linked saved Workflows using their authoritative record version, without graph or full Focus reads', async () => {
  const f = await contextFixture(); f.setSelection([]);
  const linked = { project_item_id: 'workflow-link', item_type: 'workflow', target_id_encrypted: await encryptWithAesGcmCombined('workflow', key), updated_at: 1, encrypted_metadata: '' };
  const detail = { project: {}, folders: [], items: [...f.items, linked] }; let catalog: unknown;
  await assessCliProjectAuthoring({ ...f.client, async getProject() { return detail; }, async listWorkflows() { return [
    { id: 'workflow', title: 'Saved Workflow', description: 'Bound definition', status: 'draft', version: 7 },
    { id: 'unlinked', title: 'Unrelated Workflow', status: 'active', version: 3 } ]; },
    async requestProjectAuthoringRecommendations(_project: string, input: Record<string, unknown>) { catalog = input.catalog; return []; },
  } as never, { chat_id: 'chat', project_id: 'project', user_message_id: 'turn' }, [{ role: 'user', content: 'Update Project guidance.' }]);
  assert.equal(f.reads.length, 0);
  const workflows = (catalog as Array<Record<string, unknown>>).filter(row => row.kind === 'workflow');
  assert.deepEqual(workflows, [{ kind: 'workflow', id: 'workflow', title: 'Saved Workflow', summary: 'Bound definition', revision: '7' }]);
});

// contract-test: supporting surface=cli assertions=focus-modes.project-authoring-click,focus-modes.project-recommendation-full-assessment
it('uses the server recommendation timestamp so identical issued proposals persist identical encrypted-history event identities across devices', async () => {
  const f = await contextFixture(); let createdAt: number | undefined = 1200;
  const client = { ...f.client, async listWorkflows() { return []; },
    async requestProjectAuthoringRecommendations() { return [{ recommendation_id: '12345678-1234-4234-8234-123456789abc', chat_id: 'chat', project_id: 'project', kind: 'focus', action: 'create', created_at: createdAt, expires_at: 2400 }]; } };
  const input = { chat_id: 'chat', project_id: 'project', user_message_id: 'turn' }, history = [{ role: 'user' as const, content: 'Improve guidance' }];
  const first = await assessCliProjectAuthoring(client as never, input, history);
  createdAt = undefined;
  const legacy = await assessCliProjectAuthoring(client as never, input, history);
  assert.equal(first[0].event_id, "12345678-1234-4234-8234-123456789abc");
  assert.equal(first[0].created_at, 1200); assert.deepEqual(first, legacy);
  assert.equal(f.reads.length, 0, 'Recommendation assessment never reads unselected Focus bodies or starts an author job');
});

const phaseMetadata = { name: 'Debugging', description: 'Synthetic source checks', when_to_use: 'Synthetic incidents' };
const canonicalPhases = [{ id: 'inspect', title: 'Inspect', instructions: 'Compare source before logs.', requirements: [
  { id: 'matched', text: 'Source matches.', type: 'semantic' },
  { id: 'approved', text: 'The user confirms the comparison.', type: 'user_confirmation' },
] }, { id: 'diagnose', title: 'Diagnose', instructions: 'Read bounded logs.', requirements: [{ id: 'diagnosed', text: 'Evidence explains the failure.' }] }];
const legacyPhases = [{ id: 'Inspect_OLD', name: 'Inspect', instructions: 'Preserve this existing guidance.' }];
const phaseMarkdown = (fields: Record<string, unknown>) => `---\n${stringifyYaml({ ...phaseMetadata, ...fields })}---\nKeep global guidance in every phase.`;

// contract-test: supporting surface=cli assertions=focus-modes.phases,focus-modes.project-authoring-persistence
it('preserves canonical phase version and every ordered gate while transporting legacy phases without conversion', () => {
  const canonical = parseFocusAuthoringDocument(phaseMarkdown({ phases_version: 1, phases: canonicalPhases }));
  assert.deepEqual(canonical, { ...phaseMetadata, instructions: 'Keep global guidance in every phase.', phases_version: 1, phases: canonicalPhases });
  const legacy = parseFocusAuthoringDocument(phaseMarkdown({ phases: legacyPhases }));
  assert.deepEqual(legacy.phases, legacyPhases);
  assert.equal(Object.hasOwn(legacy, 'phases_version'), false);
  assert.equal(Object.hasOwn(legacy.phases[0], 'requirements'), false);
  assert.deepEqual(parseFocusAuthoringDocument(phaseMarkdown({})).phases, []);
});

// contract-test: supporting surface=cli assertions=focus-modes.phases,focus-modes.project-authoring-persistence
it('rejects malformed versioned phases without legacy fallback or private YAML errors', () => {
  const invalid = [
    ...[true, false, 2, null].map(phases_version => ({ phases_version, phases: canonicalPhases })),
    { phases_version: 1, phases: [] }, { phases_version: 1, phases: legacyPhases },
    { phases: canonicalPhases }, { phases_version: 1, phases: [canonicalPhases[0], canonicalPhases[0]] },
    { phases_version: 1, phases: [{ ...canonicalPhases[0], requirements: [] }] },
    { phases_version: 1, phases: [{ ...canonicalPhases[0], requirements: [canonicalPhases[0].requirements[0], canonicalPhases[0].requirements[0]] }] },
    { phases_version: 1, phases: [{ ...canonicalPhases[0], requirements: [{ id: 'gate', text: 'PRIVATE-PHASE-SENTINEL', type: 'permission' }] }] },
  ];
  for (const metadata of invalid) assert.throws(() => parseFocusAuthoringDocument(phaseMarkdown(metadata)), { message: 'invalid_focus_document' });
  const valid = phaseMarkdown({ phases_version: 1, phases: canonicalPhases });
  for (const malformed of [valid.replace('name: Debugging', 'name: First\nname: PRIVATE-PHASE-SENTINEL'),
    valid.replace('description: Synthetic source checks', 'description: &private PRIVATE-PHASE-SENTINEL\nunknown: *private')]) {
    assert.throws(() => parseFocusAuthoringDocument(malformed), { message: 'invalid_focus_document' });
  }
});

// contract-test: supporting surface=cli assertions=focus-modes.project-recommendation-full-assessment,focus-modes.project-authoring-click,focus-modes.phases
it('transmits complete canonical and genuine legacy definitions through selected inspection and click-triggered Update', async () => {
  for (const fields of [{ phases_version: 1, phases: canonicalPhases }, { phases: legacyPhases }]) {
    const f = await contextFixture(); f.setSelection([]);
    const markdown = phaseMarkdown(fields), expected = parseFocusAuthoringDocument(markdown);
    let inspected: unknown, target: unknown;
    const proposal = { recommendation_id: '12345678-1234-4234-8234-123456789abc', chat_id: 'chat', project_id: 'project', kind: 'focus',
      action: 'inspect', target_id: 'selected', expected_revision: projectItemRevision(f.items[0]), created_at: 1200, expires_at: 9999999999 };
    const client = { ...f.client, async listWorkflows() { return []; },
      async readEncryptedProjectFile(_project: string, embed: string) { f.reads.push(embed); return { content: { code: markdown }, revision: 1 }; },
      async requestProjectAuthoringRecommendations() { return [proposal]; },
      async inspectProjectFocusRecommendation(_project: string, body: Record<string, unknown>) { inspected = body.document; return { ...proposal, action: 'update' }; },
      async startProjectAuthoringJob(_project: string, body: Record<string, unknown>) { target = body.target; return { job_id: 'background', status: 'authoring' }; } };
    const history = [{ role: 'user' as const, content: 'Update saved guidance.' }];
    const receipts = await assessCliProjectAuthoring(client as never, { chat_id: 'chat', project_id: 'project', user_message_id: 'turn' }, history);
    assert.deepEqual(inspected, expected); assert.equal(target, undefined, 'Inspection does not start paid authoring');
    await startCliProjectAuthoring(client as never, receipts[0], history);
    assert.deepEqual(target, expected); assert.deepEqual(f.reads, ['selected-embed', 'selected-embed']);
  }
});

// contract-test: supporting surface=cli assertions=focus-modes.project-specialist-composition,chats.direction.context-assessment
it('publishes routing metadata before selected private Project documents finish loading', async () => {
  const f = await contextFixture();
  let release!: () => void;
  const bodyGate = new Promise<void>(resolve => { release = resolve; });
  const read = f.client.readEncryptedProjectFile;
  f.client.readEncryptedProjectFile = async (...args) => { await bodyGate; return read(...args); };
  let headers!: (value: unknown) => void;
  const routing = new Promise<unknown>(resolve => { headers = resolve; });
  const client = { ...f.client, async listProjects() { return []; }, async listUserTasks() { return []; }, async listUserPlans() { return []; } };
  let completed = false;
  const preparing = prepareCliJevContext(client as never, 'chat', {}, {}, 'Use guidance', { onRouting: headers })
    .then(value => { completed = true; return value; });
  const result = await routing;
  assert.equal(completed, false);
  assert.doesNotMatch(JSON.stringify(result), /Full private instructions|project_focus_documents/);
  assert.equal((result as { project_focus_catalog: unknown[] }).project_focus_catalog.length, 2);
  release();
  assert.equal((await preparing).project_focus_documents?.[0].document, 'Full private instructions');
});

// contract-test: supporting surface=cli assertions=chats.direction.context-assessment,chats.completion.lease-fenced
it('publishes completed Project selection before slow Task discovery, with full legacy routing later', async () => {
  let releaseTasks!: () => void;
  const taskGate = new Promise<void>(resolve => { releaseTasks = resolve; });
  let publishProject!: (value: unknown) => void;
  const projectRouting = new Promise<unknown>(resolve => { publishProject = resolve; });
  let legacyPublished = false;
  const client = {
    async listProjects() { return []; },
    async listUserTasks() { await taskGate; return []; },
  };
  const preparing = prepareCliJevContext(client as never, 'new-chat', { personal: true }, {}, 'Question', {
    sdkMintedChatId: true,
    onProjectRouting: publishProject,
    onRouting: () => { legacyPublished = true; },
  });
  assert.deepEqual(await projectRouting, { project_focus_candidates: [] });
  assert.equal(legacyPublished, false, 'Task and Plan work must not gate Project selection');
  releaseTasks();
  await preparing;
  assert.equal(legacyPublished, true);
});

// contract-test: supporting surface=cli assertions=chats.direction.context-assessment,chats.completion.lease-fenced
it('does not publish an empty Project selection when directory discovery is incomplete', async () => {
  for (const failurePoint of ['directory', 'metadata'] as const) {
    let published = false;
    let failure: unknown;
    const client = {
      async listProjects() {
        if (failurePoint === 'directory') throw new Error('Project directory unavailable');
        return [{ project_id: 'unreadable', encrypted_name: 'invalid' }];
      },
      async decryptProjectKey() { throw new Error('Project key unavailable'); },
      async getProjectSettings() { return { auto_selection: true }; },
      async listUserTasks() { return []; },
    };
    await prepareCliJevContext(client as never, 'new-chat', { personal: true }, {}, 'Question', {
      sdkMintedChatId: true,
      onProjectRouting: () => { published = true; },
      onProjectRoutingError: error => { failure = error; },
    });
    assert.equal(published, false);
    assert.match(String(failure), failurePoint === 'directory' ? /Project directory unavailable/ : /Project key unavailable/);
  }
});

// contract-test: supporting surface=cli assertions=chats.direction.context-assessment,auth.session.isolation
it('uses the verified send-socket Project candidates without REST directory fanout', async () => {
  const verified = [{ project_id: 'owned', name: 'Owned', summary: 'Current',
    auto_selection: true, focus_activation_policy: 'delayed' as const }];
  let published: unknown;
  const client = {
    async listProjects() { throw new Error('REST Project directory must not run'); },
    async getProjectSettings() { throw new Error('per-Project settings must not run'); },
    async listUserTasks() { return []; },
  };
  const result = await prepareCliJevContext(client as never, 'new-chat', { personal: true },
    { project_focus_candidates: [{ project_id: 'forged', name: 'Forged', summary: '',
      auto_selection: true, focus_activation_policy: 'delayed' }] }, 'Question', {
      sdkMintedChatId: true, verifiedProjectCandidates: verified, onProjectRouting: value => { published = value; },
    });
  assert.deepEqual(published, { project_focus_candidates: verified });
  assert.deepEqual(result.project_focus_candidates, verified);
});
