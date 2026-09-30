/* eslint-disable @typescript-eslint/no-require-imports */
/** Opt-in live authoring proof. Run only on dev with a dedicated account slot. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const {
	createWorkflowCliHome,
	deleteWorkflowQuietly,
	loginWorkflowCliViaPair,
	removeWorkflowCliHome,
	runWorkflowCliJson,
	workflowApiUrl
} = require('./helpers/workflow-cli-e2e-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

function authoredWorkflows(session: any): any[] {
	return session.workflows ?? (session.workflow ? [session.workflow] : []);
}

function skillIds(graph: any): string[] {
	return (graph.nodes ?? [])
		.filter((node: any) => node.type === 'app_skill_action')
		.map((node: any) => `${node.config?.app_id}.${node.config?.skill_id}`);
}

function scheduleConfig(graph: any): any {
	const triggers = (graph.nodes ?? []).filter((node: any) => node.type === 'schedule_trigger');
	expect(triggers).toHaveLength(1);
	return triggers[0].config?.schedule;
}

function expectNoUnsupportedDelivery(graph: any): void {
	for (const node of graph.nodes ?? []) {
		expect(String(node.type).toLowerCase()).not.toContain('slack');
		expect(String(node.config?.app_id ?? '').toLowerCase()).not.toBe('slack');
		expect(String(node.config?.destination ?? '').toLowerCase()).not.toBe('slack');
		expect(String(node.config?.destination?.type ?? '').toLowerCase()).not.toBe('slack');
	}
}

function expectExistingWorkflowsUnchanged(before: any[], after: any[]): void {
	const afterById = new Map(after.map((item: any) => [item.id, item]));
	for (const original of before) {
		const current: any = afterById.get(original.id);
		expect(current, `Existing workflow ${original.id} disappeared`).toBeDefined();
		expect(current.current_version_id).toBe(original.current_version_id);
		expect(current.enabled).toBe(original.enabled);
		expect(current.title).toBe(original.title);
	}
}

test.describe('CLI natural-language workflow guards', () => {
	test.setTimeout(180_000);
	test.skip(
		!!process.env.CI || process.env.OPENMATES_WORKFLOW_LIVE_INFERENCE !== '1' || Number(process.env.PLAYWRIGHT_WORKER_SLOT || '0') < 2,
		'Live authoring invokes paid models; run directly on dev with OPENMATES_WORKFLOW_LIVE_INFERENCE=1 and a dedicated PLAYWRIGHT_WORKER_SLOT.'
	);

	// contract-test: direct surface=cli assertions=workflows.authoring.compact-plan,workflows.authoring.provisional-validation,workflows.authoring.atomic-update,workflows.actions.skill-contract
	test('uses registered capabilities and retains only validated disabled prefixes', async ({ page }: { page: any }) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		const apiUrl = workflowApiUrl();
		const homeDir = createWorkflowCliHome('workflow-nl-guards');
		const createdIds = new Set<string>();
		let baselineIds: Set<string> | null = null;
		try {
			await loginWorkflowCliViaPair(page, apiUrl, homeDir, 'CLI_WORKFLOW_NL_GUARDS');
			const before: any[] = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'list'], 'list workflows before natural-language guards');
			baselineIds = new Set(before.map((workflow: any) => workflow.id));
			const reading = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'input',
				'Every Tuesday at 10 UTC, read https://www.w3.org/WAI/standards-guidelines/ and send an accessibility guidance summary to my chat.'
			], 'generic web reading workflow');
			const readingWorkflows = authoredWorkflows(reading);
			for (const workflow of readingWorkflows) if (!baselineIds.has(workflow.id)) createdIds.add(workflow.id);
			expect(['executed', 'draft', 'failed']).toContain(reading.status);
			if (reading.status === 'failed') {
				expect(reading.error_code).toMatch(/^WORKFLOW_INPUT_/);
				expect(readingWorkflows).toHaveLength(0);
			} else {
				expect(readingWorkflows).toHaveLength(1);
				if (reading.status === 'draft') {
					expect(reading.partial_reason).toBe('provider_error');
					expect(reading.partial_warning).toEqual(expect.any(String));
					expect(reading.partial_warning.length).toBeGreaterThan(0);
				}
				const authored = readingWorkflows[0];
				expect(authored.enabled).toBe(false);
				const saved = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'show', authored.id], 'inspect web reading workflow');
				expect(saved.id).toBe(authored.id);
				expect(saved.enabled).toBe(false);
				expectNoUnsupportedDelivery(saved.graph);
				for (const skill of skillIds(saved.graph)) expect(['web.read', 'ai.ask']).toContain(skill);
				if (reading.status === 'executed') {
					expect(skillIds(saved.graph)).toContain('web.read');
					expect(scheduleConfig(saved.graph)).toMatchObject({
						type: 'weekly', time: '10:00', timezone: 'UTC', weekdays: ['tuesday']
					});
				}
			}
			const afterReading: any[] = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'list'], 'list workflows after web reading');
			expectExistingWorkflowsUnchanged(before, afterReading);
			const readingNewIds = new Set(afterReading.filter((workflow: any) => !baselineIds?.has(workflow.id)).map((workflow: any) => workflow.id));
			expect(readingNewIds).toEqual(new Set(readingWorkflows.map((workflow: any) => workflow.id)));
			const spoken = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'input',
				'Every Tuesday at 8 in Madrid—no, make that Thursday at 9 in Lisbon—find local tech meetups and send me a chat summary.'
			], 'spoken correction workflow');
			const spokenWorkflows = authoredWorkflows(spoken);
			for (const workflow of spokenWorkflows) if (!baselineIds.has(workflow.id)) createdIds.add(workflow.id);
			expect(spoken.status).toBe('executed');
			expect(spokenWorkflows).toHaveLength(1);
			const spokenSaved = await runWorkflowCliJson(apiUrl, homeDir,
				['workflows', 'show', spokenWorkflows[0].id], 'inspect spoken correction workflow');
			expect(spokenSaved.enabled).toBe(false);
			expect(scheduleConfig(spokenSaved.graph)).toMatchObject({
				type: 'weekly', time: '09:00', timezone: 'Europe/Lisbon', weekdays: ['thursday']
			});
			expect(skillIds(spokenSaved.graph)).toContain('events.search');
			const eventNodes = (spokenSaved.graph.nodes ?? []).filter((node: any) =>
				node.type === 'app_skill_action' && node.config?.app_id === 'events' && node.config?.skill_id === 'search');
			expect(eventNodes).toHaveLength(1);
			const eventRequests = eventNodes[0].config?.input?.requests;
			expect(eventRequests).toHaveLength(1);
			expect(String(eventRequests[0].location).toLowerCase()).toContain('lisbon');
			expect(String(eventRequests[0].location).toLowerCase()).not.toContain('madrid');
			const afterSpoken: any[] = await runWorkflowCliJson(apiUrl, homeDir,
				['workflows', 'list'], 'list workflows after spoken correction');
			expectExistingWorkflowsUnchanged(afterReading, afterSpoken);
			const spokenNewIds = new Set(afterSpoken.filter((workflow: any) =>
				!afterReading.some((prior: any) => prior.id === workflow.id)).map((workflow: any) => workflow.id));
			expect(spokenNewIds).toEqual(new Set([spokenWorkflows[0].id]));
			const batch = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'input',
				'Create two workflows: send a Berlin weather update to my chat each morning, and post an accessibility news digest to Slack each Friday.'
			], 'atomic mixed-capability workflow batch');
			const batchWorkflows = authoredWorkflows(batch);
			for (const workflow of batchWorkflows) if (!baselineIds.has(workflow.id)) createdIds.add(workflow.id);
			expect(['draft', 'failed']).toContain(batch.status);
			const afterBatch: any[] = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'list'], 'list workflows after mixed batch');
			const afterSpokenIds = new Set(afterSpoken.map((workflow: any) => workflow.id));
			for (const workflow of afterBatch) if (!afterSpokenIds.has(workflow.id)) createdIds.add(workflow.id);
			expectExistingWorkflowsUnchanged(afterSpoken, afterBatch);
			const batchNewIds = new Set(afterBatch.filter((workflow: any) => !afterSpokenIds.has(workflow.id)).map((workflow: any) => workflow.id));
			if (batch.status === 'draft') {
				expect(batch.partial_reason).toBe('provider_error');
				expect(batch.partial_warning).toEqual(expect.any(String));
				expect(batch.partial_warning.length).toBeGreaterThan(0);
				expect(batchWorkflows.length).toBeGreaterThan(0);
				expect(batchNewIds).toEqual(new Set(batchWorkflows.map((workflow: any) => workflow.id)));
				for (const workflow of batchWorkflows) {
					expect(workflow.enabled).toBe(false);
					const saved = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'show', workflow.id], 'inspect partial batch workflow');
					expect(saved.id).toBe(workflow.id);
					expect(saved.enabled).toBe(false);
					expectNoUnsupportedDelivery(saved.graph);
					for (const skill of skillIds(saved.graph)) expect(['weather.rain_radar', 'news.search', 'web.read', 'ai.ask']).toContain(skill);
				}
			} else {
				expect(batch.error_code).toMatch(/^WORKFLOW_INPUT_/);
				expect(batchWorkflows).toHaveLength(0);
				expect(batchNewIds.size).toBe(0);
			}
		} finally {
			try {
				if (baselineIds) {
					try {
						const remaining: any[] = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'list'], 'find disposable workflows for cleanup');
						for (const workflow of remaining) if (!baselineIds.has(workflow.id)) createdIds.add(workflow.id);
					} catch {
						// IDs returned before an assertion failed are still cleaned below.
					}
				}
				for (const id of createdIds) {
					try {
						await deleteWorkflowQuietly(apiUrl, homeDir, id);
					} catch {
						// Browser deletion below can finish cleanup if CLI deletion failed.
					}
				}
				if (baselineIds) {
					let remaining: any[] = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'list'], 'verify disposable workflow cleanup');
					for (const workflow of remaining) {
						if (createdIds.has(workflow.id)) await page.request.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(workflow.id)}`);
					}
					remaining = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'list'], 'verify final disposable workflow cleanup');
					expect(remaining.filter((workflow: any) => createdIds.has(workflow.id))).toHaveLength(0);
				}
			} finally {
				removeWorkflowCliHome(homeDir);
			}
		}
	});
});
