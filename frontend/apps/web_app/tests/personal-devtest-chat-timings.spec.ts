/* eslint-disable @typescript-eslint/no-require-imports -- CommonJS test helpers. */
// contract-test-file: tooling
/** Read-only, deployed-dev timings. Use the private Personal DevTest workflow. */
import type { Request, Response, WebSocketRoute } from "@playwright/test";
import { preparePersonalDevtestWebOrigin } from "./helpers/personal-devtest-web-origin";

const { test, expect } = require('@playwright/test');
const { createBrowserProcessEvidence } = require('./helpers/browser-process-evidence.cjs');
const { loginToTestAccount, waitForChatReady, dismissSecurityReminderIfPresent } = require('./helpers/chat-test-helpers');
const DEV_ORIGIN = 'https://app.dev.openmates.org';
const DEV_CHAT_STATS = 'https://api.dev.openmates.org/v1/settings/chats';
const IDLE_OBSERVATION_MS = 15000;
const ROW_SELECTOR = '[data-testid="activity-history-wrapper"] [data-testid="chat-item-wrapper"][data-chat-id]';

const READ_STAGES = [
	'read-online-session', 'read-local-session', 'read-no-local-session',
	'local-session-start', 'local-session-ready', 'cache-read-start', 'cache-read-end',
	'cache-plan-owned_metadata', 'cache-plan-messages', 'cache-miss-rust',
	'cache-miss-unsupported', 'cache-miss-unavailable', 'cache-miss-empty',
	'local-cache-miss', 'cold-retention-request', 'cold-retention-io-start',
	'cold-retention-io-complete', 'cold-retention-ready',
	'cold-retention-failed-unavailable', 'cold-retention-failed-session_expired',
	'cold-retention-io-failed-unavailable', 'server-read-start', 'server-read-end',
].map(stage => 'openmates:rust:' + stage);

// Keep the private baseline and candidate on the same observable transport.
test.use({ serviceWorkers: 'block' });

test('Personal DevTest opens existing conversations after a cached launch', async ({ page, context }: { page: any; context: any }, testInfo: any) => {
	test.skip(process.env.OPENMATES_PRIVATE_ACCOUNT_TIMINGS !== '1', 'Private Personal DevTest workflow only');
	test.setTimeout(240000);
	if (process.env.PLAYWRIGHT_TEST_BASE_URL !== DEV_ORIGIN) throw new Error('Personal DevTest requires the development app');
	const credentials = {
		email: process.env.OPENMATES_PERSONAL_TEST_ACOUNT_EMAIL,
		password: process.env.OPENMATES_PERSONAL_TEST_ACOUNT_PASSWORD,
		otpKey: process.env.OPENMATES_PERSONAL_TEST_ACOUNT_OTP_KEY,
	};
	if (!credentials.email || !credentials.password || !credentials.otpKey) {
		throw new Error('Personal DevTest repository secrets are required');
	}
	let offline = false;
	const transports: Array<{ socket: WebSocketRoute; server: WebSocketRoute }> = [];
	let receivedFrames = 0;
	let receivedBytes = 0;
	const measuredKinds = new Set([
		'phase_1_last_chat_ready', 'phase_1b_chat_content_ready', 'phase_2_last_20_chats_ready',
		'phase_3_chunk_ready', 'phased_sync_complete', 'sync_metadata_chats_response',
		'load_more_chats_response', 'recovery_outputs_discovery_complete', 'pong',
	]);
	let idleTraffic: Record<string, { frames: number; bytes: number }> | undefined;
	const frameKind = (data: string | Buffer): string => {
		if (typeof data !== 'string') return 'other';
		try {
			const type = JSON.parse(data)?.type;
			return typeof type === 'string' ? type : 'other';
		} catch {
			return 'other';
		}
	};

	const olderHeaderRequests: Record<string, number> = { sync_metadata_chats: 0, load_more_chats: 0 };
	await preparePersonalDevtestWebOrigin(context);
	await page.routeWebSocket(/^wss:\/\/api\.dev\.openmates\.org\/v1\/ws(?:\?|$)/, async (socket: WebSocketRoute) => {
		if (offline) {
			await socket.close({ code: 3001, reason: 'Development benchmark transport offline' });
			return;
		}
		const server = socket.connectToServer();
		transports.push({ socket, server });
		socket.onMessage(data => {
			if (typeof data === 'string') {
				const type = frameKind(data);
				if (type === 'sync_metadata_chats' || type === 'load_more_chats') olderHeaderRequests[type]++;
			}
			server.send(data);
		});
		server.onMessage((data) => {
			receivedFrames++;
			const bytes = typeof data === 'string' ? Buffer.byteLength(data) : data.length;
			receivedBytes += bytes;
			if (idleTraffic) {
				const type = frameKind(data);
				const name = measuredKinds.has(type) ? type : 'other';
				const bucket = idleTraffic[name] ??= { frames: 0, bytes: 0 };
				bucket.frames++;
				bucket.bytes += bytes;
			}
			socket.send(data);
		});
	});
	await page.addInitScript(() => {
		const BaseSocket = window.WebSocket;
		const chatSockets: WebSocket[] = [];
		(window as typeof window & { __devTestChatSockets?: WebSocket[] }).__devTestChatSockets = chatSockets;
		window.WebSocket = class extends BaseSocket {
			constructor(url: string | URL, protocols?: string | string[]) {
				super(url, protocols);
				if (String(url).includes('/v1/ws')) chatSockets.push(this);
			}
		};
	});
	const hasOpenTransport = () => page.evaluate(() => {
		const sockets = (window as typeof window & { __devTestChatSockets?: WebSocket[] }).__devTestChatSockets ?? [];
		return sockets.some(socket => socket.readyState === WebSocket.OPEN);
	});
	// The context is still empty here. Start at the accepted credential POST,
	// including its network time, and observe the first selectable personal row
	// independently of the login helper's own waits for the editor or sync.
	const measureFreshLogin = async () => {
		const accepted: Response = await page.waitForResponse(async (response: Response) => {
			if (new URL(response.url()).pathname !== '/v1/auth/login'
				|| response.request().method() !== 'POST' || !response.ok()) return false;
			const result = await response.json();
			return result?.success === true && result.tfa_required !== true && Boolean(result.user?.id);
		}, { timeout: 90000 });
		const loginStart = accepted.request().timing().startTime;
		expect(loginStart).toBeGreaterThan(0);
		await page.locator('[data-authenticated="true"]').first().waitFor({ state: 'visible' });
		if (!(await page.getByTestId('activity-history-wrapper').isVisible())) {
			await page.getByTestId('sidebar-toggle').click();
		}
		const firstRow = await page.waitForFunction((selector: string) => {
			for (const row of document.querySelectorAll<HTMLElement>(selector)) {
				if (!/^[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}$/i.test(row.dataset.chatId ?? '')) continue;
				const bounds = row.getBoundingClientRect();
				if (!bounds.width || !bounds.height) continue;
				const target = document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
				if (target && row.contains(target)) return performance.timeOrigin + performance.now();
			}
			return 0;
		}, ROW_SELECTOR, { timeout: 45000 });
		const elapsed = Math.round((await firstRow.jsonValue()) - loginStart);
		expect(elapsed).toBeGreaterThanOrEqual(0);
		await testInfo.attach('personal-devtest-web-fresh-login', {
			body: JSON.stringify({ accepted_login_request_to_selectable_recent_row_ms: elapsed }),
			contentType: 'application/json',
		});
	};
	await Promise.all([
		measureFreshLogin(),
		loginToTestAccount(page, undefined, undefined, { credentials })
			.then(() => dismissSecurityReminderIfPresent(page)),
	]);
	await waitForChatReady(page);

	const stats = await context.request.get(DEV_CHAT_STATS);
	expect(stats.ok()).toBe(true);
	const accountChatTotal = (await stats.json()).total_count;
	expect(Number.isSafeInteger(accountChatTotal)).toBe(true);
	expect(accountChatTotal, 'The populated account exceeds the recent window').toBeGreaterThan(100);

	const count = page.getByTestId('chat-account-total');
	const assertAccountCount = async () => {
		await expect.soft(count).toBeVisible();
		await expect.soft(count).toHaveAttribute('data-chat-count', String(accountChatTotal));
	};
	const recentRowsMS: number[] = [];
	const visibleMessageMS: number[] = [];
	const selected = new Set<string>();
	const active = page.getByTestId('active-chat-container');
	const sidebar = page.getByTestId('activity-history-wrapper');
	const clickChat = async (chatId: string) => {
		if (!(await sidebar.isVisible())) await page.getByTestId('sidebar-toggle').click();
		await page.locator(ROW_SELECTOR + '[data-chat-id="' + chatId + '"]').click();
	};
	const readEvidence = (chatId: string, startedAt: number) => page.evaluate(async ({ id, start, allowed }: {
		id: string; start: number; allowed: string[];
	}) => {
		// Report aggregate counts from the selected IDB index, never rows or keys.
		const retainedRows = await new Promise<number | null>(resolve => {
			const request = indexedDB.open('chats_db');
			const deadline = window.setTimeout(() => resolve(null), 3000);
			const finish = (count: number | null) => { window.clearTimeout(deadline); resolve(count); };
			request.onupgradeneeded = () => { request.transaction?.abort(); finish(null); };
			request.onblocked = request.onerror = () => finish(null);
			request.onsuccess = () => {
				const db = request.result;
				try {
					const tx = db.transaction('messages', 'readonly');
					const count = tx.objectStore('messages').index('chat_id').count(id);
					tx.oncomplete = () => { db.close(); finish(count.result); };
					tx.onabort = tx.onerror = () => { db.close(); finish(null); };
				} catch { db.close(); finish(null); }
			};
		});
		const view = document.querySelector('[data-testid="active-chat-container"]');
		return {
			retained_rows: retainedRows,
			active_message_count: Number(view?.getAttribute('data-current-message-count') ?? 0),
			navigator_online: navigator.onLine,
			read_stages: performance.getEntriesByType('mark')
				.filter(mark => mark.startTime >= start && allowed.includes(mark.name))
				.map(mark => mark.name).slice(-40),
		};
	}, { id: chatId, start: startedAt, allowed: READ_STAGES });
	const assertTranscript = async (chatId: string, stage = 'online selection') => {
		await expect(active).toHaveAttribute('data-current-chat-id', chatId);
		await expect.poll(async () => Number(await active.getAttribute('data-current-message-count')),
			{ message: 'The ' + stage + ' has readable history' }).toBeGreaterThan(0);
		await expect(page.getByTestId('chat-history-content')).toBeVisible();
		await expect(active).toHaveAttribute('data-current-message-chat-consistent', 'true');
	};
	for (let sample = 0; sample < 3; sample++) {
		await page.goto('/', { waitUntil: 'domcontentloaded' });
		if (new URL(page.url()).origin !== DEV_ORIGIN) throw new Error('Unexpected application origin');
		if (!(await sidebar.isVisible())) await page.getByTestId('sidebar-toggle').click();
		const rows = page.locator(ROW_SELECTOR);
		await expect(rows.first()).toBeVisible();
		recentRowsMS.push(Math.round(await page.evaluate(() => performance.now())));

		// The first cached row is the startup milestone. More rows may be
		// published in later frames, so find a different candidate separately.
		const findAnotherChat = async () => {
			const current = await active.getAttribute('data-current-chat-id');
			return page.evaluate(({ rowSelector, excluded }: { rowSelector: string; excluded: string[] }) =>
				Array.from(document.querySelectorAll<HTMLElement>(rowSelector))
					.filter(row => row.getClientRects().length > 0)
					.map(row => row.dataset.chatId)
					.find(id => !!id && /^[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}$/i.test(id) && !excluded.includes(id)) ?? null,
			{ rowSelector: ROW_SELECTOR, excluded: [...selected, current ?? ''] });
		};
		let candidate: string | null = null;
		await expect.poll(async () => {
			candidate = await findAnotherChat();
			return candidate !== null;
		}, { timeout: 15000, message: 'A different existing recent chat becomes selectable' }).toBe(true);
		const chatId = candidate!;
		selected.add(chatId);
		const start = await page.evaluate(() => performance.now());
		await clickChat(chatId);
		await assertTranscript(chatId);
		visibleMessageMS.push(Math.round(await page.evaluate(() => performance.now()) - start));
		await testInfo.attach('personal-devtest-web-trial-' + (sample + 1), {
			body: JSON.stringify({ cached_navigation_to_recent_rows_ms: recentRowsMS[sample],
				select_to_visible_message_ms: visibleMessageMS[sample], ...await readEvidence(chatId, start) }),
			contentType: 'application/json',
		});
	}
	await testInfo.attach('personal-devtest-web-timings', {
		body: JSON.stringify({ cached_navigation_to_recent_rows_ms: recentRowsMS, select_to_visible_message_ms: visibleMessageMS }),
		contentType: 'application/json',
	});

	// Capture idle work in the same known browser process tree. Store only
	// resource totals and process aggregates in encrypted CI evidence.
	const measureIdle = async (attachment: string) => {
		const processMeter = await createBrowserProcessEvidence(page);
		try {
			const begin = await processMeter.begin();
			const start = { frames: receivedFrames, bytes: receivedBytes };
			idleTraffic = {};
			await new Promise(resolve => setTimeout(resolve, IDLE_OBSERVATION_MS));
			const end = await processMeter.end();
			await testInfo.attach(attachment, {
				body: JSON.stringify({ observation_ms: IDLE_OBSERVATION_MS, begin, end,
					older_header_requests_through_idle: olderHeaderRequests,
					received_frame_kinds: idleTraffic,
					received_websocket_frames: receivedFrames - start.frames,
					received_websocket_bytes: receivedBytes - start.bytes }),
				contentType: 'application/json',
			});
			expect(begin.available && end.available, 'Verified CPU collection').toBe(true);
		} finally {
			idleTraffic = undefined;
			await processMeter.close();
		}
	};
	await measureIdle('personal-devtest-web-idle');
	// Check the badge after capturing idle work on both old and updated builds.
	await assertAccountCount();

	// Use only the conversations already opened above. Keep both the existing
	// transcript and a second cached selection usable across an actual socket loss.
	const [first, , last] = [...selected];
	if (!first || !last) throw new Error('Expected three distinct existing conversations');
	await expect.poll(hasOpenTransport, { timeout: 15000 }).toBe(true);
	if (!transports.at(-1)) throw new Error('Expected the real development WebSocket route');
	const previousTransportCount = transports.length;
	const beforeDisconnect = await readEvidence(first, 0);
	let offlineHistoryRequests = 0;
	context.on('request', (request: Request) => {
		const pathname = new URL(request.url()).pathname;
		if (offline && pathname.startsWith('/v1/chats/' + first + '/messages')) offlineHistoryRequests++;
	});
	let offlineSelectionStarted: number | null = null;
	offline = true;
	await context.setOffline(true);
	try {
		// Closing the route in both directions also works when the network can
		// no longer complete a browser-initiated close handshake.
		const close = { code: 3001, reason: 'Read-only development benchmark disconnect' };
		await Promise.all(transports.flatMap(({ socket, server }) => [socket.close(close), server.close(close)]));
		await expect.poll(hasOpenTransport, { timeout: 15000 }).toBe(false);
		await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(false);
		await assertTranscript(last, 'previously visible chat');
		offlineSelectionStarted = await page.evaluate(() => performance.now());
		await clickChat(first);
		await assertTranscript(first, 'offline sidebar selection');
		expect(beforeDisconnect.retained_rows).toBeGreaterThan(0);
		expect(offlineHistoryRequests).toBe(0);
	} finally {
		try {
			const duringOffline = offlineSelectionStarted === null ? null : await readEvidence(first, offlineSelectionStarted);
			await testInfo.attach('personal-devtest-web-offline-read', {
				body: JSON.stringify({
					retained_rows_before_disconnect: beforeDisconnect.retained_rows,
					offline_history_requests: offlineHistoryRequests,
					open_transport: await hasOpenTransport(),
					during_offline: duringOffline,
				}),
				contentType: 'application/json',
			});
		} finally {
			offline = false;
			await context.setOffline(false);
		}
	}
	await expect.poll(() => transports.length, { timeout: 30000 }).toBeGreaterThan(previousTransportCount);
	await expect.poll(hasOpenTransport, { timeout: 30000 }).toBe(true);
	await waitForChatReady(page);
	await assertTranscript(first);
	await expect(active).toHaveAttribute('data-current-message-ids-unique', 'true');
	await assertAccountCount();
	await measureIdle('personal-devtest-web-reconnect-idle');
	await testInfo.attach('personal-devtest-recent-chat-cap', {
		body: JSON.stringify({
			account_chat_total: accountChatTotal,
			displayed_chat_total: Number(await count.getAttribute('data-chat-count')),
			older_header_requests_through_reconnect_idle: olderHeaderRequests,
			observation_ms_per_idle_window: IDLE_OBSERVATION_MS,
		}),
		contentType: 'application/json',
	});
	expect(olderHeaderRequests).toEqual({ sync_metadata_chats: 0, load_more_chats: 0 });
});
