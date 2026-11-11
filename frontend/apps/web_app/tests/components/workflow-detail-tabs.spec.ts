// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

import type { Page, TestInfo } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';

const { expect, test } = require('../helpers/cookie-audit');

const previewOf = (component: string, variant?: string, width = '430') =>
	`/dev/preview/workflows/${component}?${new URLSearchParams({
		theme: 'light',
		background: '#dbeafe',
		width,
		chrome: '0',
		...(variant ? { variant } : {})
	})}`;
const preview = (variant?: string) => previewOf('WorkflowDetailPage', variant);

/** Resolve with the detail of the next window event of this name. */
const nextPreviewEvent = <T>(page: Page, name: string) =>
	page.evaluate((eventName) => new Promise<T>(resolve =>
		window.addEventListener(eventName, (event) => resolve((event as CustomEvent<T>).detail), { once: true })), name);

const SAVED_ONLY_TEST_IDS = ['workflow-view-tabs', 'workflow-detail-metadata', 'workflow-export', 'delete-workflow', 'run-workflow', 'workflow-share'];

test.describe('Workflow detail tabs', () => {
	for (const theme of ['light', 'dark']) {
		// contract-test: direct surface=gui.web assertions=workflows-ui.responsive-accessible-reachable
		test(`keeps the gradient header title white in ${theme} mode`, async ({ page }: { page: Page }) => {
			await page.setViewportSize({ width: 430, height: 844 });
			const url = new URL(preview(), 'http://localhost');
			url.searchParams.set('theme', theme);
			await page.goto(`${url.pathname}${url.search}`, { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute('data-preview-ready', 'true', { timeout: 30_000 });
			const title = page.getByTestId('workspace-detail-title');
			await expect(title).toHaveText('Weekly AI events');
			await expect(title).toHaveCSS('color', 'rgb(255, 255, 255)');
			await title.hover();
			await expect(title).toHaveCSS('color', 'rgb(255, 255, 255)');
			await title.click();
			await page.getByRole('textbox', { name: 'Workflow name', exact: true }).fill('Updated weekly events');
			await page.getByRole('button', { name: 'Save', exact: true }).click();
			await expect(title).toHaveText('Weekly AI events');
			await expect(title).toHaveCSS('color', 'rgb(255, 255, 255)');
			await page.getByTestId('workspace-detail-header').screenshot({ path: test.info().outputPath(`workflow-header-${theme}.png`) });
		});
	}
	// contract-test: supporting surface=gui.web assertions=workflows-ui.authoring.composer-and-preview
	test('shows a provisional identity without saved-workflow actions', async ({ page }: { page: Page }) => {
		await page.goto(preview('provisional'), { waitUntil: 'networkidle' });
		await expect(page.getByTestId('workspace-detail-title')).toHaveText('Processing…');
		await expect(page.getByTestId('workspace-detail-title')).toHaveCSS('color', 'rgb(255, 255, 255)');
		await expect(page.getByTestId('workspace-detail-description')).toHaveCount(0);
		await expect(page.getByText('Click to add description')).toHaveCount(0);
		await expect(page.getByTestId('workflow-detail-metadata')).toHaveCount(0);
		await expect(page.getByTestId('toggle-workflow')).toBeDisabled();
		await expect(page.getByTestId('workflow-view-tabs')).toHaveCount(0);
		for (const id of ['workflow-export', 'delete-workflow', 'run-workflow', 'workflow-share']) {
			await expect(page.getByTestId(id)).toHaveCount(0);
		}
		await page.getByTestId('workspace-detail-title').click();
		await expect(page.getByRole('textbox', { name: 'Workflow name' })).toHaveCount(0);
		const closed = page.evaluate(() => new Promise<void>(resolve => window.addEventListener('workflow-preview-close', () => resolve(), { once: true })));
		await page.getByTestId('workflow-detail-back').click();
		await closed;
	});
	// contract-test: direct surface=gui.web assertions=workflows-ui.workspace.guest-template-preview
	test('preview-only template detail exposes a readable identity and no owner actions', async ({ page }: { page: Page }) => {
		await page.setViewportSize({ width: 430, height: 844 });
		await page.goto(preview('previewOnly'), { waitUntil: 'domcontentloaded' });
		await waitForComponentPreview(page);
		await expect(page.getByTestId('workspace-detail-header')).toBeVisible();
		await expect(page.getByTestId('workspace-detail-title')).toHaveText('Daily planning reminder');
		await expect(page.getByTestId('workspace-detail-description')).toContainText('A morning message');
		await expect(page.getByTestId('toggle-workflow')).toBeDisabled();
		for (const id of ['workflow-detail-metadata', 'workflow-view-tabs', 'workflow-export', 'delete-workflow', 'run-workflow', 'workflow-share']) {
			await expect(page.getByTestId(id)).toHaveCount(0);
		}
		await page.getByTestId('workspace-detail-title').click();
		await expect(page.getByRole('textbox', { name: 'Workflow name' })).toHaveCount(0);
		const closed = page.evaluate(() => new Promise<void>(resolve => window.addEventListener('workflow-preview-close', () => resolve(), { once: true })));
		await page.getByTestId('workflow-detail-back').click();
		await closed;
	});
	// contract-test: supporting surface=gui.web assertions=workflows-ui.files.more-export
	test('shows export in More for a saved and a blank workflow', async ({ page }: { page: Page }) => {
		await page.goto(preview(), { waitUntil: 'networkidle' });
		await page.getByRole('button', { name: 'More', exact: true }).click();
		await expect(page.getByTestId('workflow-export')).toBeEnabled();
		const emitted = page.evaluate(() => new Promise<void>(resolve => window.addEventListener('workflow-preview-export', () => resolve(), { once: true })));
		await page.getByTestId('workflow-export').click();
		await emitted;
		await page.goto(preview('blank'), { waitUntil: 'networkidle' });
		await page.getByRole('button', { name: 'More', exact: true }).click();
		await expect(page.getByTestId('workflow-export')).toBeEnabled();
	});
	// contract-test: direct surface=gui.web assertions=workflows-ui.detail.shared-template-runs-tabs
	test('uses the shared workspace tab dimensions and gradient pill', async ({ page }: { page: Page }) => {
		await page.goto(preview(), { waitUntil: 'networkidle' });

		const tabs = page.getByTestId('workflow-view-tabs');
		const pill = page.getByTestId('workflow-view-tabs-pill');
		const tabButtons = tabs.getByRole('tab');
		await expect(tabs).toBeVisible();
		await expect(tabButtons).toHaveCount(2);
		await expect(tabButtons.first()).toHaveAttribute('aria-selected', 'true');
		await expect(tabButtons.last()).toHaveAttribute('aria-selected', 'false');
		await expect(tabButtons.first().locator('span')).toHaveCSS('background-color', 'rgb(255, 255, 255)');

		const [tabsBox, pillBox, firstTabBox, iconBox] = await Promise.all([
			tabs.boundingBox(),
			pill.boundingBox(),
			tabButtons.first().boundingBox(),
			tabButtons.first().locator('span').boundingBox()
		]);
		expect(tabsBox).not.toBeNull();
		expect(pillBox).not.toBeNull();
		expect(firstTabBox).not.toBeNull();
		expect(iconBox).not.toBeNull();
		expect(tabsBox!.width).toBeCloseTo(144, 0);
		expect(tabsBox!.height).toBeCloseTo(44.8, 0);
		expect(firstTabBox!.width).toBeCloseTo(72, 0);
		expect(firstTabBox!.height).toBeCloseTo(44.8, 0);
		expect(pillBox!.width).toBeCloseTo(72, 0);
		expect(iconBox!.width).toBe(20);
		expect(iconBox!.height).toBe(20);
		await expect(pill).toHaveCSS('background-image', /linear-gradient/);
	});
	// contract-test: supporting surface=gui.web assertions=workflows-ui.detail.stable-visual-header
	test('draft header edits the identity, keeps the workflow off and saves through Save', async ({ page }: { page: Page }, testInfo: TestInfo) => {
		await page.setViewportSize({ width: 430, height: 844 });
		await page.goto(preview('draft'), { waitUntil: 'domcontentloaded' });
		await waitForComponentPreview(page);
		const header = page.getByTestId('workspace-detail-header');
		await expect(header).toHaveAttribute('data-detail-state', 'draft');
		await expect(page.getByTestId('workflow-draft-title-input')).toHaveValue('Weekly AI events');
		await expect(page.getByTestId('workflow-draft-description-input')).toHaveValue('Find useful AI events every week.');
		await expect(page.getByTestId('toggle-workflow')).toBeDisabled();
		await expect(page.getByTestId('toggle-workflow')).toHaveAttribute('aria-checked', 'false');
		await expect(page.getByTestId('workflow-enabled-state')).toHaveAttribute('data-enabled', 'false');
		for (const id of SAVED_ONLY_TEST_IDS) await expect(page.getByTestId(id)).toHaveCount(0);
		await expect(page.getByTestId('workflow-save-draft')).toBeEnabled();
		await testInfo.attach('workflow-detail-draft-header', { body: await header.screenshot(), contentType: 'image/png' });

		const identity = nextPreviewEvent<{ title: string; description: string }>(page, 'workflow-preview-draft-identity');
		await page.getByTestId('workflow-draft-title-input').fill('Weekly AI meetups');
		expect(await identity).toEqual({ title: 'Weekly AI meetups', description: 'Find useful AI events every week.' });
		await page.getByTestId('workflow-draft-title-input').focus();
		await testInfo.attach('workflow-detail-draft-header-editing', { body: await header.screenshot(), contentType: 'image/png' });

		const saved = nextPreviewEvent(page, 'workflow-preview-save-draft');
		await page.getByTestId('workflow-save-draft').click();
		await saved;
		const closed = nextPreviewEvent(page, 'workflow-preview-close');
		await page.getByTestId('workflow-detail-back').click();
		await closed;
	});
	// contract-test: supporting surface=gui.web assertions=workflows-ui.detail.stable-visual-header
	test('editor pane shows an unsaved draft with Save and no saved-workflow actions', async ({ page }: { page: Page }, testInfo: TestInfo) => {
		await page.setViewportSize({ width: 900, height: 1000 });
		await page.goto(previewOf('WorkflowEditorPane', 'draft', '900'), { waitUntil: 'domcontentloaded' });
		const canvas = await waitForComponentPreview(page);
		await expect(page.getByTestId('workspace-detail-header')).toHaveAttribute('data-detail-state', 'draft');
		await expect(page.getByTestId('workflow-draft-title-input')).toHaveValue('Weekly school weather brief');
		await expect(page.getByTestId('workflow-template-panel')).toBeVisible();
		await expect(page.getByTestId('workflow-editor')).toBeVisible();
		await expect(page.getByTestId('workflow-template-test-now')).toHaveCount(0);
		await expect(page.getByTestId('workflow-version-selector')).toHaveCount(0);
		await expect(page.getByTestId('toggle-workflow')).toBeDisabled();
		for (const id of SAVED_ONLY_TEST_IDS) await expect(page.getByTestId(id)).toHaveCount(0);
		await testInfo.attach('workflow-editor-pane-draft', { body: await canvas.screenshot(), contentType: 'image/png' });

		const saved = nextPreviewEvent<{ title: string }>(page, 'workflow-preview-save-draft');
		await page.getByTestId('workflow-save-draft').click();
		expect(await saved).toEqual({ title: 'Weekly school weather brief' });
	});
	for (const [variant, enabled] of [['saved', 'false'], ['saved-enabled', 'true']] as const) {
		// contract-test: supporting surface=gui.web assertions=workflows-ui.detail.shared-template-runs-tabs
		test(`editor pane shows the ${variant} workflow with tabs, enable state and Test now`, async ({ page }: { page: Page }, testInfo: TestInfo) => {
			await page.setViewportSize({ width: 900, height: 1000 });
			await page.goto(previewOf('WorkflowEditorPane', variant, '900'), { waitUntil: 'domcontentloaded' });
			const canvas = await waitForComponentPreview(page);
			await expect(page.getByTestId('workspace-detail-header')).toHaveAttribute('data-detail-state', 'saved');
			await expect(page.getByTestId('workspace-detail-title')).toHaveText('Weekly school weather brief');
			await expect(page.getByTestId('workflow-enabled-state')).toHaveAttribute('data-enabled', enabled);
			await expect(page.getByTestId('workflow-view-tabs')).toBeVisible();
			await expect(page.getByTestId('workflow-save-draft')).toHaveCount(0);
			await expect(page.getByTestId('workflow-template-panel')).toBeVisible();
			await expect(page.getByTestId('workflow-template-test-now')).toBeVisible();
			await testInfo.attach(`workflow-editor-pane-${variant}`, { body: await canvas.screenshot(), contentType: 'image/png' });
		});
	}
});
