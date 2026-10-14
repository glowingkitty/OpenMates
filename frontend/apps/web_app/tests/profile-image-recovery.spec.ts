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
	test.afterEach(async ({ page }: { page: Page }) => {
		// Session masking can still be fetching when the assertions finish. Drain
		// those handlers before Playwright closes the context, including on failure.
		await page.unrouteAll({ behavior: 'wait' });
	});

	// contract-test: direct surface=gui.web assertions=auth.session.lifecycle,settings-ui.composition.canonical-and-accessible
	test('reuses missing-image results and recovers an uploaded private image after reload', async ({ page }: { page: Page }) => {
		test.setTimeout(180000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		// A fresh account normally has no image. Count completed missing-image
		// requests across remounts, then let the real upload replace that absence.
		let missingImageRequests = 0;
		const imageRoute = '**/v1/users/*/profile-image';
		await page.route(imageRoute, async (route: any) => {
			missingImageRequests += 1;
			await route.fulfill({ status: 404, json: { detail: 'No profile image' } });
		});
		const missingResponse = page.waitForResponse(response =>
			response.url().includes('/profile-image') && response.status() === 404);
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);
		await missingResponse;
		await page.getByTestId('profile-container').click();
		await expect(page.getByTestId('settings-menu')).toBeVisible({ timeout: 15000 });
		await page.getByRole('button', { name: /^profile picture$/i }).click();
		const upload = page.locator('.profile-picture-container input[type="file"]');
		await expect(upload).toHaveCount(1);
		for (let remount = 0; remount < 2; remount += 1) {
			await page.getByTestId('settings-menu').getByTestId('banner-back-button').click();
			await expect(upload).toHaveCount(0);
			// Back returns to Account, whose entries are menuitems rather than
			// the main settings header's avatar button used on first entry.
			await page.getByTestId('settings-menu').getByTestId('menu-item')
				.filter({ has: page.getByText('Profile picture', { exact: true }) }).click();
			await expect(upload).toHaveCount(1);
			// Settle the remounted Svelte effect before inspecting network count.
			await page.evaluate(() => new Promise<void>(resolve =>
				requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
		}
		expect(missingImageRequests).toBe(1);
		await expect(page.getByTestId('profile-picture').first().locator('img.profile-picture-avatar'))
			.toHaveCount(0);
		await page.unroute(imageRoute);
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
