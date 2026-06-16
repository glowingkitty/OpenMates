/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Anonymous free chat web contract tests.
 *
 * These specs run against app.dev.openmates.org through scripts/run_tests.py.
 * They cover the web-only browser behavior for anonymous free usage before the
 * broader backend anonymous streaming path is fully enabled.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl, assertNoMissingTranslations } = require('./signup-flow-helpers');

test.describe('Anonymous free chat', () => {
	test('anonymous file attachment is signup-gated without uploading file bytes', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 390, height: 844 });

		const uploadRequests: string[] = [];
		page.on('request', (request: any) => {
			const url = request.url();
			if (
				url.includes('/upload') ||
				url.includes('/uploads') ||
				url.includes('/embeds') ||
				url.includes('/anonymous/chat/stream')
			) {
				uploadRequests.push(`${request.method()} ${url}`);
			}
		});

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
			timeout: 15000
		});
		await page.getByTestId('new-chat-cta-fullwidth').click();

		const editor = page.getByTestId('message-editor');
		await expect(editor).toBeVisible({ timeout: 10000 });
		await editor.click();
		await page.keyboard.type('Please summarize this image after I sign up.');

		await page.getByTestId('message-file-input').setInputFiles({
			name: 'anonymous-upload.png',
			mimeType: 'image/png',
			buffer: Buffer.from([0x89, 0x50, 0x4e, 0x47])
		});

		const banner = page.getByTestId('anonymous-upload-signup-banner');
		await expect(banner).toBeVisible({ timeout: 5000 });
		await expect(banner).toContainText('Create an account to upload files');
		await expect(page.locator('[data-action="sign-up-to-send"]')).toBeVisible({ timeout: 5000 });
		await expect(page.locator('[data-action="send-message"]')).toHaveCount(0);
		await expect(editor).toContainText('Please summarize this image after I sign up.');

		await expect.poll(() => uploadRequests).toEqual([]);

		await page.getByTestId('anonymous-upload-signup-remove').click();
		await expect(banner).toHaveCount(0);
		await expect(page.locator('[data-action="send-message"]')).toBeVisible({ timeout: 5000 });
		await assertNoMissingTranslations(page);
	});
});
