/* eslint-disable @typescript-eslint/no-require-imports */
// Web oracle for Apple chat rendering parity.
// Logs into the shared E2E account, opens the chat sidebar, and exports a
// privacy-scoped manifest of loaded chat rows plus a screenshot. The manifest is
// the web source of truth consumed by scripts/compare_chat_render_parity.py and
// the matching Apple real-account UI test.
// Runtime artifacts are written under artifacts/ and must not be committed.
export {};

const { test, expect } = require('./helpers/cookie-audit');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { createSignupLogger, getTestAccount } = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const ARTIFACT_DIR = process.env.CHAT_RENDERING_PARITY_ARTIFACT_DIR
	? path.resolve(process.env.CHAT_RENDERING_PARITY_ARTIFACT_DIR)
	: path.resolve(process.cwd(), 'artifacts', 'chat-rendering-parity');
const WEB_MANIFEST_PATH = path.join(ARTIFACT_DIR, 'web-loaded-chats-manifest.json');
const WEB_OPENED_MANIFEST_PATH = path.join(ARTIFACT_DIR, 'web-opened-chats-manifest.json');
const WEB_SCREENSHOT_PATH = path.join(ARTIFACT_DIR, 'web-loaded-chats-sidebar.png');
const MAX_CHAT_ROWS = Number(process.env.CHAT_RENDERING_PARITY_MAX_ROWS || 40);
const OPENED_CHAT_LIMIT = Number(process.env.CHAT_RENDERING_PARITY_OPENED_CHAT_LIMIT || 10);
const STATIC_GROUP_KEYS = ['incognito', 'shared_by_others', 'intro', 'examples', 'announcements', 'tips_and_tricks', 'legal'];

type RawChatRow = {
	index: number;
	chatId: string | null;
	titleText: string;
	titleState: 'ready' | 'processing' | 'untitled' | 'empty';
	groupKey: string | null;
	groupTitle: string | null;
	hasCategory: boolean;
	categoryMissing: boolean;
	unread: boolean;
	active: boolean;
	visible: boolean;
	rect: { x: number; y: number; width: number; height: number };
};

function hashStableId(value: string | null): string | null {
	if (!value) return null;
	return crypto.createHash('sha256').update(value).digest('hex').slice(0, 16);
}

function normalizeText(value: string | null | undefined): string {
	return (value || '').replace(/\s+/g, ' ').trim();
}

async function ensureSidebarOpen(page: any, log: (message: string, metadata?: Record<string, unknown>) => void): Promise<void> {
	const activityHistory = page.getByTestId('activity-history-wrapper');
	if (await activityHistory.isVisible({ timeout: 1500 }).catch(() => false)) {
		log('Chat sidebar already visible.');
		return;
	}

	const sidebarToggle = page.getByTestId('sidebar-toggle');
	await expect(sidebarToggle).toBeVisible({ timeout: 10000 });
	await sidebarToggle.click();
	await expect(activityHistory).toBeVisible({ timeout: 15000 });
	log('Opened chat sidebar.');
}

async function openUserChatByIndex(page: any, index: number): Promise<string | null> {
	return page.evaluate(({ targetIndex, staticGroupKeys }: { targetIndex: number; staticGroupKeys: string[] }) => {
		const staticGroups = new Set(staticGroupKeys);
		const rows = Array.from(document.querySelectorAll('[data-testid="chat-item-wrapper"]')).filter((row) => {
			const groupKey = row.closest('[data-testid="chat-group"]')?.getAttribute('data-group-key') || null;
			return !groupKey || !staticGroups.has(groupKey);
		});
		const row = rows[targetIndex] as HTMLElement | undefined;
		if (!row) throw new Error(`Missing user chat row at index ${targetIndex}`);
		const chatId = row.getAttribute('data-chat-id');
		row.click();
		return chatId;
	}, { targetIndex: index, staticGroupKeys: STATIC_GROUP_KEYS });
}

async function currentMessageFingerprint(page: any): Promise<string> {
	return page.evaluate(async () => {
		function normalize(value: string | null | undefined): string {
			return (value || '').replace(/\s+/g, ' ').trim();
		}

		async function hash(value: string): Promise<string> {
			const data = new TextEncoder().encode(value);
			const digest = await crypto.subtle.digest('SHA-256', data);
			return Array.from(new Uint8Array(digest)).slice(0, 8).map((byte) => byte.toString(16).padStart(2, '0')).join('');
		}

		const messages = Array.from(document.querySelectorAll('[data-testid="message-user"], [data-testid="message-assistant"], [data-testid="message-system"]'));
		const signatures = await Promise.all(messages.map(async (wrapper) => {
			const testId = wrapper.getAttribute('data-testid') || '';
			const content = wrapper.querySelector('[data-testid="message-content"]') || wrapper;
			const text = normalize((content as HTMLElement).innerText || content.textContent || '');
			return `${testId}:${text.length}:${await hash(text)}`;
		}));
		return signatures.join('|');
	});
}

async function waitForOpenedChat(page: any, chatId: string | null, previousFingerprint: string): Promise<void> {
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30000 });
	if (chatId) {
		await expect(async () => {
			const active = await page.evaluate((targetChatId: string) => {
				return Array.from(document.querySelectorAll('[data-testid="chat-item-wrapper"]')).some((row) => {
					return row.getAttribute('data-chat-id') === targetChatId && row.classList.contains('active');
				});
			}, chatId);
			expect(active, `Expected clicked chat ${hashStableId(chatId)} to become active.`).toBe(true);
		}).toPass({ timeout: 30000, intervals: [500, 1000, 2000] });
	}
	await expect(async () => {
		const count = await page.locator('[data-testid="message-user"], [data-testid="message-assistant"], [data-testid="message-system"]').count();
		expect(count, 'Expected opened chat to render at least one message.').toBeGreaterThan(0);
	}).toPass({ timeout: 30000, intervals: [500, 1000, 2000] });
	if (previousFingerprint) {
		await expect(async () => {
			const fingerprint = await currentMessageFingerprint(page);
			expect(fingerprint, 'Expected opened chat messages to replace the previous transcript.').not.toBe(previousFingerprint);
		}).toPass({ timeout: 30000, intervals: [500, 1000, 2000] });
	}
}

async function collectOpenedChatRenderState(page: any, chatIndex: number, titleText: string): Promise<Record<string, unknown>> {
	return page.evaluate(({ chatIndex, titleText }: { chatIndex: number; titleText: string }) => {
		function normalize(value: string | null | undefined): string {
			return (value || '').replace(/\s+/g, ' ').trim();
		}

		async function hash(value: string): Promise<string> {
			const data = new TextEncoder().encode(value);
			const digest = await crypto.subtle.digest('SHA-256', data);
			return Array.from(new Uint8Array(digest)).slice(0, 8).map((byte) => byte.toString(16).padStart(2, '0')).join('');
		}

		function visible(element: Element): boolean {
			return element.getClientRects().length > 0;
		}

		function blockCounts(wrapper: Element) {
			const content = wrapper.querySelector('[data-testid="message-content"]') || wrapper;
			const preCode = content.querySelectorAll('pre code').length;
			return {
				paragraph: content.querySelectorAll('p').length || (normalize(content.textContent).length > 0 ? 1 : 0),
				heading: content.querySelectorAll('h1,h2,h3,h4,h5,h6').length,
				code_block: content.querySelectorAll('pre').length,
				blockquote: content.querySelectorAll('blockquote').length,
				list: content.querySelectorAll('ul,ol').length,
				table: content.querySelectorAll('table').length,
				source_quote: content.querySelectorAll('[data-testid="source-quote-block"], .source-quote-block').length,
				embed_group: content.querySelectorAll('[data-testid="embed-preview"], [data-embed-id], [data-type="embed-preview-large"]').length,
				interactive_question: content.querySelectorAll('[data-testid="interactive-question-card"], .interactive-question-card').length,
				inline_code: Math.max(0, content.querySelectorAll('code').length - preCode)
			};
		}

		return Promise.all(
			Array.from(document.querySelectorAll('[data-testid="message-user"], [data-testid="message-assistant"], [data-testid="message-system"]'))
				.filter(visible)
				.map(async (wrapper, messageIndex) => {
					const testId = wrapper.getAttribute('data-testid') || '';
					const role = testId.replace('message-', '') || 'unknown';
					const content = wrapper.querySelector('[data-testid="message-content"]') || wrapper;
					const normalizedText = normalize((content as HTMLElement).innerText || content.textContent || '');
					return {
						index: messageIndex,
						role,
						content_hash: await hash(normalizedText),
						text_length: normalizedText.length,
						block_counts: blockCounts(wrapper),
						has_sender_name: Boolean(wrapper.querySelector('[data-testid="chat-mate-name"], [data-testid="message-sender-name"]')),
						has_thinking: Boolean(wrapper.querySelector('[data-testid="thinking-section"], .thinking-section')),
						is_streaming: Boolean(content.classList.contains('is-streaming'))
					};
				})
		).then((messages) => ({
			index: chatIndex,
			titleText,
			message_count: messages.length,
			messages
		}));
	}, { chatIndex, titleText });
}

async function collectOpenedChatsManifest(page: any, loadedManifest: Record<string, unknown>): Promise<Record<string, unknown>> {
	const loadedChats = (loadedManifest.chats as Array<{ titleText: string }>).slice(0, OPENED_CHAT_LIMIT);
	const openedChats: Record<string, unknown>[] = [];
	let previousFingerprint = await currentMessageFingerprint(page);

	for (let index = 0; index < loadedChats.length; index += 1) {
		await ensureSidebarOpen(page, () => undefined);
		const chatId = await openUserChatByIndex(page, index);
		await waitForOpenedChat(page, chatId, previousFingerprint);
		openedChats.push(await collectOpenedChatRenderState(page, index, normalizeText(loadedChats[index].titleText)));
		previousFingerprint = await currentMessageFingerprint(page);
	}

	return {
		schema_version: 1,
		surface: 'opened-user-chats',
		client: 'web',
		generated_at: new Date().toISOString(),
		environment: {
			account_email_hash: hashStableId(TEST_EMAIL || null),
			base_url: process.env.PLAYWRIGHT_TEST_BASE_URL || null,
			opened_chat_limit: OPENED_CHAT_LIMIT
		},
		sidebar: {
			chat_count: (loadedManifest.sidebar as { chat_count: number }).chat_count
		},
		opened_chats: openedChats
	};
}

async function waitForLoadedChats(page: any): Promise<void> {
	await expect(async () => {
		const chatCount = await page.evaluate((staticGroupKeys: string[]) => {
			const staticGroups = new Set(staticGroupKeys);
			return Array.from(document.querySelectorAll('[data-testid="chat-item-wrapper"]')).filter((row) => {
				const groupKey = row.closest('[data-testid="chat-group"]')?.getAttribute('data-group-key') || null;
				return !groupKey || !staticGroups.has(groupKey);
			}).length;
		}, STATIC_GROUP_KEYS).catch(() => 0);
		const noChatsVisible = await page.getByTestId('no-chats-indicator').isVisible({ timeout: 200 }).catch(() => false);
		expect(noChatsVisible, 'The parity test account should have loaded chats, not the empty state.').toBe(false);
		expect(chatCount, 'Expected at least one loaded user chat row in the sidebar.').toBeGreaterThan(0);
	}).toPass({ timeout: 45000, intervals: [1000, 2000, 5000] });

	await expect(page.getByTestId('syncing-indicator')).not.toBeVisible({ timeout: 20000 }).catch(() => undefined);
}

async function collectLoadedChatsManifest(page: any): Promise<Record<string, unknown>> {
	const rawRows: RawChatRow[] = await page.evaluate(({ maxRows, staticGroupKeys }: { maxRows: number; staticGroupKeys: string[] }) => {
		const staticGroups = new Set(staticGroupKeys);

		function rectFor(element: Element) {
			const rect = element.getBoundingClientRect();
			return {
				x: Math.round(rect.x),
				y: Math.round(rect.y),
				width: Math.round(rect.width),
				height: Math.round(rect.height)
			};
		}

		function textFor(element: Element | null): string {
			return (element?.textContent || '').replace(/\s+/g, ' ').trim();
		}

		function titleState(titleText: string, titleElement: Element | null): RawChatRow['titleState'] {
			if (!titleText) return 'empty';
			const normalized = titleText.toLowerCase();
			if (normalized.includes('processing')) return 'processing';
			if (normalized.includes('untitled')) return 'untitled';
			if (titleElement?.classList.contains('processing-title')) return 'processing';
			return 'ready';
		}

		return Array.from(document.querySelectorAll('[data-testid="chat-item-wrapper"]'))
			.filter((row) => {
				const groupKey = row.closest('[data-testid="chat-group"]')?.getAttribute('data-group-key') || null;
				return !groupKey || !staticGroups.has(groupKey);
			})
			.slice(0, maxRows)
			.map((row, index) => {
				const titleElement = row.querySelector('[data-testid="chat-title"]');
				const categoryElement = row.querySelector('[data-testid="category-circle"]');
				const groupElement = row.closest('[data-testid="chat-group"]');
				const groupTitleElement = groupElement?.querySelector('[data-testid="group-title"]') || null;
				const titleText = textFor(titleElement);
				return {
					index,
					chatId: row.getAttribute('data-chat-id'),
					titleText,
					titleState: titleState(titleText, titleElement),
					groupKey: groupElement?.getAttribute('data-group-key') || null,
					groupTitle: textFor(groupTitleElement) || null,
					hasCategory: Boolean(categoryElement),
					categoryMissing: Boolean(categoryElement?.classList.contains('missing-category')),
					unread: Boolean(row.querySelector('[data-testid="unread-badge"]')),
					active: row.classList.contains('active'),
					visible: row.getClientRects().length > 0,
					rect: rectFor(row)
				};
			});
	}, { maxRows: MAX_CHAT_ROWS, staticGroupKeys: STATIC_GROUP_KEYS });

	const groups = await page.evaluate(() => {
		return Array.from(document.querySelectorAll('[data-testid="chat-group"]')).map((group, index) => ({
			index,
			key: group.getAttribute('data-group-key'),
			title: (group.querySelector('[data-testid="group-title"]')?.textContent || '').replace(/\s+/g, ' ').trim(),
			rowCount: group.querySelectorAll('[data-testid="chat-item-wrapper"]').length
		}));
	});

	const viewport = page.viewportSize() || { width: 0, height: 0 };
	const sidebarVisible = await page.getByTestId('activity-history-wrapper').isVisible().catch(() => false);
	const syncingVisible = await page.getByTestId('syncing-indicator').isVisible().catch(() => false);
	const noChatsVisible = await page.getByTestId('no-chats-indicator').isVisible().catch(() => false);

	return {
		schema_version: 1,
		surface: 'loaded-user-chats',
		client: 'web',
		generated_at: new Date().toISOString(),
		environment: {
			account_email_hash: hashStableId(TEST_EMAIL || null),
			base_url: process.env.PLAYWRIGHT_TEST_BASE_URL || null,
			viewport_width: viewport.width,
			viewport_height: viewport.height,
			max_chat_rows: MAX_CHAT_ROWS
		},
		artifacts: {
			screenshot: path.relative(process.cwd(), WEB_SCREENSHOT_PATH)
		},
		required_elements: {
			activity_history_wrapper: sidebarVisible,
			chat_item_wrapper: rawRows.length > 0,
			chat_title: rawRows.some((row) => row.titleText.length > 0),
			category_circle: rawRows.some((row) => row.hasCategory)
		},
		sidebar: {
			is_visible: sidebarVisible,
			syncing_visible: syncingVisible,
			no_chats_visible: noChatsVisible,
			chat_group_count: groups.length,
			chat_count: rawRows.length
		},
		groups,
		chats: rawRows.map(({ chatId, ...row }) => ({
			...row,
			chat_id_hash: hashStableId(chatId)
		}))
	};
}

test('exports loaded user chats web oracle for Apple parity', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	fs.mkdirSync(ARTIFACT_DIR, { recursive: true });
	const log = createSignupLogger('CHAT_RENDER_PARITY');

	await loginToTestAccount(page, log, async () => undefined);
	await ensureSidebarOpen(page, log);
	await waitForLoadedChats(page);

	await page.screenshot({ path: WEB_SCREENSHOT_PATH, fullPage: true });
	const manifest = await collectLoadedChatsManifest(page);
	fs.writeFileSync(WEB_MANIFEST_PATH, JSON.stringify(manifest, null, 2) + '\n', 'utf8');
	const openedManifest = await collectOpenedChatsManifest(page, manifest);
	fs.writeFileSync(WEB_OPENED_MANIFEST_PATH, JSON.stringify(openedManifest, null, 2) + '\n', 'utf8');

	log('Wrote loaded chats web parity oracle.', {
		manifest: path.relative(process.cwd(), WEB_MANIFEST_PATH),
		openedManifest: path.relative(process.cwd(), WEB_OPENED_MANIFEST_PATH),
		screenshot: path.relative(process.cwd(), WEB_SCREENSHOT_PATH)
	});

	expect((manifest.sidebar as { chat_count: number }).chat_count).toBeGreaterThan(0);
	expect((manifest.required_elements as { chat_title: boolean }).chat_title).toBe(true);
	expect((openedManifest.opened_chats as unknown[]).length).toBeGreaterThan(0);
});
