/* eslint-disable @typescript-eslint/no-require-imports */
/* eslint-disable @typescript-eslint/no-explicit-any -- Playwright Page handles are untyped in these CommonJS helpers. */
/**
 * Draft-save metric for the interleaved TS-vs-Rust web benchmark
 * (web-rust-core-bench-run.ts). After a sample's reload, types `SAVES` short
 * edits into the open saved chat's editor and measures, per edit, the time from
 * the debounced save trigger (last keydown + the 1200 ms editor debounce) to the
 * committed chats_db row carrying a new draft_v. The same in-page poller runs in
 * both arms, so its cost cancels. Returns the per-sample p95 and the route
 * marker (`rust-local`/`rust-synced` on the Rust arm, `ts-<code>` or none on TS).
 * The editor is cleared afterwards so the seeded chat keeps no draft.
 */
export {};

const { expect } = require('./cookie-audit');

const SAVES = 3;
/** draftSave.ts saveDraftDebounced wait; subtracted so only the save itself is measured. */
const DRAFT_DEBOUNCE_MS = 1200;

/** In-page: one committed draft_v change after the next keydown, as ms after debounce expiry. */
function awaitCommittedDraft(chatId: string): Promise<{ ms: number | null; draftV: number | null }> {
	const bench = ((window as any).__draftSaveBench ??= { lastKeydown: 0, installed: false });
	if (!bench.installed) {
		bench.installed = true;
		document.addEventListener('keydown', () => { bench.lastKeydown = performance.now(); }, true);
	}
	return new Promise((resolve) => {
		const open = indexedDB.open('chats_db');
		open.onerror = () => resolve({ ms: null, draftV: null });
		open.onsuccess = () => {
			const db = open.result;
			const read = (): Promise<number> => new Promise((done) => {
				const request = db.transaction('chats', 'readonly').objectStore('chats').get(chatId);
				request.onsuccess = () => done(Number(request.result?.draft_v ?? 0));
				request.onerror = () => done(-1);
			});
			void read().then((before) => {
				const started = performance.now();
				const tick = async () => {
					const now = performance.now();
					const value = await read();
					if (value !== before && bench.lastKeydown > started) {
						db.close();
						// 1200 = DRAFT_DEBOUNCE_MS (this function is serialized into the page).
						resolve({ ms: now - bench.lastKeydown - 1200, draftV: value });
					} else if (now - started > 15_000) {
						db.close();
						resolve({ ms: null, draftV: null });
					} else setTimeout(tick, 5);
				};
				(window as any).__draftSaveBenchArmed = true;
				void tick();
			});
		};
	});
}

/** Measures SAVES draft saves on the open chat; returns the per-sample p95 (nearest rank) and the route marker. */
async function measureDraftSaves(page: any, chatId: string, rustArm: boolean): Promise<{ draftSaveP95Ms: number | null; draftSaveMarker: string | null }> {
	// Drafts on Rust need the server-checked history admission (the real-use state: a user types after the chat opened);
	// an earlier save is routed to the TS writer by design. The TS arm has no such mark and measures straight away.
	if (rustArm) {
		await page.waitForFunction(() => performance.getEntriesByName('openmates:rust:session-ready').length > 0, null, { timeout: 30000 });
	}
	// Click the visible input itself: with a restored draft no ProseMirror has a box until the input is focused.
	await page.getByTestId('message-editor').filter({ visible: true }).first().click({ position: { x: 20, y: 10 }, timeout: 15_000 });
	const durations: number[] = [];
	for (let index = 0; index < SAVES; index += 1) {
		await page.evaluate(() => { (window as any).__draftSaveBenchArmed = false; });
		const committed = page.evaluate(awaitCommittedDraft, chatId);
		await page.waitForFunction(() => (window as any).__draftSaveBenchArmed === true);
		await page.keyboard.type(` bench draft ${index}`);
		const result = await committed;
		const route = await page.evaluate(() => `${document.documentElement.dataset.rustCoreDraft ?? 'none'}/${document.documentElement.dataset.rustCoreHistory ?? 'none'}`);
		expect(result.ms, `draft save ${index} committed (draft route/history: ${route})`).not.toBeNull();
		durations.push(Math.max(0, result.ms as number));
	}
	const marker = await page.evaluate(() => document.documentElement.dataset.rustCoreDraft ?? null);
	await page.keyboard.press('ControlOrMeta+a');
	await page.keyboard.press('Backspace');
	await page.waitForTimeout(DRAFT_DEBOUNCE_MS + 800);
	durations.sort((a, b) => a - b);
	return { draftSaveP95Ms: durations[Math.ceil(0.95 * durations.length) - 1], draftSaveMarker: marker };
}

module.exports = { measureDraftSaves, DRAFT_DEBOUNCE_MS };
