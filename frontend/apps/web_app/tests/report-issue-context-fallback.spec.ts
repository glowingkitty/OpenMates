/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Focused E2E regression for reporting a newly created chat when optional
 * context sharing cannot find the chat metadata yet.
 */
export {};

const {
	test,
	expect,
	attachConsoleListeners,
	attachNetworkListeners
} = require('./console-monitor');
const {
	createSignupLogger,
	getTestAccount,
	withMockMarker
} = require('./signup-flow-helpers');
const {
	loginToTestAccount,
	startNewChat,
	fillMessageEditor
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

async function navigateToReportIssue(
	page: any,
	logCheckpoint: (message: string) => void
): Promise<void> {
	const settingsToggle = page.locator('#settings-menu-toggle');
	await expect(settingsToggle).toBeVisible({ timeout: 10000 });
	await settingsToggle.click();

	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	const reportItem = settingsMenu
		.getByRole('menuitem', { name: /report.*issue|issue.*report|problem.*melden/i })
		.first();
	await expect(reportItem).toBeVisible({ timeout: 5000 });
	await reportItem.click();
	logCheckpoint('Navigated to Report Issue settings.');
	await expect(page.getByTestId('report-issue-form')).toBeVisible({ timeout: 10000 });
}

async function installAnonymousUsageStatusStub(page: any): Promise<void> {
	await page.route('**/v1/anonymous/free-usage/status**', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				active: false,
				can_send_text: false,
				reason: 'authenticated-report-test',
				reset_at: null,
				cta: null,
			}),
		});
	});
}

test.describe('Report Issue Context Fallback', () => {
	test.describe.configure({ timeout: 300000 });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	// contract-test: direct surface=gui.web assertions=issue-reporting.submission.confirmed-and-durable
	test('Report submission survives a 404 while sharing a new chat', async ({ page }) => {
		const logCheckpoint = createSignupLogger('REPORT_ISSUE_SHARE_404');
		await installAnonymousUsageStatusStub(page);
		attachConsoleListeners(page, logCheckpoint);
		attachNetworkListeners(page, logCheckpoint);

		const shareFailureWarnings: string[] = [];
		page.on('console', (message: any) => {
			if (message.type() === 'warning' && message.text().includes('Continuing without shared context')) {
				shareFailureWarnings.push(message.text());
			}
		});

		await loginToTestAccount(page, logCheckpoint);
		await startNewChat(page, logCheckpoint);
		const messageEditor = page.getByTestId('message-field').last().getByTestId('message-editor');
		const seedMessage = 'What is the capital of Germany?';
		await fillMessageEditor(page, messageEditor, seedMessage);
		await messageEditor.evaluate((editor: HTMLElement, testMockMarker: string) => {
			editor.dispatchEvent(new CustomEvent('custom-send-message', {
				bubbles: true,
				cancelable: true,
				detail: { testMockMarker },
			}));
		}, withMockMarker(seedMessage, 'chat_flow_capital'));

		// A failed first turn is exactly when this reporting fallback matters. Wait only
		// for the send pipeline to promote the temporary draft ID to the active chat;
		// the report must remain available without an accepted or answered message.
		await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
		const newChatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? '';
		expect(newChatId).toBeTruthy();
		await expect(page.getByTestId('active-chat-container'))
			.toHaveAttribute('data-current-chat-id', newChatId);
		await expect(page.locator('[data-action="message-input"]').last())
			.toHaveAttribute('data-current-chat-id', newChatId);

		const plaintextMarker = 'private rendered chat text must not be attached';
		let metadataPayload: Record<string, unknown> | null = null;
		await page.route('**/v1/share/chat/metadata', async (route: any) => {
			if (route.request().method() !== 'POST') {
				await route.continue();
				return;
			}
			metadataPayload = route.request().postDataJSON();
			// Record the privacy probe through the app's intercepted console immediately
			// before log collection. Earlier warnings can be displaced from the bounded
			// last-100 report window by verbose chat synchronization logs.
			await page.evaluate((marker: string) => {
				console.warn(
					'[ReportIssueShareFailureRedactionProbe]',
					marker,
					'https://app.example/share/chat/example#key=secret-report-share-key-material'
				);
			}, plaintextMarker);
			await route.fulfill({
				status: 404,
				contentType: 'application/json',
				body: JSON.stringify({ detail: 'Chat not found' }),
			});
		});

		let reportPayload: Record<string, any> | null = null;
		await page.route('**/v1/settings/issues', async (route: any) => {
			if (route.request().method() !== 'POST') {
				await route.continue();
				return;
			}
			reportPayload = route.request().postDataJSON();
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					success: true,
					issue_id: '00000000-0000-4000-8000-000000000404',
					short_issue_id: 'ABCD4',
					screenshot_uploaded: false,
				}),
			});
		});

		await navigateToReportIssue(page, logCheckpoint);
		await expect(page.locator('#share-chat-toggle')).toBeChecked();
		await page.getByTestId('report-issue-title').fill('New chat report with unavailable sharing');
		await page.getByTestId('report-issue-user-flow').fill('Started a new chat and opened the report form.');
		await page.evaluate((marker: string) => {
			const message = document.createElement('div');
			message.setAttribute('data-message-id', 'share-failure-privacy-probe');
			message.innerHTML = `<div class="chat-message-text"><div class="ProseMirror"></div></div>`;
			const body = message.querySelector('.ProseMirror');
			if (body) body.textContent = marker;
			document.body.append(message);
		}, plaintextMarker);

		await page.getByTestId('report-issue-submit').click();
		await expect(page.getByTestId('report-issue-confirmation')).toBeVisible({ timeout: 10000 });

		expect(metadataPayload).toEqual(expect.objectContaining({
			chat_id: newChatId,
			is_shared: true,
		}));
		expect(JSON.stringify(metadataPayload)).not.toContain('#key=');
		expect(reportPayload).not.toBeNull();
		expect(reportPayload?.chat_or_embed_url).toBeNull();
		expect(reportPayload?.last_messages_html).toBeNull();
		expect(reportPayload?.description).toContain('Started a new chat');
		expect(reportPayload?.runtime_debug_state).toEqual(expect.any(Object));
		expect(reportPayload?.device_info).toEqual(expect.any(Object));
		expect(reportPayload?.console_logs).toEqual(expect.any(String));
		expect(reportPayload?.console_logs).toContain('[CHAT-CONTENT-REDACTED]');
		expect(reportPayload?.console_logs).toContain('[SHARE-KEY-REDACTED]');
		expect(JSON.stringify(reportPayload)).not.toContain(plaintextMarker);
		expect(JSON.stringify(reportPayload)).not.toContain('secret-report-share-key-material');
		expect(JSON.stringify(reportPayload)).not.toContain('#key=');
		expect(shareFailureWarnings).toHaveLength(1);
		expect(shareFailureWarnings.join('\n')).not.toContain('#key=');
		logCheckpoint('Report submitted without optional chat data after share metadata returned 404.');
	});
});
