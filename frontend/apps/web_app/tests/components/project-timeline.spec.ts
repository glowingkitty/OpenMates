// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import type { Page } from '@playwright/test';

const PREVIEW = '/dev/preview/projects/ProjectTimeline';

async function open(page: Page, variant?: string, theme = 'light', width = '720') {
	const query = new URLSearchParams({ theme, width, chrome: '0' });
	if (variant) query.set('variant', variant);
	await page.goto(`${PREVIEW}?${query}`, { waitUntil: 'domcontentloaded' });
	await waitForComponentPreview(page);
}

const shot = async (page: Page, testInfo: import('@playwright/test').TestInfo, name: string) =>
	testInfo.attach(name, { body: await page.getByTestId('project-timeline').screenshot(), contentType: 'image/png' });

test.describe('project timeline', () => {
	// contract-test: supporting surface=gui.web assertions=projects.history.native-commits
	test('lists entries newest first with author, path and version', async ({ page }, testInfo) => {
		await open(page);
		const entries = page.locator('[data-testid^="project-timeline-entry-"]');
		await expect(entries.first()).toBeVisible({ timeout: 30_000 });
		await expect(entries.first()).toHaveAttribute('data-testid', 'project-timeline-entry-c4e1f9a2b3');
		await expect(entries.last()).toHaveAttribute('data-testid', 'project-timeline-entry-v-index');
		const styles = page.getByTestId('project-timeline-entry-v-styles');
		await expect(styles).toContainText('You');
		await expect(styles).toContainText('web-app/styles.css');
		await expect(styles).toContainText('v2');
		await expect(page.getByTestId('project-timeline-entry-v-app')).toContainText('Assistant');
		await expect(page.getByTestId('project-timeline-entry-c4e1f9a2b3')).toContainText('Restored from a91b2c3');
		await expect(page.getByTestId('project-timeline-load-more')).toBeVisible();
		// Global button styles must not stretch or clip rows: text stays inside its row.
		const fits = await page.evaluate(() =>
			[...document.querySelectorAll('[data-testid^="project-timeline-entry-"]')].every((row) => {
				const r = row.getBoundingClientRect();
				const t = row.querySelector('.pt-path')!.getBoundingClientRect();
				return t.top >= r.top && t.bottom <= r.bottom && r.height < 120;
			}),
		);
		expect(fits, 'row text stays inside its row').toBe(true);
		// Version chips sit fully inside their row on every row kind (div rows overflowed once).
		const chipsInside = await page.evaluate(() =>
			[...document.querySelectorAll('[data-testid^="project-timeline-entry-"] .pt-chip')].every((chip) => {
				const r = chip.closest('[data-testid^="project-timeline-entry-"]')!.getBoundingClientRect();
				const c = chip.getBoundingClientRect();
				return c.left >= r.left && c.right <= r.right - 4;
			}),
		);
		expect(chipsInside, 'version chips stay inside their row').toBe(true);
		await shot(page, testInfo, 'timeline-default');
	});

	// contract-test: supporting surface=gui.web assertions=projects.history.native-commits
	test('removed file shows a neutral label', async ({ page }) => {
		await open(page);
		await expect(page.getByTestId('project-timeline-entry-op-removed')).toContainText('Removed file');
	});

	// contract-test: supporting surface=gui.web assertions=projects.history.native-commits
	test('commit expands to its files', async ({ page }, testInfo) => {
		await open(page);
		await page.getByTestId('project-timeline-commit-toggle-a91b2c3d4e').click();
		const files = page.getByTestId('project-timeline-commit-files-a91b2c3d4e');
		await expect(files).toContainText('web-app/index.html');
		await expect(files).toContainText('web-app/styles.css');
		await shot(page, testInfo, 'timeline-commit-expanded');
	});

	// contract-test: supporting surface=gui.web assertions=projects.history.native-commits
	test('restore asks for confirmation, shows busy and then success', async ({ page }, testInfo) => {
		await open(page);
		await page.getByTestId('project-timeline-commit-toggle-a91b2c3d4e').click();
		await page.getByTestId('project-timeline-restore-a91b2c3d4e').click();
		await expect(page.getByTestId('project-timeline-restore-confirm')).toBeVisible();
		await expect(page.getByText('later history is kept', { exact: false })).toBeVisible();
		await shot(page, testInfo, 'timeline-restore-confirm');
		await page.getByTestId('project-timeline-restore-confirm').click();
		await expect(page.getByTestId('project-timeline-restore-status')).toHaveAttribute('data-state', 'busy');
		await expect(page.getByTestId('project-timeline-restore-status')).toHaveAttribute('data-state', 'done');
		await shot(page, testInfo, 'timeline-restore-done');
	});

	// contract-test: supporting surface=gui.web assertions=projects.history.native-commits
	test('cancel closes the confirmation without restoring', async ({ page }) => {
		await open(page);
		await page.getByTestId('project-timeline-commit-toggle-a91b2c3d4e').click();
		await page.getByTestId('project-timeline-restore-a91b2c3d4e').click();
		await page.getByTestId('project-timeline-restore-cancel').click();
		await expect(page.getByTestId('project-timeline-restore-confirm')).toHaveCount(0);
		await expect(page.getByTestId('project-timeline-restore-status')).toHaveCount(0);
	});

	// contract-test: supporting surface=gui.web assertions=projects.history.native-commits
	test('failed restore shows an error status', async ({ page }) => {
		await open(page, 'restoreFails');
		await page.getByTestId('project-timeline-commit-toggle-a91b2c3d4e').click();
		await page.getByTestId('project-timeline-restore-a91b2c3d4e').click();
		await page.getByTestId('project-timeline-restore-confirm').click();
		await expect(page.getByTestId('project-timeline-restore-status')).toHaveAttribute('data-state', 'error');
	});

	// contract-test: supporting surface=gui.web assertions=projects.history.native-commits
	test('empty and error states', async ({ page }, testInfo) => {
		await open(page, 'empty');
		await expect(page.getByTestId('project-timeline-empty')).toHaveText('No changes yet');
		await shot(page, testInfo, 'timeline-empty');
		await open(page, 'error');
		await expect(page.getByTestId('project-timeline-error')).toContainText('history service');
		await expect(page.getByTestId('project-timeline-empty')).toHaveCount(0);
	});

	// contract-test: supporting surface=gui.web assertions=projects.history.native-commits
	test('renders in the dark theme', async ({ page }, testInfo) => {
		await open(page, undefined, 'dark');
		await expect(page.getByTestId('project-timeline-entry-v-styles')).toBeVisible({ timeout: 30_000 });
		await shot(page, testInfo, 'timeline-dark');
	});
});
