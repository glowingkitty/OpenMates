/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * CLI Workflow rain E2E.
 *
 * Covers the CLI-first YAML lifecycle against the deployed dev backend:
 * validate, create disabled draft, reject disabled run, update, enable, run,
 * inspect, disable, and delete.
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
	waitForWorkflowRunStatus,
	workflowApiUrl,
	writeWorkflowYaml
} = require('./helpers/workflow-cli-e2e-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.describe('CLI Workflows rain YAML lifecycle', () => {
	test.setTimeout(360_000);

	test('validates, saves, enables, runs, inspects, disables, and deletes a real rain workflow', async ({ page }: { page: any }) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const apiUrl = workflowApiUrl();
		const homeDir = createWorkflowCliHome('workflow-rain');
		let workflowId: string | undefined;
		let cancelWorkflowId: string | undefined;
		try {
			await loginWorkflowCliViaPair(page, apiUrl, homeDir, 'CLI_WORKFLOW_RAIN');
			const capabilities = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'capabilities'], 'workflow capabilities');
			expect(capabilities.map((capability: any) => capability.id)).toEqual(expect.arrayContaining(['manual_trigger', 'schedule_trigger', 'app_skill_action', 'decision', 'weather.forecast']));

			const weatherHelp = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'help-app', 'weather.forecast'], 'weather help');
			expect(weatherHelp.id).toBe('weather.forecast');
			expect(weatherHelp.enabled).toBe(true);

			const initialList = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'list'], 'initial workflow list');
			expect(Array.isArray(initialList)).toBe(true);

			const title = uniqueWorkflowName('E2E rain workflow');
			const incompleteYaml = writeWorkflowYaml(homeDir, 'rain-incomplete.yml', `
title: ${title}
description: Daily rain check created by CLI E2E.
start_when:
  schedule:
    type: daily
    time: "07:00"
    timezone: Europe/Berlin
steps:
  - id: forecast
    use_app_skill: weather.forecast
    input: {}
  - id: notify
    send_notification:
      title: "Rain check"
      body: "Weather step finished"
`);

			const validation = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'validate', '--file', incompleteYaml], 'validate incomplete');
			expect(validation.draft_valid).toBe(true);
			expect(validation.enable_ready).toBe(false);
			expect(validation.diagnostics.some((item: any) => item.step_id === 'forecast' && item.field === 'location')).toBe(true);

			const created = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'create', '--file', incompleteYaml], 'create incomplete');
			workflowId = created.workflow.id;
			expect(created.workflow.enabled).toBe(false);
			expect(created.validation.enable_ready).toBe(false);

			const disabledRun = await runWorkflowCli(apiUrl, homeDir, ['workflows', 'run', workflowId, '--idempotency-key', `${workflowId}-disabled`, '--json'], 30_000);
			expect(disabledRun.code).not.toBe(0);
			expect(`${disabledRun.stdout}\n${disabledRun.stderr}`).toMatch(/WORKFLOW_DISABLED|409|disabled/i);

			const completeYaml = writeWorkflowYaml(homeDir, 'rain-complete.yml', `
title: ${title}
description: Daily rain check created by CLI E2E.
start_when:
  schedule:
    type: daily
    time: "07:00"
    timezone: Europe/Berlin
steps:
  - id: forecast
    use_app_skill: weather.forecast
    input:
      location: Berlin
      days: 1
  - id: check
    if:
      left: 1
      op: gte
      right: 0
    if_true:
      - id: notify
        send_notification:
          title: "Rain check"
          body: "Weather step finished"
    if_false: []
`);

			const updated = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'update', workflowId, '--file', completeYaml], 'update complete');
			expect(updated.validation.enable_ready).toBe(true);

			const enabled = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'enable', workflowId], 'enable workflow');
			expect(enabled.enabled).toBe(true);
			const shown = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'show', workflowId], 'show workflow');
			expect(shown.id).toBe(workflowId);
			expect(shown.enabled).toBe(true);

			const acceptedRun = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'run', workflowId, '--idempotency-key', `${workflowId}-manual`], 'run workflow');
			expect(acceptedRun.status).toMatch(/queued|running|completed/);
			const completedRun = await waitForWorkflowRunStatus(apiUrl, homeDir, workflowId, acceptedRun.id, ['completed'], 'rain workflow');
			expect(completedRun.node_runs.map((node: any) => node.node_id)).toContain('forecast');
			const notifyRun = completedRun.node_runs.find((node: any) => node.node_id === 'notify');
			expect(notifyRun, `notification branch was not recorded: ${JSON.stringify(completedRun.node_runs)}`).toBeTruthy();
			expect(
				notifyRun.status === 'completed' ||
					(notifyRun.status === 'skipped' && ['push_notifications_not_enabled', 'push_subscription_not_configured'].includes(notifyRun.skipped_reason))
			).toBe(true);
			expect(completedRun.cost_summary || {}).toBeTruthy();

			const runs = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'runs', workflowId], 'list workflow runs');
			expect(runs.some((run: any) => run.id === acceptedRun.id)).toBe(true);

			const disabled = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'disable', workflowId], 'disable workflow');
			expect(disabled.enabled).toBe(false);
			const deleted = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'delete', workflowId, '--yes'], 'delete workflow');
			expect(deleted.deleted).toBe(true);
			workflowId = undefined;

			const cancelYaml = writeWorkflowYaml(homeDir, 'cancel-wait.yml', `
title: ${uniqueWorkflowName('E2E cancel workflow')}
description: Waiting Workflow used to verify run-cancel.
start_when:
  manual: {}
steps:
  - id: ask
    ask_for_user_input:
      prompt: "Should this run be cancelled?"
      input_schema:
        type: object
        properties:
          answer:
            type: string
        required:
          - answer
      timeout_seconds: 600
`);
			const cancelCreated = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'create', '--file', cancelYaml], 'create cancel workflow');
			cancelWorkflowId = cancelCreated.workflow.id;
			expect(cancelCreated.validation.enable_ready).toBe(true);
			await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'enable', cancelWorkflowId], 'enable cancel workflow');
			const cancelAcceptedRun = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'run', cancelWorkflowId, '--idempotency-key', `${cancelWorkflowId}-cancel`], 'run cancel workflow');
			await waitForWorkflowRunStatus(apiUrl, homeDir, cancelWorkflowId, cancelAcceptedRun.id, ['waiting'], 'cancel workflow');
			const cancelled = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'run-cancel', cancelWorkflowId, cancelAcceptedRun.id], 'cancel workflow run');
			expect(cancelled.run_id).toBe(cancelAcceptedRun.id);
			expect(cancelled.status).toBe('cancellation_requested');
			const deletedCancel = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'delete', cancelWorkflowId, '--yes'], 'delete cancel workflow');
			expect(deletedCancel.deleted).toBe(true);
			cancelWorkflowId = undefined;
		} finally {
			await deleteWorkflowQuietly(apiUrl, homeDir, workflowId);
			await deleteWorkflowQuietly(apiUrl, homeDir, cancelWorkflowId);
			removeWorkflowCliHome(homeDir);
		}
	});
});
