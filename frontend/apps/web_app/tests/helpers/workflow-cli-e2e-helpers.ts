/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Shared Workflow CLI Playwright helpers.
 *
 * These tests use Playwright only to authorize the CLI through pair login and,
 * for chat-delivery coverage, keep a browser device online to claim encrypted
 * pending Workflow deliveries. Workflow behavior is exercised through the real
 * CLI against the deployed dev backend.
 */
export {};

const { expect } = require('@playwright/test');
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { deriveApiUrl, CLI_DIST } = require('./cli-test-helpers');
const { loginToTestAccount } = require('./chat-test-helpers');

type CliResult = { code: number | null; stdout: string; stderr: string };

const TRANSIENT_WORKFLOW_READ_STATUS_RE = /Workflow run get failed with HTTP (500|502|503|504)/;

function isTransientWorkflowRunReadError(error: unknown): boolean {
	const message = error instanceof Error ? error.message : String(error);
	return TRANSIENT_WORKFLOW_READ_STATUS_RE.test(message) || message.includes('failed with code null');
}

function createWorkflowCliHome(prefix: string): string {
	return fs.mkdtempSync(path.join(os.tmpdir(), `openmates-${prefix}-`));
}

function removeWorkflowCliHome(homeDir: string): void {
	if (!homeDir || !homeDir.startsWith(os.tmpdir())) return;
	fs.rmSync(homeDir, { recursive: true, force: true });
}

function clearWorkflowCliSyncCache(homeDir: string): void {
	if (!homeDir || !homeDir.startsWith(os.tmpdir())) return;
	fs.rmSync(path.join(homeDir, '.openmates', 'sync_cache.json'), { force: true });
}

function writeWorkflowYaml(homeDir: string, fileName: string, source: string): string {
	const filePath = path.join(homeDir, fileName);
	fs.writeFileSync(filePath, source.trimStart(), 'utf8');
	return filePath;
}

function workflowCliEnv(apiUrl: string, homeDir: string): Record<string, string | undefined> {
	const cliDir = path.dirname(path.dirname(CLI_DIST));
	return {
		...process.env,
		HOME: homeDir,
		OPENMATES_API_KEY: undefined,
		OPENMATES_API_URL: apiUrl,
		NODE_PATH: path.join(cliDir, 'node_modules'),
		TERM: 'dumb'
	};
}

function spawnCliLogin(apiUrl: string, homeDir: string) {
	const child = spawn('node', [CLI_DIST, 'login'], {
		env: workflowCliEnv(apiUrl, homeDir),
		stdio: ['pipe', 'pipe', 'pipe']
	});

	const stdout: string[] = [];
	const stderr: string[] = [];
	child.stdout.on('data', (chunk: Buffer) => stdout.push(chunk.toString()));
	child.stderr.on('data', (chunk: Buffer) => stderr.push(chunk.toString()));

	return {
		waitForToken(): Promise<string> {
			return new Promise((resolve, reject) => {
				const timeout = setTimeout(() => {
					reject(new Error(`CLI did not output pair token. stdout:\n${stdout.join('')}\nstderr:\n${stderr.join('')}`));
				}, 15_000);
				const interval = setInterval(() => {
					const match = stdout.join('').match(/pair=([A-Z0-9]{6})/);
					if (!match) return;
					clearTimeout(timeout);
					clearInterval(interval);
					resolve(match[1]);
				}, 250);
			});
		},
		sendPin(pin: string): void {
			child.stdin.write(`${pin}\n`);
		},
		waitForExit(): Promise<{ code: number | null; output: string }> {
			return new Promise((resolve) => {
				const timeout = setTimeout(() => {
					child.kill('SIGTERM');
					resolve({ code: null, output: stdout.join('') + stderr.join('') });
				}, 30_000);
				child.on('close', (code: number | null) => {
					clearTimeout(timeout);
					resolve({ code, output: stdout.join('') + stderr.join('') });
				});
			});
		},
		kill(): void {
			child.kill('SIGTERM');
		}
	};
}

async function loginWorkflowCliViaPair(page: any, apiUrl: string, homeDir: string, label: string): Promise<void> {
	await loginToTestAccount(page, (message: string) => console.log(`[${label}] ${message}`));

	const cli = spawnCliLogin(apiUrl, homeDir);
	let token: string;
	try {
		token = await cli.waitForToken();
	} catch (error) {
		cli.kill();
		throw error;
	}

	const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
	await page.goto(`${baseUrl}/#pair=${token}`);
	const allowButton = page.getByTestId('pair-allow-button');
	await expect(allowButton).toBeVisible({ timeout: 15_000 });
	await allowButton.click();
	const pinDisplay = page.getByTestId('pair-pin-display');
	await expect(pinDisplay).toBeVisible({ timeout: 15_000 });
	const pin = ((await pinDisplay.textContent()) || '').replace(/\s/g, '').trim();
	expect(pin).toMatch(/^[A-Z0-9]{6}$/);
	cli.sendPin(pin);
	const { code, output } = await cli.waitForExit();
	expect(output).toContain('Login successful');
	expect(code).toBe(0);
}

async function runWorkflowCli(apiUrl: string, homeDir: string, args: string[], timeoutMs = 60_000): Promise<CliResult> {
	return new Promise((resolve) => {
		const child = spawn('node', [CLI_DIST, ...args], {
			env: workflowCliEnv(apiUrl, homeDir),
			stdio: ['pipe', 'pipe', 'pipe']
		});
		const stdout: string[] = [];
		const stderr: string[] = [];
		child.stdout.on('data', (chunk: Buffer) => stdout.push(chunk.toString()));
		child.stderr.on('data', (chunk: Buffer) => stderr.push(chunk.toString()));
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

function expectCliSuccess(result: CliResult, label: string): void {
	expect(
		result.code,
		`${label} failed with code ${result.code}\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`
	).toBe(0);
}

function parseCliJson(result: CliResult, label: string): any {
	expectCliSuccess(result, label);
	try {
		return JSON.parse(result.stdout);
	} catch {
		throw new Error(`${label} returned non-JSON stdout:\n${result.stdout}\nstderr:\n${result.stderr}`);
	}
}

async function runWorkflowCliJson(
	apiUrl: string,
	homeDir: string,
	args: string[],
	label: string,
	timeoutMs = 60_000
): Promise<any> {
	return parseCliJson(await runWorkflowCli(apiUrl, homeDir, [...args, '--json'], timeoutMs), label);
}

async function deleteWorkflowQuietly(apiUrl: string, homeDir: string, workflowId?: string): Promise<void> {
	if (!workflowId) return;
	await runWorkflowCli(apiUrl, homeDir, ['workflows', 'disable', workflowId, '--json'], 30_000);
	await runWorkflowCli(apiUrl, homeDir, ['workflows', 'delete', workflowId, '--yes', '--json'], 30_000);
}

async function waitForWorkflowRunStatus(
	apiUrl: string,
	homeDir: string,
	workflowId: string,
	runId: string,
	allowedStatuses: string[],
	label: string,
	timeoutMs = 180_000
): Promise<any> {
	const started = Date.now();
	let lastRun: any = null;
	let lastTransientError: string | null = null;
	while (Date.now() - started < timeoutMs) {
		try {
			lastRun = await runWorkflowCliJson(
				apiUrl,
				homeDir,
				['workflows', 'run-show', workflowId, runId],
				`${label} run-show`,
				30_000
			);
			lastTransientError = null;
		} catch (error) {
			if (!isTransientWorkflowRunReadError(error)) throw error;
			lastTransientError = error instanceof Error ? error.message : String(error);
			await new Promise((resolve) => setTimeout(resolve, 3_000));
			continue;
		}
		if (allowedStatuses.includes(lastRun.status)) return lastRun;
		if (lastRun.status === 'failed' || lastRun.status === 'cancelled') {
			throw new Error(`${label} reached terminal status ${lastRun.status}: ${JSON.stringify(lastRun, null, 2)}`);
		}
		await new Promise((resolve) => setTimeout(resolve, 3_000));
	}
	throw new Error(
		`${label} did not reach ${allowedStatuses.join('/')} in ${timeoutMs}ms. Last run: ${JSON.stringify(lastRun, null, 2)}. Last transient error: ${lastTransientError ?? 'none'}`
	);
}

async function waitForWorkflowRunListStatus(
	apiUrl: string,
	homeDir: string,
	workflowId: string,
	allowedStatuses: string[],
	label: string,
	timeoutMs = 180_000
): Promise<any> {
	const started = Date.now();
	let lastRuns: any[] = [];
	while (Date.now() - started < timeoutMs) {
		lastRuns = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'runs', workflowId], `${label} runs`, 30_000);
		const matching = lastRuns.find((run: any) => allowedStatuses.includes(run.status));
		if (matching) return matching;
		await new Promise((resolve) => setTimeout(resolve, 5_000));
	}
	throw new Error(`${label} did not create a run with status ${allowedStatuses.join('/')} in ${timeoutMs}ms. Runs: ${JSON.stringify(lastRuns, null, 2)}`);
}

async function waitForChatTitle(apiUrl: string, homeDir: string, title: string, timeoutMs = 120_000): Promise<any> {
	const started = Date.now();
	let lastResult: any = null;
	while (Date.now() - started < timeoutMs) {
		clearWorkflowCliSyncCache(homeDir);
		lastResult = await runWorkflowCliJson(apiUrl, homeDir, ['chats', 'list', '--limit', '30'], 'chats list', 90_000);
		const chats = Array.isArray(lastResult?.chats) ? lastResult.chats : [];
		const chat = chats.find((item: any) => item.title === title || item.encrypted_title === title);
		if (chat) return chat;
		await new Promise((resolve) => setTimeout(resolve, 5_000));
	}
	throw new Error(`Chat title ${title} did not appear. Last result: ${JSON.stringify(lastResult, null, 2)}`);
}

function uniqueWorkflowName(prefix: string): string {
	return `${prefix} ${Date.now()} ${Math.random().toString(36).slice(2, 8)}`;
}

function workflowApiUrl(): string {
	return deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
}

module.exports = {
	createWorkflowCliHome,
	deleteWorkflowQuietly,
	expectCliSuccess,
	loginWorkflowCliViaPair,
	parseCliJson,
	removeWorkflowCliHome,
	runWorkflowCli,
	runWorkflowCliJson,
	uniqueWorkflowName,
	waitForChatTitle,
	waitForWorkflowRunListStatus,
	waitForWorkflowRunStatus,
	workflowApiUrl,
	writeWorkflowYaml
};
