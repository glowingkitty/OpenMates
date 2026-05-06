/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * CLI Memories E2E Test
 *
 * Tests the full zero-knowledge memory lifecycle via the CLI:
 *   1. Login via pair auth (shared helper from cli-pair-login.spec.ts)
 *   2. List memory types
 *   3. Create a memory entry (verifies encryption round-trip)
 *   4. List memories — verify the entry is decrypted and present
 *   5. Verify item_key in Directus is a 32-char hash (not the plaintext key)
 *   6. Update the memory entry
 *   7. Delete the memory entry
 *   8. Verify it's gone from list
 *
 * Architecture doc: docs/architecture/openmates-cli.md
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

const { test, expect } = require('./helpers/cookie-audit');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	createSignupLogger,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');

const CLI_DIST = fs.existsSync('/workspace/cli/dist/cli.js')
	? '/workspace/cli/dist/cli.js'
	: path.resolve(__dirname, '../../../packages/openmates-cli/dist/cli.js');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const consoleLogs: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log(
			'\n--- CLI MEMORIES DEBUG ---\n' + consoleLogs.slice(-50).join('\n') + '\n--- END DEBUG ---\n'
		);
	}
});

// ---------------------------------------------------------------------------
// Helpers (reuse pattern from cli-pair-login.spec.ts)
// ---------------------------------------------------------------------------

function deriveApiUrl(baseUrl: string): string {
	try {
		const url = new URL(baseUrl);
		if (url.hostname === 'openmates.org' || url.hostname === 'www.openmates.org')
			return 'https://api.openmates.org';
		if (url.hostname.startsWith('app.')) return `${url.protocol}//api.${url.hostname.slice(4)}`;
		if (url.hostname === 'localhost') return 'http://localhost:8000';
	} catch {
		/* fall through */
	}
	return 'https://api.openmates.org';
}

function spawnCliLogin(apiUrl: string) {
	const cliDir = path.dirname(path.dirname(CLI_DIST));
	const child = spawn('node', [CLI_DIST, 'login'], {
		env: {
			...process.env,
			OPENMATES_API_URL: apiUrl,
			NODE_PATH: path.join(cliDir, 'node_modules'),
			TERM: 'dumb'
		},
		stdio: ['pipe', 'pipe', 'pipe']
	});

	const stdout: string[] = [];
	const stderr: string[] = [];
	child.stdout.on('data', (d: Buffer) => {
		const l = d.toString();
		stdout.push(l);
		consoleLogs.push(`[CLI] ${l.trim()}`);
	});
	child.stderr.on('data', (d: Buffer) => {
		const l = d.toString();
		stderr.push(l);
		consoleLogs.push(`[CLI err] ${l.trim()}`);
	});

	return {
		process: child,
		stdout,
		stderr,
		waitForToken(): Promise<string> {
			return new Promise((resolve, reject) => {
				const timeout = setTimeout(
					() => reject(new Error(`No pair token in 15s. stdout: ${stdout.join('')}`)),
					15_000
				);
				const check = () => {
					const m = stdout.join('').match(/pair=([A-Z0-9]{6})/);
					if (m) {
						clearTimeout(timeout);
						resolve(m[1]);
					}
				};
				const interval = setInterval(check, 300);
				child.stdout.on('data', check);
				const origResolve = resolve;
				resolve = ((v: string) => {
					clearInterval(interval);
					origResolve(v);
				}) as any;
			});
		},
		sendPin(pin: string) {
			child.stdin.write(pin + '\n');
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
		kill() {
			child.kill('SIGTERM');
		}
	};
}

async function runCli(
	apiUrl: string,
	args: string[],
	timeoutMs = 25_000
): Promise<{ code: number | null; stdout: string; stderr: string }> {
	const cliDir = path.dirname(path.dirname(CLI_DIST));
	return new Promise((resolve) => {
		const child = spawn('node', [CLI_DIST, ...args], {
			env: {
				...process.env,
				OPENMATES_API_URL: apiUrl,
				NODE_PATH: path.join(cliDir, 'node_modules')
			},
			stdio: ['pipe', 'pipe', 'pipe']
		});
		const out: string[] = [],
			err: string[] = [];
		child.stdout.on('data', (d: Buffer) => out.push(d.toString()));
		child.stderr.on('data', (d: Buffer) => err.push(d.toString()));
		const timeout = setTimeout(() => {
			child.kill('SIGTERM');
			resolve({ code: null, stdout: out.join(''), stderr: err.join('') });
		}, timeoutMs);
		child.on('close', (code: number | null) => {
			clearTimeout(timeout);
			resolve({ code, stdout: out.join(''), stderr: err.join('') });
		});
	});
}

function parseJsonOutput(stdout: string, label: string): any {
	const trimmed = stdout.trim();
	if (!trimmed) {
		throw new Error(`${label} returned empty stdout`);
	}
	return JSON.parse(trimmed);
}

async function loginViaPair(page: any, apiUrl: string, logCheckpoint: (msg: string) => void) {
	const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';

	// Log in to web app
	await page.goto('/');
	const loginBtn = page.getByTestId('header-login-signup-btn');
	await expect(loginBtn).toBeVisible({ timeout: 15000 });
	await loginBtn.click();

	// Click Login tab to switch from signup to login view
	const loginTab = page.getByTestId('tab-login');
	await expect(loginTab).toBeVisible({ timeout: 10000 });
	await loginTab.click();

	const emailInput = page.locator('#login-email-input');
	await expect(emailInput).toBeVisible({ timeout: 15000 });
	await emailInput.fill(TEST_EMAIL);
	// Wait for Continue button to become enabled after email input
	const continueBtn = page.getByRole('button', { name: /continue/i });
	await expect(continueBtn).toBeEnabled({ timeout: 5000 });
	await continueBtn.click();

	const passwordInput = page.locator('#login-password-input');
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);

	// Submit password first, then handle OTP if required.
	// OTP field only appears after backend confirms 2FA is needed (anti-enumeration).
	const { submitPasswordAndHandleOtp, waitForChatReady } = require('./helpers/chat-test-helpers');
	await submitPasswordAndHandleOtp(page, TEST_OTP_KEY, (msg: string) => logCheckpoint(msg));

	await waitForChatReady(page, (msg: string) => logCheckpoint(msg));
	logCheckpoint('Web app logged in.');

	// Start CLI login
	const cli = spawnCliLogin(apiUrl);
	let token: string;
	try {
		token = await cli.waitForToken();
	} catch (err) {
		cli.kill();
		throw err;
	}
	logCheckpoint(`CLI pair token: ${token}`);

	// Approve pair
	await page.goto(`${baseUrl}/#pair=${token}`);
	const allowBtn = page.getByTestId('pair-allow-button');
	await expect(allowBtn).toBeVisible({ timeout: 15000 });
	await allowBtn.click();

	const pinDisplay = page.getByTestId('pair-pin-display');
	await expect(pinDisplay).toBeVisible({ timeout: 15000 });
	const pinText = await pinDisplay.textContent();
	const pin = (pinText || '').replace(/\s/g, '').trim();
	logCheckpoint(`PIN: ${pin}`);

	cli.sendPin(pin);
	const { code, output } = await cli.waitForExit();
	expect(output).toContain('Login successful');
	expect(code).toBe(0);
	logCheckpoint('CLI login complete.');
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('CLI Memories', () => {
	test.setTimeout(240_000);

	test('full memory lifecycle: create → list (decrypted) → update → delete', async ({
		page
	}: {
		page: any;
	}) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const logCheckpoint = createSignupLogger('CLI_MEMORIES');
		const takeScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'cli-memories'
		});
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const apiUrl = deriveApiUrl(baseUrl);

		page.on('console', (msg: any) => consoleLogs.push(`[browser] ${msg.type()}: ${msg.text()}`));

		// -----------------------------------------------------------------------
		// Step 1: Login
		// -----------------------------------------------------------------------
		logCheckpoint('Step 1: Logging in...');
		await loginViaPair(page, apiUrl, logCheckpoint);
		await takeScreenshot(page, 'logged-in');

		// -----------------------------------------------------------------------
		// Step 2: List memory types
		// -----------------------------------------------------------------------
		logCheckpoint('Step 2: Listing memory types...');
		const typesResult = await runCli(apiUrl, [
			'settings',
			'memories',
			'types',
			'--app-id',
			'code',
			'--json'
		]);
		consoleLogs.push(`[types stdout] ${typesResult.stdout}`);
		expect(typesResult.code).toBe(0);
		const types = parseJsonOutput(typesResult.stdout, 'memory types list');
		expect(Array.isArray(types)).toBe(true);
		expect(types.length).toBeGreaterThan(0);
		const preferredTechType = types.find((t: any) => t.item_type === 'preferred_tech');
		expect(preferredTechType).toBeTruthy();
		expect(preferredTechType.required).toContain('name');
		logCheckpoint(`Found ${types.length} code memory types.`);

		// -----------------------------------------------------------------------
		// Step 3: Create a memory entry
		// -----------------------------------------------------------------------
		logCheckpoint('Step 3: Creating memory entry...');
		const createResult = await runCli(
			apiUrl,
			[
				'settings',
				'memories',
				'create',
				'--app-id',
				'code',
				'--item-type',
				'preferred_tech',
				'--data',
				JSON.stringify({ name: 'TestLang-E2E', proficiency: 'intermediate' }),
				'--json'
			],
			30_000
		);
		consoleLogs.push(`[create stdout] ${createResult.stdout}`);
		consoleLogs.push(`[create stderr] ${createResult.stderr}`);
		expect(createResult.code).toBe(0);
		const createData = parseJsonOutput(createResult.stdout, 'memories create');
		expect(createData.success).toBe(true);
		expect(typeof createData.id).toBe('string');
		const entryId = createData.id;
		logCheckpoint(`Created entry: ${entryId}`);

		// -----------------------------------------------------------------------
		// Step 4: List memories — verify decryption and content
		// -----------------------------------------------------------------------
		logCheckpoint('Step 4: Listing memories to verify decryption...');
		const listResult = await runCli(
			apiUrl,
			[
				'settings',
				'memories',
				'list',
				'--app-id',
				'code',
				'--item-type',
				'preferred_tech',
				'--json'
			],
			30_000
		);
		consoleLogs.push(`[list stdout] ${listResult.stdout}`);
		expect(listResult.code).toBe(0);
		const memories = parseJsonOutput(listResult.stdout, 'memories list');
		expect(Array.isArray(memories)).toBe(true);

		const ourEntry = memories.find((m: any) => m.id === entryId);
		expect(ourEntry).toBeTruthy();
		// Verify the entry was properly decrypted
		expect(ourEntry.data.name).toBe('TestLang-E2E');
		expect(ourEntry.data.proficiency).toBe('intermediate');
		// Verify zero-knowledge: item_key_hash is a 32-char hex hash, NOT 'preferred_tech'
		expect(ourEntry.item_key_hash).toMatch(/^[0-9a-f]{32}$/);
		expect(ourEntry.item_key_hash).not.toBe('preferred_tech');
		// Verify _original_item_key is stored inside the encrypted payload
		expect(ourEntry.data._original_item_key).toBe('preferred_tech');
		expect(ourEntry.data.settings_group).toBe('code');
		logCheckpoint(`Decrypted entry verified. item_key_hash: ${ourEntry.item_key_hash}`);
		await takeScreenshot(page, 'memory-listed');

		// -----------------------------------------------------------------------
		// Step 5: Update the memory entry
		// -----------------------------------------------------------------------
		logCheckpoint('Step 5: Updating memory entry...');
		const updateResult = await runCli(
			apiUrl,
			[
				'settings',
				'memories',
				'update',
				'--id',
				entryId,
				'--app-id',
				'code',
				'--item-type',
				'preferred_tech',
				'--data',
				JSON.stringify({ name: 'TestLang-E2E-Updated', proficiency: 'advanced' }),
				'--version',
				String(ourEntry.item_version),
				'--json'
			],
			30_000
		);
		consoleLogs.push(`[update stdout] ${updateResult.stdout}`);
		expect(updateResult.code).toBe(0);
		const updateData = parseJsonOutput(updateResult.stdout, 'memories update');
		expect(updateData.success).toBe(true);
		logCheckpoint('Entry updated.');

		// Verify the update
		const listAfterUpdate = await runCli(
			apiUrl,
			[
				'settings',
				'memories',
				'list',
				'--app-id',
				'code',
				'--item-type',
				'preferred_tech',
				'--json'
			],
			30_000
		);
		const memoriesAfterUpdate = parseJsonOutput(listAfterUpdate.stdout, 'memories list after update');
		const updatedEntry = memoriesAfterUpdate.find((m: any) => m.id === entryId);
		expect(updatedEntry).toBeTruthy();
		expect(updatedEntry.data.name).toBe('TestLang-E2E-Updated');
		expect(updatedEntry.data.proficiency).toBe('advanced');
		logCheckpoint('Update verified.');

		// -----------------------------------------------------------------------
		// Step 6: Delete the memory entry
		// -----------------------------------------------------------------------
		logCheckpoint('Step 6: Deleting memory entry...');
		const deleteResult = await runCli(
			apiUrl,
			['settings', 'memories', 'delete', '--id', entryId, '--json'],
			30_000
		);
		consoleLogs.push(`[delete stdout] ${deleteResult.stdout}`);
		consoleLogs.push(`[delete stderr] ${deleteResult.stderr}`);
		expect(deleteResult.code).toBe(0);
		const deleteData = parseJsonOutput(deleteResult.stdout, 'memories delete');
		expect(deleteData.success).toBe(true);
		logCheckpoint('Entry deleted.');

		// Verify deletion
		const listAfterDelete = await runCli(
			apiUrl,
			[
				'settings',
				'memories',
				'list',
				'--app-id',
				'code',
				'--item-type',
				'preferred_tech',
				'--json'
			],
			30_000
		);
		const memoriesAfterDelete = parseJsonOutput(listAfterDelete.stdout, 'memories list after delete');
		const deletedEntry = memoriesAfterDelete.find((m: any) => m.id === entryId);
		expect(deletedEntry).toBeUndefined();
		logCheckpoint('Deletion verified — entry no longer in list.');
		await takeScreenshot(page, 'memory-deleted');

		// -----------------------------------------------------------------------
		// Step 7: Schema validation — reject invalid input
		// -----------------------------------------------------------------------
		logCheckpoint('Step 7: Testing schema validation...');
		const invalidCreate = await runCli(apiUrl, [
			'settings',
			'memories',
			'create',
			'--app-id',
			'code',
			'--item-type',
			'preferred_tech',
			'--data',
			JSON.stringify({ proficiency: 'advanced' }), // missing required 'name'
			'--json'
		]);
		expect(invalidCreate.code).toBe(1);
		expect(invalidCreate.stderr).toMatch(/Missing required fields|name/);
		logCheckpoint('Schema validation correctly rejected missing required field.');

		const invalidEnum = await runCli(apiUrl, [
			'settings',
			'memories',
			'create',
			'--app-id',
			'code',
			'--item-type',
			'preferred_tech',
			'--data',
			JSON.stringify({ name: 'Rust', proficiency: 'guru' }), // invalid enum
			'--json'
		]);
		expect(invalidEnum.code).toBe(1);
		expect(invalidEnum.stderr).toMatch(/guru|enum|Invalid/);
		logCheckpoint('Schema validation correctly rejected invalid enum value.');

		// -----------------------------------------------------------------------
		// Cleanup
		// -----------------------------------------------------------------------
		logCheckpoint('Cleaning up — logging out...');
		await runCli(apiUrl, ['logout']);
	});
});


// ---------------------------------------------------------------------------
// Additional memory app coverage
// ---------------------------------------------------------------------------

test.describe('CLI Memories — Additional Apps', () => {
	test.setTimeout(300_000);

	test('travel/trips memory lifecycle: create → list (decrypted) → update → delete', async ({
		page
	}: {
		page: any;
	}) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const logCheckpoint = createSignupLogger('CLI_MEMORIES_TRAVEL');
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const apiUrl = deriveApiUrl(baseUrl);

		page.on('console', (msg: any) => consoleLogs.push(`[browser] ${msg.type()}: ${msg.text()}`));

		// Login
		logCheckpoint('Logging in...');
		await loginViaPair(page, apiUrl, logCheckpoint);

		// -----------------------------------------------------------------------
		// Create a travel/trips memory entry
		// -----------------------------------------------------------------------
		logCheckpoint('Creating travel/trips memory...');
		const createResult = await runCli(
			apiUrl,
			[
				'settings',
				'memories',
				'create',
				'--app-id',
				'travel',
				'--item-type',
				'trips',
				'--data',
				JSON.stringify({
					destination: 'Tokyo',
					start_date: '2026-04-01',
					end_date: '2026-04-14',
					notes: 'E2E test trip — please ignore'
				}),
				'--json'
			],
			30_000
		);
		consoleLogs.push(`[travel create] ${createResult.stdout}`);
		expect(createResult.code).toBe(0);
		const createData = parseJsonOutput(createResult.stdout, 'memories create');
		expect(createData.success).toBe(true);
		expect(typeof createData.id).toBe('string');
		const entryId = createData.id;
		logCheckpoint(`Created travel entry: ${entryId}`);

		// -----------------------------------------------------------------------
		// List + verify decryption
		// -----------------------------------------------------------------------
		logCheckpoint('Listing travel/trips memories...');
		const listResult = await runCli(
			apiUrl,
			['settings', 'memories', 'list', '--app-id', 'travel', '--item-type', 'trips', '--json'],
			30_000
		);
		expect(listResult.code).toBe(0);
		const memories = parseJsonOutput(listResult.stdout, 'memories list');
		expect(Array.isArray(memories)).toBe(true);

		const ourEntry = memories.find((m: any) => m.id === entryId);
		expect(ourEntry).toBeTruthy();
		// Verify decryption worked
		expect(ourEntry.data.destination).toBe('Tokyo');
		expect(ourEntry.data.start_date).toBe('2026-04-01');
		expect(ourEntry.data.end_date).toBe('2026-04-14');
		// Zero-knowledge: item_key_hash is a 32-char hex hash, NOT 'trips'
		expect(ourEntry.item_key_hash).toMatch(/^[0-9a-f]{32}$/);
		expect(ourEntry.item_key_hash).not.toBe('trips');
		logCheckpoint(`Decrypted OK. item_key_hash: ${ourEntry.item_key_hash}`);

		// -----------------------------------------------------------------------
		// Update the entry
		// -----------------------------------------------------------------------
		logCheckpoint('Updating travel entry...');
		const updateResult = await runCli(
			apiUrl,
			[
				'settings',
				'memories',
				'update',
				'--id',
				entryId,
				'--app-id',
				'travel',
				'--item-type',
				'trips',
				'--data',
				JSON.stringify({
					destination: 'Tokyo',
					start_date: '2026-05-01',
					end_date: '2026-05-14',
					notes: 'E2E test trip — updated'
				}),
				'--version',
				String(ourEntry.item_version),
				'--json'
			],
			30_000
		);
		expect(updateResult.code).toBe(0);
		const updateData = parseJsonOutput(updateResult.stdout, 'memories update');
		expect(updateData.success).toBe(true);

		// Verify update
		const listAfterUpdate = await runCli(
			apiUrl,
			['settings', 'memories', 'list', '--app-id', 'travel', '--item-type', 'trips', '--json'],
			30_000
		);
		const updatedMemories = parseJsonOutput(listAfterUpdate.stdout, 'memories list after update');
		const updatedEntry = updatedMemories.find((m: any) => m.id === entryId);
		expect(updatedEntry).toBeTruthy();
		expect(updatedEntry.data.start_date).toBe('2026-05-01');
		logCheckpoint('Update verified.');

		// -----------------------------------------------------------------------
		// Delete and verify gone
		// -----------------------------------------------------------------------
		logCheckpoint('Deleting travel entry...');
		const deleteResult = await runCli(
			apiUrl,
			['settings', 'memories', 'delete', '--id', entryId, '--json'],
			30_000
		);
		expect(deleteResult.code).toBe(0);
		const deleteData = parseJsonOutput(deleteResult.stdout, 'memories delete');
		expect(deleteData.success).toBe(true);

		const listAfterDelete = await runCli(
			apiUrl,
			['settings', 'memories', 'list', '--app-id', 'travel', '--item-type', 'trips', '--json'],
			30_000
		);
		const memoriesAfterDelete = parseJsonOutput(listAfterDelete.stdout, 'memories list after delete');
		const deletedEntry = memoriesAfterDelete.find((m: any) => m.id === entryId);
		expect(deletedEntry).toBeUndefined();
		logCheckpoint('Deletion verified — entry no longer in list.');

		await runCli(apiUrl, ['logout']);
	});

	test('ai/communication_style memory lifecycle: create → list (decrypted) → update → delete', async ({
		page
	}: {
		page: any;
	}) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const logCheckpoint = createSignupLogger('CLI_MEMORIES_AI');
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const apiUrl = deriveApiUrl(baseUrl);

		page.on('console', (msg: any) => consoleLogs.push(`[browser] ${msg.type()}: ${msg.text()}`));

		// Login
		logCheckpoint('Logging in...');
		await loginViaPair(page, apiUrl, logCheckpoint);

		// -----------------------------------------------------------------------
		// List memory types for ai app (JSON output test)
		// -----------------------------------------------------------------------
		logCheckpoint('Listing ai memory types with --json...');
		const typesResult = await runCli(apiUrl, [
			'settings',
			'memories',
			'types',
			'--app-id',
			'ai',
			'--json'
		]);
		expect(typesResult.code).toBe(0);

		// --json must produce valid parseable JSON
		let types: any[];
		try {
			types = parseJsonOutput(typesResult.stdout, 'memory types list');
		} catch (_e) {
			throw new Error(
				`Expected JSON from memories types --json, got:\n${typesResult.stdout}\nstderr:\n${typesResult.stderr}`
			);
		}
		expect(Array.isArray(types)).toBe(true);
		const commStyleType = types.find((t: any) => t.item_type === 'communication_style');
		expect(commStyleType).toBeTruthy();
		expect(commStyleType.required).toContain('title');
		expect(commStyleType.required).toContain('tone');
		expect(commStyleType.required).toContain('verbosity');
		logCheckpoint(`Found ${types.length} ai memory types. communication_style validated.`);

		// -----------------------------------------------------------------------
		// Create an ai/communication_style memory entry
		// -----------------------------------------------------------------------
		logCheckpoint('Creating ai/communication_style memory...');
		const createResult = await runCli(
			apiUrl,
			[
				'settings',
				'memories',
				'create',
				'--app-id',
				'ai',
				'--item-type',
				'communication_style',
				'--data',
				JSON.stringify({
					title: 'E2E Test Style',
					tone: 'professional',
					verbosity: 'concise'
				}),
				'--json'
			],
			30_000
		);
		consoleLogs.push(`[ai create] ${createResult.stdout}`);
		consoleLogs.push(`[ai create stderr] ${createResult.stderr}`);
		expect(createResult.code).toBe(0);
		const createData = parseJsonOutput(createResult.stdout, 'memories create');
		expect(createData.success).toBe(true);
		expect(typeof createData.id).toBe('string');
		const entryId = createData.id;
		logCheckpoint(`Created ai entry: ${entryId}`);

		// -----------------------------------------------------------------------
		// List + verify decryption
		// -----------------------------------------------------------------------
		logCheckpoint('Listing ai/communication_style memories...');
		const listResult = await runCli(
			apiUrl,
			[
				'settings',
				'memories',
				'list',
				'--app-id',
				'ai',
				'--item-type',
				'communication_style',
				'--json'
			],
			30_000
		);
		expect(listResult.code).toBe(0);
		const memories = parseJsonOutput(listResult.stdout, 'memories list');
		expect(Array.isArray(memories)).toBe(true);

		const ourEntry = memories.find((m: any) => m.id === entryId);
		expect(ourEntry).toBeTruthy();
		// Verify decryption
		expect(ourEntry.data.title).toBe('E2E Test Style');
		expect(ourEntry.data.tone).toBe('professional');
		expect(ourEntry.data.verbosity).toBe('concise');
		// Zero-knowledge: item_key_hash is a 32-char hex hash
		expect(ourEntry.item_key_hash).toMatch(/^[0-9a-f]{32}$/);
		expect(ourEntry.item_key_hash).not.toBe('communication_style');
		logCheckpoint(`Decrypted OK. tone=${ourEntry.data.tone}, verbosity=${ourEntry.data.verbosity}`);

		// -----------------------------------------------------------------------
		// Update the entry
		// -----------------------------------------------------------------------
		logCheckpoint('Updating ai entry...');
		const updateResult = await runCli(
			apiUrl,
			[
				'settings',
				'memories',
				'update',
				'--id',
				entryId,
				'--app-id',
				'ai',
				'--item-type',
				'communication_style',
				'--data',
				JSON.stringify({
					title: 'E2E Test Style Updated',
					tone: 'casual',
					verbosity: 'detailed'
				}),
				'--version',
				String(ourEntry.item_version),
				'--json'
			],
			30_000
		);
		expect(updateResult.code).toBe(0);
		const updateData = parseJsonOutput(updateResult.stdout, 'memories update');
		expect(updateData.success).toBe(true);

		// Verify update
		const listAfterUpdate = await runCli(
			apiUrl,
			[
				'settings',
				'memories',
				'list',
				'--app-id',
				'ai',
				'--item-type',
				'communication_style',
				'--json'
			],
			30_000
		);
		const updatedMemories = parseJsonOutput(listAfterUpdate.stdout, 'memories list after update');
		const updatedEntry = updatedMemories.find((m: any) => m.id === entryId);
		expect(updatedEntry).toBeTruthy();
		expect(updatedEntry.data.tone).toBe('casual');
		expect(updatedEntry.data.verbosity).toBe('detailed');
		logCheckpoint('Update verified.');

		// -----------------------------------------------------------------------
		// Delete and verify gone
		// -----------------------------------------------------------------------
		logCheckpoint('Deleting ai entry...');
		const deleteResult = await runCli(
			apiUrl,
			['settings', 'memories', 'delete', '--id', entryId, '--json'],
			30_000
		);
		expect(deleteResult.code).toBe(0);
		const deleteData = parseJsonOutput(deleteResult.stdout, 'memories delete');
		expect(deleteData.success).toBe(true);
		logCheckpoint('Entry deleted.');

		// Verify gone
		const listAfterDelete = await runCli(
			apiUrl,
			[
				'settings',
				'memories',
				'list',
				'--app-id',
				'ai',
				'--item-type',
				'communication_style',
				'--json'
			],
			30_000
		);
		const memoriesAfterDelete = parseJsonOutput(listAfterDelete.stdout, 'memories list after delete');
		const deletedEntry = memoriesAfterDelete.find((m: any) => m.id === entryId);
		expect(deletedEntry).toBeUndefined();
		logCheckpoint('Deletion verified — entry gone from list.');

		await runCli(apiUrl, ['logout']);
	});
});
