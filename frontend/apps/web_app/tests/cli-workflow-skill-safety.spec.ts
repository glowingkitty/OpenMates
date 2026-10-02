/* eslint-disable @typescript-eslint/no-require-imports */
/** Deterministic preflight coverage: no app skill or provider is invoked. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const {
	createWorkflowCliHome,
	deleteWorkflowQuietly,
	loginWorkflowCliViaPair,
	removeWorkflowCliHome,
	runWorkflowCli,
	runWorkflowCliJson,
	uniqueWorkflowName,
	workflowApiUrl,
	writeWorkflowYaml
} = require('./helpers/workflow-cli-e2e-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const UNSUPPORTED_SKILLS = [
	'audio.generate', 'audio.speak', 'images.generate', 'images.generate_draft',
	'music.generate', 'social_media.get-posts',
	'social_media.search', 'videos.generate', 'videos.create', 'openmates.share-usecase'
];
const REPRESENTATIVES = ['images.generate', 'videos.create', 'openmates.share-usecase'];

test.describe('CLI workflow skill safety', () => {
	test.setTimeout(300_000);

	// contract-test: direct surface=cli assertions=workflows.actions.skill-contract,workflows.billing.skill-usage
	test('keeps unsupported skills disabled and rejects saved drafts before dispatch', async ({ page }: { page: any }) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		const apiUrl = workflowApiUrl();
		const homeDir = createWorkflowCliHome('workflow-skill-safety');
		const createdIds: string[] = [];
		try {
			await loginWorkflowCliViaPair(page, apiUrl, homeDir, 'CLI_WORKFLOW_SKILL_SAFETY');
			const beforeAccount = await runWorkflowCliJson(apiUrl, homeDir, ['whoami'], 'credits before blocked workflows');
			expect(typeof beforeAccount.credits).toBe('number');
			expect(Number.isFinite(beforeAccount.credits)).toBe(true);
			const capabilities: any[] = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'capabilities'], 'workflow capabilities');
			const byId = new Map(capabilities.map((capability: any) => [capability.id, capability]));
			for (const skillId of UNSUPPORTED_SKILLS) {
				const capability: any = byId.get(skillId);
				expect(capability, `Missing ${skillId} workflow capability`).toBeDefined();
				expect(capability.enabled, skillId).toBe(false);
				expect(capability.reason, skillId).toBe('WORKFLOW_RUNTIME_UNSUPPORTED');
			}
			// The 3D source classification is guarded even when this runtime does not register the skill.
			const models3d = byId.get('models3d.generate');
			if (models3d) {
				expect(models3d.enabled).toBe(false);
				expect(models3d.reason).toBe('WORKFLOW_RUNTIME_UNSUPPORTED');
			}
			expect(byId.get('images.generate').metadata.workflow.execution_mode).toBe('async_job');
			expect(byId.get('videos.create').metadata.workflow.execution_mode).toBe('sandbox');
			expect(byId.get('openmates.share-usecase').metadata.workflow).toMatchObject({
				approval: 'always', unattended: false
			});

			for (const skillId of REPRESENTATIVES) {
				const example = byId.get(skillId).metadata?.workflow?.test_example_input;
				expect(example, `${skillId} must advertise a test example`).toEqual(expect.any(Object));
				const yamlFile = writeWorkflowYaml(homeDir, `${skillId.replace('.', '-')}.yml`, `
title: ${uniqueWorkflowName(`Blocked ${skillId}`)}
start_when:
  schedule:
    type: daily
    time: "09:00"
    timezone: UTC
steps:
  - id: unsafe
    use_app_skill: ${skillId}
    input: ${JSON.stringify(example)}
`);
				const created = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'create', '--file', yamlFile], `save ${skillId} draft`);
				const workflowId = created.workflow.id;
				createdIds.push(workflowId);
				expect(created.workflow.graph.version).toBe(2);
				expect(created.workflow.enabled).toBe(false);
				expect(created.validation.draft_valid).toBe(true);
				expect(created.validation.enable_ready).toBe(false);
				expect(created.validation.diagnostics).toEqual(expect.arrayContaining([
					expect.objectContaining({
						code: 'WORKFLOW_CAPABILITY_UNAVAILABLE',
						step_id: 'unsafe',
						message: expect.stringContaining('WORKFLOW_RUNTIME_UNSUPPORTED')
					})
				]));

				const enable = await runWorkflowCli(apiUrl, homeDir, ['workflows', 'enable', workflowId, '--json']);
				expect(enable.code, `${skillId} unexpectedly enabled: ${enable.stdout} ${enable.stderr}`).not.toBe(0);
				expect(`${enable.stdout}\n${enable.stderr}`).toMatch(/HTTP 400/);
				const run = await runWorkflowCli(apiUrl, homeDir, [
					'workflows', 'run', workflowId, '--idempotency-key', `${workflowId}-blocked`, '--json'
				]);
				expect(run.code, `${skillId} unexpectedly ran: ${run.stdout} ${run.stderr}`).not.toBe(0);
				expect(`${run.stdout}\n${run.stderr}`).toMatch(/HTTP 400/);
				const stepTest = await runWorkflowCli(apiUrl, homeDir, [
					'workflows', 'step-test', workflowId, 'unsafe', '--yes', '--json'
				]);
				expect(stepTest.code, `${skillId} unexpectedly step-tested: ${stepTest.stdout} ${stepTest.stderr}`).not.toBe(0);
				expect(`${stepTest.stdout}\n${stepTest.stderr}`).toMatch(/HTTP 409/);

				const saved = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'show', workflowId], `inspect ${skillId} draft`);
				expect(saved.enabled).toBe(false);
				const runs: any[] = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'runs', workflowId], `inspect ${skillId} runs`);
				expect(runs).toHaveLength(0);
			}
			const afterAccount = await runWorkflowCliJson(apiUrl, homeDir, ['whoami'], 'credits after blocked workflows');
			expect(typeof afterAccount.credits).toBe('number');
			expect(Number.isFinite(afterAccount.credits)).toBe(true);
			expect(afterAccount.credits).toBe(beforeAccount.credits);
		} finally {
			try {
				for (const workflowId of createdIds) {
					try {
						await deleteWorkflowQuietly(apiUrl, homeDir, workflowId);
					} catch {
						// Preserve the preflight assertion failure if cleanup is unavailable.
					}
				}
			} finally {
				removeWorkflowCliHome(homeDir);
			}
		}
	});
});
