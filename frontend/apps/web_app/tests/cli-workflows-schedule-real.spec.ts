/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * CLI Workflow scheduled execution E2E.
 *
 * Creates a near-future one-time Workflow through the CLI, disconnects from web
 * UI actions, and later inspects the run accepted by the backend scheduler.
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
	runWorkflowCliJson,
	uniqueWorkflowName,
	waitForWorkflowRunListStatus,
	waitForWorkflowRunStatus,
	workflowApiUrl,
	writeWorkflowYaml
} = require('./helpers/workflow-cli-e2e-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.describe('CLI Workflows scheduled execution', () => {
	test.setTimeout(420_000);

	test('creates a one-time scheduled Workflow and inspects the backend-accepted run', async ({ page }: { page: any }) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const apiUrl = workflowApiUrl();
		const homeDir = createWorkflowCliHome('workflow-schedule');
		let workflowId: string | undefined;
		try {
			await loginWorkflowCliViaPair(page, apiUrl, homeDir, 'CLI_WORKFLOW_SCHEDULE');
			const runAt = new Date(Date.now() + 75_000).toISOString();
			const yamlFile = writeWorkflowYaml(homeDir, 'schedule.yml', `
title: ${uniqueWorkflowName('E2E scheduled workflow')}
description: Near-future one-time scheduled Workflow.
start_when:
  schedule:
    type: once
    at: "${runAt}"
steps:
  - id: forecast
    use_app_skill: weather.forecast
    input:
      location: Berlin
      days: 1
`);

			const created = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'create', '--file', yamlFile], 'create scheduled workflow');
			workflowId = created.workflow.id;
			expect(created.validation.enable_ready).toBe(true);
			const enabled = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'enable', workflowId], 'enable scheduled workflow');
			expect(enabled.enabled).toBe(true);

			await page.close();
			const scheduledRun = await waitForWorkflowRunListStatus(apiUrl, homeDir, workflowId, ['queued', 'running', 'completed'], 'scheduled workflow', 240_000);
			const completedRun = scheduledRun.status === 'completed'
				? scheduledRun
				: await waitForWorkflowRunStatus(apiUrl, homeDir, workflowId, scheduledRun.id, ['completed'], 'scheduled workflow completion', 180_000);
			expect(completedRun.trigger_type).toBe('schedule');
			expect(completedRun.node_runs.some((node: any) => node.node_id === 'forecast' && node.status === 'completed')).toBe(true);
		} finally {
			await deleteWorkflowQuietly(apiUrl, homeDir, workflowId);
			removeWorkflowCliHome(homeDir);
		}
	});
});
