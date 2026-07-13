/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * CLI Workflow search and control-flow E2E.
 *
 * Exercises shared Workflow capabilities plus If, For every, Repeat until, and
 * Wait controls through real CLI-created YAML.
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
	waitForWorkflowRunStatus,
	workflowApiUrl,
	writeWorkflowYaml
} = require('./helpers/workflow-cli-e2e-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.describe('CLI Workflows search skills and controls', () => {
	test.setTimeout(420_000);

	test('runs search skills and persists inspectable control-step results', async ({ page }: { page: any }) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const apiUrl = workflowApiUrl();
		const homeDir = createWorkflowCliHome('workflow-controls');
		let workflowId: string | undefined;
		try {
			await loginWorkflowCliViaPair(page, apiUrl, homeDir, 'CLI_WORKFLOW_CONTROLS');
			const yamlFile = writeWorkflowYaml(homeDir, 'search-controls.yml', `
title: ${uniqueWorkflowName('E2E search controls workflow')}
description: Search skills and plain-language controls.
start_when:
  manual: {}
steps:
  - id: web
    use_app_skill: web.search
    input:
      requests:
        - query: OpenMates
          count: 1
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
  - id: gate
    if:
      left: 1
      op: gte
      right: 0
    if_true:
      - id: wait
        wait:
          seconds: 1
      - id: each
        for_every:
          items:
            - one
            - two
          as: item
          max_iterations: 2
          do:
            - id: each_notify
              send_notification:
                title: "Workflow item"
                body: "Item processed"
      - id: repeat
        repeat_until:
          condition:
            left: 1
            op: eq
            right: 1
          max_iterations: 1
          do:
            - id: repeat_notify
              send_notification:
                title: "Workflow repeat"
                body: "Repeat processed"
    if_false: []
`);

			const created = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'create', '--file', yamlFile], 'create search controls workflow');
			workflowId = created.workflow.id;
			expect(created.validation.enable_ready).toBe(true);
			await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'enable', workflowId], 'enable search controls workflow');
			const acceptedRun = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'run', workflowId, '--idempotency-key', `${workflowId}-manual`], 'run search controls workflow', 150_000);
			const completedRun = await waitForWorkflowRunStatus(apiUrl, homeDir, workflowId, acceptedRun.id, ['completed'], 'search controls workflow', 240_000);

			const nodeIds = completedRun.node_runs.map((node: any) => node.node_id);
			expect(nodeIds).toEqual(expect.arrayContaining(['web', 'news', 'events', 'gate', 'wait', 'each', 'repeat']));
			expect(completedRun.node_runs.find((node: any) => node.node_id === 'gate')?.output_summary?.matched).toBe(true);
			expect(completedRun.node_runs.find((node: any) => node.node_id === 'wait')?.output_summary?.waited).toBe(true);
			expect(completedRun.node_runs.find((node: any) => node.node_id === 'each')?.output_summary?.mode).toBe('for_every');
			expect(completedRun.node_runs.find((node: any) => node.node_id === 'repeat')?.output_summary?.mode).toBe('repeat_until');
		} finally {
			await deleteWorkflowQuietly(apiUrl, homeDir, workflowId);
			removeWorkflowCliHome(homeDir);
		}
	});
});
