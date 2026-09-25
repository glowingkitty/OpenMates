/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Cross-client chat producer and consumer scaffold.
 * Uses only opaque run IDs and chat IDs in artifacts. Synthetic prompt text is
 * reconstructed in each client and never persisted in control-plane files.
 * A control-plane runner supplies one shared artifact directory to Web, CLI,
 * and Apple test jobs; credentials remain in each client's normal test setup.
 * This test intentionally uses deployed Playwright execution only.
 */
// @privacy-promise: client-side-chat-encryption
export {};

const { test, expect } = require('./helpers/cookie-audit');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, waitForAssistantMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const {
	waitForEmbedFinished,
	openFullscreen,
	verifySearchGrid,
	closeFullscreen
} = require('./helpers/embed-test-helpers');

// The bounded Apple-to-web proof receives the same unnumbered personal dev
// account environment as CrossClientChatSyncUITests.fromEnvironment().
const fallbackAccount = getTestAccount();
const TEST_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL || fallbackAccount.email;
const TEST_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD || fallbackAccount.password;
const TEST_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY || fallbackAccount.otpKey;
const RUN_ID = process.env.APPLE_CROSS_CLIENT_RUN_ID || '';
const ARTIFACT_DIR = process.env.APPLE_CROSS_CLIENT_ARTIFACT_DIR || '';

function requireControlPlane(): { runId: string; artifactDir: string } {
	if (!RUN_ID || !ARTIFACT_DIR) throw new Error('APPLE_CROSS_CLIENT_RUN_ID and APPLE_CROSS_CLIENT_ARTIFACT_DIR are required');
	return { runId: RUN_ID, artifactDir: path.resolve(ARTIFACT_DIR) };
}

function marker(client: string): string {
	return `Apple parity ${client} marker ${RUN_ID}`;
}

function manifestPath(artifactDir: string, name: string): string {
	return path.join(artifactDir, `apple-cross-client-${RUN_ID}-${name}.json`);
}

function writeManifest(artifactDir: string, name: string, value: Record<string, unknown>): void {
	fs.mkdirSync(artifactDir, { recursive: true });
	fs.writeFileSync(manifestPath(artifactDir, name), `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

function readManifest(artifactDir: string, name: string): Record<string, unknown> {
	return JSON.parse(fs.readFileSync(manifestPath(artifactDir, name), 'utf8'));
}

// contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
test('publishes a saved web producer manifest for Apple consumption', async ({ page }: { page: any }) => {
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const { runId, artifactDir } = requireControlPlane();
	const webMarker = marker('web');

	await loginToTestAccount(page, undefined, undefined, {
		credentials: { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY }
	});
	await startNewChat(page);
	await sendMessage(page, webMarker);
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 30000 });
	await expect(page.getByTestId('message-user').last()).toContainText(webMarker);
	await waitForAssistantMessage(page, { timeout: 120000 });
	const chatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
	expect(chatId).toBeTruthy();

	writeManifest(artifactDir, 'web-producer', {
		schema_version: 1,
		run_id: runId,
		producer: 'web',
		chat_id: chatId,
		marker_hash: crypto.createHash('sha256').update(webMarker).digest('hex'),
		created_at: new Date().toISOString()
	});
});

// contract-test: direct surface=gui.web assertions=chats.message.identity-idempotent,chats.surface.semantic-parity
test('opens the Apple-produced chat once when its consumer manifest is available', async ({ page }: { page: any }) => {
	test.setTimeout(240000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const { runId, artifactDir } = requireControlPlane();
	const apple = readManifest(artifactDir, 'apple-producer');
	expect(apple.run_id).toBe(runId);
	expect(typeof apple.chat_id).toBe('string');
	const appleMarker = `Apple parity Apple web search ${runId}`;

	await loginToTestAccount(page, undefined, undefined, {
		credentials: { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY }
	});
	await page.goto(`/#chat-id=${encodeURIComponent(String(apple.chat_id))}`);
	await assertAppleSearchChat(page, appleMarker);

	await page.reload({ waitUntil: 'networkidle' });
	await assertAppleSearchChat(page, appleMarker);

	writeManifest(artifactDir, 'web-consumer', {
		schema_version: 1,
		run_id: runId,
		consumer: 'web',
		chat_id: apple.chat_id,
		marker_hash: crypto.createHash('sha256').update(appleMarker).digest('hex'),
		consumed_at: new Date().toISOString()
	});
	await deleteActiveChat(page);
});

async function assertAppleSearchChat(page: any, appleMarker: string): Promise<void> {
	const title = page.getByTestId('chat-header-title');
	const summary = page.getByTestId('chat-header-summary');
	await expect(title).toBeVisible({ timeout: 60_000 });
	await expect(title).not.toHaveText('', { timeout: 60_000 });
	await expect(title).not.toContainText(/creating|untitled/i);
	await expect(summary).toBeVisible({ timeout: 60_000 });
	await expect(summary).not.toHaveText('', { timeout: 60_000 });

	const user = page.getByTestId('message-user');
	const assistant = page.getByTestId('message-assistant');
	await expect(user).toHaveCount(1, { timeout: 60_000 });
	await expect(user.last()).toContainText(appleMarker);
	await expect(assistant).toHaveCount(1, { timeout: 60_000 });
	await expect(assistant.last()).toBeVisible();
	await expect(assistant.last()).not.toHaveText('');
	await expect(assistant.last()).not.toContainText(/app_skill_use|embed_ref/);

	const skill = await waitForEmbedFinished(page, 'web', 'search', 90_000);
	await expect(skill).toBeVisible();
	const fullscreen = await openFullscreen(page, skill);
	const children = await verifySearchGrid(fullscreen, 1, 60_000);
	expect(await children.count()).toBeGreaterThan(0);
	await closeFullscreen(page, fullscreen);
}
