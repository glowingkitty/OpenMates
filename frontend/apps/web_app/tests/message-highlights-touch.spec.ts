/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { devices } = require('@playwright/test');

// Force every test in this file into an iPad-style touch context so the
// MessageSelectionToolbar path (the only workable entry point on iOS/iPadOS)
// is actually exercised. hasTouch: true makes Playwright emit real
// touchstart/touchmove/touchend events and expose `page.touchscreen`.
test.use({
	...devices['iPad Pro 11'],
	hasTouch: true,
	isMobile: true
});

const consoleLogs: string[] = [];
const networkActivities: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
	networkActivities.length = 0;
});

test.afterEach(async ({ page: _page }: { page: any }, testInfo: any) => {
	void _page;
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-30).forEach((log) => console.log(log));
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-30).forEach((activity) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

/**
 * Message highlights — TOUCH-DEVICE regression spec.
 *
 * Locks in two bugs fixed in this session that only reproduced on iPad:
 *   1. Rendered-text vs raw-markdown offset mismatch caused the highlight
 *      to land on wrong text (often stretching to the start of the
 *      message). This spec checks the BOUNDING RECT of the rendered box
 *      against the BOUNDING RECT of the original selection — they must
 *      overlap meaningfully. A "highlight appeared somewhere" assertion
 *      wouldn't have caught the bug.
 *   2. The selection-toolbar tap racing with iOS selectionchange events
 *      that shrink the selection mid-tap → committed snapshot wins.
 *
 * Uses a real iPad-emulation context (hasTouch: true, devices['iPad Pro 11']).
 * Selection is scripted via page.evaluate because iOS word-select gestures
 * can't be replayed reliably by Playwright, but every click/tap after the
 * selection uses page.touchscreen so the Svelte `ontouchstart` path runs.
 *
 * REQUIRED ENV VARS (same as other chat specs):
 *   OPENMATES_TEST_ACCOUNT_EMAIL / _PASSWORD / _OTP_KEY, PLAYWRIGHT_TEST_BASE_URL
 */

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const SELECTORS = {
	userMessageContent: '[data-testid="user-message-content"]',
	selectionToolbar: '[data-testid="message-selection-toolbar"]',
	selectionToolbarHighlight: '[data-testid="message-selection-highlight"]',
	highlightBox: '[data-testid="message-highlight-box"]',
	headerHighlightCount: '[data-testid="chat-header-highlight-count"]'
};

function setupPageListeners(page: any): void {
	page.on('console', (msg: any) => {
		const ts = new Date().toISOString();
		consoleLogs.push(`[${ts}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (r: any) => networkActivities.push(`>> ${r.method()} ${r.url()}`));
	page.on('response', (r: any) => networkActivities.push(`<< ${r.status()} ${r.url()}`));
}

/**
 * Select `needle` inside `messageSelector` via the DOM Selection API and
 * return the selection's bounding rect (viewport coords). Selection survives
 * subsequent taps because my selection-toolbar code commits the source-offset
 * snapshot on selectionchange.
 */
async function selectInsideMessage(
	page: any,
	messageSelector: string,
	needle: string
): Promise<{ x: number; y: number; width: number; height: number } | null> {
	return page.evaluate(
		({ sel, n }: { sel: string; n: string }) => {
			const container = document.querySelector(sel) as HTMLElement | null;
			if (!container) return null;
			const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
			let node: Node | null = walker.nextNode();
			while (node) {
				const t = node as Text;
				const idx = (t.nodeValue ?? '').indexOf(n);
				if (idx !== -1) {
					const range = document.createRange();
					range.setStart(t, idx);
					range.setEnd(t, idx + n.length);
					const selection = window.getSelection();
					if (!selection) return null;
					selection.removeAllRanges();
					selection.addRange(range);
					const r = range.getBoundingClientRect();
					return { x: r.x, y: r.y, width: r.width, height: r.height };
				}
				node = walker.nextNode();
			}
			return null;
		},
		{ sel: messageSelector, n: needle }
	);
}

/** Tap a locator by computing its centre + using page.touchscreen. */
async function touchTap(page: any, selector: string): Promise<void> {
	const box = await page.locator(selector).first().boundingBox();
	if (!box) throw new Error(`touchTap: no bounding box for ${selector}`);
	await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
}

/**
 * Assert that two rects overlap "meaningfully" — used to verify the rendered
 * highlight box lines up with the original selection rather than drifting to
 * a different part of the message (the exact bug that prompted this spec).
 *
 * Criteria: the HIGHLIGHT's horizontal centre falls within the SELECTION's
 * horizontal extent AND they share at least 50% vertical overlap. Tolerant
 * enough to survive sub-pixel rendering differences on mobile viewports.
 */
function assertRectsOverlap(
	selectionRect: { x: number; y: number; width: number; height: number },
	highlightRect: { x: number; y: number; width: number; height: number },
	label: string
): void {
	const selCx = selectionRect.x + selectionRect.width / 2;
	const highCx = highlightRect.x + highlightRect.width / 2;
	const selLeft = selectionRect.x;
	const selRight = selectionRect.x + selectionRect.width;
	const horizontallyInside =
		highCx >= selLeft - selectionRect.width * 0.2 &&
		highCx <= selRight + selectionRect.width * 0.2;

	const topOverlap = Math.max(selectionRect.y, highlightRect.y);
	const botOverlap = Math.min(
		selectionRect.y + selectionRect.height,
		highlightRect.y + highlightRect.height
	);
	const overlapH = Math.max(0, botOverlap - topOverlap);
	const fraction = overlapH / Math.max(1, selectionRect.height);

	if (!horizontallyInside || fraction < 0.5) {
		throw new Error(
			`[${label}] Highlight rect does not overlap selection rect. ` +
				`selection=(${selectionRect.x.toFixed(1)}, ${selectionRect.y.toFixed(1)}, ` +
				`${selectionRect.width.toFixed(1)}x${selectionRect.height.toFixed(1)}) vs ` +
				`highlight=(${highlightRect.x.toFixed(1)}, ${highlightRect.y.toFixed(1)}, ` +
				`${highlightRect.width.toFixed(1)}x${highlightRect.height.toFixed(1)}). ` +
				`selCx=${selCx.toFixed(1)} highCx=${highCx.toFixed(1)} vOverlap=${(fraction * 100).toFixed(1)}%`
		);
	}
}

test('message highlights on touch devices (iPad Pro 11) — selection toolbar + geometric overlap', async ({
	page
}: {
	page: any;
}) => {
	setupPageListeners(page);
	test.setTimeout(240000);

	const logCheckpoint = createSignupLogger('HIGHLIGHTS_TOUCH');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'msg-highlights-touch'
	});

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting iPad touch highlights spec.');

	// ───────────────────────────────────────────────────────────
	// STEP 1 — Login + new chat + seed message (touch context)
	// ───────────────────────────────────────────────────────────
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	const seedText =
		'The quick brown fox jumps over the lazy dog near the old bridge today.';
	await sendMessage(page, seedText, logCheckpoint, takeStepScreenshot, 'touch-seed');

	const userMsg = page.locator(SELECTORS.userMessageContent).first();
	await expect(userMsg).toBeVisible({ timeout: 15000 });
	await expect(userMsg).toContainText('quick brown fox');
	await takeStepScreenshot(page, 'seed-rendered');

	// Scroll into view via DOM to avoid Playwright actionability waits while
	// the AI is streaming a response in the background.
	await page.evaluate((sel: string) => {
		const el = document.querySelector(sel) as HTMLElement | null;
		el?.scrollIntoView({ block: 'center', inline: 'nearest' });
	}, SELECTORS.userMessageContent);
	await page.waitForTimeout(200);

	// ───────────────────────────────────────────────────────────
	// STEP 2 — Select "lazy dog" → toolbar appears → tap Highlight
	// ───────────────────────────────────────────────────────────
	logCheckpoint('Selecting "lazy dog" via DOM Selection API...');
	const sel1Rect = await selectInsideMessage(page, SELECTORS.userMessageContent, 'lazy dog');
	expect(sel1Rect).not.toBeNull();
	await takeStepScreenshot(page, 'selection-lazy-dog');

	// The toolbar is driven off selectionchange — it should appear without
	// any user tap.
	const toolbar = page.locator(SELECTORS.selectionToolbar);
	await expect(toolbar).toBeVisible({ timeout: 5000 });
	logCheckpoint('Floating selection toolbar appeared after selectionchange.');
	await takeStepScreenshot(page, 'toolbar-visible');

	// Tap the Highlight button using the real touchscreen so the Svelte
	// `ontouchstart` handler runs (NOT `onclick` — iOS fires touch events
	// first and would cancel the selection before click).
	logCheckpoint('Tapping Highlight button via touchscreen...');
	await touchTap(page, SELECTORS.selectionToolbarHighlight);
	await takeStepScreenshot(page, 'after-toolbar-tap');

	// A single highlight should exist.
	const highlightBox = page.locator(SELECTORS.highlightBox);
	await expect(highlightBox).toHaveCount(1, { timeout: 10000 });

	// ───────────────────────────────────────────────────────────
	// STEP 3 — GEOMETRY check: rendered box must overlap selection
	// ───────────────────────────────────────────────────────────
	// This is the core regression guard: a "wrong-text" highlight (like the
	// iPad bug where the yellow stretched from the start of the message)
	// would produce a box with a totally different horizontal centre from
	// the user's original selection. Fail fast with a diagnostic message.
	const box1 = await highlightBox.boundingBox();
	expect(box1).not.toBeNull();
	logCheckpoint(
		`sel1 rect=(${sel1Rect!.x.toFixed(1)}, ${sel1Rect!.y.toFixed(1)}, ${sel1Rect!.width.toFixed(1)}x${sel1Rect!.height.toFixed(1)})`
	);
	logCheckpoint(
		`highlight1 rect=(${box1!.x.toFixed(1)}, ${box1!.y.toFixed(1)}, ${box1!.width.toFixed(1)}x${box1!.height.toFixed(1)})`
	);
	assertRectsOverlap(sel1Rect!, box1!, 'lazy dog');
	logCheckpoint('Geometry check passed — yellow box lines up with "lazy dog".');

	// ───────────────────────────────────────────────────────────
	// STEP 4 — Second selection on a different word → independent
	//          highlight lands on its own position (catches offset-
	//          accumulation regressions).
	// ───────────────────────────────────────────────────────────
	logCheckpoint('Selecting "old bridge" and highlighting via toolbar...');
	await page.evaluate((sel: string) => {
		const el = document.querySelector(sel) as HTMLElement | null;
		el?.scrollIntoView({ block: 'center', inline: 'nearest' });
	}, SELECTORS.userMessageContent);
	await page.waitForTimeout(150);

	const sel2Rect = await selectInsideMessage(page, SELECTORS.userMessageContent, 'old bridge');
	expect(sel2Rect).not.toBeNull();
	await expect(toolbar).toBeVisible({ timeout: 5000 });
	await touchTap(page, SELECTORS.selectionToolbarHighlight);
	await takeStepScreenshot(page, 'after-second-tap');

	await expect(highlightBox).toHaveCount(2, { timeout: 10000 });
	// The SECOND box should overlap the SECOND selection rect (not the first).
	const box2 = await highlightBox.nth(1).boundingBox();
	expect(box2).not.toBeNull();
	logCheckpoint(
		`sel2 rect=(${sel2Rect!.x.toFixed(1)}, ${sel2Rect!.y.toFixed(1)}, ${sel2Rect!.width.toFixed(1)}x${sel2Rect!.height.toFixed(1)})`
	);
	logCheckpoint(
		`highlight2 rect=(${box2!.x.toFixed(1)}, ${box2!.y.toFixed(1)}, ${box2!.width.toFixed(1)}x${box2!.height.toFixed(1)})`
	);
	assertRectsOverlap(sel2Rect!, box2!, 'old bridge');
	logCheckpoint('Geometry check passed — second yellow box lines up with "old bridge".');

	// ChatHeader pill reflects the new count.
	const pill = page.locator(SELECTORS.headerHighlightCount);
	await expect(pill).toBeVisible({ timeout: 5000 });
	const pillText = (await pill.textContent())?.trim() ?? '';
	logCheckpoint(`ChatHeader pill: "${pillText}"`);
	expect(pillText).toMatch(/2/);

	// Cleanup
	logCheckpoint('Cleaning up the test chat.');
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'cleanup-touch');
	logCheckpoint('message-highlights-touch spec completed.');
});
