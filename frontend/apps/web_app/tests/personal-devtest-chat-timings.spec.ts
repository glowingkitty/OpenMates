/* eslint-disable @typescript-eslint/no-require-imports -- CommonJS test helpers. */
// contract-test-file: tooling
/** Read-only, deployed-dev timings. Use the private Personal DevTest workflow. */
import type { Request, Response, WebSocketRoute } from "@playwright/test";
import { preparePersonalDevtestWebOrigin } from "./helpers/personal-devtest-web-origin";
import {
	armSelectedFrameProbe, browserNavigationTimings, clearSelectedFrameProbe, takeSelectedFrameProbe,
} from "./helpers/personal-devtest-web-timing";

const { test, expect } = require('@playwright/test');
const { browserResourceSnapshot } = require('./helpers/performance-evidence.cjs');
const { createBrowserProcessEvidence } = require('./helpers/browser-process-evidence.cjs');
const { loginToTestAccount, waitForChatReady, dismissSecurityReminderIfPresent } = require('./helpers/chat-test-helpers');
const DEV_ORIGIN = 'https://app.dev.openmates.org';
const DEV_AUTHORIZED_CHAT_COUNT = 'https://api.dev.openmates.org/v1/chats?order=modified&limit=1';
const IDLE_OBSERVATION_MS = 15000;
const SETTLED_READINESS_TIMEOUT_MS = 15000;
const READABLE_FRAME_TIMEOUT_MS = 8000;
const INBOUND_KINDS = new Set([
	'phase_1_last_chat_ready', 'phase_1b_chat_content_ready', 'phase_2_last_20_chats_ready',
	'phase_3_chunk_ready', 'phase_3_last_100_chats_ready', 'background_message_sync',
	'phased_sync_complete', 'phased_sync_retryable_error', 'chat_startup_opened_ready',
	'sync_metadata_chats_response', 'load_more_chats_response', 'recovery_outputs_discovery_complete',
	'cache_primed', 'cache_status_response', 'sync_status_response', 'active_chat_set_ack', 'pong',
]);
const OUTBOUND_KINDS = new Set([
	'phased_sync_request', 'sync_status_request', 'cache_status_request', 'sync_metadata_chats',
	'load_more_chats', 'native_client_lifecycle', 'set_active_chat', 'ping',
]);
type FrameCounts = Record<string, { frames: number; bytes: number }>;
type SyncTransport = {
	socket: WebSocketRoute;
	server: WebSocketRoute;
	requestEpoch: number | null;
	wireCompleteEpoch: number | null;
	requestAt: number | null;
	wireCompleteAt: number | null;
	phase2Received: boolean;
	phase1bReceived: boolean;
	phase1bApplied: boolean;
};
const ROW_SELECTOR = '[data-testid="activity-history-wrapper"] [data-testid="chat-item-wrapper"][data-chat-id]';

const READ_STAGES = [
	'read-online-session', 'read-local-session', 'read-no-local-session',
	'local-session-start', 'local-session-ready', 'session-start', 'session-ready', 'cache-read-start', 'cache-read-end',
	'cache-plan-owned_metadata', 'cache-plan-messages', 'cache-miss-rust',
	'cache-miss-unsupported', 'cache-miss-unavailable', 'cache-miss-empty',
	'load-chat', 'history-load', 'history-request', 'history-joined-pending', 'history-replaced-pending-target',
	'admission-bootstrap-wait-start', 'admission-bootstrap-wait-end',
	'admission-platform-ready', 'admission-profile-capture-start', 'admission-worker-acquired',
	'admission-restore-start', 'admission-restore-response', 'admission-profile-verified',
	'platform-ready', 'worker-ready', 'local-platform-ready',
	'local-cache-miss', 'local-cache-empty-latest', 'local-cache-failed-unavailable',
	'local-cache-failed-invalidated_snapshot', 'local-cache-failed-cancelled', 'local-cache-failed-session_expired',
	'cold-retention-request', 'cold-retention-io-start',
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
	const transports: SyncTransport[] = [];
	let lastLaunchTransportOffset = 0;
	let lastLaunchStartedAt = 0;
	const received = { frames: 0, bytes: 0 };
	const sent = { frames: 0, bytes: 0 };
	let idleTraffic: { inbound: FrameCounts; outbound: FrameCounts } | undefined;
	const inspectFrame = (data: string | Buffer, totals: typeof received, counts: FrameCounts | undefined, allowed: Set<string>) => {
		const bytes = typeof data === 'string' ? Buffer.byteLength(data) : data.length;
		totals.frames++;
		totals.bytes += bytes;
		let envelope: { type?: unknown; payload?: { context_epoch?: unknown; chats?: unknown } } | null = null;
		if (typeof data === 'string') {
			try { envelope = JSON.parse(data); } catch { /* Non-protocol frames are counted as other. */ }
		}
		const type = typeof envelope?.type === 'string' && allowed.has(envelope.type) ? envelope.type : 'other';
		if (counts) {
			const bucket = counts[type] ??= { frames: 0, bytes: 0 };
			bucket.frames++;
			bucket.bytes += bytes;
		}
		const epoch = envelope?.payload?.context_epoch;
		return { type, epoch: typeof epoch === 'number' && Number.isSafeInteger(epoch) ? epoch : null,
			hasChats: Array.isArray(envelope?.payload?.chats) };
	};
	const latestSyncTransport = () => transports.slice(lastLaunchTransportOffset).findLast(transport => transport.requestEpoch !== null);

	const olderHeaderRequests: Record<string, number> = { sync_metadata_chats: 0, load_more_chats: 0 };
	await preparePersonalDevtestWebOrigin(context);
	const httpCacheMode = process.env.OPENMATES_PRIVATE_WEB_PREVIEW
		? 'disabled_by_playwright_http_routing' : 'browser_default';
	await page.routeWebSocket(/^wss:\/\/api\.dev\.openmates\.org\/v1\/ws(?:\?|$)/, async (socket: WebSocketRoute) => {
		if (offline) {
			await socket.close({ code: 3001, reason: 'Development benchmark transport offline' });
			return;
		}
		const server = socket.connectToServer();
		const transport: SyncTransport = {
			socket, server, requestEpoch: null, wireCompleteEpoch: null, requestAt: null, wireCompleteAt: null,
			phase2Received: false, phase1bReceived: false, phase1bApplied: false,
		};
		transports.push(transport);
		socket.onMessage(data => {
			const { type, epoch } = inspectFrame(data, sent, idleTraffic?.outbound, OUTBOUND_KINDS);
			if (type === 'sync_metadata_chats' || type === 'load_more_chats') olderHeaderRequests[type]++;
			if (type === 'phased_sync_request') {
				transport.requestEpoch = epoch;
				transport.requestAt = Date.now();
				transport.wireCompleteEpoch = null;
				transport.wireCompleteAt = null;
				transport.phase2Received = false;
				transport.phase1bReceived = false;
				transport.phase1bApplied = false;
			}
			server.send(data);
		});
		server.onMessage(data => {
			const { type, epoch, hasChats } = inspectFrame(data, received, idleTraffic?.inbound, INBOUND_KINDS);
			if (transport.requestEpoch !== null && transport.requestEpoch === epoch) {
				if (type === 'phased_sync_complete') {
					transport.wireCompleteEpoch = epoch;
					transport.wireCompleteAt = Date.now();
				}
				if (type === 'phase_2_last_20_chats_ready' && hasChats) transport.phase2Received = true;
				if (type === 'phase_1b_chat_content_ready') transport.phase1bReceived = true;
			}
			socket.send(data);
		});
	});
	page.on('console', (message: { text(): string }) => {
		if (message.text() !== '[ChatSyncService:CoreSync] ✅ Phase 1b complete') return;
		const transport = latestSyncTransport();
		if (transport?.phase1bReceived) transport.phase1bApplied = true;
	});
	await page.addInitScript(() => {
		// Capacity without a resource observer during the measured idle windows.
		performance.setResourceTimingBufferSize(4096);
		const BaseSocket = window.WebSocket;
		const applied = { phase2: false, completeEpoch: null as number | null, completeAt: null as number | null };
		Object.defineProperty(window, '__devTestAppliedSync', { value: applied });
		// These are the application's own EventTarget events after Phase 2 storage
		// and the full completion handler. Observe only flags and the scope epoch.
		const nativeDispatch = EventTarget.prototype.dispatchEvent;
		EventTarget.prototype.dispatchEvent = function(event: Event): boolean {
			const dispatched = nativeDispatch.call(this, event);
			if (event.type === 'phase_2_last_20_chats_ready') applied.phase2 = true;
			if (event.type === 'phasedSyncComplete' && event instanceof CustomEvent && event.detail?.synthetic !== true) {
				const epoch = event.detail?.context_epoch;
				if (typeof epoch === 'number' && Number.isSafeInteger(epoch)) {
					applied.completeEpoch = epoch;
					applied.completeAt = Date.now();
				}
			}
			return dispatched;
		};
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

	// The list is permission-scoped and excludes deletion-fenced rows. Use the
	// independent REST list result rather than the settings storage inventory.
	const readAuthorizedChatCount = async (): Promise<number> => {
		const result = await context.request.get(DEV_AUTHORIZED_CHAT_COUNT);
		expect(result.ok()).toBe(true);
		const total: unknown = (await result.json()).total_count;
		if (typeof total !== 'number' || !Number.isSafeInteger(total) || total <= 100) {
			throw new Error('Expected a populated authorized chat inventory');
		}
		return total;
	};
	let accountChatTotal = await readAuthorizedChatCount();

	const count = page.getByTestId('chat-account-total');
	const assertAccountCount = async () => {
		accountChatTotal = await readAuthorizedChatCount();
		await expect.soft(count).toBeVisible();
		await expect.soft(count).toHaveAttribute('data-chat-count', String(accountChatTotal));
	};
	const recentRowsMS: number[] = [];
	const visibleMessageMS: number[] = [];
	const selected = new Set<string>();
	const readableSelections: string[] = [];
	let failedOnlineSelections = 0;
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
					const tx = db.transaction((db.objectStoreNames.contains('saved_messages_v34') ? 'saved_messages_v34' : 'messages'), 'readonly');
					const count = tx.objectStore(tx.db.objectStoreNames.contains('saved_messages_v34') ? 'saved_messages_v34' : 'messages').index('chat_id').count(id);
					tx.oncomplete = () => { db.close(); finish(count.result); };
					tx.onabort = tx.onerror = () => { db.close(); finish(null); };
				} catch { db.close(); finish(null); }
			};
		});
		const view = document.querySelector('[data-testid="active-chat-container"]');
		const observedMarks = performance.getEntriesByType('mark').filter(mark => allowed.includes(mark.name));
		const marks = observedMarks.filter(mark => mark.startTime >= start).slice(-56);
		// An admission can start while the sidebar is painting, before the selected click.
		// These are the selected-session spine's fixed events, without chat identity.
		const previousAdmission = observedMarks.filter(mark => mark.startTime < start &&
			(mark.name.startsWith('openmates:rust:admission-') ||
				mark.name === 'openmates:rust:session-start' || mark.name === 'openmates:rust:session-ready')).slice(-12);
		return {
			retained_rows: retainedRows,
			active_message_count: Number(view?.getAttribute('data-current-message-count') ?? 0),
			navigator_online: navigator.onLine,
			read_stages: marks.map(mark => mark.name),
			read_stage_timing_ms: marks.map(mark => ({
				stage: mark.name,
				elapsed_ms: Math.round(mark.startTime - start),
			})),
			preclick_admission_timing_ms: previousAdmission.map(mark => ({
				stage: mark.name,
				elapsed_ms: Math.round(mark.startTime - start),
			})),
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
		lastLaunchTransportOffset = transports.length;
		lastLaunchStartedAt = Date.now();
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
		await page.evaluate(armSelectedFrameProbe, { rowSelector: ROW_SELECTOR, chatId, timeoutMs: READABLE_FRAME_TIMEOUT_MS });
		const start = await page.evaluate(() => performance.now());
		let firstFrame: Awaited<ReturnType<typeof takeSelectedFrameProbe>>;
		let selectedRead: Awaited<ReturnType<typeof readEvidence>>;
		try {
			await clickChat(chatId);
			await assertTranscript(chatId);
			visibleMessageMS.push(Math.round(await page.evaluate(() => performance.now()) - start));
			selectedRead = await readEvidence(chatId, start);
			firstFrame = await page.evaluate(takeSelectedFrameProbe);
			readableSelections.push(chatId);
		} catch {
			failedOnlineSelections++;
			// Diagnose this one deliberately selected chat after its timed attempt.
			// Only numeric counts, fixed stage names and HTTP status enter evidence.
			const snapshot = await readEvidence(chatId, start);
			const tail = await context.request.get('https://api.dev.openmates.org/v1/chats/' + chatId +
				'/messages/window?direction=latest&limit=1&respect_compression_boundary=false', { timeout: 10000 }).catch(() => null);
			const body = tail?.ok() ? await tail.json().catch(() => null) : null;
			const serverRows = Array.isArray(body?.messages) ? body.messages.length : null;
			await testInfo.attach('personal-devtest-web-failed-selection-' + (sample + 1), {
				body: JSON.stringify({ ...snapshot, server_status: tail?.status() ?? null, server_tail_rows: serverRows }),
				contentType: 'application/json',
			});
			continue;
		} finally {
			await page.evaluate(clearSelectedFrameProbe);
		}
		const navigation = await page.evaluate(browserNavigationTimings);
		const assets = await page.evaluate(browserResourceSnapshot);
		await testInfo.attach('personal-devtest-web-trial-' + (sample + 1), {
			body: JSON.stringify({ cached_navigation_to_recent_rows_ms: recentRowsMS[sample],
				select_to_visible_message_ms: visibleMessageMS[sample], selected_viewport: firstFrame,
				navigation, app_load: {
					http_cache_mode: httpCacheMode, service_workers: 'blocked',
					document_sizes: assets.navigation, resource_buckets: assets.buckets,
					resource_count: assets.totalEntries,
					resource_timing_may_be_truncated: assets.totalEntries >= 4096,
				}, ...selectedRead }),
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
		const processMeter = await createBrowserProcessEvidence(page, { collectRendererMetrics: true });
		try {
			const begin = await processMeter.begin();
			const receivedAtStart = { ...received };
			const sentAtStart = { ...sent };
			const transportCountAtStart = transports.length;
			idleTraffic = { inbound: {}, outbound: {} };
			await new Promise(resolve => setTimeout(resolve, IDLE_OBSERVATION_MS));
			const end = await processMeter.end();
			await testInfo.attach(attachment, {
				body: JSON.stringify({ observation_ms: IDLE_OBSERVATION_MS, begin, end,
					older_header_requests_through_idle: olderHeaderRequests,
					received_frame_kinds: idleTraffic.inbound,
					received_websocket_frames: received.frames - receivedAtStart.frames,
					received_websocket_bytes: received.bytes - receivedAtStart.bytes,
					sent_frame_kinds: idleTraffic.outbound,
					sent_websocket_frames: sent.frames - sentAtStart.frames,
					sent_websocket_bytes: sent.bytes - sentAtStart.bytes,
					new_connection_count: transports.length - transportCountAtStart }),
				contentType: 'application/json',
			});
			expect(begin.available && end.available, 'Verified CPU collection').toBe(true);
		} finally {
			idleTraffic = undefined;
			await processMeter.close();
		}
	};
	await measureIdle('personal-devtest-web-idle');

	// The launch observation intentionally includes work after first paint.
	// Measure a separate settled window only after this connection completed
	// sync and the page confirmed application of its startup data.
	const settledWaitStart = Date.now();
	let readiness = {
		requested: false, wire_complete: false, app_complete: false, phase2_applied: false,
		phase1b_pending: false, selected_chat_ready: false,
		navigation_to_sync_request_ms: null as number | null,
		navigation_to_wire_complete_ms: null as number | null,
		navigation_to_app_complete_ms: null as number | null,
	};
	const checkSettled = async () => {
		const transport = latestSyncTransport();
		const app = await page.evaluate(() => {
			const applied = (window as Window & { __devTestAppliedSync?: { phase2: boolean; completeEpoch: number | null; completeAt: number | null } }).__devTestAppliedSync;
			const selected = document.querySelector('[data-testid="active-chat-container"]');
			return { ...applied, selectedReady: selected?.getAttribute('data-chat-load-state') === 'ready' &&
				Number(selected.getAttribute('data-current-message-count')) > 0 };
		});
		const appComplete = transport?.requestEpoch != null && app.completeEpoch === transport.requestEpoch;
		const msSinceLaunch = (at: number | null | undefined) =>
			at != null && at >= lastLaunchStartedAt ? at - lastLaunchStartedAt : null;
		readiness = {
			requested: !!transport,
			wire_complete: transport?.wireCompleteEpoch != null,
			app_complete: appComplete,
			phase2_applied: transport?.phase2Received === true && app.phase2 === true,
			phase1b_pending: transport?.phase1bReceived === true && !transport.phase1bApplied,
			selected_chat_ready: app.selectedReady,
			navigation_to_sync_request_ms: msSinceLaunch(transport?.requestAt),
			navigation_to_wire_complete_ms: msSinceLaunch(transport?.wireCompleteAt),
			navigation_to_app_complete_ms: appComplete ? msSinceLaunch(app.completeAt) : null,
		};
		return readiness.wire_complete && readiness.app_complete && readiness.phase2_applied &&
			!readiness.phase1b_pending && readiness.selected_chat_ready && await hasOpenTransport();
	};
	let settled = false;
	try {
		await expect.poll(checkSettled, { timeout: SETTLED_READINESS_TIMEOUT_MS }).toBe(true);
		settled = true;
	} catch {
		// The launch measurement remains usable. Record which readiness stages
		// timed out and continue to the independent offline/reconnect assertions.
	} finally {
		await testInfo.attach('personal-devtest-web-settled-readiness', {
			body: JSON.stringify({ settled, readiness_wait_ms: Date.now() - settledWaitStart, ...readiness }),
			contentType: 'application/json',
		});
	}
	if (settled) await measureIdle('personal-devtest-web-settled-idle');
	// Check the badge after capturing idle work on both old and updated builds.
	await assertAccountCount();

	// Use only the conversations already opened above. Keep both the existing
	// transcript and a second cached selection usable across an actual socket loss.
	const first = readableSelections[0];
	const last = readableSelections.at(-1);
	if (!first || !last || first === last) throw new Error('Offline navigation requires two independently opened and readable conversations');
	if (await active.getAttribute('data-current-chat-id') !== last) {
		await clickChat(last);
		await assertTranscript(last, 'restore readable selection before disconnect');
	}
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
	expect(failedOnlineSelections, 'All three online selections must render').toBe(0);
	expect(readableSelections).toHaveLength(3);
});
