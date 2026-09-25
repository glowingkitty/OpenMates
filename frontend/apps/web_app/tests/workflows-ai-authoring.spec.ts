/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
/** Dedicated Ask AI and AI Check authoring contract with deterministic hint responses. */
export {};

import type { Page, Response, Route } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

function apiUrl(): string {
	const url = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
	return url.hostname === 'localhost'
		? 'http://localhost:8000'
		: `${url.protocol}//${url.hostname.replace(/^app\./, 'api.')}`;
}

test.describe('Workflow AI authoring', () => {
	// contract-test: direct surface=gui.web assertions=workflows-ui.mvp.authoring,workflows-ui.mvp.ask-ai,workflows.control.ai-check
	test('offers Ask AI separately, debounces hints, blocks app requests, and adds Unsure to AI Check', async ({ page }: { page: Page }) => {
		test.setTimeout(180_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, () => {}, async () => {});

		const graph = {
			version: 2,
			trigger_node_id: null,
			nodes: [{
				id: 'events',
				type: 'app_skill_action',
				title: 'Events search',
				config: {
					app_id: 'events',
					skill_id: 'search',
					input: { requests: [{ query: 'Design events in Berlin' }] }
				}
			}],
			edges: []
		};
		const response = await page.request.post(`${apiUrl()}/v1/workflows`, {
			data: { title: `Workflow AI authoring ${Date.now()}`, graph, enabled: false }
		});
		expect(response.ok()).toBe(true);
		const { workflow } = await response.json();

		await page.route('**/v1/workflows/ai-authoring/hints', async (route: Route) => {
			const body = route.request().postDataJSON() as {
				instruction: string;
				references: Array<{ reference: string }>;
			};
			const resultReference = body.references.find((item) => item.reference.includes('.results'))?.reference
				?? body.references[0]?.reference;
			if (body.instruction.includes('Search for new events')) {
				await route.fulfill({ json: { verdict: 'asks_to_invoke_app_skill', validation_path: 'jev', suggested_references: [] } });
				return;
			}
			if (body.instruction.includes('Neutral validation')) {
				await route.fulfill({ json: {
					verdict: 'unverified',
					validation_path: 'jev_unavailable',
					suggested_references: [],
					reminder: "We couldn't verify this instruction right now. You can still save it; Ask AI cannot use app skills."
				} });
				return;
			}
			await route.fulfill({ json: {
				verdict: 'allowed',
				validation_path: 'jev',
				suggested_references: resultReference ? [resultReference] : []
			} });
		});

		try {
			await page.goto(getE2EDebugUrl(`/#workflow-id=${workflow.id}&workflow-tab=details`), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('workspace-detail-title')).toHaveText(workflow.title, { timeout: 30_000 });
			await page.getByTestId('workflow-add-step').click();
			const choices = page.getByTestId('workflow-step-menu').locator('.choice');
			await expect(choices).toHaveText(['Use app', 'Ask AI', 'Add check', 'Send message']);
			await page.getByTestId('workflow-step-ask-ai').click();

			const instruction = page.getByTestId('workflow-message-template');
			await instruction.fill('Summarize the events and explain what makes each one useful');
			await expect(page.getByTestId('workflow-ai-suggestions')).toContainText('Results', { timeout: 10_000 });
			const suggestionBox = await page.getByTestId('workflow-ai-suggestions').boundingBox();
			const instructionBox = await instruction.boundingBox();
			expect(suggestionBox && instructionBox && suggestionBox.y < instructionBox.y).toBe(true);

			await instruction.fill('Search for new events for me using the Events app');
			await expect(page.getByTestId('workflow-ai-app-warning')).toHaveText(
				"You can't ask for using app skills here. Instead add an 'Use app' action to trigger an app skill.",
				{ timeout: 10_000 }
			);
			await expect(page.getByTestId('workflow-node-save')).toBeDisabled();

			await instruction.fill('Neutral validation: summarize the existing event results');
			await expect(page.getByTestId('workflow-ai-neutral-reminder')).toContainText('You can still save it', { timeout: 10_000 });
			await expect(page.getByTestId('workflow-node-save')).toBeEnabled();
			await page.getByRole('button', { name: 'Close' }).click();

			await page.getByTestId('workflow-add-step').click();
			await page.getByTestId('workflow-step-menu').getByText('Add check', { exact: true }).click();
			await page.getByLabel('How should this be checked?').selectOption('ai');
			await page.getByTestId('workflow-message-template').fill('Are these events genuinely useful for a design professional?');
			await expect(page.getByTestId('workflow-node-save')).toBeDisabled();
			await page.getByTestId('workflow-ai-check-variable-chips').getByRole('button').first().click();
			await expect(page.getByTestId('workflow-node-save')).toBeEnabled();
			const saved = page.waitForResponse((item: Response) =>
				item.url().endsWith(`/v1/workflows/${workflow.id}`)
				&& item.request().method() === 'PATCH'
			);
			await page.getByTestId('workflow-node-save').click();
			expect((await saved).ok()).toBe(true);
			await expect(page.locator('.branch-label')).toHaveText(['If true', 'Else', 'If unsure']);
		} finally {
			await page.request.delete(`${apiUrl()}/v1/workflows/${encodeURIComponent(workflow.id)}`).catch(() => null);
		}
	});
});
