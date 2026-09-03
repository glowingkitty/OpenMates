/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Focused component coverage for API-key scope selection settings.
 * Uses the deterministic bare preview to verify full-access and limited-access
 * toggle states without account, API, or IndexedDB dependencies.
 * Product Plan: docs/plans/api-key-scopes-v1/plan.yml.
 */
export {};

import type { Page, TestInfo } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';
const PREVIEW_URL = '/dev/preview/settings/developers/SettingsApiKeys?chrome=0';
const PROOF_KEY_NAME = 'OpenMates integration';
const PROOF_TYPING_DELAY_MS = 100;
const PROOF_SCOPE_FRAME_OFFSET_PX = 80;

const API_KEY_SCOPES_PROOF = defineVideoProof({
	id: 'api-key-scopes-settings',
	title: 'API-key scope selection',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'full-access',
			text: 'Full access starts enabled before individual permission controls are revealed.',
			checkpoint: 'full-access',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'limited-scopes',
			text: 'Turning Full access off reveals individual permissions grouped into labeled categories with consistent toggle rows.',
			checkpoint: 'limited-scopes',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'independent-selection',
			text: 'Each permission starts disabled and can be enabled independently, including create-only access.',
			checkpoint: 'independent-selection',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'full-access-default',
			checkpoint: 'full-access',
			visual: 'The Full access toggle is enabled and its warning is visible.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'categorized-scope-list',
			checkpoint: 'limited-scopes',
			visual: 'The limited-access list uses readable category headings and canonical Settings toggle rows.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'scope-toggle-independence',
			checkpoint: 'independent-selection',
			visual: 'Selected toggles are enabled without changing unrelated permissions.',
			devices: ['web-laptop', 'web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

async function openPreview(page: Page): Promise<void> {
	const response = await page.goto(PREVIEW_URL, { waitUntil: 'networkidle' });
	expect(response?.status()).toBe(200);
	await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute('data-preview-ready', 'true', {
		timeout: 15_000
	});
	await expect(page.getByTestId('preview-toolbar')).toHaveCount(0);
	await expect(page.getByTestId('preview-status-bar')).toHaveCount(0);
	await expect(page.getByTestId('render-error')).not.toBeVisible({ timeout: 5_000 });
}

test.describe('API-key scope selection settings', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.auth.approved-api-key-device
	test('switches from full access to independent scope toggles', async ({ page }: { page: Page }, testInfo: TestInfo) => {
		const proof = createVideoProofRuntime(API_KEY_SCOPES_PROOF, {
			device: PROOF_DEVICE,
			attach: testInfo.attach.bind(testInfo),
			captureFrame: () => page.screenshot({ type: 'png' })
		});
		await openPreview(page);

		const fullAccessRow = page.getByTestId('api-key-full-access');
		const fullAccessInput = page.getByTestId('api-key-full-access-toggle').locator('input');
		const fullAccessWarning = page.getByRole('alert').filter({
			hasText: /full access can read encrypted account metadata/i
		});
		await fullAccessRow.scrollIntoViewIfNeeded();
		await fullAccessWarning.scrollIntoViewIfNeeded();
		await proof.assert('full-access-default', async () => {
			await expect(fullAccessInput).toBeChecked();
			await expect(fullAccessWarning).toContainText(/full access can read encrypted account metadata/i);
		});
		await proof.checkpoint('full-access');
		const nameInput = page.getByTestId('api-key-name-input');
		await nameInput.pressSequentially(PROOF_KEY_NAME, { delay: PROOF_TYPING_DELAY_MS });
		await expect(nameInput).toHaveValue(PROOF_KEY_NAME);
		await fullAccessRow.hover();
		await fullAccessRow.evaluate(async (element) => {
			const finiteAnimations = element.getAnimations({ subtree: true }).filter((animation) => {
				const endTime = animation.effect?.getComputedTiming().endTime;
				return typeof endTime === 'number' && Number.isFinite(endTime);
			});
			await Promise.all(finiteAnimations.map((animation) => animation.finished.catch(() => undefined)));
		});

		await proof.action('disable-full-access', () => fullAccessRow.click());
		const fixedScopeInputs = page.locator('[data-testid^="api-key-scope-"][data-testid$="-toggle"] input');
		await proof.assert('categorized-scope-list', async () => {
			await expect(fullAccessInput).not.toBeChecked();
			await expect(page.getByRole('heading', { name: 'Chats' })).toBeVisible();
			await expect(page.getByRole('heading', { name: 'Tasks' })).toBeVisible();
			await expect(page.getByRole('heading', { name: 'App skills' })).toBeVisible();
			expect(await fixedScopeInputs.count()).toBe(32);
			for (const input of await fixedScopeInputs.all()) await expect(input).not.toBeChecked();
		});
		await page.getByTestId('api-key-scope-task-create').scrollIntoViewIfNeeded();
		await page.getByTestId('component-preview-canvas').evaluate((element, offset) => {
			element.scrollBy({ top: -offset, behavior: 'instant' });
		}, PROOF_SCOPE_FRAME_OFFSET_PX);
		await proof.checkpoint('limited-scopes');

		await proof.action('select-independent-scopes', async () => {
			await page.getByTestId('api-key-scope-task-create').click();
		});
		await proof.assert('scope-toggle-independence', async () => {
			await expect(page.getByTestId('api-key-scope-task-create-toggle').locator('input')).toBeChecked();
			await expect(page.getByTestId('api-key-scope-task-read-toggle').locator('input')).not.toBeChecked();
			await expect(page.getByTestId('api-key-scope-project-create-toggle').locator('input')).not.toBeChecked();
		});
		await proof.checkpoint('independent-selection');
		await proof.attach();
	});
});
