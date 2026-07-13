/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * CLI Workflow AI, chat delivery, and user-input E2E.
 *
 * Keeps a browser device online so Workflow pending chat delivery can be claimed
 * and encrypted by a real client while all Workflow commands run through the CLI.
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
	waitForChatTitle,
	waitForWorkflowRunStatus,
	workflowApiUrl,
	writeWorkflowYaml
} = require('./helpers/workflow-cli-e2e-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.describe('CLI Workflows AI, chat, and user input', () => {
	test.setTimeout(420_000);

	test('runs AI mode, delivers chat through a client claim, waits, and resumes through CLI respond', async ({ page }: { page: any }) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const apiUrl = workflowApiUrl();
		const homeDir = createWorkflowCliHome('workflow-ai-chat');
		let workflowId: string | undefined;
		try {
			await loginWorkflowCliViaPair(page, apiUrl, homeDir, 'CLI_WORKFLOW_AI_CHAT');
			const title = uniqueWorkflowName('E2E AI chat workflow');
			const chatTitle = uniqueWorkflowName('Workflow chat delivery');
			const yamlFile = writeWorkflowYaml(homeDir, 'ai-chat.yml', `
title: ${title}
description: AI, pending chat delivery, and user-input wait coverage.
start_when:
  manual: {}
steps:
  - id: ask_ai
    use_app_skill: ai.ask
    input:
      prompt: "Reply with exactly: Workflow AI OK"
      conversation: e2e-local
  - id: chat
    send_chat_message:
      title: "${chatTitle}"
      message: "Workflow delivery from CLI E2E"
  - id: ask_user
    ask_for_user_input:
      prompt: "Which city should this Workflow use next?"
      input_schema:
        type: object
        properties:
          city:
            type: string
        required:
          - city
`);

			const created = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'create', '--file', yamlFile], 'create AI chat workflow');
			workflowId = created.workflow.id;
			expect(created.validation.enable_ready).toBe(true);
			await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'enable', workflowId], 'enable AI chat workflow');

			const acceptedRun = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'run', workflowId, '--idempotency-key', `${workflowId}-manual`], 'run AI chat workflow', 120_000);
			const waitingRun = await waitForWorkflowRunStatus(apiUrl, homeDir, workflowId, acceptedRun.id, ['waiting'], 'AI chat workflow', 240_000);
			expect(waitingRun.node_runs.some((node: any) => node.node_id === 'ask_ai' && node.status === 'completed')).toBe(true);
			const chatNode = waitingRun.node_runs.find((node: any) => node.node_id === 'chat');
			expect(chatNode?.output_summary?.status).toBe('delivery_pending');
			expect(chatNode?.output_summary?.delivery_id).toBeTruthy();
			expect(waitingRun.node_runs.find((node: any) => node.node_id === 'ask_user')?.output_summary?.wait_for_user_input).toBe(true);

			await waitForChatTitle(apiUrl, homeDir, chatTitle, 150_000);

			const resumedRun = await runWorkflowCliJson(
				apiUrl,
				homeDir,
				['workflows', 'respond', workflowId, acceptedRun.id, 'ask_user', '--input', JSON.stringify({ city: 'Berlin' })],
				'respond to workflow wait'
			);
			expect(resumedRun.status).toBe('completed');
			expect(resumedRun.output_summary.user_input_response.input.city).toBe('Berlin');
		} finally {
			await deleteWorkflowQuietly(apiUrl, homeDir, workflowId);
			removeWorkflowCliHome(homeDir);
		}
	});
});
