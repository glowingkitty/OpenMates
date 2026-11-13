/* eslint-disable @typescript-eslint/no-require-imports */
/* eslint-disable @typescript-eslint/no-explicit-any -- Playwright Page handles are untyped in these CommonJS helpers. */
/**
 * Draft-save metric for the interleaved TS-vs-Rust web benchmark
 * (web-rust-core-bench-run.ts). After a sample's reload, types `SAVES` short
 * edits into the open saved chat's editor and measures, per edit, the time from
 * the debounced save trigger (last keydown + the 1200 ms editor debounce) to the
 * committed chats_db row carrying a new draft_v. The same in-page poller runs in
 * both arms, so its cost cancels. Returns the per-sample p95 (max of the 3 saves,
 * kept for continuity), the first save and the median of the later saves
 * separately, the pending_sync_changes size around the saves, per-save Rust stage
 * timings (rustDraftRoute.ts mark) and the route marker (`rust-local`/`rust-synced`
 * on the Rust arm, `ts-<code>` or none on TS).
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

/** In-page: number of entries in chats_db/pending_sync_changes (null when unreadable). */
function countPendingSyncChanges(): Promise<number | null> {
	return new Promise((resolve) => {
		const open = indexedDB.open('chats_db');
		open.onerror = () => resolve(null);
		open.onsuccess = () => {
			const db = open.result;
			if (!db.objectStoreNames.contains('pending_sync_changes')) { db.close(); resolve(null); return; }
			const request = db.transaction('pending_sync_changes', 'readonly').objectStore('pending_sync_changes').count();
			request.onsuccess = () => { db.close(); resolve(request.result); };
			request.onerror = () => { db.close(); resolve(null); };
		};
	});
}

/**
 * In-page: the Rust route's stage mark (rustDraftRoute.ts `openmates:rust:draft-timing`)
 * for the save triggered by the last keydown, plus the route entry delay after the
 * debounce (`preRouteMs`: draftSave.ts work and the route's dynamic import).
 */
function draftTimingAfterLastKeydown(): Record<string, unknown> | null {
	const lastKeydown = Number((window as any).__draftSaveBench?.lastKeydown ?? 0);
	const entries = performance.getEntriesByName('openmates:rust:draft-timing').filter((entry) => entry.startTime > lastKeydown);
	const entry = entries[entries.length - 1] as PerformanceMark | undefined;
	if (!entry) return null;
	// 1200 = DRAFT_DEBOUNCE_MS (this function is serialized into the page).
	return { preRouteMs: entry.startTime - lastKeydown - 1200, ...(entry.detail as Record<string, unknown>) };
}

const median = (values: number[]): number | null => {
	if (values.length === 0) return null;
	const sorted = [...values].sort((a, b) => a - b);
	const middle = Math.floor(sorted.length / 2);
	return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
};

interface DraftSaveSample {
	/** Old continuity field: max of the SAVES saves (nearest-rank p95 of 3). */
	draftSaveP95Ms: number | null;
	/** First save after the reload (unit open, dynamic import, first chats_db open). */
	draftSaveFirstMs: number | null;
	/** Median of saves 2..SAVES (steady state on the same page). */
	draftSaveRestMedianMs: number | null;
	/** pending_sync_changes size before the first and after the last save of this sample. */
	draftQueueEntriesBefore: number | null;
	draftQueueEntriesAfter: number | null;
	/** Per save: committed ms plus, on the Rust arm, the route's stage mark. */
	draftSaves: Record<string, unknown>[];
	draftSaveMarker: string | null;
}

/** Measures SAVES draft saves on the open chat; returns first/steady/p95 durations, queue size, stages and the route marker. */
async function measureDraftSaves(page: any, chatId: string, rustArm: boolean): Promise<DraftSaveSample> {
	// Drafts on Rust need the server-checked history admission (the real-use state: a user types after the chat opened);
	// an earlier save is routed to the TS writer by design. The TS arm has no such mark and measures straight away.
	if (rustArm) {
		await page.waitForFunction(() => performance.getEntriesByName('openmates:rust:session-ready').length > 0, null, { timeout: 30000 });
	}
	// Click the visible input itself: with a restored draft no ProseMirror has a box until the input is focused.
	await page.getByTestId('message-editor').filter({ visible: true }).first().click({ position: { x: 20, y: 10 }, timeout: 15_000 });
	const draftQueueEntriesBefore = await page.evaluate(countPendingSyncChanges);
	const durations: number[] = [];
	const draftSaves: Record<string, unknown>[] = [];
	for (let index = 0; index < SAVES; index += 1) {
		await page.evaluate(() => { (window as any).__draftSaveBenchArmed = false; });
		const committed = page.evaluate(awaitCommittedDraft, chatId);
		await page.waitForFunction(() => (window as any).__draftSaveBenchArmed === true);
		await page.keyboard.type(` bench draft ${index}`);
		const result = await committed;
		const route = await page.evaluate(() => `${document.documentElement.dataset.rustCoreDraft ?? 'none'}/${document.documentElement.dataset.rustCoreHistory ?? 'none'}`);
		expect(result.ms, `draft save ${index} committed (draft route/history: ${route})`).not.toBeNull();
		const ms = Math.max(0, result.ms as number);
		durations.push(ms);
		let stages: Record<string, unknown> | null = null;
		if (rustArm) {
			// The row commits inside the Worker before the save reply (and its mark) reaches the page.
			await page.waitForFunction(draftTimingAfterLastKeydown, null, { timeout: 5_000 }).catch(() => undefined);
			stages = await page.evaluate(draftTimingAfterLastKeydown);
		}
		draftSaves.push({ ms, ...(stages ?? {}) });
	}
	const draftQueueEntriesAfter = await page.evaluate(countPendingSyncChanges);
	const marker = await page.evaluate(() => document.documentElement.dataset.rustCoreDraft ?? null);
	await page.keyboard.press('ControlOrMeta+a');
	await page.keyboard.press('Backspace');
	await page.waitForTimeout(DRAFT_DEBOUNCE_MS + 800);
	const sorted = [...durations].sort((a, b) => a - b);
	return {
		draftSaveP95Ms: sorted[Math.ceil(0.95 * sorted.length) - 1],
		draftSaveFirstMs: durations[0],
		draftSaveRestMedianMs: median(durations.slice(1)),
		draftQueueEntriesBefore,
		draftQueueEntriesAfter,
		draftSaves,
		draftSaveMarker: marker
	};
}

module.exports = { measureDraftSaves, DRAFT_DEBOUNCE_MS };
