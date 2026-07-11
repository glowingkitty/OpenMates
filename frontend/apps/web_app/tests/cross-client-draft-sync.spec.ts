/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Cross-client encrypted draft lifecycle contract.
 *
 * Pairs the interactive CLI with an authenticated browser, then proves draft
 * create, edit, clear, send, and missed-deletion reconciliation end to end.
 * Draft plaintext is asserted only inside authenticated client boundaries.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const {
	createSignupLogger,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount, waitForChatReady } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const CLI_DIST = fs.existsSync('/workspace/cli/dist/cli.js')
	? '/workspace/cli/dist/cli.js'
	: path.resolve(__dirname, '../../../packages/openmates-cli/dist/cli.js');
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount(1);

function deriveApiUrl(baseUrl: string): string {
	const url = new URL(baseUrl);
	if (url.hostname === 'openmates.org' || url.hostname === 'www.openmates.org') {
		return 'https://api.openmates.org';
	}
	if (url.hostname.startsWith('app.')) {
		return `${url.protocol}//api.${url.hostname.slice(4)}`;
	}
	if (url.hostname === 'localhost') return 'http://localhost:8000';
	throw new Error(`Cannot derive API URL from ${baseUrl}`);
}

function cliEnvironment(apiUrl: string): Record<string, string | undefined> {
	const cliDir = path.dirname(path.dirname(CLI_DIST));
	return {
		...process.env,
		OPENMATES_API_URL: apiUrl,
		NODE_PATH: path.join(cliDir, 'node_modules'),
		TERM: 'dumb'
	};
}

async function runCli(
	apiUrl: string,
	args: string[],
	timeoutMs = 60_000
): Promise<{ code: number | null; stdout: string; stderr: string }> {
	return new Promise((resolve) => {
		const child = spawn('node', [CLI_DIST, ...args], {
			env: cliEnvironment(apiUrl),
			stdio: ['ignore', 'pipe', 'pipe']
		});
		const stdout: string[] = [];
		const stderr: string[] = [];
		child.stdout.on('data', (data: Buffer) => stdout.push(data.toString()));
		child.stderr.on('data', (data: Buffer) => stderr.push(data.toString()));
		const timeout = setTimeout(() => {
			child.kill('SIGTERM');
			resolve({ code: null, stdout: stdout.join(''), stderr: stderr.join('') });
		}, timeoutMs);
		child.on('close', (code: number | null) => {
			clearTimeout(timeout);
			resolve({ code, stdout: stdout.join(''), stderr: stderr.join('') });
		});
	});
}

async function runCliJson(apiUrl: string, args: string[], timeoutMs = 60_000): Promise<any> {
	const result = await runCli(apiUrl, [...args, '--json'], timeoutMs);
	expect(
		result.code,
		`openmates ${args.join(' ')} failed with ${result.stdout.length} stdout bytes\nstderr:\n${result.stderr}`
	).toBe(0);
	return JSON.parse(result.stdout);
}

async function pairCli(page: any, apiUrl: string, baseUrl: string): Promise<void> {
	const child = spawn('node', [CLI_DIST, 'login'], {
		env: cliEnvironment(apiUrl),
		stdio: ['pipe', 'pipe', 'pipe']
	});
	const stdout: string[] = [];
	const stderr: string[] = [];
	child.stdout.on('data', (data: Buffer) => stdout.push(data.toString()));
	child.stderr.on('data', (data: Buffer) => stderr.push(data.toString()));

	try {
		const token = await expect
			.poll(() => stdout.join('').match(/pair=([A-Z0-9]{6})/)?.[1] ?? null, {
				timeout: 15_000,
				intervals: [250, 500]
			})
			.not.toBeNull();
		void token;
		const pairToken = stdout.join('').match(/pair=([A-Z0-9]{6})/)?.[1];
		expect(pairToken).toBeTruthy();

		await page.goto(`${baseUrl}/#pair=${pairToken}`);
		await page.getByTestId('pair-allow-button').click();
		const pinDisplay = page.getByTestId('pair-pin-display');
		await expect(pinDisplay).toBeVisible({ timeout: 15_000 });
		const pin = ((await pinDisplay.textContent()) || '').replace(/\s/g, '');
		expect(pin).toMatch(/^[A-Z0-9]{6}$/);
		child.stdin.write(`${pin}\n`);

		const exit = await new Promise<{ code: number | null }>((resolve) => {
			const timeout = setTimeout(() => {
				child.kill('SIGTERM');
				resolve({ code: null });
			}, 30_000);
			child.on('close', (code: number | null) => {
				clearTimeout(timeout);
				resolve({ code });
			});
		});
		expect(exit.code, `CLI login failed: ${stdout.join('')} ${stderr.join('')}`).toBe(0);
		expect(stdout.join('')).toContain('Login successful');
	} finally {
		if (child.exitCode === null) child.kill('SIGTERM');
	}
}

async function openSidebar(page: any): Promise<void> {
	const toggle = page.getByTestId('sidebar-toggle');
	if (await toggle.isVisible({ timeout: 2_000 }).catch(() => false)) {
		const mounted = await page.getByTestId('chat-item-wrapper').first().isVisible().catch(() => false);
		if (!mounted) await toggle.click();
	}
}

function chatItem(page: any, chatId: string): any {
	return page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${chatId}"]`);
}

async function openDraft(page: any, chatId: string, expectedText: string): Promise<void> {
	await openSidebar(page);
	const item = chatItem(page, chatId);
	await expect(item).toBeVisible({ timeout: 30_000 });
	await expect(item).toContainText(expectedText);
	await item.click();
	const editor = page.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 15_000 });
	await expect(editor).toContainText(expectedText, { timeout: 15_000 });
}

test.describe('Cross-client encrypted draft sync', () => {
	test.setTimeout(360_000);

	test('CLI and web reconcile draft lifecycle and missed chat deletion', async ({ page }: { page: any }) => {
		test.slow();
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		const log = createSignupLogger('CROSS_CLIENT_DRAFT_SYNC');
		const screenshot = createStepScreenshotter(log, { filenamePrefix: 'cross-client-draft-sync' });
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const apiUrl = deriveApiUrl(baseUrl);
		const unique = Date.now().toString(36);
		const initialText = `CLI encrypted draft ${unique}`;
		const updatedText = `Web updated encrypted draft ${unique}`;
		const sentText = `Cross-client sent draft ${unique}`;
		const cleanupDraftIds = new Set<string>();
		const cleanupChatIds = new Set<string>();
		let cliPaired = false;

		await loginToTestAccount(page, log, screenshot);
		try {
			await pairCli(page, apiUrl, baseUrl);
			cliPaired = true;
			await page.goto(baseUrl);
			await waitForChatReady(page, log);

			const created = await runCliJson(apiUrl, ['drafts', 'create', initialText]);
			const draftChatId = String(created.chatId);
			expect(draftChatId).toMatch(/^[0-9a-f-]{36}$/i);
			cleanupDraftIds.add(draftChatId);
			await openDraft(page, draftChatId, initialText);

			const editor = page.getByTestId('message-editor');
			await editor.click();
			await page.keyboard.press('ControlOrMeta+A');
			await page.keyboard.insertText(updatedText);
			await page.getByTestId('input-dismiss-button').click();
			await expect
				.poll(async () => (await runCliJson(apiUrl, ['drafts', 'get', draftChatId, '--refresh'])).draft?.markdown, {
					timeout: 30_000,
					intervals: [1_000, 2_000]
				})
				.toBe(updatedText);

			await editor.click();
			await page.keyboard.press('ControlOrMeta+A');
			await page.keyboard.press('Backspace');
			await page.getByTestId('input-dismiss-button').click();
			await expect
				.poll(async () => (await runCliJson(apiUrl, ['drafts', 'get', draftChatId, '--refresh'])).draft, {
					timeout: 30_000,
					intervals: [1_000, 2_000]
				})
				.toBeNull();
			cleanupDraftIds.delete(draftChatId);

			const sendDraft = await runCliJson(apiUrl, ['drafts', 'create', sentText]);
			const sentChatId = String(sendDraft.chatId);
			cleanupDraftIds.add(sentChatId);
			await openDraft(page, sentChatId, sentText);
			const sendButton = page.locator('[data-action="send-message"]');
			await expect(sendButton).toBeVisible({ timeout: 15_000 });
			await sendButton.click();
			await expect(page.getByTestId('message-user').last()).toContainText(sentText, { timeout: 30_000 });
			await expect
				.poll(async () => (await runCliJson(apiUrl, ['drafts', 'get', sentChatId, '--refresh'])).draft, {
					timeout: 30_000,
					intervals: [1_000, 2_000]
				})
				.toBeNull();
			cleanupDraftIds.delete(sentChatId);
			cleanupChatIds.add(sentChatId);

			await page.context().setOffline(true);
			await runCliJson(apiUrl, ['chats', 'delete', sentChatId, '--yes']);
			cleanupChatIds.delete(sentChatId);
			await page.context().setOffline(false);
			await page.reload();
			await waitForChatReady(page, log);
			await openSidebar(page);
			await expect(chatItem(page, sentChatId)).toHaveCount(0, { timeout: 30_000 });
		} finally {
			await page.context().setOffline(false);
			for (const chatId of cleanupDraftIds) {
				await runCli(apiUrl, ['drafts', 'clear', chatId]);
			}
			for (const chatId of cleanupChatIds) {
				await runCli(apiUrl, ['chats', 'delete', chatId, '--yes']);
			}
			if (cliPaired) await runCli(apiUrl, ['logout']);
		}
	});
});
