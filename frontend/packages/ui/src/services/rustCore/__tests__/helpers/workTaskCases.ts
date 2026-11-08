// Cases for the user-Task `work` parity vectors (workTaskVectors.test.ts).
// Each case drives the real flag-off userTaskService (crypto, fetch, Team
// context and key lookups stubbed by the test) and records what it produced;
// the Rust ops in packages/openmates-rust/src/web_work replay the same inputs
// (tasks_tests.rs). Ciphertexts are `sealed:<plaintext>` (AAD-bound:
// `sealedaad:<aad>|<plaintext>`); the stub seals with `sealed:<key byte>:`.
import type * as Tasks from '../../../userTaskService';

type TaskService = typeof Tasks;
type View = Tasks.UserTaskViewModel;
type Json = Record<string, unknown>;

export const FRESH_ID = '00000000-0000-4000-8000-000000000001';
export const NOW_SECONDS = 1_700_000_000;
export const TEAM = 'team-a';

const seal = (value: unknown) => `sealed:${typeof value === 'string' ? value : JSON.stringify(value)}`;
export const aadSeal = (aad: string, value: string) => `sealedaad:${aad}|${value}`;

export function taskRecord(over: Json = {}): Json {
	return {
		task_id: 'task-1', encrypted_task_key: 'wrapped-key', encrypted_title: seal('Write docs'), encrypted_description: seal('Details'),
		encrypted_tags: seal(['a', 'b']), encrypted_latest_instruction: seal('Next step'), encrypted_linked_project_ids: seal(['project-a', 3, 'project-b']),
		status: 'todo', assignee_type: 'user', primary_chat_id: 'chat-a', version: 2, created_at: 1, updated_at: 2,
		...over,
	};
}

const teamWrapper = (over: Json = {}) => ({ key_type: 'team', hashed_team_id: `hash:${TEAM}`, team_key_epoch: 1, encrypted_task_key: 'team-wrapped', created_at: 1, ...over });
export const teamRecord = (over: Json = {}) => taskRecord({ hashed_team_id: `hash:${TEAM}`, encrypted_task_key: null, key_wrappers: [teamWrapper()], ...over });

/** Records projected by `taskView` (through listTaskBoardItems); Team rows name the envelope the page substitutes. */
export const taskViewCases: Array<{ name: string; record: Json; team?: string; envelope?: string }> = [
	{ name: 'full personal record', record: taskRecord() },
	{ name: 'minimal record takes every default', record: { task_id: 'task-2', encrypted_task_key: 'k', encrypted_title: seal('T'), status: 'backlog', assignee_type: 'openmates', version: 1, created_at: 5, updated_at: 6 } },
	{ name: 'tags that are not an array are kept as parsed', record: taskRecord({ encrypted_tags: seal({ x: 1 }) }) },
	{ name: 'malformed tags read as empty', record: taskRecord({ encrypted_tags: 'sealed:[oops' }) },
	{ name: 'undecryptable, empty and null members read as empty', record: taskRecord({ encrypted_title: 'garbage', encrypted_description: '', encrypted_blocked_reason: null }) },
	{ name: 'linked project ids that are not an array read as empty', record: taskRecord({ encrypted_linked_project_ids: seal({ a: 1 }) }) },
	{ name: 'external chat context is decrypted', record: taskRecord({ primary_chat_id: null, external_chat_provider: 'codex', encrypted_external_chat_id: seal('ses-1'), encrypted_external_chat_title: seal('Ext title') }) },
	{ name: 'a provider without an external id has no external chat', record: taskRecord({ external_chat_provider: 'claude' }) },
	{ name: 'blocked, plan, AI and scheduling members are kept', record: taskRecord({ status: 'blocked', blocked_reason_code: 'missing_credentials', encrypted_blocked_reason: seal('Need a key'), plan_id: 'plan-1', ai_execution_state: 'running', due_at: 50, priority: 3, position: 7, assignee_identity: 'codex', assignee_type: 'external_ai' }) },
	{ name: 'a missing version is refused', record: taskRecord({ version: undefined }) },
	{ name: 'a non-number version is refused', record: taskRecord({ version: '3' }) },
	{ name: 'Team record carries the active Team', record: teamRecord(), team: TEAM, envelope: 'team-wrapped' },
];

/** Records whose key envelope `taskKeyEnvelope` picks (observed as the unwrap argument). */
export const envelopeCases: Array<{ name: string; record: Json; team?: string }> = [
	{ name: 'personal wrapped key', record: taskRecord() },
	{ name: 'personal record without a key has no envelope', record: taskRecord({ encrypted_task_key: null }) },
	{ name: 'unique Team wrapper', record: teamRecord(), team: TEAM },
	{ name: 'Team row without wrappers fails closed', record: teamRecord({ key_wrappers: [] }), team: TEAM },
	{ name: 'Team row with absent wrappers fails closed', record: teamRecord({ key_wrappers: undefined }), team: TEAM },
	{ name: 'two valid Team wrappers fail closed', record: teamRecord({ key_wrappers: [teamWrapper(), teamWrapper({ encrypted_task_key: 'other' })] }), team: TEAM },
	{ name: 'epoch zero and foreign wrappers are skipped', record: teamRecord({ key_wrappers: [teamWrapper({ team_key_epoch: 0, encrypted_task_key: 'old' }), { key_type: 'master', encrypted_task_key: 'm', created_at: 1 }, teamWrapper({ team_key_epoch: 2 })] }), team: TEAM },
	{ name: 'a fractional epoch fails closed', record: teamRecord({ key_wrappers: [teamWrapper({ team_key_epoch: 1.5 })] }), team: TEAM },
	{ name: 'another Team hash fails closed', record: teamRecord({ key_wrappers: [teamWrapper({ hashed_team_id: 'hash:team-b' })] }), team: TEAM },
	{ name: 'an empty wrapped key fails closed', record: teamRecord({ key_wrappers: [teamWrapper({ encrypted_task_key: '' })] }), team: TEAM },
];

export const workflowRunCases: Array<{ name: string; record: Json }> = [
	{ name: 'full workflow run projection', record: { task_id: 'wf-1', source: 'workflow_run', projection_kind: 'next_run', workflow_id: 'w-1', workflow_run_id: 'r-1', trigger_id: 't-1', label: 'Workflow run', title: 'Nightly', status: 'todo', run_status: 'scheduled', can_cancel: true, can_delete: true, due_at: 50, scheduled_at: 50, blocked_message: 'Waiting', read_only: true, created_at: 1, updated_at: 2, position: 3 } },
	{ name: 'minimal projection falls back to the label', record: { task_id: 'wf-2', source: 'workflow_run', projection_kind: 'last_run', workflow_id: 'w-2', label: 'Workflow run', title: '', status: 'done', run_status: 'ok', can_cancel: false, read_only: true, created_at: 1, updated_at: 2, position: 0 } },
];

export const dependencies = [
	{ edge_id: 'e1', target_ref: 'plan:p1', target_kind: 'plan', target_id: 'p1', target_status: 'active', satisfied: false },
	{ edge_id: null, target_ref: 'task:t2', target_kind: 'task', target_id: 't2', satisfied: true },
];

const commentAad = (entry: string) => `task_activity_comment:task-1:${entry}:v1`;
const embedAad = (entry: string) => `task_activity_embed_keys:task-1:${entry}:v1`;
const activityBase = { task_id: 'task-1', actor_type: 'user', event_type: 'comment_added', source_surface: 'web', created_at: 5 };

/** Activity records decrypted for the personal fixture task (through listUserTaskActivity). */
export const activityCases: Array<{ name: string; record: Json }> = [
	{ name: 'comment message', record: { ...activityBase, entry_id: 'e-1', kind: 'comment', actor_hash: 'h1', embed_refs: ['em-1'], encrypted_message: aadSeal(commentAad('e-1'), 'Hello') } },
	{ name: 'comment with embed keys', record: { ...activityBase, entry_id: 'e-2', kind: 'comment', embed_refs: [], encrypted_message: aadSeal(commentAad('e-2'), 'Hi'), encrypted_embed_key_material: aadSeal(embedAad('e-2'), 'keys') } },
	{ name: 'a comment under another AAD is refused', record: { ...activityBase, entry_id: 'e-3', kind: 'comment', embed_refs: [], encrypted_message: aadSeal(commentAad('e-x'), 'Hello') } },
	{ name: 'embed keys under another AAD are refused', record: { ...activityBase, entry_id: 'e-4', kind: 'comment', embed_refs: [], encrypted_message: aadSeal(commentAad('e-4'), 'Hi'), encrypted_embed_key_material: aadSeal(commentAad('e-4'), 'keys') } },
	{ name: 'a comment without content is refused', record: { ...activityBase, entry_id: 'e-5', kind: 'comment', embed_refs: [] } },
	{ name: 'tombstone drops refs and never decrypts', record: { ...activityBase, entry_id: 'e-6', kind: 'tombstone', embed_refs: ['em-1'], encrypted_message: 'x', deleted_at: 9, deleted_by_hash: 'h2', deleted_by_display_name: 'Ann' } },
	{ name: 'lifecycle update keeps actor and status members', record: { ...activityBase, entry_id: 'e-7', kind: 'lifecycle_update', actor_type: 'openmates', actor_identity: 'openmates', actor_display_name: 'OpenMates', actor_profile_image_url: 'https://x/y.png', author_hash: 'a1', previous_status: 'todo', next_status: 'done', embed_refs: [], event_type: 'status_changed', source_surface: 'system' } },
];

/** One path case: the service call, its replies, the op input and which request carries the path. */
export interface PathCase {
	name: string;
	op: string;
	team?: string;
	replies: Json[];
	request?: number;
	run: (service: TaskService, task: View) => Promise<unknown>;
	input: Json | ((service: TaskService, task: View) => Promise<Json> | Json);
}

const ext = { provider: 'codex' as const, id: 'ses-private', title: 'Ext' };
const claude = { provider: 'claude' as const, id: 'ABCDEF00-0000-4000-8000-00000000000A', title: 'Claude chat' };
const listPath = (name: string, filters: Tasks.ListUserTasksFilters): PathCase => ({
	name, op: 'taskListPath', replies: [{ tasks: [] }], run: (s) => s.listTaskBoardItems(filters),
	input: async (s) => ({ filters, external_chat_lookup_hash: filters.externalChat ? await s.externalChatLookupHash(filters.externalChat) : null }),
});
const tombstone = { ...activityBase, entry_id: 'e/1', kind: 'tombstone', embed_refs: [] };
const asTeam = (task: View): View => ({ ...task, teamId: TEAM });
const workflowView: Tasks.WorkflowRunTaskProjectionViewModel = {
	task_id: 'wf-1', source: 'workflow_run', projectionKind: 'next_run', workflowId: 'w 1', workflowRunId: 'r/1', triggerId: null, title: 'Nightly',
	description: '', tags: [], latestInstruction: '', status: 'todo', assigneeType: 'user', assigneeIdentity: null, primaryChatId: null,
	linkedProjectIds: [], dueAt: null, priority: 0, position: 0, version: 0, canCancel: true, canDelete: true, readOnly: true,
};

export const pathCases: PathCase[] = [
	listPath('no filters', {}),
	listPath('every plain filter is encoded', { teamId: 'team a', status: 'blocked', chatId: 'chat&1', projectId: 'p/1' }),
	listPath('empty filter strings are skipped', { status: '' as never, chatId: '' }),
	listPath('external codex chat uses the blind index', { externalChat: ext }),
	listPath('external Claude chat with a Team', { teamId: 'team-1', externalChat: claude }),
	{ name: 'item path is encoded', op: 'taskItemPath', replies: [{ task: taskRecord() }], run: (s) => s.getUserTask('task/1 ü'), input: { task_id: 'task/1 ü', team_id: null } },
	{ name: 'item path in the active Team', op: 'taskItemPath', team: 'team a', replies: [{ task: taskRecord({ task_id: 'task-9' }) }], run: (s) => s.getUserTask('task-9'), input: { task_id: 'task-9', team_id: 'team a' } },
	{ name: 'key wrappers path', op: 'taskKeyWrappersPath', replies: [{ key_wrappers: [] }], run: (s) => s.listUserTaskKeyWrappers('task-1', null), input: { task_id: 'task-1', team_id: null } },
	{ name: 'key wrappers path with a Team', op: 'taskKeyWrappersPath', replies: [{ key_wrappers: [] }], run: (s) => s.listUserTaskKeyWrappers('task 1', 'team-1'), input: { task_id: 'task 1', team_id: 'team-1' } },
	{ name: 'dependencies path is encoded', op: 'taskDependenciesPath', replies: [{ dependencies: [] }], run: (s) => s.listUserTaskDependencies('task/1'), input: { task_id: 'task/1' } },
	{ name: 'activity path', op: 'taskActivityPath', replies: [{ entries: [], next_cursor: null }], run: (s, t) => s.listUserTaskActivity(t),
		input: (_s, t) => ({ task_id: t.task_id, team_id: null, task_team_id: t.teamId ?? null, cursor: null }) },
	{ name: 'activity path with an explicit Team', op: 'taskActivityPath', replies: [{ entries: [], next_cursor: null }], run: (s, t) => s.listUserTaskActivity(asTeam(t), 'team-b'),
		input: (_s, t) => ({ task_id: t.task_id, team_id: 'team-b', task_team_id: TEAM, cursor: null }) },
	{ name: 'activity next page carries the cursor and the task Team', op: 'taskActivityPath', request: 1,
		replies: [{ entries: [], next_cursor: 'c 1/2' }, { entries: [], next_cursor: null }], run: (s, t) => s.listUserTaskActivity(asTeam(t)),
		input: (_s, t) => ({ task_id: t.task_id, team_id: null, task_team_id: TEAM, cursor: 'c 1/2' }) },
	{ name: 'activity delete path', op: 'taskActivityDeletePath', replies: [{ entry: tombstone }], run: (s, t) => s.deleteUserTaskActivity(t, 'e/1'),
		input: (_s, t) => ({ task_id: t.task_id, entry_id: 'e/1', team_id: null, task_team_id: t.teamId ?? null }) },
	{ name: 'activity delete path with the task Team', op: 'taskActivityDeletePath', replies: [{ entry: tombstone }], run: (s, t) => s.deleteUserTaskActivity(asTeam(t), 'e/1'),
		input: (_s, t) => ({ task_id: t.task_id, entry_id: 'e/1', team_id: null, task_team_id: TEAM }) },
	{ name: 'activity delete path with an explicit Team', op: 'taskActivityDeletePath', replies: [{ entry: tombstone }], run: (s, t) => s.deleteUserTaskActivity(asTeam(t), 'e/1', 'team b'),
		input: (_s, t) => ({ task_id: t.task_id, entry_id: 'e/1', team_id: 'team b', task_team_id: TEAM }) },
	{ name: 'delete path carries the version', op: 'taskDeletePath', replies: [{}], run: (s, t) => s.deleteUserTask(t),
		input: (_s, t) => ({ task: { task_id: t.task_id, version: t.version, source: null, teamId: t.teamId } }) },
	{ name: 'delete path in a Team', op: 'taskDeletePath', replies: [{}], run: (s, t) => s.deleteUserTask(asTeam(t)),
		input: (_s, t) => ({ task: { task_id: t.task_id, version: t.version, source: null, teamId: TEAM } }) },
	{ name: 'workflow run delete path', op: 'taskDeletePath', replies: [{}], run: (s) => s.deleteUserTask(workflowView),
		input: { task: { task_id: workflowView.task_id, version: 0, source: 'workflow_run', teamId: null } } },
	{ name: 'workflow run cancel path is encoded', op: 'taskWorkflowCancelPath', replies: [{}], run: (s) => s.cancelWorkflowRunTaskProjection(workflowView),
		input: { workflow_id: 'w 1', workflow_run_id: 'r/1' } },
	{ name: 'cancel without a run id is refused', op: 'taskWorkflowCancelPath', replies: [{}], run: (s) => s.cancelWorkflowRunTaskProjection({ ...workflowView, workflowRunId: null }),
		input: { workflow_id: 'w 1', workflow_run_id: null } },
];

/** One request-body case: the service call and the op input the flag-on branch sends. */
export interface BodyCase {
	name: string;
	op: string;
	/** Runs on the Team fixture task under the active Team. */
	team?: boolean;
	reply: Json;
	run: (service: TaskService, task: View) => Promise<unknown>;
	input: (task: View) => Json;
	/** The page input `encrypt_input` steps stringify. */
	source: (task: View) => Json;
}

const at = NOW_SECONDS;
export const facts = (task: View) => ({ task_id: task.task_id, version: task.version, teamId: task.teamId, primaryChatId: task.primaryChatId, linkedProjectIds: task.linkedProjectIds });
const reply = { task: taskRecord() };

function create(name: string, input: Tasks.CreateUserTaskInput, team = false): BodyCase {
	return { name, op: 'taskCreateBody', team, reply, run: (s) => s.createUserTask(input),
		input: () => ({ input, team_id: input.teamId === undefined ? (team ? TEAM : null) : input.teamId, task_id: FRESH_ID, timestamp: at }), source: () => input as unknown as Json };
}
function update(name: string, patch: Json, options: { team?: boolean; task?: (task: View) => View } = {}): BodyCase {
	const target = options.task ?? ((task: View) => task);
	return { name, op: 'taskUpdateBody', team: options.team, reply, run: (s, task) => s.updateUserTask(target(task), patch as never),
		input: (task) => ({ task: facts(target(task)), patch, timestamp: at }), source: () => patch };
}
function action(name: string, verb: 'complete' | 'unblock' | 'skip', team = false): BodyCase {
	const run = { complete: 'completeUserTask', unblock: 'unblockUserTask', skip: 'skipUserTask' } as const;
	return { name, op: 'taskActionBody', team, reply, run: (s, task) => (s[run[verb]] as (t: View) => Promise<unknown>)(task),
		input: (task) => ({ action: verb, task: facts(task) }), source: () => ({}) };
}
function activity(name: string, input: Tasks.CreateUserTaskActivityInput, team = false): BodyCase {
	return { name, op: 'taskActivityCreateBody', team, reply: { entry: { ...activityBase, entry_id: 'e-1', kind: 'lifecycle_update', embed_refs: [] } },
		run: (s, task) => s.createUserTaskActivity(task, input),
		input: (task) => ({ task_id: task.task_id, input, fresh_id: FRESH_ID, timestamp: at, team_id: input.teamId ?? null, task_team_id: task.teamId ?? null }), source: () => input as unknown as Json };
}
const moves = (task: View, other: View) => [
	{ task, beforeTaskId: 'task-0', afterTaskId: null, status: 'done' as const, position: 4 },
	{ task: other, beforeTaskId: undefined, afterTaskId: 'task-1', status: undefined, position: undefined },
];
const moveFacts = (list: ReturnType<typeof moves>) => list.map((move) => ({
	task_id: move.task.task_id, team_id: move.task.teamId, version: move.task.version,
	beforeTaskId: move.beforeTaskId, afterTaskId: move.afterTaskId, status: move.status, position: move.position,
}));
const externalTask = (task: View): View => ({ ...task, primaryChatId: null, externalChat: { ...ext }, linkedProjectIds: [] });
const startFacts = (task: View) => ({ ...facts(task), title: task.title, description: task.description, latestInstruction: task.latestInstruction, externalChat: task.externalChat });

export const bodyCases: BodyCase[] = [
	create('create with only a title', { title: 'T' }),
	create('create with every personal member', { title: 'Ship', description: 'Desc', tags: ['x', 'y'], status: 'blocked', assigneeType: 'user', assigneeHash: 'ah',
		primaryChatId: 'chat-a', linkedProjectIds: ['project-a', 'project-b'], dueAt: 99, priority: 2 }),
	create('openmates without a due date starts in progress', { title: 'T', assigneeType: 'openmates' }),
	create('openmates with a due date stays todo', { title: 'T', assigneeType: 'openmates', dueAt: 5, assigneeIdentity: 'codex' }),
	create('external codex chat seals id and title', { title: 'T', externalChat: ext }),
	create('Claude session UUIDs are case-insensitive', { title: 'T', externalChat: claude }),
	create('Team create wraps with the Team key', { title: 'Team task', teamId: TEAM, linkedProjectIds: ['project-a'] }, true),
	create('native and external chat together are refused', { title: 'T', primaryChatId: 'chat-a', externalChat: ext }),
	create('an unsupported provider is refused', { title: 'T', externalChat: { provider: 'gpt' as never, id: 'x', title: '' } }),
	create('a non-UUID Claude id is refused', { title: 'T', externalChat: { provider: 'claude', id: 'ses-1', title: '' } }),
	create('an empty external id is refused', { title: 'T', externalChat: { provider: 'codex', id: '', title: '' } }),
	update('update seals text members and tags', { title: 'New', description: '', tags: ['z'], status: 'in_progress' }),
	update('update with null tags seals null', { tags: null }),
	update('assigning OpenMates defaults the identity', { assigneeType: 'openmates', assigneeHash: 'h' }),
	update('an explicit assignee identity is kept', { assigneeType: 'external_ai', assigneeIdentity: 'codex' }),
	update('a new native chat clears external context and re-wraps', { primaryChatId: 'chat-b' }),
	update('clearing the chat re-wraps without a chat wrapper', { primaryChatId: null }),
	update('an external chat replaces the native chat', { externalChat: ext }),
	update('clearing the chat and binding an external chat', { primaryChatId: null, externalChat: claude }),
	update('new links re-wrap with the current chat', { linkedProjectIds: ['project-b'] }),
	update('a null external chat re-wraps with the current chat', { externalChat: null }),
	update('due date and priority', { dueAt: null, priority: 3 }),
	update('native and external chat together are refused', { primaryChatId: 'chat-a', externalChat: ext }),
	update('null links are refused', { linkedProjectIds: null }),
	update('Team task links re-wrap for the Team', { linkedProjectIds: ['project-a'] }, { team: true }),
	action('complete', 'complete'),
	action('unblock', 'unblock'),
	action('skip', 'skip'),
	action('complete in a Team', 'complete', true),
	{ name: 'block with a sealed reason', op: 'taskBlockBody', reply, run: (s, task) => s.blockUserTask(task, 'external_dependency', 'Vendor down'),
		input: (task) => ({ task: facts(task), blocked_reason_code: 'external_dependency', blocked_reason: 'Vendor down' }), source: () => ({}) },
	{ name: 'block with the defaults', op: 'taskBlockBody', reply, run: (s, task) => s.blockUserTask(task),
		input: (task) => ({ task: facts(task), blocked_reason_code: 'needs_user_input', blocked_reason: '' }), source: () => ({}) },
	{ name: 'reorder drops nullish neighbours', op: 'taskReorderBody', reply: { tasks: [] }, run: (s, task) => s.reorderUserTasks(moves(task, { ...task, task_id: 'task-2', version: 5 })),
		input: (task) => ({ moves: moveFacts(moves(task, { ...task, task_id: 'task-2', version: 5 })) }), source: () => ({}) },
	{ name: 'reorder across workspaces is refused', op: 'taskReorderBody', reply: { tasks: [] }, run: (s, task) => s.reorderUserTasks(moves(task, asTeam(task))),
		input: (task) => ({ moves: moveFacts(moves(task, asTeam(task))) }), source: () => ({}) },
	{ name: 'an empty reorder', op: 'taskReorderBody', reply: { tasks: [] }, run: (s) => s.reorderUserTasks([]), input: () => ({ moves: [] }), source: () => ({}) },
	{ name: 'start with AI shares the chat prompt context', op: 'taskStartAiBody', reply, run: (s, task) => s.startUserTaskWithAI(task),
		input: (task) => ({ task: startFacts(task), timestamp: at }), source: () => ({}) },
	{ name: 'start with AI from an external chat', op: 'taskStartAiBody', reply, run: (s, task) => s.startUserTaskWithAI(externalTask(task)),
		input: (task) => ({ task: startFacts(externalTask(task)), timestamp: at }), source: () => ({}) },
	{ name: 'start with AI in a Team', op: 'taskStartAiBody', team: true, reply, run: (s, task) => s.startUserTaskWithAI(task),
		input: (task) => ({ task: startFacts(task), timestamp: at }), source: () => ({}) },
	{ name: 'extract with defaults', op: 'taskExtractBody', reply: { proposed_tasks: [] }, run: (s) => s.extractUserTaskProposals({ correctedText: 'Buy milk' }),
		input: () => ({ input: { correctedText: 'Buy milk' } }), source: () => ({}) },
	{ name: 'extract with every member', op: 'taskExtractBody', reply: { proposed_tasks: [] },
		run: (s) => s.extractUserTaskProposals({ correctedText: 'Fix it', mode: 'update', contextChatId: 'chat-a', projectIds: ['p'] }),
		input: () => ({ input: { correctedText: 'Fix it', mode: 'update', contextChatId: 'chat-a', projectIds: ['p'] } }), source: () => ({}) },
	{ name: 'add key wrappers', op: 'taskKeyWrappersAddBody', reply: { key_wrappers: [] },
		run: (s) => s.addUserTaskKeyWrappers('task-1', 2, [{ key_type: 'chat', encrypted_task_key: 'w', hashed_chat_id: 'hash:c', created_at: 1 }]),
		input: () => ({ task_id: 'task-1', version: 2, key_wrappers: [{ key_type: 'chat', encrypted_task_key: 'w', hashed_chat_id: 'hash:c', created_at: 1 }] }), source: () => ({}) },
	activity('activity comment seals under its AAD', { message: 'Hello' }),
	activity('activity with embed keys, refs, id, time and Team', { message: 'Hi', embedKeyMaterial: 'keys', embedRefs: ['em-1'], entryId: 'e-9', createdAt: 7, teamId: 'team-b' }),
	activity('activity on a Team task', { message: 'Team note' }, true),
];
