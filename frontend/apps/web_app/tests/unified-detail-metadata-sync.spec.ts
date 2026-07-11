/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Multi-device metadata contract for an owned encrypted Chat.
 *
 * The test creates one uniquely owned chat, observes authoritative metadata
 * versions from server WebSocket messages, and deletes only that exact chat.
 */

export {};

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount, sendMessage, startNewChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount, withMockMarker } = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

type ServerMetadataVersion = {
	chatId: string;
	type: string;
	version: number;
};

function captureServerMetadataVersions(page: any, versions: ServerMetadataVersion[]): void {
	page.on('websocket', (websocket: any) => {
		websocket.on('framereceived', (frame: any) => {
			try {
				const message = JSON.parse(String(frame.payload));
				const payload = message.payload ?? message;
				const chatId = payload.chat_id ?? message.chat_id;
				const metadataVersion = payload.versions?.metadata_v ?? message.versions?.metadata_v;
				if (chatId && Number.isInteger(metadataVersion)) {
					versions.push({
						chatId,
						type: message.type ?? message.event ?? 'unknown',
						version: metadataVersion
					});
				}
			} catch {
				// WebSockets also carry non-JSON control frames.
			}
		});
	});
}

function latestServerMetadataVersion(
	versions: ServerMetadataVersion[],
	chatId: string,
	types?: string[]
): number {
	return Math.max(
		0,
		...versions
			.filter((entry) => entry.chatId === chatId && (!types || types.includes(entry.type)))
			.map((entry) => entry.version)
	);
}

async function localMetadataVersion(page: any, chatId: string): Promise<number> {
	return page.evaluate(async (id: string) => {
		const database = await new Promise<IDBDatabase>((resolve, reject) => {
			const request = indexedDB.open('chats_db');
			request.onerror = () => reject(request.error ?? new Error('Failed to open chats_db'));
			request.onsuccess = () => resolve(request.result);
		});

		try {
			if (!database.objectStoreNames.contains('chats')) return 0;
			const chat = await new Promise<any>((resolve, reject) => {
				const request = database.transaction('chats', 'readonly').objectStore('chats').get(id);
				request.onerror = () => reject(request.error ?? new Error(`Failed to read chat ${id}`));
				request.onsuccess = () => resolve(request.result);
			});
			return chat?.metadata_v ?? chat?.title_v ?? 0;
		} finally {
			database.close();
		}
	}, chatId);
}

async function waitForNextTotpWindow(page: any): Promise<void> {
	const millisecondsUntilNextWindow = 30_000 - (Date.now() % 30_000) + 500;
	await page.waitForTimeout(millisecondsUntilNextWindow);
}

async function ensureSidebarClosed(page: any): Promise<void> {
	const sidebar = page.getByTestId('activity-history-wrapper');
	if (await sidebar.isVisible().catch(() => false)) {
		await page.getByTestId('sidebar-toggle').click();
		await expect(sidebar).not.toBeVisible();
	}
}

async function openOwnedChat(page: any, chatId: string): Promise<any> {
	await page.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`), {
		waitUntil: 'domcontentloaded'
	});
	await ensureSidebarClosed(page);
	const header = page.getByTestId('workspace-detail-header');
	await expect(header).toBeVisible({ timeout: 45_000 });
	await expect(header).toHaveAttribute('data-header-system', 'workspace-detail');
	return header;
}

async function coldBootContextPage(context: any, baseUrl: string): Promise<any> {
	const page = await context.newPage();
	const resetUrl = `${new URL(baseUrl).origin}/e2e-unified-detail-cold-boot`;
	await page.route(resetUrl, (route: any) =>
		route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Cold boot</title>' })
	);
	await page.goto(resetUrl);
	await page.evaluate(async () => {
		localStorage.clear();
		const databases = await indexedDB.databases();
		await Promise.all(
			databases
				.map((database) => database.name)
				.filter((name): name is string => Boolean(name))
				.map(
					(name) =>
						new Promise<void>((resolve, reject) => {
							const request = indexedDB.deleteDatabase(name);
							request.onerror = () =>
								reject(request.error ?? new Error(`Failed to delete ${name}`));
							request.onblocked = () => reject(new Error(`Deleting ${name} was blocked`));
							request.onsuccess = () => resolve();
						})
				)
		);
	});
	await page.unroute(resetUrl);
	await context.clearCookies();
	return page;
}

async function deleteExactChat(page: any, chatId: string): Promise<void> {
	await page.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`), {
		waitUntil: 'domcontentloaded'
	});
	const sidebar = page.getByTestId('activity-history-wrapper');
	if (!(await sidebar.isVisible().catch(() => false))) {
		await page.getByTestId('sidebar-toggle').click();
		await expect(sidebar).toBeVisible({ timeout: 15_000 });
	}

	const chatItems = page.getByTestId('chat-item-wrapper');
	const itemCount = await chatItems.count();
	for (let index = 0; index < itemCount; index += 1) {
		const item = chatItems.nth(index);
		if ((await item.getAttribute('data-chat-id')) !== chatId) continue;
		await item.click({ button: 'right' });
		const deleteButton = page.getByTestId('chat-context-delete');
		await expect(deleteButton).toBeVisible();
		await deleteButton.click();
		await deleteButton.click();
		await expect(item).not.toBeVisible({ timeout: 15_000 });
		return;
	}

	throw new Error(`Owned chat ${chatId} was not available for exact cleanup`);
}

test.describe('Unified detail metadata multi-device sync', () => {
	test('title and summary converge live and survive a second-device cold boot', async ({
		browser
	}: {
		browser: any;
	}) => {
		test.slow();
		test.setTimeout(360_000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
		const contextA = await browser.newContext({ baseURL });
		const contextB = await browser.newContext({ baseURL });
		const serverVersionsA: ServerMetadataVersion[] = [];
		const serverVersionsB: ServerMetadataVersion[] = [];
		const pageA = await contextA.newPage();
		let pageB = await contextB.newPage();
		let chatId = '';

		captureServerMetadataVersions(pageA, serverVersionsA);
		captureServerMetadataVersions(pageB, serverVersionsB);

		try {
			await pageA.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
			await loginToTestAccount(pageA);
			await ensureSidebarClosed(pageA);

			await waitForNextTotpWindow(pageA);
			await pageB.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
			await loginToTestAccount(pageB);
			await ensureSidebarClosed(pageB);

			const unique = `${Date.now()}-${test.info().workerIndex}`;
			await startNewChat(pageA);
			await sendMessage(
				pageA,
				withMockMarker(`Create metadata sync chat ${unique}`, 'chat_flow_capital')
			);
			chatId = pageA.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? '';
			expect(chatId).toBeTruthy();
			await expect(pageA.getByTestId('message-assistant').last()).toBeVisible({ timeout: 60_000 });

			const headerA = await openOwnedChat(pageA, chatId);
			const headerB = await openOwnedChat(pageB, chatId);
			await expect
				.poll(
					() =>
						latestServerMetadataVersion(serverVersionsA, chatId, [
							'post_processing_metadata_stored',
							'encrypted_metadata_stored'
						]),
					{ timeout: 45_000 }
				)
				.toBeGreaterThan(0)
			const initialVersion = latestServerMetadataVersion(serverVersionsA, chatId, [
				'post_processing_metadata_stored',
				'encrypted_metadata_stored'
			]);

			const savedTitle = `Synced detail title ${unique}`;
			await headerA.getByTestId('chat-header-title').click();
			await headerA.getByTestId('workspace-detail-title-input').fill(savedTitle);
			await headerA.getByTestId('workspace-detail-title-save').click();
			await expect(headerA.getByTestId('chat-header-title')).toHaveText(savedTitle);
			await expect
				.poll(() => latestServerMetadataVersion(serverVersionsA, chatId, ['encrypted_metadata_stored']), {
					timeout: 30_000
				})
				.toBeGreaterThan(initialVersion);
			const titleVersion = latestServerMetadataVersion(serverVersionsA, chatId, [
				'encrypted_metadata_stored'
			]);
			await expect
				.poll(() => latestServerMetadataVersion(serverVersionsB, chatId, ['encrypted_chat_metadata']), {
					timeout: 30_000
				})
				.toBeGreaterThanOrEqual(titleVersion);
			await expect(headerB.getByTestId('chat-header-title')).toHaveText(savedTitle, {
				timeout: 30_000
			});

			const savedSummary = `Newest encrypted summary ${unique}`;
			await headerA.getByTestId('chat-header-summary').click();
			await headerA.getByTestId('workspace-detail-description-input').fill(savedSummary);
			await headerA.getByTestId('workspace-detail-description-save').click();
			await expect(headerA.getByTestId('chat-header-summary')).toHaveText(savedSummary);
			await expect
				.poll(() => latestServerMetadataVersion(serverVersionsA, chatId, ['encrypted_metadata_stored']), {
					timeout: 30_000
				})
				.toBeGreaterThan(titleVersion);
			const summaryVersion = latestServerMetadataVersion(serverVersionsA, chatId, [
				'encrypted_metadata_stored'
			]);
			await expect(headerB.getByTestId('chat-header-summary')).toHaveText(savedSummary, {
				timeout: 30_000
			});
			await expect
				.poll(() => localMetadataVersion(pageB, chatId), { timeout: 30_000 })
				.toBeGreaterThanOrEqual(summaryVersion);
			expect(
				latestServerMetadataVersion(serverVersionsB, chatId, ['encrypted_chat_metadata'])
			).toBeGreaterThanOrEqual(summaryVersion);

			await pageB.close();
			pageB = await coldBootContextPage(contextB, baseURL);
			captureServerMetadataVersions(pageB, serverVersionsB);
			await waitForNextTotpWindow(pageA);
			await pageB.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
			await loginToTestAccount(pageB);
			await ensureSidebarClosed(pageB);
			await expect
				.poll(() => localMetadataVersion(pageB, chatId), { timeout: 60_000 })
				.toBeGreaterThanOrEqual(summaryVersion);

			await openOwnedChat(pageB, chatId);
			await pageB.reload({ waitUntil: 'domcontentloaded' });
			await ensureSidebarClosed(pageB);
			const coldBootHeader = pageB.getByTestId('workspace-detail-header');
			await expect(coldBootHeader.getByTestId('chat-header-title')).toHaveText(savedTitle, {
				timeout: 45_000
			});
			await expect(coldBootHeader.getByTestId('chat-header-summary')).toHaveText(savedSummary, {
				timeout: 45_000
			});
		} finally {
			if (chatId) {
				await deleteExactChat(pageA, chatId).catch((error: Error) => {
					console.warn(`Exact chat cleanup failed: ${error.message}`);
				});
			}
			await contextA.close();
			await contextB.close();
		}
	});
});
