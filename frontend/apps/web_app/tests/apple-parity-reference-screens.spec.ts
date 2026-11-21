/**
 * Web reference screenshots at iPhone size (390x844) for Apple/web parity:
 * start screen, active chat top bar, composer with the @ mention dropdown and
 * the recording state (fake media stream), plus every workspace start screen
 * (Chats, Apps, Workflows, Projects, Tasks) signed out and signed in.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 */
import { test, expect } from './helpers/cookie-audit';
import { getTestAccount, withMockMarker } from './signup-flow-helpers';
import {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	waitForAssistantMessage
} from './helpers/chat-test-helpers';
import { skipWithoutCredentials } from './helpers/env-guard';

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.use({
	launchOptions: {
		args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream']
	},
	permissions: ['microphone'],
	viewport: { width: 390, height: 844 }
});

/** Closes visible toasts (e.g. "Sounds are on") so they never cover a reference shot. */
async function closeToasts(page: any) {
	const dismiss = page.getByTestId('notification-dismiss');
	for (let index = (await dismiss.count()) - 1; index >= 0; index -= 1) {
		const button = dismiss.nth(index);
		if (await button.isVisible()) await button.click();
	}
	await expect(page.getByTestId('notification-dismiss').filter({ visible: true })).toHaveCount(0, { timeout: 5000 });
}

async function shoot(page: any, testInfo: any, name: string) {
	await closeToasts(page);
	const path = testInfo.outputPath(`web-before-${name}.png`);
	await page.screenshot({ path });
	await testInfo.attach(`web-before-${name}`, { path, contentType: 'image/png' });
}

// contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
test('iPhone-size reference screens: start, mention, recording, chat top bar', async ({
	page
}: {
	page: any;
}, testInfo: any) => {
	test.slow();
	test.setTimeout(300000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await page.setViewportSize({ width: 390, height: 844 });
	await loginToTestAccount(page);
	await startNewChat(page);

	const editor = page.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 15000 });
	await shoot(page, testInfo, '01-start-screen');

	// Mention dropdown
	await editor.click();
	await page.keyboard.type('@');
	await expect(page.getByTestId('mention-dropdown-header')).toBeVisible({ timeout: 10000 });
	await shoot(page, testInfo, '03-composer-mention-dropdown');
	await page.keyboard.press('Backspace');

	// Active chat
	await sendMessage(page, withMockMarker('What is the boiling point of water at sea level?', 'chat_flow_capital', 'instant'));
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 30000 });
	await waitForAssistantMessage(page, { which: 'last', timeout: 60000 });
	await expect(page.getByTestId('report-issue-button').first()).toBeVisible({ timeout: 10000 });
	await shoot(page, testInfo, '02-active-chat-top-bar-composer');
	// Recording state (fake audio device), last: the overlay is left open.
	// The follow-up composer is collapsed until it is focused; the mic shows then.
	await closeToasts(page);
	await editor.click();
	const mic = page.locator('[data-testid="message-field"]').last().getByTestId('record-audio-button');
	await expect(mic).toBeVisible({ timeout: 10000 });
	await mic.click({ delay: 50 });
	const overlay = page.getByTestId('record-overlay');
	await expect(overlay).toBeVisible({ timeout: 5000 });
	await expect(overlay.getByTestId('record-finish-button')).toBeVisible();
	// Shot without closeToasts: any click could end the recording; the overlay must still be open after it.
	const path = testInfo.outputPath('web-before-04-composer-recording.png');
	await page.screenshot({ path });
	await testInfo.attach('web-before-04-composer-recording', { path, contentType: 'image/png' });
	await expect(overlay.getByTestId('record-finish-button')).toBeVisible();
});

/** The five workspace start screens: route and the heading that marks the screen as rendered. */
const WORKSPACES = [
	{ name: 'chats', path: '/', heading: 'chat-welcome-heading' },
	{ name: 'apps', path: '/#apps', heading: 'apps-home-heading' },
	{ name: 'workflows', path: '/workflows', heading: 'workflows-home-heading' },
	{ name: 'projects', path: '/projects', heading: 'projects-home-heading' },
	{ name: 'tasks', path: '/tasks', heading: 'tasks-home-heading' }
];

/** Opens every workspace start screen and attaches an iPhone-size shot named `web-<state>-<workspace>`. */
async function shootWorkspaces(page: any, testInfo: any, state: 'signed-out' | 'signed-in') {
	for (const workspace of WORKSPACES) {
		await page.goto(workspace.path, { waitUntil: 'domcontentloaded' });
		const heading = page.getByTestId(workspace.heading);
		// Signed out, Projects and Tasks may show their sign-in screen instead; shoot what a guest sees.
		// isVisible() never waits; waitFor does.
		const rendered = await heading.waitFor({ state: 'visible', timeout: 30000 }).then(
			() => true,
			() => false
		);
		if (state === 'signed-in') {
			expect(rendered, `${workspace.name} start screen heading`).toBe(true);
			await expect(heading).not.toContainText(/Hey there/, { timeout: 30000 });
		}
		await expect(page.getByTestId('daily-inspiration-banner')).toHaveCount(0);
		await closeToasts(page);
		const path = testInfo.outputPath(`web-${state}-${workspace.name}.png`);
		await page.screenshot({ path });
		await testInfo.attach(`web-${state}-${workspace.name}`, { path, contentType: 'image/png' });
	}
}

// contract-test: supporting surface=gui.web assertions=daily-inspiration.start-row-rhythm
test('iPhone-size reference screens: every workspace start screen, signed out and signed in', async ({
	page
}: {
	page: any;
}, testInfo: any) => {
	test.slow();
	test.setTimeout(300000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await page.setViewportSize({ width: 390, height: 844 });
	await shootWorkspaces(page, testInfo, 'signed-out');
	await loginToTestAccount(page);
	await shootWorkspaces(page, testInfo, 'signed-in');
});
