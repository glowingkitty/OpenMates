/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Explain in new chat E2E coverage.
 *
 * Verifies the selected-assistant-text workflow: selecting text exposes the
 * Explain in new chat option in the existing highlight context menu, starts a
 * clean background chat, shows an open action notification, and auto-sends only
 * the explanation prompt without appending anything to the source transcript.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	withMockMarker
} = require('./signup-flow-helpers');
const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	waitForAssistantMessage,
	deleteActiveChat
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const IS_PROOF_CAPTURE = Boolean(process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT);
const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';
const PROOF_VISIBLE_STATE_MS = 1200;
const MIN_CONTEXT_MENU_TEXT_CONTRAST = 4.5;
const MIN_CHAT_HEADER_ICON_TOP_GAP = 12;

const EXPLAIN_IN_NEW_CHAT_PROOF_CONTRACT = defineVideoProof({
	id: 'explain-in-new-chat-notification-action',
	title: 'Explain in new chat notification action proof',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'assistant-selection-action',
			text: 'I select assistant text in an existing chat and choose Explain in new chat.',
			checkpoint: 'assistant-selection-action',
			devices: ['web-laptop']
		},
		{
			id: 'source-chat-unchanged',
			text: 'The source chat still shows the original vector database exchange without adding the explanation prompt.',
			checkpoint: 'source-chat-unchanged',
			devices: ['web-laptop']
		},
		{
			id: 'background-open-action',
			text: 'The front notification shows an Open chat action for the background explanation chat.',
			checkpoint: 'background-open-action',
			devices: ['web-laptop']
		},
		{
			id: 'explanation-chat-content',
			text: 'The new chat contains only the explanation prompt and then receives an assistant response.',
			checkpoint: 'explanation-chat-content',
			devices: ['web-laptop']
		},
		{
			id: 'mobile-signed-in',
			text: 'I open OpenMates in a 390 pixel mobile viewport and sign into the test account.',
			checkpoint: 'mobile-signed-in',
			devices: ['web-phone']
		},
		{
			id: 'mobile-selection-ready',
			text: 'After the assistant mentions vector database, I select that text in the response.',
			checkpoint: 'mobile-selection-ready',
			devices: ['web-phone']
		},
		{
			id: 'mobile-toolbar-fits',
			text: 'The mobile selection toolbar stays inside the screen and shows Explain in new chat.',
			checkpoint: 'mobile-toolbar-fits',
			devices: ['web-phone']
		}
	],
	assertions: [
		{
			id: 'assistant-selection-action',
			checkpoint: 'assistant-selection-action',
			visual: 'User-message selection does not expose Explain in new chat, while assistant-message selection does in a readable action surface whose text has sufficient contrast and whose action icons render as icons rather than square placeholders.',
			devices: ['web-laptop']
		},
		{
			id: 'source-chat-unchanged',
			checkpoint: 'source-chat-unchanged',
			visual: 'The source chat still shows the original seed prompt and vector database answer, with no Tell me more prompt added.',
			devices: ['web-laptop']
		},
		{
			id: 'background-open-action',
			checkpoint: 'background-open-action',
			visual: 'The background notification is the front card and presents a visible Open chat action.',
			devices: ['web-laptop']
		},
		{
			id: 'explanation-chat-content',
			checkpoint: 'explanation-chat-content',
			visual: 'The new chat contains Tell me more about: vector database, omits the original seed prompt and answer, and shows an assistant response.',
			devices: ['web-laptop']
		},
		{
			id: 'mobile-toolbar-fits',
			checkpoint: 'mobile-toolbar-fits',
			visual: 'The mobile selection toolbar is visible, includes Explain in new chat, and fits within the 390px viewport.',
			devices: ['web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1200, maximumHoldMs: 5000 }
});

const SELECTORS = {
	userMessageContent: '[data-testid="user-message-content"]',
	mateMessageContent: '[data-testid="mate-message-content"]',
	selectionToolbar: '[data-testid="message-selection-toolbar"]',
	selectionToolbarExplain: '[data-testid="message-selection-explain-new-chat"]',
	contextMenuExplain: '[data-testid="chat-context-explain-new-chat"]',
	notification: '[data-testid="notification"]',
	notificationAction: '[data-testid="notification-action"]',
	chatMessage: '[data-testid="message-user"], [data-testid="message-assistant"]'
};

async function selectInsideMessage(
	page: any,
	messageSelector: string,
	needle: string
): Promise<{ selected: boolean; rect: { x: number; y: number; width: number; height: number } | null }> {
	return page.evaluate(
		({ sel, n }: { sel: string; n: string }) => {
			const container = document.querySelector(sel) as HTMLElement | null;
			if (!container) return { selected: false, rect: null };
			container.scrollIntoView({ block: 'nearest', inline: 'nearest' });

			const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
			let node: Node | null = walker.nextNode();
			while (node) {
				const textNode = node as Text;
				const idx = (textNode.nodeValue ?? '').indexOf(n);
				if (idx !== -1) {
					const range = document.createRange();
					range.setStart(textNode, idx);
					range.setEnd(textNode, idx + n.length);
					const selection = window.getSelection();
					if (!selection) return { selected: false, rect: null };
					selection.removeAllRanges();
					selection.addRange(range);
					document.dispatchEvent(new Event('selectionchange'));
					const r = range.getBoundingClientRect();
					return { selected: true, rect: { x: r.x, y: r.y, width: r.width, height: r.height } };
				}
				node = walker.nextNode();
			}
			return { selected: false, rect: null };
		},
		{ sel: messageSelector, n: needle }
	);
}

async function openMessageContextMenu(
	page: any,
	messageSelector: string,
	rect: { x: number; y: number; width: number; height: number },
	options: { requireExplainAction?: boolean; selectedText?: string } = {}
): Promise<void> {
	const point = { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
	await page.evaluate(
		({ sel, p }: { sel: string; p: { x: number; y: number } }) => {
			const container = document.querySelector(sel) as HTMLElement | null;
			if (!container) throw new Error(`Message container not found for selector: ${sel}`);
			container.dispatchEvent(
				new MouseEvent('contextmenu', {
					bubbles: true,
					cancelable: true,
					clientX: p.x,
					clientY: p.y,
					button: 2
				})
			);
		},
		{ sel: messageSelector, p: point }
	);
	if (!options.requireExplainAction) return;
	try {
		await expect(page.locator(`${SELECTORS.contextMenuExplain}, ${SELECTORS.selectionToolbarExplain}`).first()).toBeVisible({ timeout: 1000 });
		return;
	} catch {
		await page.evaluate(() => {
			document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, clientX: 1, clientY: 1 }));
		});
		if (options.selectedText) {
			await selectInsideMessage(page, messageSelector, options.selectedText);
		}
		await page.mouse.click(point.x, point.y, { button: 'right' });
	}
}

async function expectContextMenuVisualIntegrity(page: any): Promise<void> {
	const actionSurfaceSelector = '[data-testid="message-context-menu"], [data-testid="message-selection-toolbar"]';
	await expect(page.locator(actionSurfaceSelector).first()).toBeVisible({ timeout: 5000 });
	const issues = await page.evaluate((minimumContrast: number) => {
		const surfaces = Array.from(
			document.querySelectorAll<HTMLElement>('[data-testid="message-context-menu"], [data-testid="message-selection-toolbar"]')
		);
		const surface = surfaces.find((candidate) => {
			const style = getComputedStyle(candidate);
			const rect = candidate.getBoundingClientRect();
			return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity || '1') > 0 && rect.width > 0 && rect.height > 0;
		});
		if (!surface) return ['selected-text action surface is missing'];
		const itemSelector = surface.dataset.testid === 'message-selection-toolbar' ? '.sel-btn' : '.menu-item';

		function parseRgb(value: string): [number, number, number] | null {
			const match = value.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
			return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : null;
		}

		function channel(value: number): number {
			const normalized = value / 255;
			return normalized <= 0.03928 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
		}

		function luminance(rgb: [number, number, number]): number {
			return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
		}

		function contrast(foreground: [number, number, number], background: [number, number, number]): number {
			const lighter = Math.max(luminance(foreground), luminance(background));
			const darker = Math.min(luminance(foreground), luminance(background));
			return (lighter + 0.05) / (darker + 0.05);
		}

		const background = parseRgb(getComputedStyle(surface).backgroundColor);
		if (!background) return ['selected-text action surface background color could not be parsed'];
		return Array.from(surface.querySelectorAll<HTMLElement>(itemSelector)).flatMap((item) => {
			const style = getComputedStyle(item);
			if (style.display === 'none' || style.visibility === 'hidden') return [];
			const label = (item.textContent || item.getAttribute('data-testid') || item.className).trim();
			const foreground = parseRgb(style.color);
			const itemIssues: string[] = [];
			if (!foreground || contrast(foreground, background) < minimumContrast) {
				itemIssues.push(`${label} text is unreadable against the menu background`);
			}
			const icon = item.querySelector<HTMLElement>('.clickable-icon');
			if (icon) {
				const iconStyle = getComputedStyle(icon);
				const maskImage = iconStyle.maskImage || (iconStyle as any).webkitMaskImage || '';
				if (!maskImage || maskImage === 'none') itemIssues.push(`${label} icon renders without a mask and would appear as a square`);
			}
			return itemIssues;
		});
	}, MIN_CONTEXT_MENU_TEXT_CONTRAST);
	expect(issues).toEqual([]);
}

async function expectChatHeaderIconNotClipped(page: any): Promise<void> {
	const issues = await page.evaluate((minimumTopGap: number) => {
		const banner = document.querySelector<HTMLElement>('[data-testid="chat-header-banner"]');
		const icon = banner?.querySelector<HTMLElement>('[data-testid="chat-header-icon"]');
		if (!banner || !icon) return ['chat header icon is missing'];
		const bannerRect = banner.getBoundingClientRect();
		const iconRect = icon.getBoundingClientRect();
		if (iconRect.width <= 0 || iconRect.height <= 0) return ['chat header icon has no visible box'];
		const visibleBannerTop = Math.max(0, bannerRect.top);
		const topGap = iconRect.top - visibleBannerTop;
		return topGap < minimumTopGap ? [`chat header icon is clipped against the visible banner top edge (${Math.round(topGap)}px gap)`] : [];
	}, MIN_CHAT_HEADER_ICON_TOP_GAP);
	expect(issues).toEqual([]);
}

async function restoreProofHeaderViewport(page: any): Promise<void> {
	await page.evaluate(() => {
		const scroller = document.querySelector<HTMLElement>('[data-testid="chat-history-container"]');
		scroller?.scrollTo({ top: 0, behavior: 'instant' });
	});
	await expect(page.getByTestId('chat-header-banner')).toBeVisible({ timeout: 5000 });
	await expectChatHeaderIconNotClipped(page);
}

async function waitForCompletedAssistantResponse(page: any, log: (message: string, metadata?: Record<string, unknown>) => void): Promise<void> {
	await waitForAssistantMessage(page, { timeout: 120_000, logCheckpoint: log });
	await expect
		.poll(async () => {
			const typingCount = await page.locator('[data-testid="typing-indicator"]').count();
			const processingCount = await page.getByText(/Processing|is thinking/i).count();
			return typingCount + processingCount;
		}, { timeout: 120_000 })
		.toBe(0);
	log('Assistant response completed; no visible processing or thinking indicator remains.');
}

async function dismissSecurityReminder(page: any): Promise<void> {
	const reminder = page
		.locator(SELECTORS.notification)
		.filter({ hasText: /Security Reminder|secure your account|2FA|passkey/i })
		.first();
	if (!(await reminder.isVisible({ timeout: 3000 }).catch(() => false))) return;
	await reminder.getByTestId('notification-dismiss').click();
	await expect(reminder).toBeHidden({ timeout: 5000 });
}

async function triggerExplainInNewChat(page: any): Promise<void> {
	const explainActionSelector = `${SELECTORS.contextMenuExplain}, ${SELECTORS.selectionToolbarExplain}`;
	await expect(page.locator(explainActionSelector).first()).toBeVisible({ timeout: 5000 });
	await page.evaluate((selector: string) => {
		const button = document.querySelector(selector);
		if (!button) throw new Error('Explain in new chat action closed before mousedown');
		button.dispatchEvent(new MouseEvent('mousedown', { button: 0, bubbles: true, cancelable: true }));
	}, explainActionSelector);
}

async function holdProofState(page: any): Promise<void> {
	if (IS_PROOF_CAPTURE) await page.waitForTimeout(PROOF_VISIBLE_STATE_MS);
}

function createProofRuntime(page: any, testInfo: any) {
	if (!IS_PROOF_CAPTURE) return null;
	return createVideoProofRuntime(EXPLAIN_IN_NEW_CHAT_PROOF_CONTRACT, {
		device: PROOF_DEVICE,
		attach: testInfo.attach.bind(testInfo),
		captureFrame: () => page.screenshot({ type: 'png' })
	});
}

// contract-test: supporting surface=gui.web assertions=message-input.send.ownership,chat-navigation.open.local-first-coherent,notifications.web.stacked-deck
test('explains selected assistant text in a background new chat', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.skip(IS_PROOF_CAPTURE && PROOF_DEVICE === 'web-phone', 'Laptop proof is captured separately.');
	test.setTimeout(300_000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const proof = PROOF_DEVICE === 'web-laptop' ? createProofRuntime(page, testInfo) : null;

	const log = createSignupLogger('EXPLAIN_NEW_CHAT');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'explain-new-chat' });
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	await dismissSecurityReminder(page);
	await startNewChat(page, log);

	const seedPrompt = 'Reply in one short sentence that includes the exact phrase: vector database.';
	await sendMessage(page, seedPrompt, log, screenshot, 'seed', {
		testMockMarker: withMockMarker(seedPrompt, 'explain_in_new_chat_seed')
	});
	await waitForAssistantMessage(page, {
		which: 'last',
		contains: 'vector database',
		timeout: 90_000,
		logCheckpoint: log
	});
	// The mock answer text arrives before backend post-processing publishes title,
	// quick-tip, and follow-up updates. Let those UI updates settle before opening
	// the transient selection context menu, otherwise the menu can close on scroll
	// between the visibility assertion and the click.
	await page.waitForTimeout(3000);
	await restoreProofHeaderViewport(page);

	const sourceUrl = page.url();
	const sourceChatTextBefore = await page.locator(SELECTORS.chatMessage).allTextContents();
	expect(sourceChatTextBefore.join('\n')).toContain('vector database');

	log('Verifying user-message selections do not expose Explain in new chat.');
	const userSelection = await selectInsideMessage(page, SELECTORS.userMessageContent, 'vector database');
	expect(userSelection.selected).toBe(true);
	expect(userSelection.rect).not.toBeNull();
	await openMessageContextMenu(page, SELECTORS.userMessageContent, userSelection.rect!);
	await expect(page.locator(`${SELECTORS.contextMenuExplain}, ${SELECTORS.selectionToolbarExplain}`)).toHaveCount(0);
	if (proof) {
		await proof.checkpoint('user-selection-no-explain');
		await holdProofState(page);
	}
	await page.mouse.click(10, 10);
	await restoreProofHeaderViewport(page);

	log('Selecting assistant phrase and clicking Explain in new chat from the highlight menu.');
	const assistantSelection = await selectInsideMessage(page, SELECTORS.mateMessageContent, 'vector database');
	expect(assistantSelection.selected).toBe(true);
	expect(assistantSelection.rect).not.toBeNull();
	await openMessageContextMenu(page, SELECTORS.mateMessageContent, assistantSelection.rect!, {
		requireExplainAction: true,
		selectedText: 'vector database'
	});
	if (proof) {
		await proof.assert('assistant-selection-action', async () => {
			await expect(page.locator(`${SELECTORS.contextMenuExplain}, ${SELECTORS.selectionToolbarExplain}`).first()).toBeVisible({ timeout: 5000 });
			await expectContextMenuVisualIntegrity(page);
			await expectChatHeaderIconNotClipped(page);
		});
		await proof.checkpoint('assistant-selection-action');
		await holdProofState(page);
	}
	// The product handles this action on mousedown to preserve the selected text
	// before focus/click can collapse it. Dispatch that leading edge immediately;
	// the explain action is transient and can close between a diagnostic screenshot
	// and a later locator action.
	await triggerExplainInNewChat(page);

	await expect(page).toHaveURL(sourceUrl, { timeout: 5000 });
	const explanationNotification = page.locator(SELECTORS.notification).filter({ hasText: /background/i });
	await expect(explanationNotification).toBeVisible({ timeout: 20_000 });
	const sourceChatTextAfter = await page.locator(SELECTORS.chatMessage).allTextContents();
	expect(sourceChatTextAfter.join('\n')).not.toContain('Tell me more about: vector database');
	if (proof) {
		await proof.assert('source-chat-unchanged', async () => {
			await expect(page).toHaveURL(sourceUrl);
			expect(sourceChatTextAfter.join('\n')).not.toContain('Tell me more about: vector database');
		});
		await proof.checkpoint('source-chat-unchanged');
		await holdProofState(page);
	}

	log('Opening background explanation chat from notification action.');
	const openAction = explanationNotification.locator(SELECTORS.notificationAction).filter({ hasText: /open/i }).first();
	await expect(openAction).toBeVisible({ timeout: 10_000 });
	if (proof) {
		await proof.assert('background-open-action', async () => {
			await expect(openAction).toBeVisible();
		});
		await proof.checkpoint('background-open-action');
		await holdProofState(page);
	}
	if (proof) {
		await proof.action('open-background-explanation-chat', async () => {
			await openAction.click();
		});
	} else {
		await openAction.click();
	}
	await expect(page).not.toHaveURL(sourceUrl, { timeout: 15_000 });
	await expect(explanationNotification).toHaveCount(0, { timeout: 5000 });

	const promptText = 'Tell me more about: vector database';
	await expect(page.getByTestId('message-user').filter({ hasText: promptText })).toBeVisible({ timeout: 30_000 });
	const explanationChatTextBeforeResponse = (await page.locator(SELECTORS.chatMessage).allTextContents()).join('\n');
	expect(explanationChatTextBeforeResponse).toContain(promptText);
	expect(explanationChatTextBeforeResponse).not.toContain('Reply in one short sentence');
	expect(explanationChatTextBeforeResponse).not.toContain(
		'A vector database stores and searches embeddings so similar items can be found quickly.'
	);
	await waitForCompletedAssistantResponse(page, log);
	await screenshot(page, 'background-explanation-chat-opened');
	if (proof) {
		await proof.assert('explanation-chat-content', async () => {
			const explanationChatTextAfterResponse = (await page.locator(SELECTORS.chatMessage).allTextContents()).join('\n');
			expect(explanationChatTextAfterResponse).toContain(promptText);
			expect(explanationChatTextAfterResponse).not.toContain('Reply in one short sentence');
			expect(explanationChatTextAfterResponse).not.toContain(
				'A vector database stores and searches embeddings so similar items can be found quickly.'
			);
			await expect(page.locator('[data-testid="typing-indicator"]')).toHaveCount(0);
			await expect(page.getByText(/Processing|is thinking/i)).toHaveCount(0);
		});
		await proof.checkpoint('explanation-chat-content');
		await holdProofState(page);
		await proof.attach();
		return;
	}

	await deleteActiveChat(page, log, screenshot, 'cleanup-explanation-chat');
	await page.goto(sourceUrl);
	await page.waitForTimeout(1500);
	await deleteActiveChat(page, log, screenshot, 'cleanup-source-chat');
});

// contract-test: supporting surface=gui.web assertions=message-input.actions.visibility
test('selection toolbar wraps within a mobile viewport', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.skip(IS_PROOF_CAPTURE && PROOF_DEVICE === 'web-laptop', 'Phone proof is captured separately.');
	test.setTimeout(300_000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const proof = PROOF_DEVICE === 'web-phone' ? createProofRuntime(page, testInfo) : null;

	const log = createSignupLogger('EXPLAIN_NEW_CHAT_MOBILE_TOOLBAR');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'explain-new-chat-mobile-toolbar' });
	await archiveExistingScreenshots(log);
	await page.setViewportSize({ width: 390, height: 844 });

	await loginToTestAccount(page, log, screenshot);
	await dismissSecurityReminder(page);
	await startNewChat(page, log);
	if (proof) {
		await proof.checkpoint('mobile-signed-in');
		await holdProofState(page);
	}

	const mobileSeedPrompt = 'Reply in one short sentence that includes the exact phrase: vector database.';
	await sendMessage(page, mobileSeedPrompt, log, screenshot, 'mobile-seed', {
		testMockMarker: withMockMarker(mobileSeedPrompt, 'explain_in_new_chat_seed')
	});
	await waitForAssistantMessage(page, {
		which: 'last',
		contains: 'vector database',
		timeout: 90_000,
		logCheckpoint: log
	});
	await page.waitForTimeout(3000);
	if (proof) {
		await proof.checkpoint('mobile-selection-ready');
		await holdProofState(page);
	}

	const assistantSelection = await selectInsideMessage(page, SELECTORS.mateMessageContent, 'vector database');
	expect(assistantSelection.selected).toBe(true);
	await expect(page.locator(SELECTORS.selectionToolbar)).toBeVisible({ timeout: 5000 });
	await expect(page.locator(SELECTORS.selectionToolbarExplain)).toBeVisible({ timeout: 5000 });

	const toolbarBox = await page.locator(SELECTORS.selectionToolbar).boundingBox();
	expect(toolbarBox).not.toBeNull();
	expect(toolbarBox!.x).toBeGreaterThanOrEqual(0);
	expect(toolbarBox!.x + toolbarBox!.width).toBeLessThanOrEqual(390);
	await screenshot(page, 'mobile-toolbar-wrapped');
	if (proof) {
		await proof.assert('mobile-toolbar-fits', async () => {
			await expect(page.locator(SELECTORS.selectionToolbar)).toBeVisible();
			await expect(page.locator(SELECTORS.selectionToolbarExplain)).toBeVisible();
			expect(toolbarBox!.x).toBeGreaterThanOrEqual(0);
			expect(toolbarBox!.x + toolbarBox!.width).toBeLessThanOrEqual(390);
		});
		await proof.checkpoint('mobile-toolbar-fits');
		await holdProofState(page);
		await proof.attach();
		return;
	}

	await deleteActiveChat(page, log, screenshot, 'cleanup-mobile-toolbar-chat');
});
