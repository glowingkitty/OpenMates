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

const CORS_HEADERS = {
	'access-control-allow-origin': '*',
	'access-control-allow-methods': 'POST, OPTIONS',
	'access-control-allow-headers': 'content-type'
};

function anonymousActiveServerStatusBody() {
	return {
		is_self_hosted: false,
		payment_enabled: true,
		server_edition: 'development',
		domain: 'app.dev.openmates.org',
		ai_models_configured: true,
		anonymous_free_usage: {
			active: true,
			reason: null,
			reset_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
			cta: 'Create an account to keep using OpenMates.'
		}
	};
}

async function mockAnonymousActiveServerStatus(page: any) {
	await page.route('**/v1/settings/server-status', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(anonymousActiveServerStatusBody())
		});
	});
}

test.describe('Anonymous free chat', () => {
	test('anonymous text chat shows terms reminder before send and feature notice in chat', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 390, height: 844 });
		await mockAnonymousActiveServerStatus(page);

		const anonymousRequests: Array<Record<string, unknown>> = [];
		await page.route('**/v1/anonymous/chat/stream', async (route: any) => {
			if (route.request().method() === 'OPTIONS') {
				await route.fulfill({
					status: 204,
					headers: CORS_HEADERS
				});
				return;
			}
			const body = JSON.parse(route.request().postData() || '{}') as Record<string, unknown>;
			anonymousRequests.push(body);
			const responseNumber = anonymousRequests.length;
			await route.fulfill({
				status: 200,
				headers: CORS_HEADERS,
				contentType: 'application/json',
				body: JSON.stringify({
					status: 'completed',
					messageId: `anonymous-assistant-${responseNumber}`,
					assistant: `Anonymous answer ${responseNumber}`,
					category: 'ai',
					modelName: 'test-model'
				})
			});
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
		await page.keyboard.insertText('Hello anonymous text');
		const termsReminder = page.getByTestId('anonymous-terms-reminder');
		await expect(termsReminder).toBeVisible({ timeout: 5000 });
		await expect(termsReminder).toContainText(
			'By sending a message you accept the terms & privacy policy of OpenMates.'
		);
		await page.locator('[data-action="send-message"]').click();

		await expect(termsReminder).toHaveCount(0);
		await expect(
			page.getByTestId('message-system').filter({
				hasText: 'You are using free anonymous credits.'
			})
		).toBeVisible({ timeout: 10000 });
		await expect(
			page.getByTestId('message-system').filter({
				hasText: 'By sending a message you accept the terms'
			})
		).toHaveCount(0);
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'Anonymous answer 1' })).toBeVisible({
			timeout: 10000
		});

		expect(anonymousRequests).toHaveLength(1);
		expect(anonymousRequests[0].plaintext_message).toBe('Hello anonymous text');
		expect(anonymousRequests[0].message_history).toEqual([]);

		await editor.click();
		await page.keyboard.insertText('Second anonymous text');
		await page.locator('[data-action="send-message"]').click();
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'Anonymous answer 2' })).toBeVisible({
			timeout: 10000
		});

		expect(anonymousRequests).toHaveLength(2);
		expect(JSON.stringify(anonymousRequests[1].message_history)).not.toContain(
			'By sending a message you accept the terms'
		);
		expect(JSON.stringify(anonymousRequests[1].message_history)).not.toContain(
			'You are using free anonymous credits.'
		);
		expect(anonymousRequests[1].message_history).toEqual([
			expect.objectContaining({ role: 'user', content: 'Hello anonymous text' }),
			expect.objectContaining({ role: 'assistant', content: 'Anonymous answer 1' })
		]);

		const encryptedPayload = await page.evaluate(() => localStorage.getItem('openmates_anonymous_chats_v1'));
		expect(encryptedPayload).toBeTruthy();
		expect(encryptedPayload).not.toContain('Hello anonymous text');
		expect(encryptedPayload).not.toContain('Anonymous answer 1');
		expect(encryptedPayload).not.toContain('By sending a message you accept the terms');
		expect(encryptedPayload).not.toContain('You are using free anonymous credits.');

		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'Anonymous answer 2' })).toBeVisible({
			timeout: 10000
		});

		await page.evaluate(() => sessionStorage.removeItem('openmates_anonymous_chat_key'));
		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect
			.poll(() => page.evaluate(() => localStorage.getItem('openmates_anonymous_chats_v1')))
			.toBeNull();
		await assertNoMissingTranslations(page);
	});

	test('anonymous file attachment is signup-gated without uploading file bytes', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 390, height: 844 });
		await mockAnonymousActiveServerStatus(page);

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
		await page.keyboard.insertText('Please summarize this image after I sign up.');
		await expect(editor).toContainText('Please summarize this image after I sign up.');

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
