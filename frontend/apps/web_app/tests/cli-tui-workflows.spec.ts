/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * CLI TUI Workflow GitHub Actions contract.
 *
 * Runs the package-level Workflow TUI interaction test through the Playwright
 * control plane so the TUI remains covered by scheduled/dispatchable E2E CI.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { spawn } = require('child_process');
const { mkdtempSync, rmSync } = require('fs');
const { tmpdir } = require('os');
const path = require('path');

test.describe('CLI TUI workflows', () => {
	// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,workflows.surface.semantic-parity
	test('keeps the Workflow TUI usable through the built package test harness', async () => {
		const packageDir = path.resolve(__dirname, '../../../packages/openmates-cli');
		const result = await runNodeTest(packageDir, [
			'--test',
			'--experimental-strip-types',
			'--loader',
			'./tests/loader.mjs',
			'tests/tui.test.ts',
			'tests/tuiExampleContinuation.test.ts',
			'tests/tuiWorkflowInteraction.test.ts',
			'tests/tuiWorkspaceInteraction.test.ts',
			'tests/tuiLayout.test.ts',
			'tests/tuiTerminal.test.ts',
			'tests/tuiTasksWorkspace.test.ts',
			'tests/tuiProjectsWorkspace.test.ts',
			'tests/tuiWorkflowWorkspace.test.ts',
			'tests/tuiAttachments.test.ts',
			'tests/tuiCancellation.test.ts',
			'tests/tuiWorkflowVersion.test.ts',
			'tests/tuiAppsWorkspace.test.ts',
			'tests/tuiHome.test.ts',
			'tests/embedRenderers.test.ts',
			'tests/tuiChatSidebar.test.ts',
			'tests/sdk-chat-sidebar.test.ts',
			'tests/ws.test.ts',
			'tests/draft-sync.test.ts',
			'tests/sdk-draft-sync.test.ts'
		]);

		expect(
			result.code,
			`Workflow TUI interaction test failed\n── stdout ──\n${result.stdout}\n── stderr ──\n${result.stderr}`
		).toBe(0);
		expect(result.stdout).toContain('opens workflows, switches tabs, runs, cancels, expands, and edits node details');
		expect(result.stdout).toContain('startup renders cached chats before background sync');
		expect(result.stdout).toContain('requires the sync completion frame before publishing collected history');
		expect(result.stdout).toContain('does not create response timers after the socket has already closed');
		expect(result.stdout).toContain('cold startup shows verified synced previews while saved output recovery is still pending');
		expect(result.stdout).toContain('verified synced history is published and retained on disk before slow recovery finishes');
		expect(result.stdout).toContain('failed sync keeps cached chats usable');
		expect(result.stdout).toContain('background activity failures preserve the cached-chat sync status');
		expect(result.stdout).toContain('opening a cached chat renders messages before slow draft lookup');
		expect(result.stdout).toContain('cached chat opening and drafts bypass full sync');
		expect(result.stdout).toContain('metadata-only chat opening reads canonical history without saved-output recovery');
		expect(result.stdout).toContain('batched command text precedes Enter and Escape interrupts pending fullscreen loading');
	});
});

function runNodeTest(
	cwd: string,
	args: string[]
): Promise<{ code: number | null; stdout: string; stderr: string }> {
	return new Promise((resolve, reject) => {
		const home = mkdtempSync(path.join(tmpdir(), 'openmates-tui-unit-'));
		const child = spawn('node', args, {
			cwd,
			// Mocked lifecycle tests create their own sessions and local servers.
			// They must not inherit the runner's authenticated integration profile.
			env: {
				...process.env,
				HOME: home,
				OPENMATES_STATE_DIR: undefined,
				OPENMATES_PROFILE: undefined,
				OPENMATES_API_KEY: undefined,
				OPENMATES_API_URL: undefined
			},
			stdio: ['ignore', 'pipe', 'pipe']
		});
		const stdout: string[] = [];
		const stderr: string[] = [];
		child.stdout.on('data', (chunk: Buffer) => stdout.push(chunk.toString()));
		child.stderr.on('data', (chunk: Buffer) => stderr.push(chunk.toString()));
		child.on('error', (error: Error) => {
			rmSync(home, { recursive: true, force: true });
			reject(error);
		});
		child.on('close', (code: number | null) => {
			rmSync(home, { recursive: true, force: true });
			resolve({ code, stdout: stdout.join(''), stderr: stderr.join('') });
		});
	});
}
