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
const WEB_SCREENSHOT_PATH = path.join(ARTIFACT_DIR, 'web-loaded-chats-sidebar.png');
const MAX_CHAT_ROWS = Number(process.env.CHAT_RENDERING_PARITY_MAX_ROWS || 40);
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

	log('Wrote loaded chats web parity oracle.', {
		manifest: path.relative(process.cwd(), WEB_MANIFEST_PATH),
		screenshot: path.relative(process.cwd(), WEB_SCREENSHOT_PATH)
	});

	expect((manifest.sidebar as { chat_count: number }).chat_count).toBeGreaterThan(0);
	expect((manifest.required_elements as { chat_title: boolean }).chat_title).toBe(true);
});
