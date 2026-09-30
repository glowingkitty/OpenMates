/* eslint-disable @typescript-eslint/no-require-imports */
/** CLI authoring guards that require no paid inference in isolated CI. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const {
	createWorkflowCliHome,
	loginWorkflowCliViaPair,
	removeWorkflowCliHome,
	runWorkflowCliJson,
	workflowApiUrl
} = require('./helpers/workflow-cli-e2e-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.describe('CLI natural-language workflow guards', () => {
	test.setTimeout(180_000);

	// contract-test: direct surface=cli assertions=workflows.actions.skill-contract,workflows.schedule.edge-cases
	test('asks for clarification instead of silently substituting an unavailable skill or schedule', async ({ page }: { page: any }) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		const apiUrl = workflowApiUrl();
		const homeDir = createWorkflowCliHome('workflow-nl-guards');
		try {
			await loginWorkflowCliViaPair(page, apiUrl, homeDir, 'CLI_WORKFLOW_NL_GUARDS');
			const before = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'list'], 'list workflows before natural-language guards');
			for (const instruction of [
				'Every Tuesday at 10 UTC, search the web for new W3C accessibility guidance and send three source links to my chat.',
				'Every other Monday at 10 UTC, search news for W3C accessibility updates and send the results to my chat.'
			]) {
				const session = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'input', instruction], 'guard natural-language workflow');
				expect(session.status).toBe('needs_clarification');
				expect(session.workflow).toBeFalsy();
			}
			const after = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'list'], 'list workflows after natural-language guards');
			expect(after.map((workflow: any) => workflow.id)).toEqual(before.map((workflow: any) => workflow.id));
		} finally {
			removeWorkflowCliHome(homeDir);
		}
	});
});
