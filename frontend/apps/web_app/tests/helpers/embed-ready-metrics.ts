/* eslint-disable @typescript-eslint/no-require-imports, @typescript-eslint/no-explicit-any -- Playwright helpers expose untyped CommonJS exports. */
/**
 * Shared seeding + measurement for the embed-ready comparison between the TS
 * embed data path (default build) and the Rust-core embed data path
 * (VITE_OPENMATES_RUST_CORE=1 build). Both specs seed the same mock-replayed code
 * embed chat and measure the same reload window, so their JSON attachments are
 * directly comparable: embed ready time, browser CPU (all verified Chromium
 * processes, includes the Rust embed Worker) and memory (main JS heap + RSS).
 */
export {};

const { expect } = require('@playwright/test');
const { getE2EDebugUrl, withMockMarker } = require('../signup-flow-helpers');
const { loginToTestAccount, sendMessage } = require('./chat-test-helpers');
const { createBrowserProcessEvidence } = require('./browser-process-evidence.cjs');

const CODE_PROMPT = 'Write a Python function called "process_csv" that reads a CSV file, '
	+ 'accepts a "sort_column" parameter, sorts the data by that column, '
	+ 'and returns the top 5 rows. Use pandas. Show the complete code in a single code block.';

/** Login, send one mock-replayed message that yields a finished code embed, return its chat id. */
async function seedCodeEmbedChat(page: any, log: any, screenshot: any, options: { blockProductionWorker?: boolean } = {}): Promise<string> {
	let storedReplies = 0;
	page.on('websocket', (socket: any) => socket.on('framereceived', (frame: any) => {
		if (String(frame.payload).includes('"ai_response_storage_confirmed"')) storedReplies++;
	}));
	await loginToTestAccount(page, log, screenshot);
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30000 });
	const newChatButton = page.getByTestId('new-chat-button');
	if (await newChatButton.isVisible()) await newChatButton.click();
	// The flag-on build would otherwise admit the shared Rust core Worker for the TS send.
	if (options.blockProductionWorker) await page.route('**/shared.worker*', (route: any) => route.abort());
	await sendMessage(page, withMockMarker(CODE_PROMPT, 'code_gen_turn1'), log, screenshot, 'seed-code-embed');
	await expect(page).toHaveURL(/chat-id=[0-9a-f]{8}-/, { timeout: 30000 });
	const chatId = page.url().match(/chat-id=([0-9a-f-]{36})/)![1];
	await expect(page.locator('[data-testid="message-assistant"] [data-testid="embed-preview"][data-app-id="code"][data-status="finished"]').first())
		.toBeVisible({ timeout: 90000 });
	await expect.poll(() => storedReplies, { timeout: 60000, message: 'server stored the assistant reply with its embed' }).toBeGreaterThanOrEqual(1);
	if (options.blockProductionWorker) await page.unroute('**/shared.worker*');
	log('seeded code embed chat', { chatId });
	return chatId;
}

/**
 * In-page: ms since navigation start until a finished code embed preview matches
 * `selector`, plus attribution: when the first assistant row appeared and the
 * app's own `openmates:rust*` performance marks/measures (Rust builds only).
 */
function waitEmbedReady({ selector, rowSelector }: { selector: string; rowSelector: string }): Promise<{
	embedReadyMs: number | null; assistantRowMs: number | null; rustStages: Record<string, number>;
}> {
	return new Promise((resolve) => {
		let assistantRowMs: number | null = null;
		const stages = (): Record<string, number> => Object.fromEntries(performance.getEntries()
			.filter((entry) => entry.name.startsWith('openmates:rust'))
			.map((entry) => [entry.name.replace('openmates:', ''), Math.round(entry.entryType === 'measure' ? entry.duration : entry.startTime)]));
		const tick = () => {
			const now = performance.now();
			if (assistantRowMs === null && document.querySelector(rowSelector)) assistantRowMs = now;
			if (document.querySelector(selector)) resolve({ embedReadyMs: now, assistantRowMs, rustStages: stages() });
			else if (now > 90000) resolve({ embedReadyMs: null, assistantRowMs, rustStages: stages() });
			else setTimeout(tick, 10);
		};
		tick();
	});
}

function median(values: number[]): number | null {
	if (!values.length) return null;
	const sorted = [...values].sort((a, b) => a - b);
	return sorted[Math.floor(sorted.length / 2)];
}

/**
 * Reloads the seeded chat `samples` times and measures each reload window until
 * the embed preview inside `scope` is finished. Returns per-sample rows + medians.
 */
async function measureEmbedReady(page: any, chatId: string, scope: string, samples = 3): Promise<Record<string, unknown>> {
	const selector = `${scope} [data-testid="embed-preview"][data-app-id="code"][data-status="finished"]`;
	const processes = await createBrowserProcessEvidence(page);
	const rows: Record<string, unknown>[] = [];
	try {
		for (let index = 0; index < samples; index += 1) {
			await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`));
			await processes.begin();
			await page.reload();
			const workersBefore = page.workers().length;
			const { embedReadyMs, assistantRowMs, rustStages } = await page.evaluate(waitEmbedReady, { selector, rowSelector: scope });
			const process = await processes.end();
			const heap = await page.evaluate(() => (performance as Performance & { memory?: { usedJSHeapSize: number } }).memory?.usedJSHeapSize ?? null);
			rows.push({
				embedReadyMs,
				assistantRowMs,
				workers: Math.max(workersBefore, page.workers().length),
				rustStages,
				browserCpuMs: process.available ? process.stableReportedProcessCpuMs : null,
				browserRssBytes: process.available ? process.after.summedReportedProcessRssBytes : null,
				mainHeapBytes: heap,
			});
		}
	} finally {
		await processes.close();
	}
	const pick = (key: string) => median(rows.map((row) => row[key]).filter((v): v is number => typeof v === 'number'));
	return {
		samples: rows,
		median: { embedReadyMs: pick('embedReadyMs'), assistantRowMs: pick('assistantRowMs'), browserCpuMs: pick('browserCpuMs'), browserRssBytes: pick('browserRssBytes'), mainHeapBytes: pick('mainHeapBytes') },
		definition: 'Reload of the seeded chat route until the finished code embed preview is in the DOM. CPU/RSS: CDP SystemInfo process window around the reload (all verified Chromium processes incl. workers; see browser-process-evidence.cjs limitations).',
	};
}

module.exports = { seedCodeEmbedChat, measureEmbedReady };
