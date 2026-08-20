/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Real-terminal proof source for the OpenMates CLI application catalog.
 *
 * The actual built CLI runs in a PTY displayed by a graphical terminal on Xvfb;
 * FFmpeg records terminal pixels and Playwright retains the resulting artifacts.
 */

// contract-test-file: tooling
export {};

const {test, expect} = require('@playwright/test');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

function run(command: string, args: string[], cwd: string): Promise<{code: number | null; stdout: string; stderr: string}> {
	return new Promise((resolve) => {
		const child = spawn(command, args, {cwd, env: process.env, stdio: ['ignore', 'pipe', 'pipe']});
		const stdout: string[] = [];
		const stderr: string[] = [];
		child.stdout.on('data', (chunk: Buffer) => stdout.push(chunk.toString()));
		child.stderr.on('data', (chunk: Buffer) => stderr.push(chunk.toString()));
		child.on('close', (code: number | null) => resolve({code, stdout: stdout.join(''), stderr: stderr.join('')}));
	});
}

test.describe('Proof video real CLI architecture', () => {
	// eslint-disable-next-line no-empty-pattern
	test('records the real OpenMates CLI apps catalog in a graphical terminal', async ({}, testInfo: any) => {
		test.setTimeout(120000);
		const repositoryRoot = path.resolve(process.cwd(), '../../..');
		const cliPath = fs.existsSync('/workspace/cli/dist/cli.js')
			? '/workspace/cli/dist/cli.js'
			: path.join(repositoryRoot, 'frontend/packages/openmates-cli/dist/cli.js');
		const outputDir = path.resolve(process.cwd(), 'test-results/cli-proof/apps-list');
		fs.rmSync(outputDir, {recursive: true, force: true});
		const result = await run('python3', [
			path.join(repositoryRoot, 'scripts/cli_video_capture.py'),
			'--output-dir', outputDir,
			'--target-environment', process.env.OPENMATES_E2E_API_URL || 'https://api.dev.openmates.org',
			'--display-number', '92',
			'--', 'node', cliPath, 'apps', 'list'
		], repositoryRoot);

		expect(result.code, `${result.stdout}\n${result.stderr}`).toBe(0);
		const manifestPath = path.join(outputDir, 'manifest.json');
		const videoPath = path.join(outputDir, 'raw-terminal.mp4');
		const transcriptPath = path.join(outputDir, 'transcript.txt');
		const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
		expect(manifest.capture_kind).toBe('real_terminal_screen');
		expect(manifest.reconstructed).toBe(false);
		expect(manifest.exit_status).toBe(0);
		expect(fs.readFileSync(transcriptPath, 'utf8')).toContain('OpenMates');

		await testInfo.attach('openmates-cli-real-terminal-video', {path: videoPath, contentType: 'video/mp4'});
		await testInfo.attach('openmates-cli-real-terminal-transcript', {path: transcriptPath, contentType: 'text/plain'});
		await testInfo.attach('openmates-cli-real-terminal-manifest', {path: manifestPath, contentType: 'application/json'});
	});
});
