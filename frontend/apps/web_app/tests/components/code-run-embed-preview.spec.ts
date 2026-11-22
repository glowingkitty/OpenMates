// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import type { Page } from '@playwright/test';

const PREVIEW = '/dev/preview/embeds/code/CodeRunEmbedPreview';

async function open(page: Page, variant?: string) {
	const query = new URLSearchParams({ theme: 'light', width: '600', chrome: '0' });
	if (variant) query.set('variant', variant);
	await page.goto(`${PREVIEW}?${query}`, { waitUntil: 'domcontentloaded' });
	await waitForComponentPreview(page);
}

test.describe('code run (cloud command) preview card', () => {
	// contract-test: supporting surface=gui.web assertions=code-run.cloud.commands
	test('finished command shows the command line, exit code and the server icon', async ({ page }, testInfo) => {
		await open(page);
		await expect(page.getByTestId('code-run-command')).toHaveText('$ cd web-app && npm run build');
		await expect(page.getByTestId('code-run-result')).toHaveText('exit 0 · 4.2 s');
		await expect(page.getByText('exit 0 · 4.2 s'), 'the exit line is shown once, not also in the header').toHaveCount(1);
		await expect(page.getByTestId('code-run-output'), 'the result line shows the end of the output').toContainText('built in 143ms');
		await expect(page.locator('[data-skill-icon="server"]').first()).toBeVisible();
		await expect(page.locator('[data-skill-icon="ai"]')).toHaveCount(0);
		await testInfo.attach('code-run-finished', { body: await page.screenshot(), contentType: 'image/png' });
	});

	// contract-test: supporting surface=gui.web assertions=code-run.cloud.commands
	test('running command already shows what is being run', async ({ page }, testInfo) => {
		await open(page, 'running');
		await expect(page.getByTestId('code-run-command')).toHaveText('$ cd web-app && npm run build');
		await expect(page.getByTestId('code-run-details')).toHaveAttribute('data-run-status', 'processing');
		await expect(page.getByTestId('code-run-result')).toHaveCount(0);
		await expect(page.getByTestId('code-run-output')).toHaveCount(0);
		await testInfo.attach('code-run-running', { body: await page.screenshot(), contentType: 'image/png' });
	});

	// contract-test: supporting surface=gui.web assertions=code-run.cloud.commands
	test('failed command shows the failure and its exit code', async ({ page }, testInfo) => {
		await open(page, 'failed');
		await expect(page.getByTestId('code-run-command')).toContainText('npx playwright test');
		await expect(page.getByTestId('code-run-result')).toContainText('exit 1');
		await testInfo.attach('code-run-failed', { body: await page.screenshot(), contentType: 'image/png' });
	});
});
