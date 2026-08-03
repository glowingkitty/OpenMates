/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Deployed media reader compatibility contract.
 *
 * The preview route exercises production image fetch/decrypt/render code with
 * deterministic encrypted bytes. The shared-link case preserves the shipped
 * six-character legacy resolver contract without mutating backend state.
 */

const { test, expect } = require('./helpers/cookie-audit');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const LEGACY_SHORT_LINK = `${BASE_URL}/s/zuygP79v#BUw56h`;
const KEY = Buffer.from('000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f', 'hex');
const NONCE = Buffer.from('000102030405060708090a0b', 'hex');
const SAMPLE_IMAGE = path.join(__dirname, 'fixtures', 'sample.png');

function encryptImage(plaintext: Buffer, noncePrefixed: boolean): Buffer {
	const cipher = crypto.createCipheriv('aes-256-gcm', KEY, NONCE);
	const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final(), cipher.getAuthTag()]);
	return noncePrefixed ? Buffer.concat([NONCE, ciphertext]) : ciphertext;
}

test('renders frozen legacy and explicit v2 encrypted media', async ({ page }: { page: any }) => {
	const plaintext = fs.readFileSync(SAMPLE_IMAGE);
	const encryptedMedia = new Map([
		['legacy.png', encryptImage(plaintext, false)],
		['v2.png', encryptImage(plaintext, true)]
	]);
	const consoleErrors: string[] = [];
	page.on('console', (message: any) => {
		if (message.type() === 'error') consoleErrors.push(message.text());
	});

	await page.route('**/v1/embeds/presigned-url**', async (route: any) => {
		const s3Key = new URL(route.request().url()).searchParams.get('s3_key') || '';
		const filename = s3Key.split('/').pop();
		if (!filename || !encryptedMedia.has(filename)) return route.continue();
		await route.fulfill({
			contentType: 'application/json',
			body: JSON.stringify({ url: `${BASE_URL}/__e2e/media-encryption/${filename}` })
		});
	});
	await page.route('**/__e2e/media-encryption/*', async (route: any) => {
		const filename = new URL(route.request().url()).pathname.split('/').pop();
		const body = filename ? encryptedMedia.get(filename) : undefined;
		if (!body) return route.abort();
		await route.fulfill({ status: 200, contentType: 'application/octet-stream', body });
	});

	await page.goto(`${BASE_URL}/dev/preview/embeds/images`);
	for (const accessibleName of ['legacy-encrypted.png', 'v2-encrypted.png']) {
		const card = page.getByRole('button', { name: new RegExp(accessibleName) }).first();
		await card.scrollIntoViewIfNeeded();
		const image = card.getByRole('img', { name: accessibleName });
		await expect(image).toBeVisible({ timeout: 30000 });
		await expect(image).toHaveAttribute('src', /^blob:/);
		await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.complete && node.naturalWidth > 0)).toBe(true);
	}
	await expect(page.getByText(/AES-GCM media decryption failed|Unsupported media encryption marker/)).not.toBeVisible();
	expect(consoleErrors.filter((message) => /media decryption|unsupported media encryption/i.test(message))).toEqual([]);
});

test('resolves the deployed six-character legacy shared link', async ({ page }: { page: any }) => {
	test.slow();
	await page.goto(LEGACY_SHORT_LINK);
	await expect(page).toHaveURL(/#chat-id=/, { timeout: 60000 });
	await expect(page.getByTestId('chat-header-banner').getByTestId('shared-chat-badge')).toHaveText('Shared chat');
	await expect(page.getByText('[Content decryption failed]')).not.toBeVisible();
});
