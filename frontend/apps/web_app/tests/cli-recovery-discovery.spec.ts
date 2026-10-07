/* eslint-disable @typescript-eslint/no-require-imports */
/** Cold, noninteractive CLI sync must finish typed recovery discovery without inference. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { runCli } = require('./helpers/cli-test-helpers');
const { installRecorderDeps } = require('./cli-tui-proof-helpers');
const {
	clearWorkflowCliSyncCache, createWorkflowCliHome, loginWorkflowCliViaPair,
	removeWorkflowCliHome, workflowApiUrl, workflowCliEnv
} = require('./helpers/workflow-cli-e2e-helpers');

const { email, password, otpKey } = getTestAccount();

// contract-test: direct surface=cli assertions=chats.sync.key-gated-recovery,chats.completion.recovery-takeover
test('noninteractive cold chats list completes recovery discovery', async ({ page }: { page: any }, testInfo: any) => {
	test.setTimeout(300_000);
	test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
		|| process.env.CI_TEST_MODE !== 'e2e',
		'Requires the isolated GitHub product stack');
	skipWithoutCredentials(test, email, password, otpKey);
	const apiUrl = workflowApiUrl();
	const home = createWorkflowCliHome('recovery-discovery');
	let draftChatId = '';
	const quietJson = async (args: string[]) => {
		const result = await runCli(apiUrl, [...args, '--json'], 60_000, {
			useApiKey: false, record: false, env: workflowCliEnv(apiUrl, home)
		});
		expect(result.code, `CLI fixture command failed: ${result.stderr}`).toBe(0);
		return JSON.parse(result.stdout);
	};
	try {
		await loginWorkflowCliViaPair(page, apiUrl, home, 'CLI_RECOVERY_DISCOVERY');
		const draft = await quietJson(['drafts', 'create', 'Cold recovery discovery fixture']);
		draftChatId = draft.chatId;
		expect(draft.encryptedDraftMd).not.toContain(draft.markdown);
		clearWorkflowCliSyncCache(home);

		// chats list has no --refresh flag: removing its cache forces a new WebSocket sync.
		installRecorderDeps();
		const result = await runCli(apiUrl, ['chats', 'list', '--limit', '100', '--json'], 120_000, {
			useApiKey: false,
			env: { ...workflowCliEnv(apiUrl, home), OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: 'cli-recovery-discovery' }
		});
		expect(result.code, `Cold CLI sync failed. stdout: ${result.stdout.slice(-2000)}\nstderr: ${result.stderr.slice(-2000)}`).toBe(0);
		const listed = JSON.parse(result.stdout);
		expect(listed.error).toBeUndefined();
		expect(Array.isArray(listed.chats)).toBe(true);
		expect(listed.chats.some((chat: { id: string }) => chat.id === draftChatId)).toBe(true);
		expect(result.recording?.videoPath).toBeTruthy();
		await testInfo.attach('cold-cli-recovery-discovery', {
			path: result.recording.videoPath, contentType: 'video/mp4'
		});
	} finally {
		if (draftChatId) await quietJson(['drafts', 'clear', draftChatId]).catch(() => undefined);
		removeWorkflowCliHome(home);
	}
});
