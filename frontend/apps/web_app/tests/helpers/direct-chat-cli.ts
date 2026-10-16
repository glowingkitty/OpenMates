/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
import { dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import type { Page } from '@playwright/test';

const { spawn } = require('node:child_process');
const { expect } = require('./cookie-audit');
const { workflowCliEnv } = require('./workflow-cli-e2e-helpers');

/** Authorizes an isolated CLI home with the already signed-in actor's real web session. */
export async function pairDirectChatCli(page: Page, apiUrl: string, home: string, candidateCli: string): Promise<void> {
	const child = spawn('node', [candidateCli, 'login'], {
		env: workflowCliEnv(apiUrl, home), stdio: ['pipe', 'pipe', 'pipe']
	});
	let output = '';
	child.stdout.on('data', (part: Buffer) => { output += part.toString(); });
	child.stderr.on('data', (part: Buffer) => { output += part.toString(); });
	try {
		let token = '';
		await expect.poll(() => {
			token = output.match(/pair=([A-Z0-9]{6})/)?.[1] ?? '';
			return token;
		}, { timeout: 20_000 }).toMatch(/^[A-Z0-9]{6}$/);
		await page.goto(`${process.env.PLAYWRIGHT_TEST_BASE_URL || ''}/#pair=${token}`);
		await page.getByTestId('pair-allow-button').click();
		const pin = ((await page.getByTestId('pair-pin-display').innerText()) || '').replace(/\s/g, '').trim();
		expect(pin).toMatch(/^[A-Z0-9]{6}$/);
		await expect.poll(() => output.includes('Enter 6-char pairing PIN:'), { timeout: 20_000 }).toBe(true);
		child.stdin.write(`${pin}\n`);
		const code = await Promise.race([
			new Promise<number | null>(resolve => child.on('close', resolve)),
			new Promise<null>(resolve => setTimeout(() => { child.kill('SIGTERM'); resolve(null); }, 30_000))
		]);
		expect(code, output).toBe(0);
		expect(output).toContain('Login successful');
	} finally {
		if (child.exitCode === null) child.kill('SIGTERM');
	}
}

/** A fresh SDK process must decrypt the cached Team DM with every HTTP fetch blocked. */
export async function readDirectChatOffline(
	apiUrl: string, home: string, candidateCli: string, teamId: string, chatId: string
): Promise<{ messages: Array<{ content?: string }>; networkAttempts: number }> {
	const sdkUrl = pathToFileURL(join(dirname(candidateCli), 'index.js')).href;
	const source = `
import { OpenMatesClient } from ${JSON.stringify(sdkUrl)};
let networkAttempts = 0;
globalThis.fetch = async () => { networkAttempts += 1; throw new TypeError('Offline cache proof blocked network'); };
const client = new OpenMatesClient({ apiUrl: process.env.OPENMATES_API_URL });
const result = await client.getChatMessages(process.env.OPENMATES_DM_CHAT_ID, {
  teamId: process.env.OPENMATES_DM_TEAM_ID, preferCache: true, maxHistoryPages: 0
});
process.stdout.write(JSON.stringify({ messages: result.messages.map(message => ({ content: message.content })), networkAttempts }));
`;
	const child = spawn(process.execPath, ['--input-type=module', '--eval', source], {
		env: { ...workflowCliEnv(apiUrl, home), OPENMATES_DM_TEAM_ID: teamId, OPENMATES_DM_CHAT_ID: chatId },
		stdio: ['ignore', 'pipe', 'pipe']
	});
	let stdout = '', stderr = '';
	child.stdout.on('data', (part: Buffer) => { stdout += part.toString(); });
	child.stderr.on('data', (part: Buffer) => { stderr += part.toString(); });
	const code = await new Promise<number | null>((resolve, reject) => {
		const timeout = setTimeout(() => { child.kill('SIGKILL'); reject(new Error('Offline direct-chat cache read timed out')); }, 20_000);
		child.on('error', error => { clearTimeout(timeout); reject(error); });
		child.on('close', status => { clearTimeout(timeout); resolve(status); });
	});
	expect(code, stderr).toBe(0);
	return JSON.parse(stdout);
}
