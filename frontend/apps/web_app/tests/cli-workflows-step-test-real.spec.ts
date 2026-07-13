/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * CLI Workflow real step-test E2E.
 *
 * Verifies disabled workflows can still run confirmed individual action tests
 * through real app-skill/action adapters and persist step_test run history.
 */
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

test.describe('CLI Workflows real step tests', () => {
	test.setTimeout(420_000);

	test('runs real app-skill and side-effect step tests for a disabled Workflow', async ({ page }: { page: any }) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const apiUrl = workflowApiUrl();
		const homeDir = createWorkflowCliHome('workflow-step-test');
		let workflowId: string | undefined;
		try {
			await loginWorkflowCliViaPair(page, apiUrl, homeDir, 'CLI_WORKFLOW_STEP_TEST');
			const chatTitle = uniqueWorkflowName('Workflow step-test chat');
			const yamlFile = writeWorkflowYaml(homeDir, 'step-test.yml', `
title: ${uniqueWorkflowName('E2E step-test workflow')}
description: Real individual action-test coverage.
start_when:
  manual: {}
steps:
  - id: web
    use_app_skill: web.search
    input:
      requests:
        - query: OpenMates
          count: 1
  - id: weather
    use_app_skill: weather.forecast
    input: {}
  - id: news
    use_app_skill: news.search
    input:
      requests:
        - query: OpenMates
          count: 1
  - id: events
    use_app_skill: events.search
    input:
      requests:
        - query: AI meetup
          location: Berlin
          count: 1
  - id: ai
    use_app_skill: ai.ask
    input:
      prompt: "Reply with exactly: step test ok"
  - id: notify
    send_notification:
      title: "Workflow step test"
      body: "Notification step test"
  - id: chat
    send_chat_message:
      title: "${chatTitle}"
      message: "Chat step test"
`);

			const created = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'create', '--file', yamlFile], 'create step-test workflow');
			workflowId = created.workflow.id;
			expect(created.workflow.enabled).toBe(false);
			expect(created.validation.enable_ready).toBe(false);

			const weatherRun = await runWorkflowCliJson(
				apiUrl,
				homeDir,
				['workflows', 'step-test', workflowId, 'weather', '--input', JSON.stringify({ location: 'Berlin', days: 1 }), '--yes'],
				'weather step-test',
				120_000
			);
			expect(weatherRun.trigger_type).toBe('step_test');
			expect(weatherRun.status).toBe('completed');
			expect(weatherRun.node_runs[0].node_id).toBe('weather');

			for (const stepId of ['web', 'news', 'events', 'ai']) {
				const run = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'step-test', workflowId, stepId, '--yes'], `${stepId} step-test`, 150_000);
				expect(run.trigger_type).toBe('step_test');
				expect(run.status).toBe('completed');
				expect(run.node_runs[0].node_id).toBe(stepId);
			}

			const unconfirmedNotification = await runWorkflowCli(apiUrl, homeDir, ['workflows', 'step-test', workflowId, 'notify', '--json'], 30_000);
			expect(unconfirmedNotification.code).not.toBe(0);
			expect(`${unconfirmedNotification.stdout}\n${unconfirmedNotification.stderr}`).toMatch(/CONFIRMATION|409|confirm/i);

			const notificationRun = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'step-test', workflowId, 'notify', '--yes'], 'notification step-test');
			expect(notificationRun.status).toBe('completed');

			const chatRun = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'step-test', workflowId, 'chat', '--yes'], 'chat step-test');
			expect(chatRun.status).toBe('completed');
			expect(chatRun.node_runs[0].output_summary.status).toBe('delivery_pending');

			const runs = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'runs', workflowId], 'list step-test runs');
			expect(runs.filter((run: any) => run.trigger_type === 'step_test').length).toBeGreaterThanOrEqual(7);
		} finally {
			await deleteWorkflowQuietly(apiUrl, homeDir, workflowId);
			removeWorkflowCliHome(homeDir);
		}
	});
});
