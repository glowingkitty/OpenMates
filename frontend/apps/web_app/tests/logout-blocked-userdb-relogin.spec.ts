/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * R4SF3: an open IndexedDB connection in another tab can block logout's
 * user_db deletion. The next login must recover the real account profile and
 * server chat list once that connection closes.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage } = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

async function openSettings(page: any): Promise<any> {
	const settings = page.locator('[data-testid="settings-menu"].visible');
	if (!(await settings.isVisible().catch(() => false))) {
		await page.getByTestId('profile-container').click();
	}
	await expect(settings).toBeVisible({ timeout: 10000 });
	await expect(settings).toHaveAttribute('data-active-view', 'main');
	return settings;
}

async function openChatList(page: any): Promise<void> {
	const activity = page.getByTestId('activity-history-wrapper');
	if (!(await activity.isVisible().catch(() => false))) {
		await page.getByTestId('sidebar-toggle').click();
	}
	await expect(activity).toBeVisible({ timeout: 15000 });
}

async function readProfile(page: any): Promise<{ username: string; credits: number | null }> {
	const settings = await openSettings(page);
	const username = (await settings.locator('.settings-main-header .username-label').textContent())?.trim() || '';
	// Isolated self-hosted CI has no billing display; hosted accounts do.
	const creditsAmount = settings.getByTestId('credits-amount');
	const creditsText = (await creditsAmount.count()) > 0 ? (await creditsAmount.textContent()) || '' : '';
	const credits = creditsText ? Number.parseInt(creditsText.replace(/[^\d]/g, ''), 10) : null;
	expect(username, 'authenticated profile must show the account name').not.toBe('');
	expect(username, 'authenticated profile must not fall back to Guest').not.toBe('Guest');
	if (credits !== null) {
		expect(credits, 'hosted account must show its positive server credit balance').toBeGreaterThan(0);
	}
	return { username, credits };
}

// contract-test: direct surface=gui.web assertions=auth.session.lifecycle,sync.startup.bounded-phases,chats.persistence.client-encrypted
test('blocked cross-tab user_db deletion recovers profile and recent chats after re-login', async ({
	page,
	context
}: {
	page: any;
	context: any;
}) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const storageErrors: string[] = [];
	page.on('console', (message: any) => {
		const text = message.text();
		if (message.type() === 'error' && /NotFoundError|object store.*does not exist/i.test(text)) {
			storageErrors.push(text);
		}
	});
	page.on('pageerror', (error: Error) => {
		if (/NotFoundError|object store.*does not exist/i.test(error.message)) {
			storageErrors.push(error.message);
		}
	});

	await loginToTestAccount(page, undefined, undefined, { waitForEditor: true });
	// Isolated CI provisions a fresh account. Create a real encrypted server chat
	// before deleting local chat storage so Phase 2 has metadata to restore.
	const seedPrompt = 'R4SF3 recent chat fixture';
	const logSeed = (message: string, metadata?: Record<string, unknown>) => {
		console.log(`[R4SF3 seed] ${message}`, metadata ?? '');
	};
	await startNewChat(page, logSeed);
	const fixtureMarker = withMockMarker(seedPrompt, 'explain_in_new_chat_seed')
		.match(/<<<TEST_MOCK:[^>]+>>>$/)?.[0];
	expect(fixtureMarker, 'the isolated browser test needs a standalone mock marker').toBeTruthy();
	await sendMessage(page, seedPrompt, logSeed, undefined, 'r4sf3-seed', {
		testMockMarker: fixtureMarker
	});
	await openChatList(page);
	const recentChat = page.locator(
		'[data-testid="chat-item-wrapper"][data-chat-id]:not([data-chat-id^="demo-"]):not([data-chat-id^="legal-"])'
	).first();
	await expect(recentChat).toBeVisible({ timeout: 30000 });
	const recentChatId = await recentChat.getAttribute('data-chat-id');
	expect(recentChatId, 'a real synced chat must be available before logout').toBeTruthy();
	const originalProfile = await readProfile(page);

	const holder = await context.newPage();
	try {
		const holderUrl = new URL('/e2e-user-db-holder', page.url()).toString();
		await holder.route(holderUrl, (route: any) => route.fulfill({
			contentType: 'text/html',
			body: '<!doctype html><title>IndexedDB connection holder</title>'
		}));
		await holder.goto(holderUrl);
		const heldStorePresent = await holder.evaluate(async () => {
			const db = await new Promise<IDBDatabase>((resolve, reject) => {
				const request = indexedDB.open('user_db');
				request.onsuccess = () => resolve(request.result);
				request.onerror = () => reject(request.error);
			});
			const holderWindow = window as unknown as {
				__r4sf3UserDb?: IDBDatabase;
				__r4sf3VersionChangeSeen?: boolean;
			};
			holderWindow.__r4sf3UserDb = db;
			holderWindow.__r4sf3VersionChangeSeen = false;
			db.onversionchange = () => {
				holderWindow.__r4sf3VersionChangeSeen = true;
			};
			return db.objectStoreNames.contains('user_data');
		});
		expect(heldStorePresent, 'the second tab must hold the existing account database').toBe(true);

		await page.getByRole('menuitem', { name: /logout|abmelden/i }).click();
		await expect(page.locator('[data-authenticated="true"]')).toHaveCount(0, { timeout: 15000 });
		await expect.poll(() => holder.evaluate(() => Boolean(
			(window as unknown as { __r4sf3VersionChangeSeen?: boolean }).__r4sf3VersionChangeSeen
		)), {
			timeout: 15000,
			message: 'the second tab should receive the real logout user_db deletion request'
		}).toBe(true);

		await holder.evaluate(() => {
			const holderWindow = window as unknown as { __r4sf3UserDb?: IDBDatabase };
			holderWindow.__r4sf3UserDb?.close();
			delete holderWindow.__r4sf3UserDb;
		});
		await expect.poll(() => page.evaluate(() => localStorage.getItem('openmates_user_db_initialized')), {
			timeout: 15000,
			message: 'logout should finish removing the old user database after the other tab closes it'
		}).toBeNull();
	} finally {
		await holder.close();
	}

	const syncFrames: string[] = [];
	page.on('websocket', (socket: any) => {
		socket.on('framereceived', (frame: any) => {
			try {
				const payload = JSON.parse(String(frame.payload));
				const type = payload?.type || payload?.event;
				if (typeof type === 'string') syncFrames.push(type);
			} catch {
				// Binary and non-JSON frames are unrelated to phased chat sync.
			}
		});
	});
	await loginToTestAccount(page, undefined, undefined, { waitForEditor: true });
	const recoveredProfile = await readProfile(page);
	expect(recoveredProfile).toEqual(originalProfile);
	await expect.poll(() => syncFrames.includes('phase_2_last_20_chats_ready'), {
		timeout: 30000,
		message: 'fresh login should finish recent-chat metadata sync'
	}).toBe(true);
	await page.getByTestId('icon-button-close').click();
	// The reported stale September 12 entry appeared in this carousel, so
	// confirm the newly created account chat returns here after Phase 2.
	await page.evaluate(() => (document.activeElement as HTMLElement)?.blur?.());
	await expect(page.getByTestId('recent-chats-scroll-container').locator(
		`[data-chat-id="${recentChatId}"]`
	)).toBeVisible({ timeout: 30000 });
	await openChatList(page);
	await expect(page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${recentChatId}"]`)).toBeVisible({
		timeout: 30000
	});
	expect(storageErrors, 'login and sync must not hit a missing user_data store').toEqual([]);
});
