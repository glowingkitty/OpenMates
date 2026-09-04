/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Focused deployed proof for encrypted Task Activity.
 * Uses bare deterministic component previews for rich composer states,
 * attribution, stable ordering, tombstones, and responsive reachability.
 * Plan: docs/plans/task-activity-comments/plan.yml.
 */
export {};

import type { Page, TestInfo } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';

const TASK_ACTIVITY_PROOF = defineVideoProof({
	id: 'task-activity',
	title: 'Encrypted Task Activity comments',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{ id: 'final-activity', text: 'Task detail ends with one Activity section. Its comment composer appears before a stable chronological stream.', checkpoint: 'final-activity', devices: ['web-laptop', 'web-phone'] },
		{ id: 'rich-composer', text: 'The composer accepts multiline content and exposes voice and file controls while pending uploads and transcription prevent sending.', checkpoint: 'rich-composer', devices: ['web-laptop', 'web-phone'] },
		{ id: 'attribution-tombstones', text: 'Web, CLI, SDK, and OpenMates entries have distinct attribution, while deleted comments retain only author and deleter identities.', checkpoint: 'attribution-tombstones', devices: ['web-laptop', 'web-phone'] }
	],
	assertions: [
		{ id: 'single-final-section', checkpoint: 'final-activity', visual: 'One Activity section is the final Task detail section with its composer first.', devices: ['web-laptop', 'web-phone'] },
		{ id: 'composer-parity', checkpoint: 'rich-composer', visual: 'Multiline, file, voice, processing, and failure states are visible and usable without obstruction.', devices: ['web-laptop', 'web-phone'] },
		{ id: 'safe-attribution', checkpoint: 'attribution-tombstones', visual: 'Attribution suffixes and content-free deletion tombstones match the Activity contract.', devices: ['web-laptop', 'web-phone'] }
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

async function openActivityPreview(page: Page, variant?: string): Promise<void> {
	const query = new URLSearchParams({ chrome: '0' });
	if (variant) query.set('variant', variant);
	const response = await page.goto(`/dev/preview/tasks/TaskActivity?${query.toString()}`, { waitUntil: 'networkidle' });
	expect(response?.status()).toBe(200);
	await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute('data-preview-ready', 'true', { timeout: 15_000 });
	await expect(page.getByTestId('preview-toolbar')).toHaveCount(0);
	await expect(page.getByTestId('preview-status-bar')).toHaveCount(0);
	await expect(page.getByTestId('render-error')).not.toBeVisible({ timeout: 5_000 });
	await expect(page.getByTestId('task-activity')).toBeVisible();
}

test.describe('Task Activity component', () => {
	// contract-test: direct surface=gui.web assertions=tasks.activity.single-final-section,tasks.activity.composer-message-parity,tasks.activity.context-attribution,tasks.activity.deletion-tombstone,tasks.surface.semantic-parity
	test('renders and operates the complete Activity surface', async ({ page }: { page: Page }, testInfo: TestInfo) => {
		const proof = createVideoProofRuntime(TASK_ACTIVITY_PROOF, {
			device: PROOF_DEVICE,
			attach: testInfo.attach.bind(testInfo),
			captureFrame: () => page.screenshot({ type: 'png' })
		});
		await openActivityPreview(page);

		const activity = page.getByTestId('task-activity');
		const composer = page.getByTestId('task-activity-composer');
		await proof.assert('single-final-section', async () => {
			await expect(activity.getByRole('heading', { name: 'Activity' })).toBeVisible();
			expect(await composer.evaluate((node) => {
				const streamNode = node.parentElement?.querySelector('[data-testid="task-activity-stream"]');
				return Boolean(streamNode && (node.compareDocumentPosition(streamNode) & Node.DOCUMENT_POSITION_FOLLOWING));
			})).toBe(true);
			await expect(page.getByText('I added the launch milestones')).toBeVisible();
		});
		await proof.checkpoint('final-activity');

		const editor = page.getByTestId('task-activity-editor').locator('.ProseMirror');
		await proof.action('write-multiline-comment', async () => {
			await editor.click();
			await page.keyboard.type('First line');
			await page.keyboard.press('Shift+Enter');
			await page.keyboard.type('Second line');
		});
		await expect(page.getByTestId('task-activity-attach')).toBeVisible();
		await expect(page.getByTestId('task-activity-voice')).toBeVisible();
		await expect(page.getByTestId('task-activity-submit')).toBeEnabled();
		await proof.action('send-comment', () => page.getByTestId('task-activity-submit').click());
		await expect(page.getByTestId('task-activity-entry-created-preview-comment')).toContainText('First line');
		await expect(page.getByTestId('task-activity-entry-created-preview-comment')).toContainText('Second line');

		await proof.action('show-upload-gate', () => openActivityPreview(page, 'uploading'));
		await expect(page.getByTestId('task-activity-processing')).toContainText('Uploading');
		await expect(page.getByTestId('task-activity-submit')).toBeDisabled();
		await proof.action('show-transcription-gate', () => openActivityPreview(page, 'transcribing'));
		await expect(page.getByTestId('task-activity-processing')).toContainText('Transcribing');
		await expect(page.getByTestId('task-activity-submit')).toBeDisabled();
		await proof.action('show-processing-error', () => openActivityPreview(page, 'error'));
		await expect(page.getByTestId('task-activity-embed-error')).toBeVisible();
		await proof.assert('composer-parity', async () => {
			await expect(page.getByTestId('task-activity-attach')).toBeVisible();
			await expect(page.getByTestId('task-activity-voice')).toBeVisible();
			await expect(page.getByTestId('task-activity-submit')).toBeDisabled();
		});
		await proof.checkpoint('rich-composer');

		await proof.action('return-to-activity-stream', () => openActivityPreview(page));
		await expect(page.getByTestId('task-activity-entry-web')).toContainText('Alice Weber');
		expect(await page.locator('[data-testid^="task-activity-entry-"]').evaluateAll((nodes) => nodes.slice(0, 2).map((node) => node.getAttribute('data-testid')))).toEqual(['task-activity-entry-web', 'task-activity-entry-cli']);
		await expect(page.getByTestId('task-activity-entry-web')).not.toContainText('via OpenMates');
		await expect(page.getByTestId('task-activity-entry-web').locator('img')).toBeVisible();
		await expect(page.getByTestId('task-activity-entry-cli')).toContainText('via OpenMates CLI');
		await expect(page.getByTestId('task-activity-entry-sdk')).toContainText('via OpenMates SDK');
		await expect(page.getByTestId('task-activity-entry-mate')).toContainText('OpenMates');
		await expect(page.getByTestId('task-activity-entry-deleted-user')).toContainText('Comment by Alice Weber deleted by Sam Rivera');
		await expect(page.getByTestId('task-activity-entry-deleted-mate')).toContainText('Comment by OpenMates deleted by Alice Weber');
		await proof.assert('safe-attribution', async () => {
			await expect(page.getByTestId('task-activity-entry-deleted-user')).not.toContainText('launch milestones');
			await expect(page.getByTestId('task-activity-entry-deleted-user').locator('[data-testid^="embed-"]')).toHaveCount(0);
		});
		await proof.checkpoint('attribution-tombstones');
		await proof.attach();

		const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
		expect(overflow, 'Task Activity should not create horizontal overflow').toBeLessThan(8);
	});

	// contract-test: supporting surface=gui.web assertions=tasks.activity.single-final-section
	test('is the final Task detail section', async ({ page }: { page: Page }) => {
		const response = await page.goto('/dev/preview/tasks/TaskDetailFullscreen?chrome=0', { waitUntil: 'networkidle' });
		expect(response?.status()).toBe(200);
		await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute('data-preview-ready', 'true', { timeout: 15_000 });
		const detail = page.getByTestId('task-detail-content');
		const activity = detail.getByTestId('task-activity');
		await expect(activity).toBeVisible();
		expect(await detail.evaluate((node) => node.lastElementChild?.getAttribute('data-testid') === 'task-activity')).toBe(true);
		await expect(detail.getByText('Updates', { exact: true })).toHaveCount(0);
		await expect(detail.getByText('Comments', { exact: true })).toHaveCount(0);
	});
});
