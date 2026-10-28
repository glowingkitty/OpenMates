/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Settings deep-link checks.
 *
 * Verifies the deployed web app opens nested settings destinations from a cold
 * hash navigation. These links are intentionally hash-based so the selected
 * settings page remains client-side after the initial document request.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { createSignupLogger, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { focusComposer } = require('./helpers/composer-focus');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const EXPECTED_SETTINGS_VIEW = 'privacy/hide-personal-data';
const EXPECTED_ACCOUNT_DELETE_VIEW = 'account/delete';

async function expectHidePersonalDataSettings(page: any): Promise<void> {
	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toBeVisible({ timeout: 20000 });
	await expect(settingsMenu).toHaveAttribute('data-active-view', EXPECTED_SETTINGS_VIEW, {
		timeout: 20000
	});
	await expect.poll(() => new URL(page.url()).search, {
		message: 'settings deep links must not add query parameters',
		timeout: 5000
	}).toBe('');
}

async function expectAccountDeleteSettings(page: any): Promise<void> {
	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toBeVisible({ timeout: 20000 });
	await expect(settingsMenu).toHaveAttribute('data-active-view', EXPECTED_ACCOUNT_DELETE_VIEW, {
		timeout: 20000
	});
	await expect(page.getByTestId('delete-account-container')).toBeVisible({ timeout: 20000 });
}

type PrivacyEntry = { id: string; item_key: string; item_version: number; encrypted_item_json: string };

/** Observe the real encrypted write and its server persistence acknowledgment. */
function observePrivacyPersistence(page: import('@playwright/test').Page) {
	const writes: PrivacyEntry[] = [];
	const stored: Array<{ entry_id: string; item_key: string }> = [];
	const synced: PrivacyEntry[] = [];
	page.on('websocket', socket => {
		socket.on('framesent', ({ payload }) => {
			try {
				const frame = JSON.parse(String(payload));
				const entry = frame.payload?.entry;
				if (frame.type === 'store_app_settings_memories_entry' && entry?.app_id === 'privacy'
					&& entry.item_type === 'pii_detection_settings') writes.push(entry);
			} catch { /* Non-JSON transport control frames are unrelated. */ }
		});
		socket.on('framereceived', ({ payload }) => {
			try {
				const frame = JSON.parse(String(payload));
				if (frame.type === 'app_settings_memories_entry_stored' && frame.payload?.app_id === 'privacy'
					&& frame.payload.success === true) stored.push(frame.payload);
				if (frame.type === 'app_settings_memories_sync_ready') {
					for (const entry of frame.payload?.entries ?? []) {
						if (entry.app_id === 'privacy' && entry.item_type === 'pii_detection_settings') synced.push(entry);
					}
				}
			} catch { /* Non-JSON transport control frames are unrelated. */ }
		});
	});
	return { writes, stored, synced };
}

async function setPersistedPrivacyToggle(
	page: import('@playwright/test').Page,
	input: import('@playwright/test').Locator,
	clickTarget: import('@playwright/test').Locator,
	checked: boolean,
	protocol: ReturnType<typeof observePrivacyPersistence>,
): Promise<PrivacyEntry | undefined> {
	await expect(input).toBeEnabled({ timeout: 30000 });
	if (await input.isChecked() === checked) return undefined;
	const writeStart = protocol.writes.length;
	const ackStart = protocol.stored.length;
	await clickTarget.click();
	await expect(input).toBeChecked({ checked });
	await expect.poll(() => protocol.writes.length, { message: 'Encrypted privacy write must leave the browser', timeout: 30000 }).toBeGreaterThan(writeStart);
	const entry = protocol.writes[writeStart];
	expect({ encrypted: typeof entry.encrypted_item_json === 'string' && entry.encrypted_item_json.length > 0,
		containsPlaintextPreference: entry.encrypted_item_json.includes('enhancedEnabled') }).toEqual({ encrypted: true, containsPlaintextPreference: false });
	await expect.poll(() => protocol.stored.slice(ackStart).some(ack => ack.entry_id === entry.id && ack.item_key === entry.item_key), {
		message: 'Server must acknowledge persistence of this exact encrypted privacy entry', timeout: 30000,
	}).toBe(true);
	await expect.poll(() => page.evaluate(async expected => {
		const db = await new Promise<IDBDatabase>((resolve, reject) => {
			const open = indexedDB.open('chats_db'); open.onsuccess = () => resolve(open.result); open.onerror = () => reject(open.error);
		});
		try {
			return await new Promise<boolean>((resolve, reject) => {
				const request = db.transaction('app_settings_memories', 'readonly').objectStore('app_settings_memories').get(expected.id);
				request.onsuccess = () => resolve(request.result?.encrypted_item_json === expected.encrypted_item_json
					&& request.result?.item_version === expected.item_version);
				request.onerror = () => reject(request.error);
			});
		} finally { db.close(); }
	}, entry), { message: 'IndexedDB must contain the acknowledged encrypted preference version', timeout: 15000 }).toBe(true);
	return entry;
}

test.describe('settings deep links', () => {
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	// contract-test: supporting surface=gui.web assertions=settings-ui.shell.lifecycle-and-routing
	test('opens Hide personal data from hash aliases and /privacy/pii', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(180000);

		const log = createSignupLogger('SETTINGS_PRIVACY_PII_DEEP_LINK');
		await loginToTestAccount(page, log);

		for (const path of ['/#settings/privacy/hide-personal-data', '/#settings/privacy/pii']) {
			log(`Checking settings deep link: ${path}`);
			await page.goto(getE2EDebugUrl(path), { waitUntil: 'domcontentloaded' });
			await expectHidePersonalDataSettings(page);
		}

		log('Checking settings short URL redirect: /privacy/pii');
		const privacyPiiUrl = new URL('/privacy/pii', page.url()).toString();
		const redirectResponse = await page.request.get(privacyPiiUrl, { maxRedirects: 0 });
		expect(redirectResponse.status()).toBe(302);
		expect(redirectResponse.headers().location).toBe('/#settings/privacy/pii');

		await page.goto(getE2EDebugUrl('/#settings/privacy/pii'), { waitUntil: 'domcontentloaded' });
		await expectHidePersonalDataSettings(page);
	});

	// contract-test: supporting surface=gui.web assertions=settings-ui.shell.lifecycle-and-routing
	test('opens Delete account from a cold authenticated hash navigation', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(180000);

		const log = createSignupLogger('SETTINGS_ACCOUNT_DELETE_DEEP_LINK');
		await loginToTestAccount(page, log);

		await page.goto(getE2EDebugUrl('/#settings/account/delete'), { waitUntil: 'domcontentloaded' });
		await expectAccountDeleteSettings(page);
	});

	// contract-test: direct surface=gui.web assertions=pii.web.enhanced-default-and-opt-out,pii.web.local-bounded-inference,pii.composer.detect-redact-exclude
	test('restores an authenticated encrypted enhanced opt-out before cold settings and composer startup', async ({ page }: { page: import('@playwright/test').Page }) => {
		test.setTimeout(270000);
		const log = createSignupLogger('SETTINGS_PRIVACY_ENHANCED_OFF');
		const protocol = observePrivacyPersistence(page);
		let observeOff = false;
		const runtimeRequests: string[] = [];
		const vendorRequests: string[] = [];
		page.on('request', request => {
			if (!observeOff) return;
			const url = new URL(request.url());
			if (url.pathname.startsWith('/pii-runtime/')) runtimeRequests.push(url.pathname);
			if (url.hostname === 'desertant.com' || url.hostname.endsWith('.desertant.com')) vendorRequests.push(url.hostname);
		});
		await page.addInitScript(() => {
			const state = window as typeof window & { __piiSettingsWorkerStarts: number };
			state.__piiSettingsWorkerStarts = 0;
			window.Worker = new Proxy(window.Worker, {
				construct(target, args, newTarget) {
					if (new URL(String(args[0]), location.href).pathname.startsWith('/pii-runtime/')) state.__piiSettingsWorkerStarts += 1;
					return Reflect.construct(target, args, newTarget);
				},
			});
		});
		const expectNoOffModelActivity = async () => {
			expect(runtimeRequests, 'Opt-out must prevent worker and model asset requests').toEqual([]);
			expect(vendorRequests, 'Opt-out must prevent provider licensing traffic').toEqual([]);
			expect(await page.evaluate(() => (window as typeof window & { __piiSettingsWorkerStarts: number }).__piiSettingsWorkerStarts),
				'Opt-out must prevent worker construction even when its script is cached').toBe(0);
		};
		await loginToTestAccount(page, log);
		await page.goto(getE2EDebugUrl('/#settings/privacy/hide-personal-data'), { waitUntil: 'domcontentloaded' });
		await expectHidePersonalDataSettings(page);
		const enhancedRow = page.getByTestId('enhanced-personal-data-protection');
		const enhancedInput = enhancedRow.getByRole('checkbox');
		const enhancedToggle = enhancedRow.getByTestId('enhanced-personal-data-protection-toggle');
		const masterRow = page.getByTestId('personal-data-master-protection');
		const masterInput = masterRow.getByRole('checkbox');
		const masterToggle = masterRow.getByTestId('personal-data-master-protection-toggle');
		try {
			// This CI account is leased exclusively to this spec by the runner.
			await setPersistedPrivacyToggle(page, masterInput, masterToggle, true, protocol);
			await setPersistedPrivacyToggle(page, enhancedInput, enhancedToggle, true, protocol);
			const offEntry = await setPersistedPrivacyToggle(page, enhancedInput, enhancedToggle, false, protocol);
			expect(offEntry, 'The test must create and acknowledge its own encrypted off version').toBeDefined();
			observeOff = true;
			await page.evaluate(() => { (window as typeof window & { __piiSettingsWorkerStarts: number }).__piiSettingsWorkerStarts = 0; });
			await page.reload({ waitUntil: 'domcontentloaded' });
			await expectHidePersonalDataSettings(page);
			await expect(enhancedInput).toBeEnabled({ timeout: 30000 });
			await expect(enhancedInput).not.toBeChecked();
			await expect(masterInput).toBeChecked();
			await expectNoOffModelActivity();

			// Remove only this test account's acknowledged cached singleton. The
			// next document must restore the real server ciphertext before warming.
			await page.evaluate(async id => {
				const db = await new Promise<IDBDatabase>((resolve, reject) => {
					const open = indexedDB.open('chats_db'); open.onsuccess = () => resolve(open.result); open.onerror = () => reject(open.error);
				});
				try {
					await new Promise<void>((resolve, reject) => {
						const transaction = db.transaction('app_settings_memories', 'readwrite');
						transaction.objectStore('app_settings_memories').delete(id);
						transaction.oncomplete = () => resolve(); transaction.onerror = () => reject(transaction.error);
						transaction.onabort = () => reject(transaction.error);
					});
				} finally { db.close(); }
			}, offEntry!.id);
			const syncStart = protocol.synced.length;
			await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
			await expect.poll(() => protocol.synced.slice(syncStart).some(entry => entry.id === offEntry!.id
				&& entry.item_version === offEntry!.item_version && entry.encrypted_item_json === offEntry!.encrypted_item_json), {
				message: 'Cold account sync must restore this acknowledged encrypted off version', timeout: 60000,
			}).toBe(true);
			await focusComposer(page);
			const editor = page.getByTestId('message-editor').getByRole('textbox');
			await editor.fill('Email private.reference@example.net about the schedule.');
			await expect(page.getByTestId('pii-highlight').filter({ hasText: 'private.reference@example.net' }))
				.toHaveAttribute('data-pii-type', 'EMAIL', { timeout: 15000 });
			await expect(page.getByTestId('pii-model-status')).toHaveCount(0);
			await expectNoOffModelActivity();
			await editor.fill('');
			await page.evaluate(() => { location.hash = 'settings/privacy/hide-personal-data'; });
			await expectHidePersonalDataSettings(page);
			await expect(enhancedInput).toBeEnabled({ timeout: 30000 });
			await expect(enhancedInput).not.toBeChecked();
			await expect(masterInput).toBeChecked();
			await expectNoOffModelActivity();
		} finally {
			const draftEditor = page.getByTestId('message-editor').getByRole('textbox');
			if (await draftEditor.isVisible().catch(() => false)
				&& await draftEditor.textContent() === 'Email private.reference@example.net about the schedule.') await draftEditor.fill('');
			observeOff = false;
			await page.goto(getE2EDebugUrl('/#settings/privacy/hide-personal-data'), { waitUntil: 'domcontentloaded' });
			await expectHidePersonalDataSettings(page);
			await setPersistedPrivacyToggle(page, masterInput, masterToggle, true, protocol);
			await setPersistedPrivacyToggle(page, enhancedInput, enhancedToggle, true, protocol);
		}
	});
});
