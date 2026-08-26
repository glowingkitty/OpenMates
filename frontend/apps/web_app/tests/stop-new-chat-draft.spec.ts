/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Stop-new-chat draft restoration regression.
 *
 * Verifies that pressing Stop while the first message is still creating a new
 * chat reverses the optimistic chat creation UI and puts the message back into
 * the composer as a draft.
 */

const { test, expect } = require('./helpers/cookie-audit');
const {
	archiveExistingScreenshots,
	createSignupLogger,
	createStepScreenshotter,
	getTestAccount,
	withMockMarker
} = require('./signup-flow-helpers');
const { deleteActiveChat, loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const IS_PROOF_CAPTURE = Boolean(process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT);
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';
const DRAFT_SELECTION_PROOF = defineVideoProof({
	id: 'late-draft-activation-navigation-authority',
	title: 'Late draft activation preserves newer chat navigation',
	surface: 'web',
	devices: ['web-phone', 'web-laptop'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'draft-saved',
			text: 'A new chat draft is saved while another chat is ready to open.',
			checkpoint: 'draft-saved',
			devices: ['web-phone', 'web-laptop']
		},
		{
			id: 'target-selected',
			text: 'The saved chat is selected before the delayed draft activation completes.',
			checkpoint: 'target-selected',
			devices: ['web-phone', 'web-laptop']
		},
		{
			id: 'target-preserved',
			text: 'The newer selection remains active when draft persistence finishes.',
			checkpoint: 'target-preserved',
			devices: ['web-phone', 'web-laptop']
		},
		{
			id: 'draft-reopened',
			text: 'The draft remains saved and can still be reopened later.',
			checkpoint: 'draft-reopened',
			devices: ['web-phone', 'web-laptop']
		}
	],
	assertions: [
		{
			id: 'target-remains-rendered',
			checkpoint: 'target-preserved',
			visual: 'The selected target chat remains rendered after delayed draft activation is released.',
			devices: ['web-phone', 'web-laptop']
		},
		{
			id: 'target-route-remains-active',
			checkpoint: 'target-preserved',
			visual: 'The URL continues to identify the selected target chat.',
			devices: ['web-phone', 'web-laptop']
		},
		{
			id: 'draft-does-not-reopen',
			checkpoint: 'target-preserved',
			visual: 'No delayed activation reopens the draft.',
			devices: ['web-phone', 'web-laptop']
		},
		{
			id: 'draft-remains-navigable',
			checkpoint: 'draft-reopened',
			visual: 'The persisted draft remains navigable for cleanup.',
			devices: ['web-phone', 'web-laptop']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});
test.describe.configure({ mode: 'serial' });

async function insertComposerText(page: any, messageEditor: any, text: string, visibleText: string): Promise<void> {
	await messageEditor.click({ position: { x: 12, y: 12 }, force: true });
	await expect
		.poll(
			async () => messageEditor.evaluate((element: HTMLElement) => {
				const activeElement = document.activeElement;
				return Boolean(
					activeElement instanceof HTMLElement &&
					element.contains(activeElement) &&
					activeElement.isContentEditable
				);
			}),
			{ timeout: 5000 }
		)
		.toBeTruthy();

	await page.keyboard.insertText(text);
	const keyboardInserted = await expect
		.poll(
			async () => (await messageEditor.textContent().catch(() => '')) ?? '',
			{ timeout: 2000 }
		)
		.toContain(visibleText)
		.then(() => true)
		.catch(() => false);

	if (!keyboardInserted) {
		await messageEditor.evaluate((element: HTMLElement, insertedText: string) => {
			const editableElement = element.isContentEditable
				? element
				: element.querySelector<HTMLElement>('[contenteditable="true"]');
			if (!editableElement) {
				throw new Error('Message editor contenteditable target was not found.');
			}
			editableElement.focus();
			const range = document.createRange();
			range.selectNodeContents(editableElement);
			range.collapse(false);
			const selection = window.getSelection();
			selection?.removeAllRanges();
			selection?.addRange(range);

			const inserted = document.execCommand('insertText', false, insertedText);
			if (!inserted || !editableElement.textContent?.includes(insertedText)) {
				editableElement.textContent = insertedText;
				editableElement.dispatchEvent(new InputEvent('input', {
					bubbles: true,
					cancelable: true,
					data: insertedText,
					inputType: 'insertText'
				}));
			}
		}, text);
	}

	await expect
		.poll(
			async () => (await messageEditor.textContent().catch(() => '')) ?? '',
			{ timeout: 10000 }
		)
		.toContain(visibleText);
}

// contract-test: direct surface=gui.web assertions=drafts.draft-only.lifecycle,drafts.persistence.local-first-encrypted
test('stop during new chat creation restores the sent message as a draft', async ({ page }: { page: any }) => {
	test.skip(IS_PROOF_CAPTURE, 'Proof profiles record only the late draft activation navigation contract.');
	test.slow();
	test.setTimeout(150000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const logCheckpoint = createSignupLogger('STOP_NEW_CHAT_DRAFT');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'stop-new-chat-draft'
	});
	await archiveExistingScreenshots(logCheckpoint);

	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	let shouldTryCleanup = false;
	try {
		const visibleDraft = 'Please keep this exact draft text when I stop creating the new chat.';
		const messageEditor = page.getByTestId('message-editor');
		await expect(messageEditor).toBeVisible({ timeout: 15000 });
		await insertComposerText(page, messageEditor, withMockMarker(visibleDraft, 'chat_flow_capital', 'slow'), visibleDraft);
		const draftHeader = page.getByTestId('chat-header-banner');
		await expect(draftHeader).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('draft-chat-badge')).toHaveText(/Draft/i);
		await expect(page.getByTestId('chat-header-title')).toContainText(visibleDraft.slice(0, 30));
		await expect(page.getByTestId('draft-chat-last-saved')).toContainText(/Last saved:/i);
		await expect(page.getByTestId('new-chat-button')).toBeVisible();
		const draftChatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? null;
		expect(draftChatId).toBeTruthy();
		await takeStepScreenshot(page, 'draft-typed');
		await page.route(/\/v1\/user-(tasks|plans)(\?|$)/, async (route: any) => {
			await page.waitForTimeout(1500);
			await route.continue();
		});

		const sendButton = page.locator('[data-action="send-message"]');
		await expect(sendButton).toBeVisible({ timeout: 15000 });
		await expect(sendButton).toBeEnabled({ timeout: 5000 });
		await sendButton.click();
		const stopButton = page.getByTestId('stop-processing-button');
		await expect(stopButton).toBeVisible({ timeout: 10000 });
		await stopButton.click();
		logCheckpoint('Clicked Stop while the new chat was still being created.');
		await takeStepScreenshot(page, 'creating-chat-stop-clicked');
		const taskLoadingAppeared = page
			.getByTestId('active-chat-task-preview-loading')
			.waitFor({ state: 'visible', timeout: 2500 })
			.then(() => true)
			.catch(() => false);
		shouldTryCleanup = true;
		logCheckpoint('Sent fresh-chat message and stopped the creating-chat state.');

		expect(await taskLoadingAppeared).toBe(false);
		await expect(stopButton).not.toBeVisible({ timeout: 10000 });
		await expect(messageEditor).toContainText(visibleDraft, { timeout: 15000 });
		await expect(page.getByText(/Creating new chat/i)).toHaveCount(0, { timeout: 15000 });
		await expect(page.getByTestId('message-user')).toHaveCount(0, { timeout: 10000 });
		await expect(page.getByTestId('draft-chat-badge')).toBeVisible({ timeout: 15000 });
		expect(page.url()).toContain(`chat-id=${draftChatId}`);
		await takeStepScreenshot(page, 'draft-restored-after-stop');

		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(messageEditor).toBeVisible({ timeout: 15000 });
		await expect(messageEditor).toContainText(visibleDraft, { timeout: 15000 });
		await expect(page.getByTestId('message-user')).toHaveCount(0, { timeout: 10000 });
		await expect(page.getByTestId('draft-chat-badge')).toBeVisible({ timeout: 15000 });
		expect(page.url()).toContain(`chat-id=${draftChatId}`);
		await takeStepScreenshot(page, 'draft-restored-after-reload');
	} finally {
		if (shouldTryCleanup) {
			await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'cleanup');
		}
	}
});

// contract-test: direct surface=gui.web assertions=drafts.draft-only.lifecycle,chat-navigation.open.local-first-coherent
test('late draft persistence cannot override a newer explicit chat selection', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(150000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const logCheckpoint = createSignupLogger('DRAFT_SELECTION_AUTHORITY');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'draft-selection-authority'
	});
	const proof = IS_PROOF_CAPTURE
		? createVideoProofRuntime(DRAFT_SELECTION_PROOF, {
			device: PROOF_DEVICE,
			attach: (name: string, options: { body: Buffer; contentType: string }) => testInfo.attach(name, options),
			captureFrame: () => page.screenshot({ animations: 'disabled' })
		})
		: null;
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	let draftChatId: string | null = null;
	const targetChatId = `e2e-draft-selection-target-${Date.now()}`;
	try {
		const visibleDraft = 'Keep this draft while I open a different saved chat.';
		const messageEditor = page.getByTestId('message-editor');
		await insertComposerText(page, messageEditor, visibleDraft, visibleDraft);
		await expect(page.getByTestId('draft-chat-badge')).toBeVisible({ timeout: 15000 });
		if (IS_PROOF_CAPTURE && PROOF_DEVICE === 'web-phone') {
			const composerGeometry = await page.evaluate(() => {
				const messageField = document.querySelector<HTMLElement>('[data-testid="message-field"]');
				const messageEditor = document.querySelector<HTMLElement>('[data-testid="message-editor"]');
				const contentEditable = messageEditor?.querySelector<HTMLElement>('[contenteditable="true"]');
				if (!messageField || !messageEditor || !contentEditable) throw new Error('Composer geometry targets are unavailable');
				const fieldRect = messageField.getBoundingClientRect();
				const editorRect = messageEditor.getBoundingClientRect();
				return {
					documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
					fieldContentOverflow: messageField.scrollWidth - messageField.clientWidth,
					editorContentOverflow: contentEditable.scrollWidth - contentEditable.clientWidth,
					fieldRight: fieldRect.right,
					editorRight: editorRect.right,
					viewportWidth: window.innerWidth
				};
			});
			expect(composerGeometry.documentOverflow, 'Phone composer must not create horizontal page overflow').toBeLessThanOrEqual(1);
			expect(composerGeometry.fieldContentOverflow, 'Phone message field content must remain clipped to the field').toBeLessThanOrEqual(1);
			expect(composerGeometry.editorContentOverflow, 'Phone message editor content must fit its editor').toBeLessThanOrEqual(1);
			expect(composerGeometry.fieldRight, 'Phone message field must remain inside the viewport').toBeLessThanOrEqual(composerGeometry.viewportWidth);
			expect(composerGeometry.editorRight, 'Phone message editor must remain inside the viewport').toBeLessThanOrEqual(composerGeometry.viewportWidth);
		}
		draftChatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? null;
		expect(draftChatId).toBeTruthy();
		await proof?.checkpoint('draft-saved');
		await startNewChat(page, logCheckpoint);
		await page.evaluate(async (chatId: string) => {
			const seedChat = (window as typeof window & {
				__openmatesE2ESeedChat?: (input: {
					chat: Record<string, unknown>;
					messages: Record<string, unknown>[];
				}) => Promise<unknown>;
			}).__openmatesE2ESeedChat;
			if (!seedChat) throw new Error('E2E chat seed helper is unavailable');
			const now = Math.floor(Date.now() / 1000);
			await seedChat({
				chat: {
					chat_id: chatId,
					title: 'Draft selection target',
					messages_v: 1,
					title_v: 1,
					created_at: now,
					updated_at: now,
					last_edited_overall_timestamp: now
				},
				messages: [{
					message_id: `${chatId}-message`,
					chat_id: chatId,
					role: 'user',
					created_at: now,
					status: 'synced',
					content: 'Keep this saved chat selected.'
				}]
			});
		}, targetChatId);

		await page.evaluate((chatId: string) => {
			const replay = (window as typeof window & {
				__openmatesE2EReplayDraftSelection?: (draftChatId: string, pauseBeforeCommit?: boolean) => void;
			}).__openmatesE2EReplayDraftSelection;
			if (!replay) throw new Error('Draft selection E2E hook is unavailable');
			replay(chatId, true);
		}, draftChatId);

		await expect.poll(() => page.evaluate(() =>
			(window as typeof window & {
				__openmatesE2EDraftSelectionTrace?: Array<{ chatId: string; consumer: string; result: string }>;
			}).__openmatesE2EDraftSelectionTrace?.filter((decision) => decision.result === 'paused') ?? []
		), { message: 'A mounted draft activation consumer should reach its asynchronous commit point' })
			.not.toHaveLength(0);
		const pausedConsumerCount = await page.evaluate(() =>
			(window as typeof window & {
				__openmatesE2EDraftSelectionTrace?: Array<{ chatId: string; consumer: string; result: string }>;
			}).__openmatesE2EDraftSelectionTrace?.filter((decision) => decision.result === 'paused').length ?? 0
		);

		await page.evaluate((chatId: string) => {
			window.location.hash = `chat-id=${encodeURIComponent(chatId)}`;
		}, targetChatId);
		await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', targetChatId);
		await proof?.checkpoint('target-selected');
		await page.evaluate(() => {
			const release = (window as typeof window & {
				__openmatesE2EReleaseDraftSelection?: () => void;
			}).__openmatesE2EReleaseDraftSelection;
			if (!release) throw new Error('Draft selection E2E release hook is unavailable');
			release();
		});

		await expect.poll(() => page.evaluate(() =>
			(window as typeof window & {
				__openmatesE2EDraftSelectionTrace?: Array<{ chatId: string; consumer: string; result: string }>;
			}).__openmatesE2EDraftSelectionTrace?.filter((decision) => decision.result === 'skipped') ?? []
		), { message: 'Every mounted draft activation consumer should reject the stale commit' })
			.toHaveLength(pausedConsumerCount);
		const finalDecisions = await page.evaluate(() =>
			(window as typeof window & {
				__openmatesE2EDraftSelectionTrace?: Array<{ chatId: string; consumer: string; result: string }>;
			}).__openmatesE2EDraftSelectionTrace ?? []
		);
		expect(finalDecisions.some((decision) => decision.result === 'applied')).toBe(false);
		expect(finalDecisions.some((decision) => decision.result === 'skipped')).toBe(true);
		await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', targetChatId);
		await expect.poll(() => new URL(page.url()).hash).toContain(`chat-id=${encodeURIComponent(targetChatId!)}`);
		if (proof && draftChatId) {
			await proof.assert('target-remains-rendered', async () => {
				await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', targetChatId);
			});
			await proof.assert('target-route-remains-active', async () => {
				await expect.poll(() => new URL(page.url()).hash).toContain(`chat-id=${encodeURIComponent(targetChatId)}`);
			});
			await proof.assert('draft-does-not-reopen', async () => {
				expect(finalDecisions.some((decision) => decision.result === 'applied')).toBe(false);
			});
			await proof.checkpoint('target-preserved');
			await page.evaluate((chatId: string) => {
				window.location.hash = `chat-id=${encodeURIComponent(chatId)}`;
			}, draftChatId);
			await proof.assert('draft-remains-navigable', async () => {
				await expect(page.getByTestId('active-chat-container'))
					.toHaveAttribute('data-current-chat-id', draftChatId, { timeout: 10000 });
			});
			await proof.checkpoint('draft-reopened');
			await proof.attach();
		}
	} finally {
		await page.evaluate(() => {
			(window as typeof window & {
				__openmatesE2EReleaseDraftSelection?: () => void;
			}).__openmatesE2EReleaseDraftSelection?.();
			delete (window as typeof window & {
				__openmatesE2EDraftSelectionTrace?: unknown;
			}).__openmatesE2EDraftSelectionTrace;
		}).catch(() => undefined);
		await page.evaluate((chatId: string) => {
			window.location.hash = `chat-id=${encodeURIComponent(chatId)}`;
		}, targetChatId).catch(() => undefined);
		await expect(page.getByTestId('active-chat-container'))
			.toHaveAttribute('data-current-chat-id', targetChatId, { timeout: 10000 })
			.catch(() => undefined);
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'cleanup-selection-target').catch(() => undefined);
		if (draftChatId) {
			await page.evaluate((chatId: string) => {
				window.location.hash = `chat-id=${encodeURIComponent(chatId)}`;
			}, draftChatId).catch(() => undefined);
			await expect(page.getByTestId('active-chat-container'))
				.toHaveAttribute('data-current-chat-id', draftChatId, { timeout: 10000 })
				.catch(() => undefined);
			await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'cleanup-late-draft').catch(() => undefined);
		}
	}
});
