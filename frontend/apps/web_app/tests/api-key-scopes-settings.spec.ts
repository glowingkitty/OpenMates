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

const API_KEY_SCOPES_PROOF = defineVideoProof({
	id: 'api-key-scopes-settings',
	title: 'API-key scope selection',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'full-access',
			text: 'API keys start with Full access enabled and a warning that explains the broad permission level.',
			checkpoint: 'full-access',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'limited-scopes',
			text: 'Turning Full access off reveals individual permission toggles grouped by Chats, Tasks, Projects, Plans, Workflows, Memories, Account, API keys, Devices, and App skills.',
			checkpoint: 'limited-scopes',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'independent-selection',
			text: 'Each permission starts disabled and can be enabled independently, including create-only and account export access.',
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
			visual: 'The long scope list uses readable category headings and canonical Settings toggle rows.',
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

		const fullAccessInput = page.getByTestId('api-key-full-access-toggle').locator('input');
		await proof.assert('full-access-default', async () => {
			await expect(fullAccessInput).toBeChecked();
			await expect(page.getByText(/full access can read encrypted account metadata/i)).toBeVisible();
		});
		await proof.checkpoint('full-access');

		await proof.action('disable-full-access', () => page.getByTestId('api-key-full-access').click());
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
		await proof.checkpoint('limited-scopes');

		await proof.action('select-task-create', () => page.getByTestId('api-key-scope-task-create').click());
		await proof.action('select-account-export', () => page.getByTestId('api-key-scope-account-export').click());
		await page.getByTestId('api-key-scope-account-export').scrollIntoViewIfNeeded();
		await proof.assert('scope-toggle-independence', async () => {
			await expect(page.getByTestId('api-key-scope-task-create-toggle').locator('input')).toBeChecked();
			await expect(page.getByTestId('api-key-scope-account-export-toggle').locator('input')).toBeChecked();
			await expect(page.getByTestId('api-key-scope-task-read-toggle').locator('input')).not.toBeChecked();
		});
		await proof.checkpoint('independent-selection');
		await proof.attach();
	});
});
