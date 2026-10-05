/** Metadata discovery and selected-only private Project context. */
// contract-test-file: supporting surface=cli assertions=focus-modes.project-recommendation-full-assessment,focus-modes.project-specialist-composition,chats.direction.context-assessment
import { it } from 'node:test';
import assert from 'node:assert/strict';
import { loadActiveCliProjectContext, discoverCliProjectCandidates, collectRelatedCliTaskContext, prepareCliJevContext } from '../src/cliJevContext.ts';
import type { UserTaskRecord } from '../src/client.ts';
import { projectItemRevision, assessCliProjectAuthoring } from '../src/cliProjectAuthoring.ts';
import { encryptWithAesGcmCombined } from '../src/crypto.ts';
const key = new Uint8Array(32).fill(8);

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
  assert.deepEqual(candidates, [{ project_id: 'project', name: 'Explicit Project', summary: 'Small summary', auto_selection: false }]);
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
