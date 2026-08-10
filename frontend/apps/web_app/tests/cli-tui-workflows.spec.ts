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
const path = require('path');

test.describe('CLI TUI workflows', () => {
	test('keeps the Workflow TUI usable through the built package test harness', async () => {
		const packageDir = path.resolve(__dirname, '../../../packages/openmates-cli');
		const result = await runNodeTest(packageDir, [
			'--test',
			'--experimental-strip-types',
			'--loader',
			'./tests/loader.mjs',
			'tests/tuiWorkflowInteraction.test.ts'
		]);

		expect(
			result.code,
			`Workflow TUI interaction test failed\n── stdout ──\n${result.stdout}\n── stderr ──\n${result.stderr}`
		).toBe(0);
		expect(result.stdout).toContain('opens workflows, switches tabs, runs, cancels, expands, and edits node details');
	});
});

function runNodeTest(
	cwd: string,
	args: string[]
): Promise<{ code: number | null; stdout: string; stderr: string }> {
	return new Promise((resolve) => {
		const child = spawn('node', args, {
			cwd,
			env: process.env,
			stdio: ['ignore', 'pipe', 'pipe']
		});
		const stdout: string[] = [];
		const stderr: string[] = [];
		child.stdout.on('data', (chunk: Buffer) => stdout.push(chunk.toString()));
		child.stderr.on('data', (chunk: Buffer) => stderr.push(chunk.toString()));
		child.on('close', (code: number | null) => {
			resolve({ code, stdout: stdout.join(''), stderr: stderr.join('') });
		});
	});
}
