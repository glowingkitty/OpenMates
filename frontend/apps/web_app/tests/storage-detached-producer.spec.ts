/* eslint-disable @typescript-eslint/no-require-imports */
/** Real Docs broker/worker recovery with a signed, provider-free model fixture. */
// contract-test-file: infrastructure
export {};

const { test, expect } = require('./console-monitor');
const { spawnSync } = require('node:child_process');
const { realpathSync } = require('node:fs');
const { getTestAccount, getE2EDebugUrl, createSignupLogger,
	createStepScreenshotter, installE2EServerContentOverrideGate } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage } = require('./helpers/chat-test-helpers');

type Frame = { direction: 'sent' | 'received'; type: string; payload: Record<string, any> };

function requireProfile(): { compose: string; source: string } {
	if (process.env.E2E_STORAGE_CAPACITY !== '1' || !getTestAccount().email) {
		throw new Error('detached_producer_isolated_account_required');
	}
	const compose = process.env.E2E_STORAGE_DETACHED_COMPOSE_FILE || '';
	const source = process.env.E2E_STORAGE_DETACHED_SOURCE_COMMIT || '';
	if (!/^[0-9a-f]{40}$/.test(source) || !realpathSync(compose).includes('/ci-private/')) {
		throw new Error('detached_producer_source_profile_invalid');
	}
	return { compose, source };
}

function observe(page: any): Frame[] {
	const frames: Frame[] = [];
	page.on('websocket', (socket: any) => {
		for (const [direction, event] of [['sent', 'framesent'], ['received', 'framereceived']] as const) {
			socket.on(event, (frame: any) => {
				try {
					const decoded = JSON.parse(String(frame.payload));
					if (typeof decoded.type === 'string') {
						frames.push({ direction, type: decoded.type, payload: decoded.payload ?? {} });
					}
				} catch { /* Binary transport frames are unrelated. */ }
			});
		}
	});
	return frames;
}

function sealedBeforeForward(profile: { compose: string; source: string }, embedId: string): boolean {
	if (!/^[0-9a-f-]{36}$/.test(embedId)) return false;
	const source = [
		'import os,sys,httpx',
		'assert os.getenv("CI") == "true" and os.getenv("OPENMATES_CI_ISOLATED") == "1"',
		'assert os.getenv("OPENMATES_STORAGE_CAPACITY_FIXTURES") == "true"',
		'assert os.getenv("BUILD_COMMIT_SHA") == sys.argv[2]',
		'base = os.environ["CMS_URL"].rstrip("/")',
		'login = httpx.post(base + "/auth/login", json={',
		'  "email":os.environ["DATABASE_ADMIN_EMAIL"],',
		'  "password":os.environ["DATABASE_ADMIN_PASSWORD"],"mode":"json"}, timeout=5)',
		'login.raise_for_status()',
		'token = login.json().get("data", {}).get("access_token")',
		'assert isinstance(token, str) and token',
		'headers = {"Authorization":"Bearer " + token}',
		'producer = httpx.get(base + "/items/chat_recovery_output_producers",',
		'  params={"filter[primary_embed_id][_eq]":sys.argv[1],',
		'          "fields":"id,registered_at","limit":"1"}, headers=headers, timeout=5)',
		'producer.raise_for_status()',
		'intents = producer.json().get("data", [])',
		'assert len(intents) == 1 and intents[0].get("registered_at")',
		'response = httpx.get(base + "/items/chat_recovery_outputs",',
		'  params={"filter[subject_id][_eq]":sys.argv[1],"filter[output_kind][_eq]":"embed",',
		'          "filter[state][_eq]":"PENDING","fields":"id,producer_intent_id,created_at","limit":"1"},',
		'  headers=headers, timeout=5)',
		'response.raise_for_status()',
		'outputs = response.json().get("data", [])',
		'assert len(outputs) == 1 and outputs[0]["producer_intent_id"] == intents[0]["id"]',
		'from datetime import datetime,timezone',
		'def utc(value):',
		'  parsed = datetime.fromisoformat(value.replace("Z","+00:00"))',
		'  return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)',
		'assert utc(intents[0]["registered_at"]) <= utc(outputs[0]["created_at"])',
	].join('\n');
	const result = spawnSync('docker', [
		'compose', '-f', profile.compose, 'exec', '-T', 'api', 'python', '-c',
		source, embedId, profile.source,
	], { encoding: 'utf8', timeout: 20_000 });
	return !result.error && result.status === 0 && !result.signal;
}

async function deferCanonicalEmbedWrites(
	page: any, profile: { compose: string; source: string },
	probe: { checked: boolean; sealed: boolean },
): Promise<void> {
	await page.routeWebSocket(/\/v1\/ws(?:\?|$)/, (socket: any) => {
		const server = socket.connectToServer();
		const blocked = new Set(['store_embed', 'store_embed_diff', 'store_embed_keys',
			'store_embed_bundle',
			'recovery_output_ack_embed']);
		socket.onMessage((raw: unknown) => {
			let type = '';
			try { type = JSON.parse(String(raw)).type; } catch { /* Preserve non-JSON frames. */ }
			if (!blocked.has(type)) server.send(raw);
		});
		server.onMessage((raw: unknown) => {
			try {
				const frame = JSON.parse(String(raw));
				if (frame.type === 'send_embed_data' && frame.payload?.status === 'finished'
					&& frame.payload?.type === 'document') {
					probe.checked = true;
					probe.sealed = sealedBeforeForward(profile, frame.payload.embed_id);
				}
			} catch { /* Preserve other transport frames. */ }
			socket.send(raw);
		});
	});
}

function forgetOneEmbedCache(profile: { compose: string; source: string }, embedId: string): void {
	if (!/^[0-9a-f-]{36}$/.test(embedId)) throw new Error('detached_embed_id_invalid');
	// Only the one disposable embed cache entry is removed. The broker, account
	// session, and unrelated Redis keys remain untouched.
	const source = [
		'import os,sys,redis',
		'from urllib.parse import urlsplit',
		'assert os.getenv("CI") == "true" and os.getenv("OPENMATES_CI_ISOLATED") == "1"',
		'assert os.getenv("OPENMATES_STORAGE_CAPACITY_FIXTURES") == "true"',
		'assert os.getenv("MOCK_EXTERNAL_APIS") == "true"',
		'assert os.getenv("BUILD_COMMIT_SHA") == sys.argv[2]',
		'url = urlsplit("redis://" + os.environ["DRAGONFLY_URL"])',
		'client = redis.Redis(host=url.hostname, port=url.port or 6379, password=os.environ["DRAGONFLY_PASSWORD"], socket_timeout=5)',
		'assert client.delete("embed:" + sys.argv[1]) == 1',
	].join('\n');
	const result = spawnSync('docker', [
		'compose', '-f', profile.compose, 'exec', '-T', 'api', 'python', '-c',
		source, embedId, profile.source,
	], { encoding: 'utf8', timeout: 20_000 });
	if (result.error || result.status !== 0 || result.signal) {
		throw new Error('detached_embed_cache_loss_probe_failed');
	}
}

// contract-test: supporting surface=gui.web assertions=storage.background.saved-output-retention,storage.background.complete-sealed-recovery
test('detached Docs worker seals before publication and recovers after its Redis embed cache is lost',
	async ({ browser }: { browser: any }) => {
		const profile = requireProfile();
		test.setTimeout(360_000);
		const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
		const sourceContext = await browser.newContext({ baseURL });
		const recoveryContext = await browser.newContext({ baseURL });
		const sourcePage = await sourceContext.newPage();
		const recoveryPage = await recoveryContext.newPage();
		const sourceFrames = observe(sourcePage);
		const recoveryFrames = observe(recoveryPage);
		const publicationProbe = { checked: false, sealed: false };
		const log = createSignupLogger('storage-detached-producer');
		const screenshot = createStepScreenshotter(log);
		try {
			await deferCanonicalEmbedWrites(sourcePage, profile, publicationProbe);
			await installE2EServerContentOverrideGate(sourcePage, 'storage-detached-producer');
			await loginToTestAccount(sourcePage, log, screenshot);
			await expect.poll(() => sourceFrames.find((frame) =>
				frame.direction === 'received' && frame.type === 'recovery_outputs_discovery_complete')
				?.payload.status, { timeout: 30_000 }).toBe('completed');
			await startNewChat(sourcePage, log);
			await sendMessage(sourcePage,
				'Create a local synthetic document. STORAGE_CAPACITY_SCENARIO:recovery_detached_doc '
				+ '<<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
				log, screenshot, 'storage-detached-doc');
			const chatId = sourcePage.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
			expect(chatId).toBeTruthy();
			const finished = () => sourceFrames.find((frame) =>
				frame.direction === 'received' && frame.type === 'send_embed_data'
				&& frame.payload.chat_id === chatId && frame.payload.status === 'finished'
				&& frame.payload.type === 'document');
			await expect.poll(() => Boolean(finished()), {
				timeout: 180_000, message: 'The real app_docs worker must publish its finished document',
			}).toBe(true);
			const embedId = finished()!.payload.embed_id;
			expect(embedId).toMatch(/^[0-9a-f-]{36}$/);
			expect(publicationProbe).toEqual({ checked: true, sealed: true });
			expect(sourceFrames.some((frame) => frame.type === 'store_embed_confirmed')).toBe(false);
			forgetOneEmbedCache(profile, embedId);
			await sourceContext.close();

			await loginToTestAccount(recoveryPage, log, screenshot);
			await expect.poll(() => recoveryFrames.filter((frame) =>
				frame.direction === 'received' && frame.type === 'recovery_outputs_available')
				.flatMap((frame) => frame.payload.outputs ?? [])
				.some((output: any) => output.root_chat_id === chatId
					&& output.output_kind === 'embed' && output.subject_id === embedId), {
				timeout: 180_000, message: 'Recovery discovery must use the sealed row after cache loss',
			}).toBe(true);
			await expect.poll(() => recoveryFrames.some((frame) =>
				frame.direction === 'received' && frame.type === 'recovery_output_embed_acknowledged'
				&& frame.payload.state === 'ACKNOWLEDGED'), { timeout: 120_000 }).toBe(true);
			await expect.poll(() => recoveryFrames.some((frame) =>
				frame.direction === 'received' && frame.type === 'store_embed_confirmed'
				&& frame.payload.canonical_source === 'head'), { timeout: 120_000 }).toBe(true);
			await recoveryPage.goto(getE2EDebugUrl('/#chat-id=' + encodeURIComponent(chatId!)));
			await recoveryPage.reload();
			await expect(recoveryPage.getByTestId('message-assistant').first()).toBeVisible({ timeout: 90_000 });
		} finally {
			await sourceContext.close().catch(() => undefined);
			await recoveryContext.close();
		}
	});
