/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Code notebook E2E gate for the public notebook example chat.
 *
 * This covers the browser-specific path: notebook preview rendering, fullscreen
 * rendering, encrypted sidecar-output merge behavior, source immutability, and
 * anonymous execution blocking. Backend/API tests cover authenticated E2B runs.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const { openFullscreen } = require('./helpers/embed-test-helpers');

const NOTEBOOK_EXAMPLE_PATH = '/example/open-meteo-weather-notebook';
const NOTEBOOK_EXAMPLE_CHAT_ID = 'example-open-meteo-weather-notebook';
const NOTEBOOK_RUN_ENDPOINT = '**/v1/code/notebooks/run';
const SIDECAR_OUTPUT_TEXT = 'sidecar output smoke';

test.describe('Code notebook flow', () => {
	test('public notebook example renders cells, merges sidecar outputs, and blocks anonymous execution', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(90_000);
		await page.setViewportSize({ width: 1440, height: 1000 });

		const notebookRunRequests: string[] = [];
		await page.route(NOTEBOOK_RUN_ENDPOINT, async (route) => {
			notebookRunRequests.push(route.request().url());
			await route.abort('blockedbyclient');
		});

		await page.goto(getE2EDebugUrl(NOTEBOOK_EXAMPLE_PATH), { waitUntil: 'domcontentloaded' });
		await expect(page).toHaveURL(new RegExp(`chat-id=${NOTEBOOK_EXAMPLE_CHAT_ID}`), {
			timeout: 15_000
		});

		const notebookPreview = page
			.locator(
				'[data-testid="embed-preview"][data-app-id="code"][data-skill-id="notebook"][data-status="finished"]'
			)
			.first();
		await expect(notebookPreview).toBeVisible({ timeout: 30_000 });
		await expect(notebookPreview.getByTestId('notebook-preview')).toBeVisible({ timeout: 10_000 });
		await expect(notebookPreview).toContainText(/7 cells?, Notebook/i);

		const previewCells = notebookPreview.getByTestId('notebook-preview-cell');
		await expect.poll(async () => previewCells.count(), {
			message: 'notebook preview should render visible notebook cells',
			timeout: 10_000
		}).toBeGreaterThanOrEqual(2);
		await expect(notebookPreview).toContainText(/Berlin 7-Day Weather Analysis|import requests/i);
		await expect(notebookPreview.getByTestId('notebook-run-all-button')).toHaveCount(0);

		const previewText = await notebookPreview.evaluate((node: HTMLElement) => node.innerText || '');
		expect(previewText).not.toMatch(/"cells"\s*:/);
		expect(previewText).not.toContain('nbformat');

		const embedId = await notebookPreview.getAttribute('data-embed-id');
		expect(embedId, 'notebook preview should expose a stable embed id').toBeTruthy();

		const fullscreenOverlay = await openFullscreen(page, notebookPreview);
		await expect(fullscreenOverlay.getByTestId('notebook-fullscreen')).toBeVisible({ timeout: 15_000 });
		await expect(fullscreenOverlay).toContainText(/7 cells?, Notebook/i);

		const fullscreenCells = fullscreenOverlay.getByTestId('notebook-cell');
		await expect.poll(async () => fullscreenCells.count(), {
			message: 'fullscreen should render every notebook cell',
			timeout: 10_000
		}).toBeGreaterThanOrEqual(7);
		await expect(fullscreenOverlay).toContainText('Berlin 7-Day Weather Analysis');
		await expect(fullscreenOverlay).toContainText('import requests');

		const sourceLines = fullscreenOverlay.getByTestId('notebook-code-lines').first();
		await expect(sourceLines).toBeVisible({ timeout: 10_000 });
		const sourceBeforeSidecar = await sourceLines.innerText();
		expect(sourceBeforeSidecar).toContain('import requests');

		await page.evaluate(
			({ chatId, currentEmbedId, outputText }: { chatId: string; currentEmbedId: string; outputText: string }) => {
				const now = Date.now();
				window.dispatchEvent(
					new CustomEvent('notebookRunOutputSynced', {
						detail: {
							id: 'e2e-notebook-output',
							chat_id: chatId,
							notebook_embed_id: currentEmbedId,
							source_version: null,
							status: 'finished',
							selected_cell_indices: [1],
							cell_outputs: [
								{
									cell_index: 1,
									execution_count: 1,
									outputs: [{ output_type: 'stream', name: 'stdout', text: `${outputText}\n` }]
								}
							],
							saved_at: now,
							created_at: Math.floor(now / 1000),
							updated_at: Math.floor(now / 1000)
						}
					})
				);
			},
			{ chatId: NOTEBOOK_EXAMPLE_CHAT_ID, currentEmbedId: embedId as string, outputText: SIDECAR_OUTPUT_TEXT }
		);

		await expect(fullscreenOverlay.getByTestId('notebook-cell-output')).toContainText(
			SIDECAR_OUTPUT_TEXT,
			{ timeout: 10_000 }
		);
		expect(await sourceLines.innerText()).toBe(sourceBeforeSidecar);

		const anonymousRunAttempt = page
			.waitForRequest(
				(request) =>
					request.method() === 'POST' && request.url().includes('/v1/code/notebooks/run'),
				{ timeout: 3_000 }
			)
			.then(() => 'posted' as const)
			.catch(() => 'not-posted' as const);

		await fullscreenOverlay.getByTestId('notebook-run-all-button').click();
		await expect(page.getByTestId('tab-login')).toBeVisible({ timeout: 10_000 });
		expect(await anonymousRunAttempt).toBe('not-posted');
		expect(notebookRunRequests).toHaveLength(0);
	});
});
