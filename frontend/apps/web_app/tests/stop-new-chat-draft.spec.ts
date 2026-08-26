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

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

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
test('late draft persistence cannot override a newer explicit chat selection', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(150000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const logCheckpoint = createSignupLogger('DRAFT_SELECTION_AUTHORITY');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'draft-selection-authority'
	});
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	let draftChatId: string | null = null;
	try {
		const visibleDraft = 'Keep this draft while I open a different saved chat.';
		const messageEditor = page.getByTestId('message-editor');
		await insertComposerText(page, messageEditor, visibleDraft, visibleDraft);
		await expect(page.getByTestId('draft-chat-badge')).toBeVisible({ timeout: 15000 });
		draftChatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? null;
		expect(draftChatId).toBeTruthy();
		await startNewChat(page, logCheckpoint);

		const sidebar = page.getByTestId('activity-history-wrapper');
		if (!(await sidebar.isVisible().catch(() => false))) {
			await page.getByTestId('sidebar-toggle').click();
			await expect(sidebar).toBeVisible({ timeout: 10000 });
		}
		const targetChatId = await page.getByTestId('chat-item-wrapper').evaluateAll((rows, excludedChatId) =>
			rows
				.map((row) => row.getAttribute('data-chat-id') || '')
				.find((chatId) => chatId && chatId !== excludedChatId && !chatId.startsWith('demo-') && !chatId.startsWith('legal-') && !chatId.startsWith('example-')) ?? null,
			draftChatId
		);
		expect(targetChatId, 'The test account needs another mounted saved chat').toBeTruthy();
		const targetChatRow = page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${targetChatId}"]`);
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
			}).__openmatesE2EDraftSelectionTrace ?? []
		), { message: 'Both draft activation consumers should reach their asynchronous commit point' })
			.toEqual(expect.arrayContaining([
				expect.objectContaining({ consumer: 'active_chat', result: 'paused' }),
				expect.objectContaining({ consumer: 'chat_list', result: 'paused' })
			]));

		await targetChatRow.click();
		await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', targetChatId);
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
		), { message: 'Both draft activation consumers should reject the stale commit' }).toHaveLength(2);
		const finalDecisions = await page.evaluate(() =>
			(window as typeof window & {
				__openmatesE2EDraftSelectionTrace?: Array<{ chatId: string; consumer: string; result: string }>;
			}).__openmatesE2EDraftSelectionTrace ?? []
		);
		expect(finalDecisions.some((decision) => decision.result === 'applied')).toBe(false);
		expect(finalDecisions.some((decision) => decision.result === 'skipped')).toBe(true);
		await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', targetChatId);
		await expect.poll(() => new URL(page.url()).hash).toContain(`chat-id=${encodeURIComponent(targetChatId!)}`);
	} finally {
		await page.evaluate(() => {
			(window as typeof window & {
				__openmatesE2EReleaseDraftSelection?: () => void;
			}).__openmatesE2EReleaseDraftSelection?.();
			delete (window as typeof window & {
				__openmatesE2EDraftSelectionTrace?: unknown;
			}).__openmatesE2EDraftSelectionTrace;
		}).catch(() => undefined);
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
