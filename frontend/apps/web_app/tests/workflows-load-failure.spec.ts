/* eslint-disable @typescript-eslint/no-require-imports -- Existing account helpers use CommonJS. */
import { expect, test } from './helpers/cookie-audit';
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');
const { skipIfFeaturesDisabled, skipWithoutCredentials } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

// contract-test: supporting surface=gui.web assertions=workflows-ui.workspace.recommendation-led-composition,notifications.web.stacked-deck
test('workflow load failures leave the workspace clear while the header reports offline status', async ({ page, context }) => {
	test.setTimeout(120_000);
	const credentials = getTestAccount();
	skipWithoutCredentials(test, credentials.email, credentials.password, credentials.otpKey);
	await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
	await loginToTestAccount(page);

	const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	const title = `Workflow connection recovery ${Date.now()}`;
	const created = await page.request.post(`${apiUrl}/v1/workflows`, {
		data: {
			title,
			enabled: false,
			graph: {
				version: 1,
				trigger_node_id: 'manual',
				nodes: [
					{ id: 'manual', type: 'manual_trigger', title: 'Manual start', config: {} },
					{ id: 'notify', type: 'send_notification', title: 'Show result', config: { title: 'Ready', body: 'Ready' } },
					{ id: 'end', type: 'end', title: 'Done', config: {} }
				],
				edges: [{ from: 'manual', to: 'notify' }, { from: 'notify', to: 'end' }]
			}
		}
	});
	expect(created.ok(), await created.text()).toBe(true);
	const workflowId = (await created.json()).workflow.id;
	let failInitialLoad = true;
	await page.route('**/v1/workflows', route => {
		if (route.request().method() === 'GET' && failInitialLoad) {
			return route.fulfill({ status: 503, json: { detail: 'Load failed' } });
		}
		return route.continue();
	});

	try {
		await test.step('failed initial loading never adds a workspace error container', async () => {
			const failedLoad = page.waitForEvent('console', message =>
				message.type() === 'error' && message.text().includes('[WorkflowsRoute] Failed to warm workflow cache:')
			);
			await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
			await failedLoad;
			await expect(page.getByTestId('workflows-start-screen')).toBeVisible();
			await expect(page.getByTestId('workflow-input-composer')).toBeVisible();
			await expect(page.getByTestId('workflows-error')).toHaveCount(0);
			await expect(page.getByTestId('workflows-page')).not.toContainText('Load failed');
		});

		failInitialLoad = false;
		const recovered = page.waitForResponse(response =>
			response.url().endsWith('/v1/workflows') && response.request().method() === 'GET' && response.ok()
		);
		await page.evaluate(() => window.dispatchEvent(new Event('online')));
		await recovered;
		const cachedCard = page.getByTestId('workflow-landing-card').filter({ hasText: title });
		await expect(cachedCard).toBeVisible();

		await test.step('a failed offline refresh preserves cards and uses the header indicator', async () => {
			// Expire the workflow cache without waiting a minute or advancing timers.
			await page.clock.setFixedTime(new Date(Date.now() + 65_000));
			await context.setOffline(true);
			const refreshFailed = page.waitForEvent('requestfailed', request =>
				request.url().endsWith('/v1/workflows') && request.method() === 'GET'
			);
			await page.evaluate(() => window.dispatchEvent(new Event('focus')));
			await refreshFailed;
			await page.getByTestId('workflow-input-textarea').fill('Keep this workflow draft');
			await expect(page.getByTestId('connection-status-indicator')).toHaveAttribute('data-state', 'offline');
			await expect(cachedCard).toBeVisible();
			await expect(page.getByTestId('workflow-input-textarea')).toHaveValue('Keep this workflow draft');
			await expect(page.getByTestId('workflows-error')).toHaveCount(0);
		});

		await test.step('explicit workflow actions still show actionable errors', async () => {
			await page.getByTestId('workflow-import-input').setInputFiles({
				name: 'invalid.yaml', mimeType: 'application/yaml', buffer: Buffer.from('invalid')
			});
			await expect(page.getByTestId('workflows-error')).toContainText('Choose an OpenMates .workflow.yml file.');
		});
	} finally {
		await context.setOffline(false);
		await page.request.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(workflowId)}`);
	}
});
