/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Focused component coverage for the read-only Task detail fullscreen.
 *
 * Uses the deterministic component preview to verify the Figma-aligned content,
 * responsive layout, keyboard close behavior, and visible linked-work context.
 * Product contract: contracts/features/tasks/contract.yml
 */
export {};

const { expect, test } = require('./helpers/cookie-audit');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';

const TASK_DETAIL_PROOF = defineVideoProof({
	id: 'task-detail-fullscreen',
	title: 'Read-only task fullscreen',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'core-metadata',
			text: 'The task fullscreen presents its description, status, priority, creator, assignee, and due date with shared settings headings.',
			checkpoint: 'core-metadata',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'linked-context',
			text: 'Scrolling reveals the linked project, Plan, chat, tags, and task dependencies in the same read-only view.',
			checkpoint: 'linked-context',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'fullscreen-controls',
			text: 'The clean component capture keeps the task fullscreen and minimize control reachable without preview controls.',
			checkpoint: 'fullscreen-controls',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'canonical-headings',
			checkpoint: 'core-metadata',
			visual: 'Task fields use the shared settings section heading treatment and remain readable.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'linked-context',
			checkpoint: 'linked-context',
			visual: 'Linked workspace context, tags, and dependencies are visible without edit controls.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'bare-component',
			checkpoint: 'fullscreen-controls',
			visual: 'Only the task fullscreen component is visible, with no preview toolbar or implementation metadata.',
			devices: ['web-laptop', 'web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

async function openTaskDetailPreview(page: any): Promise<void> {
	const response = await page.goto('/dev/preview/tasks/TaskDetailFullscreen?chrome=0', { waitUntil: 'networkidle' });
	expect(response?.status()).toBe(200);
	await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute('data-preview-ready', 'true', { timeout: 15_000 });
	await expect(page.getByTestId('preview-toolbar')).toHaveCount(0);
	await expect(page.getByTestId('preview-status-bar')).toHaveCount(0);
	await expect(page.getByTestId('render-error')).not.toBeVisible({ timeout: 5_000 });
	await expect(page.getByTestId('task-detail-fullscreen')).toBeVisible({ timeout: 15_000 });
}

test.describe('Task detail fullscreen component', () => {
	// contract-test: direct surface=gui.web assertions=tasks.detail.embed-responsive,tasks.surface.semantic-parity
	test('renders complete read-only task context and closes from the keyboard', async ({ page }, testInfo) => {
		const proof = createVideoProofRuntime(TASK_DETAIL_PROOF, {
			device: PROOF_DEVICE,
			attach: testInfo.attach.bind(testInfo),
			captureFrame: () => page.screenshot({ type: 'png' })
		});
		await openTaskDetailPreview(page);

		const detail = page.getByTestId('task-detail-content');
		await expect(page.getByTestId('embed-header-title')).toContainText('Design 3D model');
		await expect(detail.getByTestId('task-detail-description')).toContainText('fits 2-3 people');
		await expect(page.getByTestId('task-detail-status')).toContainText('To do');
		await expect(page.getByTestId('task-detail-priority')).toContainText('Urgent');
		await expect(detail.getByTestId('task-detail-assignee')).toContainText('OpenMates');
		await expect(detail.getByTestId('task-detail-due')).toContainText('Oct 22, 2026');
		await expect(detail.getByTestId('task-detail-projects')).toContainText('Research project');
		await expect(detail.getByTestId('task-detail-plan')).toContainText('Research launch plan');
		await expect(detail.getByTestId('task-detail-dependencies')).toContainText('Prepare research brief');
		await expect(detail.getByTestId('task-detail-tags')).toContainText('#software');
		await expect(detail.getByTestId('task-detail-chat')).toContainText('3D model planning');
		await expect(detail.getByTestId('task-detail-project-card')).toHaveAttribute('href', '/projects/preview-project');
		await expect(detail.getByTestId('task-detail-plan-card')).toHaveAttribute('href', '/plans/preview-plan');
		await proof.assert('canonical-headings', async () => {
			for (const heading of ['Description', 'Assigned to', 'Due', 'Connected project', 'Connected plan', 'Blockers and dependencies', 'Tags', 'Connected chat']) {
				await expect(detail.getByRole('heading', { level: 3, name: heading })).toBeVisible();
			}
		});
		await proof.checkpoint('core-metadata');

		await detail.getByTestId('task-detail-chat').scrollIntoViewIfNeeded();
		await proof.assert('linked-context', async () => {
			await expect(detail.getByTestId('task-detail-project-card')).toBeVisible();
			await expect(detail.getByTestId('task-detail-plan-card')).toBeVisible();
			await expect(detail.getByTestId('task-detail-chat')).toBeVisible();
		});
		await proof.checkpoint('linked-context');

		const close = page.getByTestId('task-detail-minimize');
		await close.scrollIntoViewIfNeeded();
		await expect(close).toBeFocused();
		await proof.assert('bare-component', async () => {
			await expect(page.getByTestId('task-detail-fullscreen')).toBeVisible();
			await expect(page.getByTestId('preview-toolbar')).toHaveCount(0);
			await expect(page.getByTestId('preview-status-bar')).toHaveCount(0);
			await expect(close).toBeVisible();
		});
		await proof.checkpoint('fullscreen-controls');
		await proof.attach();
		await page.keyboard.press('Escape');
		await expect(page.getByTestId('task-detail-fullscreen')).not.toBeVisible({ timeout: 2_000 });
	});

	// contract-test: supporting surface=gui.web assertions=tasks.detail.embed-responsive
	test('keeps every detail section reachable on a phone viewport', async ({ page }) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await openTaskDetailPreview(page);

		const detail = page.getByTestId('task-detail-content');
		await expect(page.getByTestId('embed-header-title')).toBeVisible();
		await detail.getByTestId('task-detail-chat').scrollIntoViewIfNeeded();
		await expect(detail.getByTestId('task-detail-chat')).toBeVisible();
		const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
		expect(overflow, 'Task detail should not create horizontal page overflow on mobile').toBeLessThan(8);
	});
});
