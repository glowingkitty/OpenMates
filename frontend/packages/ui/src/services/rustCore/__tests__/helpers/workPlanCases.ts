// Cases for the user-Plan `work` parity vectors (workPlanVectors.test.ts).
// Each case drives the real flag-off userPlanService (crypto, fetch and key
// lookups stubbed by the test) and records what it produced; the Rust ops in
// packages/openmates-rust/src/web_work replay the same inputs (plans_tests.rs).
// Ciphertexts are `sealed:<plaintext>`; the stub seals with `sealed:<key byte>:`.
import type * as Plans from '../../../userPlanService';

type PlanService = typeof Plans;
type View = Plans.UserPlanViewModel;

export const FRESH_ID = '00000000-0000-4000-8000-000000000001';
export const NOW_SECONDS = 1_700_000_000;

const master = { key_type: 'master', encrypted_plan_key: 'wrapped-key', created_at: 1 };
const seal = (value: unknown) => `sealed:${typeof value === 'string' ? value : JSON.stringify(value)}`;

export const validFlow = {
	flow_id: 'flow-1', title: 'Sign in', actor: 'user', expected_outcome: 'Signed in',
	steps: [
		{ step_id: 's1', text: 'Open the app', references: [{ kind: 'embed', embed_id: 'embed-1', start_line: 2, end_line: 4 }] },
		{ step_id: 's2', text: 'Read docs', references: [{ kind: 'url', url: 'https://example.org/docs' }, { kind: 'file', path: 'docs/a.md', start_line: 1 }] },
		{ step_id: 's3', text: 'Done' },
	],
	linked_task_ids: ['task-1'],
} as Plans.UserPlanFlow;

export function planRecord(over: Record<string, unknown> = {}): Plans.EncryptedUserPlanRecord {
	return {
		plan_id: 'plan-1', encrypted_title: seal('Ship v2'), encrypted_goal: seal('Goal text'),
		encrypted_scope_in: seal('In scope'), encrypted_user_flows: seal([validFlow]),
		encrypted_linked_project_ids: seal(['project-a', 3, 'project-b']), status: 'draft', primary_chat_id: 'chat-a',
		linked_project_hashes: ['hash:project-a'], created_at: 1, updated_at: 2, key_wrappers: [master as Plans.UserPlanKeyWrapperRecord],
		...over,
	} as Plans.EncryptedUserPlanRecord;
}

const flowCase = (name: string, flows: unknown) => ({ name, record: planRecord({ encrypted_user_flows: seal(flows) }) });

/** Plan records projected by `planView` (through getFreshUserPlan). */
export const planViewCases = [
	{ name: 'full record with flows and linked projects', record: planRecord() },
	{ name: 'minimal record takes every default', record: { plan_id: 'plan-2', encrypted_title: seal('T'), encrypted_goal: seal('G'), status: 'active', created_at: 5, updated_at: 6, key_wrappers: [master] } },
	{ name: 'undecryptable, empty and null members read as empty', record: planRecord({ encrypted_goal: 'garbage', encrypted_risks: '', encrypted_constraints: null, encrypted_decisions: seal('Decided') }) },
	{ name: 'approval, revisions, completion and focus are kept', record: planRecord({ approval_state: 'approved', submitted_revision_id: 'r-3', approved_revision_id: 'r-3', completed_at: 99, planner_focus_id: 'focus-1', version: 4, status: 'completed' }) },
	{ name: 'linked project ids that are not an array read as empty', record: planRecord({ encrypted_linked_project_ids: seal({ x: 1 }) }) },
	flowCase('user flows that are not an array are refused', { a: 1 }),
	flowCase('a flow without a title is refused', [{ ...validFlow, title: '' }]),
	flowCase('a flow that is not an object is refused', [7]),
	flowCase('a null step is a TypeError', [{ ...validFlow, steps: [null] }]),
	flowCase('a step without text is refused', [{ ...validFlow, steps: [{ step_id: 's1' }] }]),
	flowCase('evidence URLs must use HTTPS', [{ ...validFlow, steps: [{ step_id: 's1', text: 'x', references: [{ kind: 'url', url: 'http://example.org' }] }] }]),
	flowCase('absolute evidence paths are refused', [{ ...validFlow, steps: [{ step_id: 's1', text: 'x', references: [{ kind: 'file', path: '/etc/passwd' }] }] }]),
	flowCase('parent-directory evidence paths are refused', [{ ...validFlow, steps: [{ step_id: 's1', text: 'x', references: [{ kind: 'file', path: 'docs/../secret' }] }] }]),
	flowCase('an embed reference needs an id', [{ ...validFlow, steps: [{ step_id: 's1', text: 'x', references: [{ kind: 'embed', embed_id: '' }] }] }]),
	flowCase('start_line must be a positive integer', [{ ...validFlow, steps: [{ step_id: 's1', text: 'x', references: [{ kind: 'embed', embed_id: 'e', start_line: 0 }] }] }]),
	flowCase('end_line must follow start_line', [{ ...validFlow, steps: [{ step_id: 's1', text: 'x', references: [{ kind: 'file', path: 'a.md', start_line: 5, end_line: 4 }] }] }]),
	flowCase('end_line without start_line must be at least one', [{ ...validFlow, steps: [{ step_id: 's1', text: 'x', references: [{ kind: 'embed', embed_id: 'e', end_line: 1.5 }] }] }]),
];

const criterionFull = {
	criterion_id: 'c-1', type: 'security', status: 'satisfied', required: false, linked_task_ids: ['t-1'], verification_ids: ['v-1'],
	coverage_status: 'covered', verification_scope: 'e2e', version: 3, created_at: 10, updated_at: 11,
	encrypted_text: seal('Must encrypt'), encrypted_evidence: seal('Run 42'), encrypted_coverage_note: 'garbage', encrypted_waiver_reason: '',
};
const verificationFull = {
	verification_id: 'v-1', kind: 'e2e', phase: 'red', status: 'passed', required_for_done: false, covers: ['c-1'], lifecycle_status: 'active',
	source_hash: 'h', threshold: 0.8, score: 0.9, confidence: 'high', linked_task_id: 't-1', linked_sub_chat_id: 'sub-1', source_embed_id: 'e-1',
	runner_kind: 'ci', run_id: 'run-1', created_at: 1, updated_at: 2, encrypted_description: seal('Check login'), encrypted_command: seal('npm test'),
	encrypted_evaluation_prompt: seal('Judge'), encrypted_evaluator_instructions: seal('Be strict'), encrypted_expected_result: seal('Green'),
	encrypted_result_summary: seal('Passed'), encrypted_required_fixes: seal('None'), encrypted_source_path: seal('tests/a.spec.ts'),
	encrypted_red_phase_reason: seal('Fails first'), encrypted_task_key: 'wrapped-task-key',
};
const assumptionFull = {
	assumption_id: 'a-1', category: 'api', status: 'corrected', required_before: 'planning', linked_sub_chat_id: 'sub-2', linked_task_id: 't-2',
	linked_criterion_ids: ['c-1'], source_count: 2, version: 2, created_at: 3, updated_at: 4, encrypted_text: seal('API is v2'),
	encrypted_corrected_text: seal('API is v3'), encrypted_evidence_summary: seal('Docs'), encrypted_blocker_reason: seal(''),
	encrypted_waiver_reason: seal('n/a'), encrypted_sources: seal('[1]'),
};
const patternFull = {
	pattern_id: 'p-1', category: 'ui', status: 'confirmed', required_before: 'review', source_count: 1, linked_task_ids: ['t-3'], linked_check_ids: ['v-1'],
	version: 5, created_at: 7, updated_at: 8, encrypted_title: seal('Card layout'), encrypted_description: seal('Grid'), encrypted_sources: seal('figma'),
	encrypted_match_rules: seal('rules'), encrypted_anti_patterns: seal('none'), encrypted_evidence_summary: seal('ok'), encrypted_waiver_reason: seal('w'),
};

/** Child records projected by the `plan*View` ops (through the list functions). */
export const childViewCases: Array<{ name: string; op: string; list: keyof PlanService; member: string; record: Record<string, unknown> }> = [
	{ name: 'full criterion', op: 'planCriterionView', list: 'listPlanCriteria', member: 'criteria', record: criterionFull },
	{ name: 'minimal criterion takes defaults', op: 'planCriterionView', list: 'listPlanCriteria', member: 'criteria', record: { criterion_id: 'c-2', status: 'pending' } },
	{ name: 'full verification', op: 'planVerificationView', list: 'listPlanVerifications', member: 'verifications', record: verificationFull },
	{ name: 'minimal verification takes defaults', op: 'planVerificationView', list: 'listPlanVerifications', member: 'verifications', record: { verification_id: 'v-2', kind: 'manual', status: 'pending', threshold: null } },
	{ name: 'full assumption', op: 'planAssumptionView', list: 'listPlanAssumptions', member: 'assumptions', record: assumptionFull },
	{ name: 'minimal assumption takes defaults', op: 'planAssumptionView', list: 'listPlanAssumptions', member: 'assumptions', record: { assumption_id: 'a-2', status: 'unchecked' } },
	{ name: 'full reference pattern', op: 'planPatternView', list: 'listPlanReferencePatterns', member: 'reference_patterns', record: patternFull },
	{ name: 'minimal reference pattern takes defaults', op: 'planPatternView', list: 'listPlanReferencePatterns', member: 'reference_patterns', record: { pattern_id: 'p-2', status: 'proposed' } },
];

/** `planListPath` / `planItemPath` inputs (through listFreshUserPlanRecords / getFreshUserPlan / getUserPlan). */
export const pathCases: Array<{ name: string; op: 'planListPath' | 'planItemPath'; filters?: Plans.ListUserPlansFilters; planId?: string; teamId?: string | null }> = [
	{ name: 'no filters', op: 'planListPath', filters: {} },
	{ name: 'every filter', op: 'planListPath', filters: { status: 'active', chatId: 'chat a&b', projectId: 'p/1', activeOnly: false, limit: 20 } },
	{ name: 'filters with a Team', op: 'planListPath', filters: { activeOnly: true }, teamId: 'team a' },
	{ name: 'Team without filters', op: 'planListPath', filters: {}, teamId: 'team-1' },
	{ name: 'empty filter strings are skipped', op: 'planListPath', filters: { status: '' as never, chatId: '', limit: 0 } },
	{ name: 'item path is encoded', op: 'planItemPath', planId: 'plan/1 ü', teamId: null },
	{ name: 'item path with a Team', op: 'planItemPath', planId: 'plan-1', teamId: 'team-1' },
];

/** One request-body case: the service call and the op input the flag-on branch sends. */
export interface BodyCase {
	name: string;
	op: string;
	reply: Record<string, unknown>;
	run: (service: PlanService, plan: View) => Promise<unknown>;
	input: (plan: View) => Record<string, unknown>;
	/** The page input `encrypt_input` steps stringify. */
	source: (plan: View) => Record<string, unknown>;
}

const facts = (plan: View, hasMaster = true) => ({
	plan_id: plan.plan_id, version: plan.version, primaryChatId: plan.primaryChatId, linkedProjectIds: plan.linkedProjectIds, has_master_wrapper: hasMaster,
});
const withoutMaster = (plan: View): View => ({ ...plan, encrypted: { ...plan.encrypted, key_wrappers: [] } });
const at = NOW_SECONDS;

function create(name: string, input: Plans.CreateUserPlanInput): BodyCase {
	return { name, op: 'planCreateBody', reply: { plan: planRecord() }, run: (s) => s.createUserPlan(input),
		input: () => ({ input, plan_id: FRESH_ID, timestamp: at }), source: () => input as never };
}
function update(name: string, patch: Record<string, unknown>, hasMaster = true): BodyCase {
	const target = (plan: View) => (hasMaster ? plan : withoutMaster(plan));
	return { name, op: 'planUpdateBody', reply: { plan: planRecord({ version: 2 }) }, run: (s, plan) => s.updateUserPlan(target(plan), patch as never),
		input: (plan) => ({ plan_id: plan.plan_id, plan: facts(plan, hasMaster), patch, timestamp: at }), source: () => patch };
}
function child(name: string, op: string, reply: Record<string, unknown>, input: Record<string, unknown>, run: BodyCase['run'], extra: Record<string, unknown> = {}): BodyCase {
	return { name, op, reply, run, input: (plan) => ({ plan_id: plan.plan_id, ...extra, input, timestamp: at }), source: () => input };
}

const criterionInput = { text: 'Must log in', type: 'functional', verificationIds: ['v-1'], linkedTaskIds: ['t-1'] };
const verificationTask = { kind: 'e2e', title: 'Login works', command: 'npm test', createTask: true, linkedProjectIds: ['project-b'], covers: ['c-1'], threshold: 0.5 };

export const bodyCases: BodyCase[] = [
	create('create normalizes linked projects and wraps for chat and projects', {
		title: 'Ship', goal: 'Goal', scopeIn: 'In', userFlows: [validFlow], assumptions: 'A', status: 'active',
		linkedProjectIds: [' project-a ', 'project-b', 'project-a', ''], primaryChatId: 'chat-a', plannerFocusId: 'focus-1',
	}),
	create('create with only the required members', { title: 'T', goal: 'G', linkedProjectIds: ['project-a'] }),
	create('create without a Project is refused', { title: 'T', goal: 'G', linkedProjectIds: ['  '] }),
	create('create with an invalid flow is refused', { title: 'T', goal: 'G', linkedProjectIds: ['project-a'], userFlows: [{ flow_id: 'f' }] as never }),
	update('update encrypts only the defined patch members', { title: 'New title', risks: '', status: 'active', plannerFocusId: 'focus-2' }),
	update('update of links and flows re-wraps with the current chat', { linkedProjectIds: ['project-b'], userFlows: [validFlow] }),
	update('update clearing the chat re-wraps without a chat wrapper', { primaryChatId: null }),
	update('update of links without a master wrapper is refused', { primaryChatId: 'chat-b' }, false),
	update('update with null flows is refused', { userFlows: null }),
	{ name: 'activate', op: 'planActivateBody', reply: { plan: planRecord({ status: 'active' }) }, run: (s, plan) => s.activateUserPlan(plan),
		input: (plan) => ({ plan_id: plan.plan_id, plan: facts(plan), timestamp: at }), source: () => ({}) },
	{ name: 'complete with a note', op: 'planCompleteBody', reply: { plan: planRecord({ status: 'completed' }) }, run: (s, plan) => s.completeUserPlan(plan, 'All done'),
		input: (plan) => ({ plan_id: plan.plan_id, plan: facts(plan), completion_note: 'All done', timestamp: at }), source: () => ({}) },
	{ name: 'complete without a note drops the member', op: 'planCompleteBody', reply: { plan: planRecord({ status: 'completed' }) }, run: (s, plan) => s.completeUserPlan(plan),
		input: (plan) => ({ plan_id: plan.plan_id, plan: facts(plan), timestamp: at }), source: () => ({}) },
	child('criterion with verifications is covered', 'planCriterionCreateBody', { criterion: criterionFull }, criterionInput,
		(s, plan) => s.createPlanCriterion(plan, criterionInput), { fresh_id: FRESH_ID }),
	child('criterion with an id and no verifications is uncovered', 'planCriterionCreateBody', { criterion: { criterion_id: 'c-9', status: 'pending' } },
		{ criterionId: 'c-9', text: 'x', required: false, verificationIds: [] }, (s, plan) => s.createPlanCriterion(plan, { criterionId: 'c-9', text: 'x', required: false, verificationIds: [] }), { fresh_id: FRESH_ID }),
	child('criterion update', 'planCriterionUpdateBody', { criterion: criterionFull }, { status: 'waived', waiverReason: 'Out of scope', verificationScope: 'unit' },
		(s, plan) => s.updatePlanCriterion(plan, 'c-1', { status: 'waived', waiverReason: 'Out of scope', verificationScope: 'unit' }), { criterion_id: 'c-1' }),
	{ name: 'verification with a task seals title and links with the task key', op: 'planVerificationCreateBody', reply: { verification: verificationFull },
		run: (s, plan) => s.createPlanVerification(plan, verificationTask),
		input: (plan) => ({ plan_id: plan.plan_id, plan: facts(plan), input: verificationTask, fresh_id: FRESH_ID, timestamp: at }), source: () => verificationTask },
	{ name: 'verification without a task uses the plan key', op: 'planVerificationCreateBody', reply: { verification: { verification_id: 'v-3', kind: 'manual', status: 'pending' } },
		run: (s, plan) => s.createPlanVerification(plan, { kind: 'manual', verificationId: 'v-3' }),
		input: (plan) => ({ plan_id: plan.plan_id, plan: facts(plan), input: { kind: 'manual', verificationId: 'v-3' }, fresh_id: FRESH_ID, timestamp: at }),
		source: () => ({ kind: 'manual', verificationId: 'v-3' }) },
	child('verification evidence', 'planEvidenceBody', { verification: verificationFull }, { status: 'failed', score: 0.2, resultSummary: 'Broke', runId: 'run-2' },
		(s, plan) => s.addPlanVerificationEvidence(plan, 'v-1', { status: 'failed', score: 0.2, resultSummary: 'Broke', runId: 'run-2' }), { verification_id: 'v-1' }),
	child('assumption with every member', 'planAssumptionCreateBody', { assumption: assumptionFull },
		{ text: 'API is v2', category: 'api', linkedCriterionIds: ['c-1'], sourceCount: 2, sources: '[1]', blockerReason: 'none' },
		(s, plan) => s.createPlanAssumption(plan, { text: 'API is v2', category: 'api', linkedCriterionIds: ['c-1'], sourceCount: 2, sources: '[1]', blockerReason: 'none' }), { fresh_id: FRESH_ID }),
	child('assumption with defaults', 'planAssumptionCreateBody', { assumption: { assumption_id: 'a-3', status: 'unchecked' } }, { text: 'x', assumptionId: 'a-3' },
		(s, plan) => s.createPlanAssumption(plan, { text: 'x', assumptionId: 'a-3' }), { fresh_id: FRESH_ID }),
	child('assumption update', 'planAssumptionUpdateBody', { assumption: assumptionFull }, { status: 'confirmed', linkedTaskId: null, correctedText: 'v3', sourceCount: 0 },
		(s, plan) => s.updatePlanAssumption(plan, 'a-1', { status: 'confirmed', linkedTaskId: null, correctedText: 'v3', sourceCount: 0 }), { assumption_id: 'a-1' }),
	child('reference pattern with every member', 'planPatternCreateBody', { reference_pattern: patternFull },
		{ title: 'Card layout', description: 'Grid', linkedCheckIds: ['v-1'], matchRules: 'rules', status: 'confirmed' },
		(s, plan) => s.createPlanReferencePattern(plan, { title: 'Card layout', description: 'Grid', linkedCheckIds: ['v-1'], matchRules: 'rules', status: 'confirmed' }), { fresh_id: FRESH_ID }),
	child('reference pattern with defaults', 'planPatternCreateBody', { reference_pattern: { pattern_id: 'p-3', status: 'proposed' } }, { title: 'T', patternId: 'p-3' },
		(s, plan) => s.createPlanReferencePattern(plan, { title: 'T', patternId: 'p-3' }), { fresh_id: FRESH_ID }),
];
