/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Real-terminal proof source for OpenMates CLI app skill examples.
 *
 * The actual built CLI runs in a PTY displayed by a graphical terminal on Xvfb;
 * FFmpeg records terminal pixels and Playwright retains the resulting artifacts.
 */

// contract-test-file: tooling
export {};

const {test, expect} = require('@playwright/test');
const fs = require('node:fs');
const {deriveApiUrl, expectCliSuccess, runCliProof} = require('./helpers/cli-test-helpers');

const cliExamplesProof = {
	id: 'openmates-cli-travel-search-examples',
	title: 'OpenMates CLI travel search examples',
	surface: 'cli',
	devices: ['cli-terminal'],
	transcript: [
		{
			id: 'examples-visible',
			text: 'The OpenMates CLI command runs inside a real graphical terminal. The travel search_connections example list appears in the terminal output. The recording keeps the terminal pixels readable without reconstructing the CLI text.',
			checkpoint: 'examples-visible',
			devices: ['cli-terminal']
		}
	],
	assertions: [
		{
			id: 'cli.examples.visible',
			checkpoint: 'examples-visible',
			visual: 'The terminal window shows the OpenMates CLI command and the travel search_connections example list without reconstructed text.',
			devices: ['cli-terminal']
		}
	],
	tutorial: {
		readingWordsPerSecond: 2.5,
		minimumHoldMs: 1200,
		maximumHoldMs: 5000
	}
};

test.describe('Proof video real CLI architecture', () => {
	test('records the real OpenMates CLI app skill examples in a graphical terminal', async ({baseURL}: {baseURL: string}, testInfo: any) => {
		test.setTimeout(120000);
		const apiUrl = process.env.OPENMATES_E2E_API_URL || deriveApiUrl(baseURL || 'https://app.dev.openmates.org');
		const {result, proof, recording} = await runCliProof(
			apiUrl,
			['apps', 'examples', 'travel', 'search_connections'],
			testInfo,
			cliExamplesProof,
			120000,
			{useApiKey: false}
		);

		expectCliSuccess(result, 'openmates apps examples travel/search_connections');
		await proof.assert('cli.examples.visible', async () => {
			const manifest = JSON.parse(fs.readFileSync(recording.manifestPath, 'utf8'));
			expect(manifest.capture_kind).toBe('real_terminal_screen');
			expect(manifest.reconstructed).toBe(false);
			expect(manifest.exit_status).toBe(0);
			expect(fs.readFileSync(recording.transcriptPath, 'utf8')).toContain('Example chats for travel/search_connections');
		});
		await proof.checkpoint('examples-visible');
		await proof.attach();
	});
});
