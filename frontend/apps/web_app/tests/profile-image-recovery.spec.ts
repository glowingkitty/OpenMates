/* eslint-disable @typescript-eslint/no-require-imports */
export {};

import path from 'node:path';
import type { Page } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

async function expectLoadedAvatar(page: Page): Promise<void> {
	const avatar = page.getByTestId('profile-picture').first().locator('img.profile-picture-avatar');
	await expect(avatar).toBeVisible({ timeout: 20000 });
	await expect.poll(() => avatar.evaluate((image: HTMLImageElement) => image.naturalWidth),
		{ timeout: 20000 }).toBeGreaterThan(0);
}

test.describe('Personal profile picture recovery', () => {
	// contract-test: direct surface=gui.web assertions=auth.session.lifecycle,settings-ui.composition.canonical-and-accessible
	test('shows an uploaded private image after reload even when session metadata omits its URL', async ({ page }: { page: Page }) => {
		test.setTimeout(180000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);
		await page.getByTestId('profile-container').click();
		await expect(page.getByTestId('settings-menu')).toBeVisible({ timeout: 15000 });
		await page.getByRole('button', { name: /^profile picture$/i }).click();
		const upload = page.locator('.profile-picture-container input[type="file"]');
		await expect(upload).toHaveCount(1);
		await upload.setInputFiles(path.join(__dirname, 'fixtures', 'finance.jpeg'));
		await expect(page.locator('.profile-picture-container .success-message'))
			.toBeVisible({ timeout: 60000 });
		await expectLoadedAvatar(page);

		// Model the stale local profile snapshot observed on the dev account.
		// The reload must recover from both local and session URL omissions.
		await page.evaluate(async () => {
			const database = await new Promise<IDBDatabase>((resolve, reject) => {
				const request = indexedDB.open('user_db');
				request.onsuccess = () => resolve(request.result);
				request.onerror = () => reject(request.error);
			});
			try {
				await new Promise<void>((resolve, reject) => {
					const transaction = database.transaction('user_data', 'readwrite');
					transaction.objectStore('user_data').put(null, 'profile_image_url');
					transaction.oncomplete = () => resolve();
					transaction.onerror = () => reject(transaction.error);
				});
			} finally {
				database.close();
			}
		});

		await page.route('**/v1/auth/session*', async (route: any) => {
			const response = await route.fetch();
			const body = await response.json();
			if (body.success && body.user) {
				body.user.profile_image_url = null;
			}
			await route.fulfill({ response, json: body });
		});
		await page.reload({ waitUntil: 'domcontentloaded' });
		await expectLoadedAvatar(page);
		const storedImageUrl = await page.evaluate(async () => {
			const database = await new Promise<IDBDatabase>((resolve, reject) => {
				const request = indexedDB.open('user_db');
				request.onsuccess = () => resolve(request.result);
				request.onerror = () => reject(request.error);
			});
			try {
				return await new Promise<string | null>((resolve, reject) => {
					const request = database.transaction('user_data').objectStore('user_data').get('profile_image_url');
					request.onsuccess = () => resolve(request.result ?? null);
					request.onerror = () => reject(request.error);
				});
			} finally {
				database.close();
			}
		});
		expect(storedImageUrl).toBeNull();
	});
});
