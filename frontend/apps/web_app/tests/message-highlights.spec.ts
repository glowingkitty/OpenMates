/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * message-highlights.spec.ts
 *
 * Full E2E for the text-highlighting feature — lifecycle AND correctness.
 *
 *   1. Send a seed user message, select text, click "Highlight" → verify
 *      the <mark> text EXACTLY matches the selected phrase, is visible,
 *      and doesn't eat surrounding characters.
 *   2. Second highlight via "Highlight & comment" → verify both marks wrap
 *      only their intended text, don't overlap, and the comment round-trips.
 *   3. Viewport resize (mobile 375×812, tablet 768×1024) → all marks must
 *      survive reflow: correct text, non-zero bounding box, readable color.
 *   4. Click commented highlight → popover shows saved comment + Edit/Delete.
 *   5. Delete a highlight → count decrements.
 *   6. Touch-device entry point via selection toolbar.
 *   7. Final text-integrity check: full seed text still present in DOM.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
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

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const SELECTORS = {
	userMessageContent: '[data-testid="user-message-content"]',
	mateMessageContent: '[data-testid="mate-message-content"]',
	messageContextHighlight: '[data-testid="chat-context-highlight"]',
	messageContextHighlightAndComment: '[data-testid="chat-context-highlight-and-comment"]',
	highlightBox: '[data-testid="message-highlight-box"]',
	headerHighlightCount: '[data-testid="chat-header-highlight-count"]',
	commentPopover: '[data-testid="highlight-comment-popover"]',
	commentInput: '[data-testid="highlight-comment-input"]',
	commentSave: '[data-testid="highlight-comment-save"]',
	commentDelete: '[data-testid="highlight-comment-delete"]',
	commentEdit: '[data-testid="highlight-comment-edit"]',
	commentText: '[data-testid="highlight-comment-text"]',
	selectionToolbar: '[data-testid="message-selection-toolbar"]',
	selectionToolbarHighlight: '[data-testid="message-selection-highlight"]'
};

function setupPageListeners(page: any): void {
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (request: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${response.url()}`);
	});
}

/**
 * Select text inside a rendered message AND atomically dispatch a contextmenu
 * event on the message element, all from within a single page.evaluate call so
 * the selection is still live when the event fires.
 */
async function selectAndOpenContextMenu(
	page: any,
	messageSelector: string,
	textToSelect: string
): Promise<{ selected: boolean; rect: { x: number; y: number; width: number; height: number } | null }> {
	return page.evaluate(
		({ sel, needle }: { sel: string; needle: string }) => {
			const container = document.querySelector(sel) as HTMLElement | null;
			if (!container) return { selected: false, rect: null };

			const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
			let node: Node | null = walker.nextNode();
			while (node) {
				const t = node as Text;
				const nodeText = t.nodeValue ?? '';
				const idx = nodeText.indexOf(needle);
				if (idx !== -1) {
					const range = document.createRange();
					range.setStart(t, idx);
					range.setEnd(t, idx + needle.length);
					const selection = window.getSelection();
					if (!selection) return { selected: false, rect: null };
					selection.removeAllRanges();
					selection.addRange(range);
					const r = range.getBoundingClientRect();
					const ev = new MouseEvent('contextmenu', {
						bubbles: true,
						cancelable: true,
						view: window,
						clientX: Math.max(0, r.x + r.width / 2),
						clientY: Math.max(0, r.y + r.height / 2),
						button: 2
					});
					container.dispatchEvent(ev);
					return {
						selected: true,
						rect: { x: r.x, y: r.y, width: r.width, height: r.height }
					};
				}
				node = walker.nextNode();
			}
			return { selected: false, rect: null };
		},
		{ sel: messageSelector, needle: textToSelect }
	);
}

/**
 * Assert the highlight <mark> element wraps exactly the expected text,
 * is visible, has non-zero size, and its text is readable (not hidden
 * behind a solid yellow block). Returns the mark's bounding rect.
 */
async function assertHighlightCorrectness(
	page: any,
	markLocator: any,
	expectedText: string,
	label: string
): Promise<{ x: number; y: number; width: number; height: number }> {
	// Text must exactly match the selected phrase
	const markText = (await markLocator.textContent() ?? '').trim();
	expect(markText, `[${label}] mark text must equal selected text`).toBe(expectedText);

	// Must be visible
	await expect(markLocator, `[${label}] mark must be visible`).toBeVisible();

	// Non-zero bounding box (not collapsed to 0×0)
	const rect = await markLocator.boundingBox();
	expect(rect, `[${label}] mark must have a bounding box`).not.toBeNull();
	expect(rect.width, `[${label}] mark width > 0`).toBeGreaterThan(0);
	expect(rect.height, `[${label}] mark height > 0`).toBeGreaterThan(0);

	// Text must be readable: computed color differs from background
	const styles = await markLocator.evaluate((el: HTMLElement) => {
		const cs = window.getComputedStyle(el);
		return {
			color: cs.color,
			backgroundColor: cs.backgroundColor,
			visibility: cs.visibility,
			display: cs.display,
			opacity: cs.opacity
		};
	});
	expect(styles.visibility, `[${label}] not hidden`).not.toBe('hidden');
	expect(styles.display, `[${label}] not display:none`).not.toBe('none');
	const opacity = parseFloat(styles.opacity);
	expect(isNaN(opacity) ? 1 : opacity, `[${label}] opacity > 0`).toBeGreaterThan(0);
	expect(styles.color, `[${label}] text color != background (text must be readable)`).not.toBe(styles.backgroundColor);

	// Width sanity: a phrase highlight should not span nearly the full message
	const containerWidth = await page.locator(SELECTORS.userMessageContent).first().evaluate(
		(el: HTMLElement) => el.getBoundingClientRect().width
	);
	expect(rect.width, `[${label}] mark width < 90% of message`).toBeLessThan(containerWidth * 0.9);

	return rect;
}

/**
 * Verify all N marks survive at a given viewport size: correct text, visible,
 * readable color, non-zero bounds.
 */
async function assertHighlightsAtViewport(
	page: any,
	marks: any,
	expectedTexts: Set<string>,
	viewportLabel: string,
	takeStepScreenshot: (page: any, label: string) => Promise<void>,
	screenshotLabel: string
): Promise<void> {
	const count = await marks.count();
	expect(count, `[${viewportLabel}] mark count`).toBe(expectedTexts.size);
	const seen = new Set<string>();
	for (let i = 0; i < count; i++) {
		const m = marks.nth(i);
		const txt = (await m.textContent() ?? '').trim();
		expect(expectedTexts.has(txt), `[${viewportLabel}] mark ${i} text "${txt}" is expected`).toBe(true);
		seen.add(txt);
		await expect(m, `[${viewportLabel}] mark ${i} visible`).toBeVisible();
		const box = await m.boundingBox();
		expect(box, `[${viewportLabel}] mark ${i} has bounding box`).not.toBeNull();
		expect(box.width, `[${viewportLabel}] mark ${i} width > 0`).toBeGreaterThan(0);
		expect(box.height, `[${viewportLabel}] mark ${i} height > 0`).toBeGreaterThan(0);
		const style = await m.evaluate((el: HTMLElement) => {
			const cs = window.getComputedStyle(el);
			return { color: cs.color, bg: cs.backgroundColor };
		});
		expect(style.color, `[${viewportLabel}] mark ${i} text readable`).not.toBe(style.bg);
	}
	expect(seen.size, `[${viewportLabel}] all expected texts found`).toBe(expectedTexts.size);
	await takeStepScreenshot(page, screenshotLabel);
}


test('message highlights: correctness, lifecycle, viewport resize', async ({ page }: { page: any }) => {
	setupPageListeners(page);
	test.setTimeout(240000);

	const logCheckpoint = createSignupLogger('HIGHLIGHTS');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'msg-highlights'
	});

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting message-highlights E2E test.');

	// ───────────────────────────────────────────────────────────
	// STEP 1 — Login + start fresh chat + send a seed message
	// ───────────────────────────────────────────────────────────
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	const seedText = 'The quick brown fox jumps over the lazy dog near the old bridge today.';
	await sendMessage(page, seedText, logCheckpoint, takeStepScreenshot, 'seed');

	const userMsg = page.locator(SELECTORS.userMessageContent).first();
	await expect(userMsg).toBeVisible({ timeout: 15000 });
	await expect(userMsg).toContainText('quick brown fox');
	await takeStepScreenshot(page, '01-seed-rendered');
	logCheckpoint('User message rendered.');

	// ───────────────────────────────────────────────────────────
	// STEP 2 — First highlight (no comment): "quick brown fox"
	// ───────────────────────────────────────────────────────────
	logCheckpoint('Selecting "quick brown fox"...');
	await page.evaluate((sel: string) => {
		const el = document.querySelector(sel) as HTMLElement | null;
		el?.scrollIntoView({ block: 'center', inline: 'nearest' });
	}, SELECTORS.userMessageContent);
	await page.waitForTimeout(200);

	const sel1 = await selectAndOpenContextMenu(
		page,
		SELECTORS.userMessageContent,
		'quick brown fox'
	);
	expect(sel1.selected).toBe(true);
	await takeStepScreenshot(page, '02-selection-quick-brown-fox');

	const highlightBtn = page.locator(SELECTORS.messageContextHighlight);
	await expect(highlightBtn).toBeVisible({ timeout: 5000 });
	await highlightBtn.click();
	logCheckpoint('Clicked "Highlight".');
	await takeStepScreenshot(page, '03-highlight-1-clicked');

	const marks = page.locator(SELECTORS.highlightBox);
	await expect(marks).toHaveCount(1, { timeout: 10000 });

	// ── STRICT CORRECTNESS: mark text == "quick brown fox" ──
	const rect1 = await assertHighlightCorrectness(page, marks.first(), 'quick brown fox', 'hl-1');
	logCheckpoint(`Highlight 1 verified: width=${rect1.width.toFixed(0)}px`);
	await takeStepScreenshot(page, '04-highlight-1-verified');

	// ChatHeader pill
	const pill = page.locator(SELECTORS.headerHighlightCount);
	await expect(pill).toBeVisible({ timeout: 10000 });
	const pillText1 = (await pill.textContent())?.trim() ?? '';
	logCheckpoint(`Pill after hl-1: "${pillText1}"`);
	expect(pillText1).toMatch(/1\b|^\s*1/);

	// ───────────────────────────────────────────────────────────
	// STEP 3 — Second highlight WITH comment: "old bridge"
	// ───────────────────────────────────────────────────────────
	logCheckpoint('Selecting "old bridge"...');
	await page.evaluate((sel: string) => {
		const el = document.querySelector(sel) as HTMLElement | null;
		el?.scrollIntoView({ block: 'center', inline: 'nearest' });
	}, SELECTORS.userMessageContent);
	await page.waitForTimeout(200);

	const sel2 = await selectAndOpenContextMenu(
		page,
		SELECTORS.userMessageContent,
		'old bridge'
	);
	expect(sel2.selected).toBe(true);

	const commentBtn = page.locator(SELECTORS.messageContextHighlightAndComment);
	await expect(commentBtn).toBeVisible({ timeout: 5000 });
	await commentBtn.click();
	logCheckpoint('Clicked "Highlight & comment".');
	await takeStepScreenshot(page, '05-highlight-comment-clicked');

	const popover = page.locator(SELECTORS.commentPopover);
	await expect(popover).toBeVisible({ timeout: 10000 });
	const input = page.locator(SELECTORS.commentInput);
	await expect(input).toBeVisible({ timeout: 5000 });

	const COMMENT_TEXT = 'I was here last summer — the bridge is oak, not stone.';
	await input.fill(COMMENT_TEXT);
	await takeStepScreenshot(page, '06-comment-typed');

	const saveBtn = page.locator(SELECTORS.commentSave);
	await saveBtn.click();
	logCheckpoint('Saved comment.');

	const commentView = page.locator(SELECTORS.commentText);
	await expect(commentView).toBeVisible({ timeout: 10000 });
	await expect(commentView).toHaveText(COMMENT_TEXT, { timeout: 5000 });
	await takeStepScreenshot(page, '07-comment-saved');

	await expect(marks).toHaveCount(2, { timeout: 10000 });

	// ── STRICT CORRECTNESS: both marks wrap only their intended text ──
	const expectedTexts = new Set(['quick brown fox', 'old bridge']);
	for (let i = 0; i < 2; i++) {
		const m = marks.nth(i);
		const txt = (await m.textContent() ?? '').trim();
		expect(expectedTexts.has(txt), `Mark ${i} text "${txt}" must be one of the expected phrases`).toBe(true);
		await assertHighlightCorrectness(page, m, txt, `hl-${i + 1}-detail`);
	}
	logCheckpoint('Both highlight marks verified for correctness.');
	await takeStepScreenshot(page, '08-both-verified');

	// Pill shows 2 highlights + 1 comment
	const pillText2 = (await pill.textContent())?.trim() ?? '';
	logCheckpoint(`Pill after hl-2: "${pillText2}"`);
	expect(pillText2).toMatch(/2/);
	expect(pillText2).toMatch(/1/);

	// Close popover
	await page.mouse.click(5, 5);
	await expect(popover).not.toBeVisible({ timeout: 5000 });

	// ── NO OVERLAP: marks must not overlap ──
	const box0 = await marks.nth(0).boundingBox();
	const box1 = await marks.nth(1).boundingBox();
	if (box0 && box1) {
		const first = box0.x < box1.x ? box0 : box1;
		const second = box0.x < box1.x ? box1 : box0;
		expect(
			first.x + first.width,
			'Marks must not overlap horizontally'
		).toBeLessThanOrEqual(second.x + 2);
	}

	// ───────────────────────────────────────────────────────────
	// STEP 4 — Viewport resize: mobile (375×812)
	// ───────────────────────────────────────────────────────────
	logCheckpoint('Resizing to mobile (375×812)...');
	const originalSize = page.viewportSize();
	await page.setViewportSize({ width: 375, height: 812 });
	await page.waitForTimeout(500);
	await assertHighlightsAtViewport(
		page, marks, expectedTexts, 'mobile-375',
		takeStepScreenshot, '09-mobile-verified'
	);
	logCheckpoint('Mobile viewport passed.');

	// ───────────────────────────────────────────────────────────
	// STEP 5 — Viewport resize: tablet (768×1024)
	// ───────────────────────────────────────────────────────────
	logCheckpoint('Resizing to tablet (768×1024)...');
	await page.setViewportSize({ width: 768, height: 1024 });
	await page.waitForTimeout(500);
	await assertHighlightsAtViewport(
		page, marks, expectedTexts, 'tablet-768',
		takeStepScreenshot, '10-tablet-verified'
	);
	logCheckpoint('Tablet viewport passed.');

	// Restore original viewport
	if (originalSize) {
		await page.setViewportSize(originalSize);
		await page.waitForTimeout(300);
	}

	// ───────────────────────────────────────────────────────────
	// STEP 6 — Click commented highlight → view popover
	// ───────────────────────────────────────────────────────────
	logCheckpoint('Clicking commented highlight...');
	// Find the "old bridge" mark specifically
	let commentedMarkIdx = 0;
	for (let i = 0; i < 2; i++) {
		const txt = (await marks.nth(i).textContent() ?? '').trim();
		if (txt === 'old bridge') { commentedMarkIdx = i; break; }
	}
	await marks.nth(commentedMarkIdx).click({ force: true });
	await expect(popover).toBeVisible({ timeout: 5000 });
	await expect(commentView).toHaveText(COMMENT_TEXT);
	await expect(page.locator(SELECTORS.commentEdit)).toBeVisible();
	await expect(page.locator(SELECTORS.commentDelete)).toBeVisible();
	await takeStepScreenshot(page, '11-view-popover');

	// ───────────────────────────────────────────────────────────
	// STEP 7 — Delete commented highlight
	// ───────────────────────────────────────────────────────────
	logCheckpoint('Deleting commented highlight...');
	await page.locator(SELECTORS.commentDelete).click();
	await expect(popover).not.toBeVisible({ timeout: 5000 });
	await expect(marks).toHaveCount(1, { timeout: 10000 });
	const pillText3 = (await pill.textContent())?.trim() ?? '';
	logCheckpoint(`Pill after delete: "${pillText3}"`);
	expect(pillText3).toMatch(/1/);

	// Remaining mark is "quick brown fox" — wait for overlay recompute after delete
	await page.waitForTimeout(300);
	await assertHighlightCorrectness(page, marks.first(), 'quick brown fox', 'after-delete');
	await takeStepScreenshot(page, '12-after-delete');

	// ───────────────────────────────────────────────────────────
	// STEP 8 — Embed exclusion: highlights must NOT wrap embed text
	// ───────────────────────────────────────────────────────────
	// The AI response (mate message) likely contains embed previews (web search
	// results, images, etc.). Highlight body text near embeds and verify that
	// no <mark> lands inside an .embed-full-width-wrapper subtree.
	const mateMsg = page.locator(SELECTORS.mateMessageContent).first();
	const hasMateMsg = await mateMsg.isVisible().catch(() => false);
	if (hasMateMsg) {
		// Find actual prose text in the mate message body — skip UI elements
		// like ThinkingSection, chat-mate-name, embed titles, etc.
		const mateBodyText = await mateMsg.evaluate((el: HTMLElement) => {
			// Look inside .chat-message-body for rendered ProseMirror text
			const bodyEl = el.querySelector('.chat-message-body');
			if (!bodyEl) return null;
			const walker = document.createTreeWalker(bodyEl, NodeFilter.SHOW_TEXT, {
				acceptNode(n) {
					const parent = (n as Text).parentElement;
					if (!parent) return NodeFilter.FILTER_REJECT;
					if (parent.closest('.embed-full-width-wrapper')) return NodeFilter.FILTER_REJECT;
					if (parent.closest('[data-testid]')) return NodeFilter.FILTER_REJECT;
					const text = (n.nodeValue ?? '').trim();
					if (text.length < 8) return NodeFilter.FILTER_REJECT;
					return NodeFilter.FILTER_ACCEPT;
				}
			});
			const node = walker.nextNode();
			if (!node) return null;
			const full = (node.nodeValue ?? '').trim();
			const words = full.split(/\s+/).slice(0, 4).join(' ');
			return words.length >= 5 ? words : null;
		});

		if (mateBodyText) {
			logCheckpoint(`Selecting mate body text near embeds: "${mateBodyText}"...`);
			await mateMsg.scrollIntoViewIfNeeded();
			await page.waitForTimeout(200);
			const mateSel = await selectAndOpenContextMenu(
				page,
				SELECTORS.mateMessageContent,
				mateBodyText
			);
			if (mateSel.selected) {
				const mateHighlightBtn = page.locator(SELECTORS.messageContextHighlight);
				const highlightAvailable = await mateHighlightBtn.isVisible({ timeout: 3000 }).catch(() => false);
				if (highlightAvailable) {
					await mateHighlightBtn.click();
					logCheckpoint('Highlighted mate body text.');
					await page.waitForTimeout(500);

					// Verify: no <mark> exists inside an embed wrapper
					const marksInEmbed = await mateMsg.evaluate((el: HTMLElement) => {
						const embedMarks = el.querySelectorAll(
							'.embed-full-width-wrapper mark.message-highlight-mark'
						);
						return embedMarks.length;
					});
					expect(marksInEmbed, 'No highlights should be inside embed wrappers').toBe(0);
					logCheckpoint('Embed exclusion verified — no marks inside embeds.');
					await takeStepScreenshot(page, '12b-embed-exclusion');
				} else {
					// Dismiss context menu and continue
					await page.mouse.click(5, 5);
					await page.waitForTimeout(200);
					logCheckpoint('Highlight option not in context menu for this message — skipping.');
				}
			} else {
				logCheckpoint('Could not select mate body text — skipping embed exclusion check.');
			}
		} else {
			logCheckpoint('No non-embed body text in mate message — skipping embed exclusion check.');
		}
	} else {
		logCheckpoint('No mate message visible — skipping embed exclusion check.');
	}

	// ───────────────────────────────────────────────────────────
	// STEP 9 — Popover visibility when highlight is in lower viewport
	// ───────────────────────────────────────────────────────────
	logCheckpoint('Testing popover position with highlight in lower viewport...');
	// Scroll the user message to the bottom of the viewport so the highlight
	// mark ("quick brown fox") sits in the lower half, then click it and
	// verify the popover is fully within the viewport.
	await page.evaluate((sel: string) => {
		const el = document.querySelector(sel) as HTMLElement | null;
		// Scroll so the message appears near the bottom of the viewport
		el?.scrollIntoView({ block: 'end', inline: 'nearest' });
	}, SELECTORS.userMessageContent);
	await page.waitForTimeout(300);

	// Click the remaining "quick brown fox" mark
	const remainingMark = marks.first();
	await remainingMark.click({ force: true });
	logCheckpoint('Clicked highlight in lower viewport position.');
	await page.waitForTimeout(300);

	// The popover should be visible
	await expect(popover).toBeVisible({ timeout: 5000 });
	await takeStepScreenshot(page, '12c-popover-lower-viewport');

	// The popover must be fully within the viewport (not clipped)
	const popoverBox = await popover.boundingBox();
	const viewportSize = page.viewportSize();
	expect(popoverBox, 'Popover must have a bounding box').not.toBeNull();
	if (popoverBox && viewportSize) {
		expect(popoverBox.y, 'Popover top must be >= 0 (not above viewport)').toBeGreaterThanOrEqual(0);
		expect(
			popoverBox.y + popoverBox.height,
			'Popover bottom must be within viewport'
		).toBeLessThanOrEqual(viewportSize.height + 2); // 2px tolerance
		expect(popoverBox.x, 'Popover left must be >= 0').toBeGreaterThanOrEqual(0);
		expect(
			popoverBox.x + popoverBox.width,
			'Popover right must be within viewport'
		).toBeLessThanOrEqual(viewportSize.width + 2);
		logCheckpoint(`Popover box: top=${popoverBox.y.toFixed(0)} bottom=${(popoverBox.y + popoverBox.height).toFixed(0)} viewport=${viewportSize.height}`);
	}
	// Close popover
	await page.mouse.click(5, 5);
	await expect(popover).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('Popover visibility in lower viewport verified.');

	// ───────────────────────────────────────────────────────────
	// STEP 10 — Touch-device path: selection toolbar
	// ───────────────────────────────────────────────────────────
	// Delete any extra mate-message highlights from step 8 before proceeding
	const currentMarkCount = await marks.count();
	if (currentMarkCount > 1) {
		// Delete extra marks by clicking and deleting until only 1 remains
		for (let i = currentMarkCount - 1; i >= 1; i--) {
			const m = marks.nth(i);
			const txt = (await m.textContent() ?? '').trim();
			if (txt !== 'quick brown fox') {
				await m.click({ force: true });
				const deleteBtn = page.locator(SELECTORS.commentDelete);
				if (await deleteBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
					await deleteBtn.click();
					await page.waitForTimeout(300);
				} else {
					await page.mouse.click(5, 5);
					await page.waitForTimeout(200);
				}
			}
		}
	}
	logCheckpoint('Verifying selection toolbar (touch path)...');
	await page.evaluate((sel: string) => {
		const el = document.querySelector(sel) as HTMLElement | null;
		el?.scrollIntoView({ block: 'center', inline: 'nearest' });
	}, SELECTORS.userMessageContent);
	await page.waitForTimeout(200);

	const selToolbarSelected = await page.evaluate(
		({ sel, needle }: { sel: string; needle: string }) => {
			const container = document.querySelector(sel) as HTMLElement | null;
			if (!container) return false;
			const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
			let node: Node | null = walker.nextNode();
			while (node) {
				const t = node as Text;
				const nodeText = t.nodeValue ?? '';
				const idx = nodeText.indexOf(needle);
				if (idx !== -1) {
					const range = document.createRange();
					range.setStart(t, idx);
					range.setEnd(t, idx + needle.length);
					const selection = window.getSelection();
					if (!selection) return false;
					selection.removeAllRanges();
					selection.addRange(range);
					return true;
				}
				node = walker.nextNode();
			}
			return false;
		},
		{ sel: SELECTORS.userMessageContent, needle: 'lazy' }
	);
	expect(selToolbarSelected).toBe(true);

	const toolbar = page.locator(SELECTORS.selectionToolbar);
	await expect(toolbar).toBeVisible({ timeout: 5000 });
	logCheckpoint('Selection toolbar appeared.');
	await takeStepScreenshot(page, '13-toolbar-visible');

	const toolbarHighlight = page.locator(SELECTORS.selectionToolbarHighlight);
	await toolbarHighlight.dispatchEvent('mousedown');
	logCheckpoint('Tapped toolbar Highlight.');

	await expect(marks).toHaveCount(2, { timeout: 10000 });

	// ── STRICT: the new mark should wrap "lazy" ──
	// Scope to user message only (mate message may have marks from step 8)
	const userMarks = userMsg.locator(SELECTORS.highlightBox);
	await expect(userMarks).toHaveCount(2, { timeout: 10000 });
	const toolbarExpected = new Set(['quick brown fox', 'lazy']);
	for (let i = 0; i < 2; i++) {
		const m = userMarks.nth(i);
		const txt = (await m.textContent() ?? '').trim();
		expect(toolbarExpected.has(txt), `Toolbar-hl mark ${i} text "${txt}" must be expected`).toBe(true);
		await expect(m).toBeVisible();
	}
	const pillText4 = (await pill.textContent())?.trim() ?? '';
	logCheckpoint(`Pill after toolbar-highlight: "${pillText4}"`);
	expect(pillText4).toMatch(/2/);
	await takeStepScreenshot(page, '14-toolbar-highlight-verified');

	// ───────────────────────────────────────────────────────────
	// STEP 11 — Full text integrity: seed text still intact in DOM
	// ───────────────────────────────────────────────────────────
	const fullText = await userMsg.evaluate((el: HTMLElement) => {
		return (el.textContent ?? '').replace(/\s+/g, ' ').trim();
	});
	logCheckpoint(`Full visible text: "${fullText}"`);
	expect(
		fullText,
		'Full message text must still contain the seed (highlights must not eat characters)'
	).toContain('The quick brown fox jumps over the lazy dog near the old bridge today.');
	await takeStepScreenshot(page, '15-text-integrity');

	// ── Cleanup ─────────────────────────────────────────────────
	logCheckpoint('Cleaning up test chat.');
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'cleanup');
	logCheckpoint('message-highlights test completed successfully.');
});
