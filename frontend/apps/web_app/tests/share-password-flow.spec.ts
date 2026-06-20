/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Password-protected sharing E2E coverage.
 *
 * These tests isolate the shared-link password screens from AI/provider
 * flakiness by using deterministic encrypted share blobs and mocked share API
 * responses. They still exercise the real Svelte share pages and client-side
 * password decryption logic used by production links.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { webcrypto } = require('node:crypto');

const crypto = webcrypto as Crypto;
const PASSWORD = 'secret123';
const WRONG_PASSWORD = 'wrong123';

function randomKey(): Uint8Array {
	return crypto.getRandomValues(new Uint8Array(32));
}

function base64UrlEncode(data: Uint8Array): string {
	return Buffer.from(data)
		.toString('base64')
		.replace(/\+/g, '-')
		.replace(/\//g, '_')
		.replace(/=+$/, '');
}

function bytesToBase64(data: Uint8Array): string {
	return Buffer.from(data).toString('base64');
}

async function deriveAesKey(input: string, salt: string, usages: KeyUsage[]): Promise<CryptoKey> {
	const encoder = new TextEncoder();
	const material = await crypto.subtle.importKey('raw', encoder.encode(input), 'PBKDF2', false, [
		'deriveKey'
	]);
	return crypto.subtle.deriveKey(
		{ name: 'PBKDF2', salt: encoder.encode(salt), iterations: 100000, hash: 'SHA-256' },
		material,
		{ name: 'AES-GCM', length: 256 },
		false,
		usages
	);
}

async function encryptAesGcmUrlSafe(plaintext: string, key: CryptoKey): Promise<string> {
	const iv = crypto.getRandomValues(new Uint8Array(12));
	const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(plaintext));
	const combined = new Uint8Array(iv.length + ciphertext.byteLength);
	combined.set(iv);
	combined.set(new Uint8Array(ciphertext), iv.length);
	return base64UrlEncode(combined);
}

async function encryptAesGcmBase64(plaintext: string, rawKey: Uint8Array): Promise<string> {
	const key = await crypto.subtle.importKey('raw', rawKey, { name: 'AES-GCM' }, false, ['encrypt']);
	const iv = crypto.getRandomValues(new Uint8Array(12));
	const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(plaintext));
	const combined = new Uint8Array(iv.length + ciphertext.byteLength);
	combined.set(iv);
	combined.set(new Uint8Array(ciphertext), iv.length);
	return bytesToBase64(combined);
}

async function generateProtectedShareBlob(
	id: string,
	keyField: 'chat_encryption_key' | 'embed_encryption_key',
	contentKey: Uint8Array
): Promise<string> {
	const passwordKey = await deriveAesKey(PASSWORD, `openmates-pwd-${id}`, ['encrypt']);
	const encryptedContentKey = await encryptAesGcmUrlSafe(bytesToBase64(contentKey), passwordKey);
	const params = new URLSearchParams();
	params.set(keyField, encryptedContentKey);
	params.set('generated_at', String(Math.floor(Date.now() / 1000)));
	params.set('duration_seconds', '0');
	params.set('pwd', '1');

	const idKey = await deriveAesKey(id, 'openmates-share-v1', ['encrypt']);
	return encryptAesGcmUrlSafe(params.toString(), idKey);
}

test('password-protected shared chat requires the right password before opening', async ({ page }: { page: any }) => {
	const chatId = 'pw-chat-e2e';
	const chatKey = randomKey();
	const blob = await generateProtectedShareBlob(chatId, 'chat_encryption_key', chatKey);

	await page.route('**/v1/share/time', async (route: any) => {
		await route.fulfill({ json: { timestamp: Math.floor(Date.now() / 1000) } });
	});
	await page.route(`**/v1/share/chat/${chatId}/manifest`, async (route: any) => {
		await route.fulfill({ json: { chat_id: chatId, messages: [], embeds: [], embed_keys: [] } });
	});
	await page.route(`**/v1/share/chat/${chatId}/messages**`, async (route: any) => {
		await route.fulfill({ json: { messages: [], has_more: false } });
	});

	await page.goto(`/share/chat/${chatId}#key=${blob}`);
	await expect(page.getByTestId('shared-chat-password-form')).toBeVisible({ timeout: 15000 });

	await page.getByTestId('shared-chat-password-input').fill(WRONG_PASSWORD);
	await page.getByTestId('shared-chat-password-submit').click();
	await expect(page.getByTestId('shared-chat-password-error')).toContainText(/incorrect password/i);

	await page.getByTestId('shared-chat-password-input').fill(PASSWORD);
	await page.getByTestId('shared-chat-password-submit').click();
	await expect(page).toHaveURL(new RegExp(`#chat-id=${chatId}`), { timeout: 30000 });
});

test('password-protected shared embed requires the right password before opening', async ({ page }: { page: any }) => {
	const embedId = 'pw-embed-e2e';
	const embedKey = randomKey();
	const blob = await generateProtectedShareBlob(embedId, 'embed_encryption_key', embedKey);
	const encryptedContent = await encryptAesGcmBase64('title: Password protected test embed\nurl: https://example.com', embedKey);

	await page.route('**/v1/share/time', async (route: any) => {
		await route.fulfill({ json: { timestamp: Math.floor(Date.now() / 1000) } });
	});
	await page.route(`**/v1/share/embed/${embedId}`, async (route: any) => {
		await route.fulfill({
			json: {
				embed: {
					embed_id: embedId,
					embed_type: 'web-website',
					status: 'finished',
					encrypted_content: encryptedContent
				},
				child_embeds: [],
				embed_keys: [],
				code_run_outputs: []
			}
		});
	});

	await page.goto(`/share/embed/${embedId}#key=${blob}`);
	await expect(page.getByTestId('shared-embed-password-form')).toBeVisible({ timeout: 15000 });

	await page.getByTestId('shared-embed-password-input').fill(WRONG_PASSWORD);
	await page.getByTestId('shared-embed-password-submit').click();
	await expect(page.getByTestId('shared-embed-password-error')).toContainText(/invalid password/i);

	await page.getByTestId('shared-embed-password-input').fill(PASSWORD);
	await page.getByTestId('shared-embed-password-submit').click();
	await expect(page).toHaveURL(/\/$/, { timeout: 30000 });
});
