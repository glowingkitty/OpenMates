// Cases for the Workflows `work` parity vectors (workWorkflowVectors.test.ts).
// Each case drives the real flag-off workflow services/store (fetch and the
// master-key wrap stubbed by the test) and states the input the flag-on page
// sends to the Rust op; packages/openmates-rust/src/web_work/workflows_tests.rs
// replays them. Key order matters: inputs and ordered outputs are compared as text.
// spec: specifications/features/workflows#workflows.portability.private-content-boundary
type Json = Record<string, unknown>;

export const FRESH_ID = '00000000-0000-4000-8000-000000000003';

const node = (id: string, type: string, over: Json = {}): Json => ({ id, type, config: {}, ...over });

export function workflow(over: Json = {}, graph: Json = {}): Json {
	return {
		id: 'wf-1', title: '  Morning report  ', description: ' Daily digest ', version: 3, enabled: false,
		graph: {
			version: 2, trigger_node_id: 't',
			nodes: [
				node('t', 'schedule_trigger', { title: 'Every morning', config: { cron: '0 9 * * *', zeta: 1, alpha: [1, { b: 2, a: 1 }] } }),
				node('a', 'app_skill_action', { title: 'Search', config: { app_id: 'web', skill_id: 'search', query: { text: 'news', limit: 5 } } }),
				node('n', 'send_notification', { title: '', position: { x: 1 } }),
			],
			edges: [{ from: 't', to: 'a' }, { from: 'a', to: 'n', branch: 'yes' }, { from: 'n', to: 'a', branch: '' }],
			...graph,
		},
		...over,
	};
}

const nodesWith = (...extra: Json[]) => [...((workflow().graph as Json).nodes as Json[]), ...extra];

/** Workflows built into a portable payload (`buildWorkflowTemplatePayload`). */
export const payloadCases: Array<{ name: string; workflow: Json }> = [
	{ name: 'full workflow keeps TS key order', workflow: workflow() },
	{ name: 'missing trigger is refused', workflow: workflow({}, { trigger_node_id: 'missing' }) },
	{ name: 'blank title is refused after the payload is built', workflow: workflow({ title: '    ' }) },
	{ name: 'null, missing and blank descriptions read null', workflow: workflow({ description: '   ' }) },
	{ name: 'a null description reads null', workflow: workflow({ description: null }) },
	{ name: 'a missing description reads null', workflow: { ...workflow(), description: undefined } },
	{ name: 'nested forbidden key reports its path', workflow: workflow({}, { nodes: nodesWith(node('x', 'decision', { config: { nested: { api_key: 'k' } } })) }) },
	{ name: 'the first forbidden key in insertion order is reported', workflow: workflow({}, { nodes: nodesWith(node('x', 'decision', { config: { zToken: 1, aSecret: 2 } })) }) },
	{ name: 'integer-like keys are walked first', workflow: workflow({}, { nodes: nodesWith(node('x', 'decision', { config: { b: 1, 2: { Run_ID: 1 }, 1: 2 } })) }) },
	{ name: 'forbidden key inside an array', workflow: workflow({}, { nodes: nodesWith(node('x', 'decision', { config: { list: [{ ok: 1 }, { 'Webhook-Secret': 1 }] } })) }) },
	{ name: 'trigger config forbidden key', workflow: workflow({}, { nodes: [node('t', 'manual_trigger', { config: { grantId: 1 } })] }) },
	{ name: 'capabilities are deduplicated and sorted by UTF-16', workflow: workflow({}, { nodes: [
		node('t', 'manual_trigger'),
		node('s1', 'app_skill_action', { config: { app_id: 'web', skill_id: 'search' } }),
		node('s2', 'app_skill_action', { config: { app_id: 'web', skill_id: 'read' } }),
		node('s3', 'app_skill_action', { config: { app_id: 'web', skill_id: 'search' } }),
		node('s4', 'app_skill_action', { config: { app_id: '～' } }),
		node('s5', 'app_skill_action', { config: { app_id: '\u{1f600}', skill_id: 'x' } }),
		node('s6', 'app_skill_action', { config: { app_id: '' } }),
		node('s7', 'app_skill_action', { config: { app_id: 5, skill_id: null } }),
		node('s8', 'app_skill_action', { config: null }),
		node('e', 'send_email_notification'),
	], edges: [] }) },
	{ name: 'a node sharing the trigger id is skipped', workflow: workflow({}, { nodes: nodesWith(node('t', 'decision', { title: 'dup' })) }) },
	{ name: 'a non-portable edge endpoint is caught by the final check', workflow: workflow({}, { edges: [{ from: { token: 1 }, to: 'a' }] }) },
	{ name: 'missing graph version and untitled trigger', workflow: workflow({}, { version: undefined, nodes: [node('t', 'manual_trigger', { title: 0 })], edges: [] }) },
];

const validPayload = (): Json => ({
	template_version: 1, title: 'T', description: null,
	trigger_template: { id: 't', type: 'manual_trigger', config: {} },
	node_templates: [{ id: 'a', type: 'app_skill_action', config: { app_id: 'web' } }],
	edge_templates: [{ from: 't', to: 'a' }, { from: 'a', to: 't', branch: 'b' }],
	variables_schema: {}, required_capabilities: ['web'],
	binding_requirements: [{ type: 'app_skill', node_id: 'a', app_id: 'web', skill_id: 's' }],
});

export const VALID_PAYLOAD = validPayload();

/** Received templates checked by `validateWorkflowTemplatePayload`. */
export const validateCases: Array<{ name: string; value: unknown }> = [
	{ name: 'a valid payload passes', value: validPayload() },
	{ name: 'null is an invalid version', value: null },
	{ name: 'an array is an invalid version', value: [1] },
	{ name: 'version 0', value: { ...validPayload(), template_version: 0 } },
	{ name: 'fractional version', value: { ...validPayload(), template_version: 1.5 } },
	{ name: 'string version', value: { ...validPayload(), template_version: '1' } },
	{ name: 'blank title', value: { ...validPayload(), title: ' \n' } },
	{ name: 'trigger without config', value: { ...validPayload(), trigger_template: { id: 't', type: 'x' } } },
	{ name: 'node templates not an array', value: { ...validPayload(), node_templates: {} } },
	{ name: 'edge with a numeric branch', value: { ...validPayload(), edge_templates: [{ from: 'a', to: 'b', branch: 1 }] } },
	{ name: 'edge with an empty endpoint', value: { ...validPayload(), edge_templates: [{ from: '', to: 'b' }] } },
	{ name: 'non-string capability', value: { ...validPayload(), required_capabilities: [1] } },
	{ name: 'requirement with a numeric app id', value: { ...validPayload(), binding_requirements: [{ type: 'a', node_id: 'b', app_id: 1 }] } },
	{ name: 'array variables schema', value: { ...validPayload(), variables_schema: [] } },
	{ name: 'forbidden key in the variables schema', value: { ...validPayload(), variables_schema: { db: { password: 'x' } } } },
	{ name: 'forbidden top-level key', value: { ...validPayload(), workflow_id: 'wf-1' } },
];

/** Public projections checked by `loadSharedWorkflowTemplate` before the checksum. */
export const projectionCases: Array<{ name: string; templateId: string; projection: Json }> = [
	{ name: 'matching projection passes', templateId: 'wt_1', projection: { template_id: 'wt_1', projection_schema_version: 1, ciphertext: 'abc', ciphertext_checksum: 'x' } },
	{ name: 'another template is refused', templateId: 'wt_1', projection: { template_id: 'wt_2', projection_schema_version: 1, ciphertext: 'abc', ciphertext_checksum: 'x' } },
	{ name: 'another schema version is refused', templateId: 'wt_1', projection: { template_id: 'wt_1', projection_schema_version: 2, ciphertext: 'abc', ciphertext_checksum: 'x' } },
	{ name: 'a string schema version is refused', templateId: 'wt_1', projection: { template_id: 'wt_1', projection_schema_version: '1', ciphertext: 'abc', ciphertext_checksum: 'x' } },
];

/** Import replies checked by `importWorkflowTemplate`. */
export const importCases: Array<{ name: string; reply: Json }> = [
	{ name: 'a disabled import passes', reply: { workflow: { id: 'wf-2', enabled: false } } },
	{ name: 'an enabled import is refused', reply: { workflow: { id: 'wf-2', enabled: true } } },
	{ name: 'a missing workflow is refused', reply: {} },
	{ name: 'a null workflow is refused', reply: { workflow: null } },
];

const mutation = (target: string, nodes: unknown) => ({ type: 'update_workflow', target_id: target, before: { graph: { nodes } }, after: null });

/** Session replies normalized by `normalizeSession` (through getWorkflowInstruction). */
export const sessionCases: Array<{ name: string; session: Json }> = [
	{ name: 'no changes keeps the reply', session: { status: 'executed', session_id: 's-1', workflows: [{ id: 'w', title: 'T' }] } },
	{ name: 'an empty change list keeps the reply', session: { status: 'draft', changes: [], session_id: 's-1' } },
	{ name: 'removed ids become titled nodes', session: {
		status: 'executed', changes: [{ workflow_id: 'w1', removed_node_ids: ['a', 'b', 'c', 'd'], operation: 'update' }], session_id: 's-1',
		mutations: [mutation('w0', [{ id: 'a', title: 'Wrong' }]), mutation('w1', [{ id: 'a', title: 'Fetch', type: 'x' }, { id: 'b', type: 'app_skill_action' }, { id: 'd', title: '', type: '' }])],
	} },
	{ name: 'existing lists are kept and changed ids are the fallback', session: {
		changes: [
			{ removed_nodes: [{ id: 'z', title: 'Z' }], added_node_ids: ['n'], workflow_id: 'w1', changed_node_ids: ['c'] },
			{ workflow_id: 'w2', edited_node_ids: ['e'], changed_node_ids: ['c'], added_node_ids: null },
		], session_id: 's-2', status: 'executed',
	} },
	{ name: 'missing mutations, null before and missing ids', session: {
		session_id: 's-3', changes: [{ workflow_id: 'w1', removed_node_ids: ['q'] }, { removed_node_ids: ['r'] }],
		mutations: [{ type: 'create_workflow', target_id: 'w1', before: null }],
	} },
];

/** Run provenance merged by `loadWorkflowRunPreviewMetadata`. */
export const previewCases: Array<{ name: string; provenance: Json; workflow?: Json | 'fail'; run?: Json | 'fail' }> = [
	{ name: 'nothing known reads both', provenance: { workflowId: 'w 1', runId: 'r/1' }, workflow: { title: 'T', description: null }, run: { started_at: 9 } },
	{ name: 'known title and start skip both reads', provenance: { workflowId: 'w', runId: 'r', title: 'Own', startedAt: 5, description: 'D' } },
	{ name: 'failed reads leave undefined', provenance: { workflowId: 'w', runId: 'r' }, workflow: 'fail', run: 'fail' },
	{ name: 'a null workflow title is kept', provenance: { workflowId: 'w', runId: 'r', startedAt: 0 }, workflow: { title: null, description: 'From workflow' }, run: { started_at: 3 } },
];

/** Library pages projected by `listAppsWorkflows`. */
export const libraryCases: Array<{ name: string; args: [string, string | undefined, number?, number?]; reply: Json }> = [
	{ name: 'defaults without a team', args: ['web', undefined], reply: { workflows: [{ id: 'w1', title: 'One', extra: 1 }, { id: 'w2' }], has_more: true, offset: 0, limit: 20 } },
	{ name: 'encoded app with team and paging', args: ['a b&c/é', 'team-1', 40, 10], reply: { workflows: [], has_more: false, offset: 40, limit: 10 } },
];
