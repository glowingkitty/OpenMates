/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Chat settings active Plan panel.
 *
 * Real stack: a Plan, one assumption and one Task are created through the CLI
 * (encrypted, like production), the Plan is linked to a real chat, and the
 * chat settings Plan tab must show status, the Task and the assumption.
 */
export {};

const { expect, test } = require('./helpers/cookie-audit');
const { dismissSecurityReminderIfPresent, sendMessage, startNewChat, waitForAssistantMessage } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount, withMockMarker } = require('./signup-flow-helpers');
const { deriveApiUrl, runCli } = require('./helpers/cli-test-helpers');
const { createWorkflowCliHome, loginWorkflowCliViaPair, removeWorkflowCliHome, workflowCliEnv } = require('./helpers/workflow-cli-e2e-helpers');
const { naturalProjectName } = require('./helpers/project-names');
const { closeSettingsPanel } = require('./helpers/settings-readiness');

test.describe('Chat settings active Plan', () => {
	// contract-test: supporting surface=gui.web assertions=plans.chat-settings.active-plan
	test('shows the chat Plan status, linked Task and assumption', async ({ page }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:tasks', 'platform:plans', 'platform:projects']);

		const log = createSignupLogger('CHAT_SETTINGS_ACTIVE_PLAN');
		const screenshot = createStepScreenshotter(log, { filenamePrefix: 'chat-settings-active-plan' });
		const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const home = createWorkflowCliHome('chat-active-plan');
		const env = workflowCliEnv(apiUrl, home);
		const cli = async (args: string[]) => {
			const result = await runCli(apiUrl, [...args, '--json'], 120_000, { useApiKey: false, env });
			expect(result.code, `${args.join(' ')}: ${result.stderr}`).toBe(0);
			return JSON.parse(result.stdout);
		};
		const planTitle = 'Launch the neighbourhood bakery';
		const taskTitle = 'Order the sourdough starter';
		const assumptionText = 'The landlord allows early morning deliveries';
		let projectId = '';
		let planId = '';

		try {
			// The pair-login helper logs the browser in first, then pairs the CLI.
			await loginWorkflowCliViaPair(page, apiUrl, home, 'chat-active-plan');

			await dismissSecurityReminderIfPresent(page, log);
			await closeSettingsPanel(page, test.info());

			// The browser sends the first turn (committed instant fixture; the Plan is
			// the subject, not the reply), then the paired CLI creates the Plan linked
			// to that chat. A draft Plan is shown; activation needs approval first.
			await startNewChat(page, log);
			await sendMessage(page, withMockMarker('A stable chat for plan settings.', 'chat_flow_capital', 'instant'), log, screenshot, 'plan-chat');
			await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 30_000 });
			await waitForAssistantMessage(page, { which: 'last', timeout: 90_000, logCheckpoint: log });
			const chatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? '';
			if (!chatId) throw new Error('Browser chat URL is missing chat-id');

			const project = await cli(['projects', 'create', naturalProjectName('Bakery business plan'), '--write-policy', 'apply_and_show']);
			projectId = project.projectId ?? project.project_id ?? project.project?.project_id;
			const plan = await cli(['plans', 'create', '--title', planTitle, '--goal', 'Open the bakery in spring', '--project', projectId, '--chat', chatId]);
			planId = plan.plan.plan_id;
			await cli(['plans', 'assumptions', 'create', planId, '--text', assumptionText]);
			// Slugs are unique per account; a retry on the same account needs a new one.
			const createdTask = await cli(['plans', 'tasks', 'create', planId, '--title', taskTitle, '--slug', `order-sourdough-starter-${planId.slice(0, 8)}`, '--assign', 'user']);
			console.log('[CHAT_SETTINGS_ACTIVE_PLAN] created task', JSON.stringify(createdTask).slice(0, 400));

			await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}&settings=chats/${chatId}/plan`), { waitUntil: 'domcontentloaded' });
			const settingsMenu = page.getByTestId('settings-menu');
			await expect(settingsMenu.getByTestId('chat-settings-tabpanel-plan')).toBeVisible({ timeout: 30_000 });
			const row = settingsMenu.getByTestId('chat-settings-plan-row').filter({ hasText: planTitle });
			await expect(row).toBeVisible({ timeout: 30_000 });

			const panel = settingsMenu.locator(`[data-testid="chat-active-plan-panel"][data-plan-id="${planId}"]`);
			await expect(panel).toBeVisible({ timeout: 30_000 });
			await expect(settingsMenu.getByTestId('chat-settings-plan-row').first()).toContainText(/draft|active|approved|in progress/i);
			await expect(panel.getByTestId('chat-active-plan-task').filter({ hasText: taskTitle })).toBeVisible({ timeout: 30_000 });
			await expect(panel.getByTestId('chat-active-plan-assumption').filter({ hasText: assumptionText })).toBeVisible({ timeout: 30_000 });
			await screenshot(page, 'chat-settings-active-plan');

			await panel.getByTestId('chat-active-plan-open').click();
			await expect(page).toHaveURL(new RegExp(`#plan-id=${planId}`));
			await expect(page.getByTestId('plan-detail-page')).toBeVisible({ timeout: 30_000 });
		} finally {
			if (planId) await runCli(apiUrl, ['plans', 'delete', planId, '--confirm', '--json'], 60_000, { useApiKey: false, env }).catch(() => null);
			if (projectId) await runCli(apiUrl, ['projects', 'delete', projectId, '--confirm', projectId, '--json'], 60_000, { useApiKey: false, env }).catch(() => null);
			removeWorkflowCliHome(home);
		}
	});
});
