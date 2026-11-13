/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * CLI differential harness: the npm CLI against the native Rust binary.
 *
 * Runs the SAME argument vector with both CLIs against the same account on the
 * isolated CI backend and compares three things per command:
 *   1. exit code;
 *   2. stdout (JSON by default, with volatile ids/timestamps/paths normalized;
 *      or normalized text / exit-only modes);
 *   3. stderr class (see `classifyStderr`, never the raw wording).
 *
 * Usage in a cli-native-<group>.spec.ts:
 *
 *   const { setupDifferential, finishDifferential } = require('./helpers/cli-native-differential');
 *   test('group', async ({ page }, testInfo) => {
 *     const diff = await setupDifferential(page, testInfo, 'group');   // builds binary, pair-logs both CLIs in
 *     try {
 *       await diff.check('account info', ['account', 'info']);         // read-only parity check
 *       await diff.check('timezone', ['account', 'timezone', 'set', 'Europe/Berlin'],
 *         { catalog: ['account timezone set'] });                       // mutating: caller restores state
 *     } finally { await finishDifferential(diff); }                     // attaches report, disposes, asserts
 *   });
 *
 * `check(label, args, options)` options:
 *   - catalog: catalog command path(s) this check proves ("account info"); they
 *     are written to the report so the catalog update can be derived from it.
 *   - mode: 'json' (default; appends --json), 'text' (normalized text), 'exit' (exit + stderr class only).
 *   - structureOnly: compare JSON shape (keys and value types) instead of values,
 *     for live data that legitimately changes between the two sequential runs.
 *   - ignoreKeys: JSON keys removed at every depth before comparing.
 *   - expectedGap: documented known difference; the check then passes only while
 *     the diff still contains this substring, and fails once the gap disappears.
 *   - The returned record carries a non-enumerable `raw` ({npm, native} RunResult) so a
 *     create check can read each CLI's own fixture id; it never enters the report.
 *   - nativeArgs: argument vector for the native run when each CLI must act on its own
 *     fixture (e.g. delete the entry it created); ids are normalized before comparing.
 *   - between: async hook run after the npm run and before the native run, to restore
 *     state a mutating command changed (e.g. disable learning mode again).
 *   - before(side): restores the precondition before EACH CLI run (e.g. reset an
 *     appended section), so a mutating command starts from the same state twice.
 *   - argsFor(side): per-CLI argument vector, evaluated after before(side), for state
 *     transitions that cannot be reset (start/complete/delete): each CLI acts on its
 *     own identical fixture created by before(side).
 *
 * `setupDifferential(page, testInfo, group, { paceMs })` waits that long before every check, for groups
 * whose npm commands hit per-minute rate limits.
 *
 * Adding a group: create a new cli-native-<group>.spec.ts, call setupDifferential
 * once per test (it logs both CLIs in with isolated HOME/state dirs through browser
 * pair login), list the group's commands, restore any state a mutating check changed,
 * and always end with finishDifferential. Read-only checks first; mutating checks must
 * create throwaway data and undo it. Never touch payment commands.
 *
 * The report is attached as `cli-native-differential-<group>.json` and every result is
 * printed as `DIFFERENTIAL_RESULT <pass|gap|fail> <label>` for CI log scraping.
 *
 * The native binary comes from OPENMATES_RUST_CLI_BIN or a locked release build
 * (rust-cli-terminal.ts). No secrets are ever printed: output is normalized and
 * the harness only echoes normalized stdout/diffs.
 */
export {};
import type { TestInfo } from '@playwright/test';

const { expect } = require('@playwright/test');
const fs = require('node:fs');
const os = require('node:os');
const { deriveApiUrl, runCli } = require('./cli-test-helpers');
const {
	createWorkflowCliHome,
	loginWorkflowCliViaPair,
	removeWorkflowCliHome,
	workflowCliEnv
} = require('./workflow-cli-e2e-helpers');
const { buildRustCli, createRustHome, recordRust, runRust, rustEnv } = require('./rust-cli-terminal');

type RunResult = { code: number | null; stdout: string; stderr: string };
type Mode = 'json' | 'text' | 'exit';
type Side = 'npm' | 'native';

interface CheckOptions {
	before?: (side: Side) => Promise<void>;
	argsFor?: (side: Side) => string[];
	catalog?: string[];
	mode?: Mode;
	structureOnly?: boolean;
	ignoreKeys?: string[];
	expectedGap?: string;
	timeoutMs?: number;
	nativeArgs?: string[];
	between?: () => Promise<void>;
}

interface Outcome {
	exit: number | null;
	stdout: unknown;
	stderrClass: string;
	stderrExcerpt: string;
}

interface CheckRecord {
	label: string;
	args: string[];
	catalog: string[];
	verdict: 'pass' | 'gap' | 'fail';
	diffs: string[];
	npm: Outcome;
	native: Outcome;
	/** Raw results (non-enumerable, never serialized into the report). */
	raw?: { npm: RunResult; native: RunResult };
}

interface Differential {
	apiUrl: string;
	binary: string;
	groupName: string;
	records: CheckRecord[];
	testInfo: TestInfo;
	npmHome: string;
	nativeHome: string;
	npm(args: string[], timeoutMs?: number): Promise<RunResult>;
	native(args: string[], timeoutMs?: number): Promise<RunResult>;
	check(label: string, args: string[], options?: CheckOptions): Promise<CheckRecord>;
}

const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;
/** History change-set (`chg_`) and entry (`che_`) ids differ per run, also inside printed undo commands. */
const HISTORY_ID_RE = /\b(chg|che)_[0-9a-f]{32}\b/g;
const ISO_TS_RE = /\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?/g;
const VOLATILE_KEY_RE = /(^|_)(at|time|timestamp|date|expires|expiry|created|updated|ts)$|^(created|updated|last)[A-Z_]|At$|Timestamp$/;
// eslint-disable-next-line no-control-regex -- matching terminal escape sequences requires control characters
const ANSI_RE = /\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))/g;

/**
 * The native CLI prints one informational `Task delivery: <64-hex>` line on captured (non-terminal)
 * stderr for durable Task writes so a recoverable operation id survives a runtime deadline
 * (task_queue.rs). npm has no such journal; the line is additive and never part of the error class.
 */
function stripTaskDeliveryNote(stderr: string): string {
	return stderr.replace(/^Task delivery: [0-9a-f]{64}\r?\n?/gm, '');
}

/** Coarse stderr categories so wording differences do not mask or fake a mismatch. */
function classifyStderr(stderr: string): string {
	const text = stripTaskDeliveryNote(stderr).replace(ANSI_RE, '').trim();
	if (!text) return 'none';
	const rules: Array<[RegExp, string]> = [
		[/authentication_required|not logged in|log in first|openmates login/i, 'auth-required'],
		[/--yes|confirm/i, 'confirmation-required'],
		[/web-only|browser/i, 'web-only'],
		[/unknown (command|option|flag)|unrecognized|usage:|required argument|missing (argument|value)/i, 'usage'],
		[/HTTP 401|HTTP 403|unauthori[sz]ed|forbidden/i, 'http-auth'],
		[/HTTP 404|not found/i, 'http-not-found'],
		[/HTTP 4\d\d/i, 'http-client-error'],
		[/HTTP 5\d\d|timed out|ECONN/i, 'http-server-error'],
		[/invalid|must be|expected|cannot be/i, 'validation']
	];
	for (const [pattern, name] of rules) if (pattern.test(text)) return name;
	return 'other';
}

function normalizeString(value: string, homes: string[]): string {
	let out = value.replace(ANSI_RE, '');
	for (const home of homes) if (home) out = out.split(home).join('<home>');
	return out
		.replace(UUID_RE, '<uuid>')
		.replace(HISTORY_ID_RE, '<$1_id>')
		.replace(ISO_TS_RE, '<ts>')
		.replace(os.tmpdir(), '<tmp>')
		.replace(/[ \t]+$/gm, '')
		.replace(/\r/g, '');
}

function normalizeJson(value: any, ctx: { homes: string[]; ignoreKeys: Set<string>; structureOnly: boolean }, key = ''): any {
	if (Array.isArray(value)) return value.map((entry) => normalizeJson(entry, ctx, key));
	if (value && typeof value === 'object') {
		const out: Record<string, any> = {};
		for (const k of Object.keys(value).sort()) {
			if (ctx.ignoreKeys.has(k)) continue;
			out[k] = normalizeJson(value[k], ctx, k);
		}
		return out;
	}
	if (ctx.structureOnly) return value === null ? 'null' : typeof value;
	if (typeof value === 'number' && VOLATILE_KEY_RE.test(key)) return '<time>';
	if (typeof value === 'string') return normalizeString(value, ctx.homes);
	return value;
}

function deepDiff(a: any, b: any, path: string, out: string[]): void {
	if (out.length >= 25) return;
	if (JSON.stringify(a) === JSON.stringify(b)) return;
	const objA = a && typeof a === 'object';
	const objB = b && typeof b === 'object';
	if (!objA || !objB || Array.isArray(a) !== Array.isArray(b)) {
		out.push(`${path}: npm=${JSON.stringify(a)?.slice(0, 160)} native=${JSON.stringify(b)?.slice(0, 160)}`);
		return;
	}
	if (Array.isArray(a)) {
		if (a.length !== b.length) out.push(`${path}: array length npm=${a.length} native=${b.length}`);
		for (let i = 0; i < Math.min(a.length, b.length); i += 1) deepDiff(a[i], b[i], `${path}[${i}]`, out);
		return;
	}
	for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
		if (!(k in a)) out.push(`${path}.${k}: only in native`);
		else if (!(k in b)) out.push(`${path}.${k}: only in npm`);
		else deepDiff(a[k], b[k], `${path}.${k}`, out);
	}
}

function toOutcome(result: RunResult, mode: Mode, homes: string[], options: CheckOptions): Outcome {
	const base = {
		exit: result.code,
		stderrClass: classifyStderr(result.stderr),
		stderrExcerpt: normalizeString(stripTaskDeliveryNote(result.stderr), homes).trim().slice(0, 200)
	};
	if (mode === 'exit') return { ...base, stdout: null };
	if (mode === 'text') return { ...base, stdout: normalizeString(result.stdout, homes).split('\n').map((line) => line.trimEnd()).join('\n').trim() };
	const text = result.stdout.trim();
	if (!text) return { ...base, stdout: null };
	try {
		const ctx = { homes, ignoreKeys: new Set(options.ignoreKeys ?? []), structureOnly: Boolean(options.structureOnly) };
		return { ...base, stdout: normalizeJson(JSON.parse(text), ctx) };
	} catch {
		return { ...base, stdout: { '<non-json-stdout>': normalizeString(text, homes).slice(0, 400) } };
	}
}

/** Build the binary, create isolated homes and pair-log BOTH CLIs into the page's account. */
async function setupDifferential(page: any, testInfo: TestInfo, groupName: string, setup: { paceMs?: number } = {}): Promise<Differential> {
	testInfo.setTimeout(2_700_000);
	const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
	const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(baseUrl);
	const binary = buildRustCli(testInfo);
	const npmHome = createWorkflowCliHome(`diff-npm-${groupName}`);
	const nativeHome = createRustHome(`diff-${groupName}`);
	const nativeEnv = rustEnv(nativeHome, apiUrl, baseUrl);
	const npmEnv = workflowCliEnv(apiUrl, npmHome);

	await loginWorkflowCliViaPair(page, apiUrl, npmHome, `diff-npm-${groupName}`);

	const login = recordRust(binary, ['login'], nativeEnv, testInfo, `diff-login-${groupName}`, { timeoutSeconds: 180 });
	try {
		const token = (await login.waitForOutput(/#pair=([A-Za-z0-9]+)/, 30_000))[1];
		await page.goto(`${baseUrl}/#pair=${token}`);
		const allow = page.getByTestId('pair-allow-button');
		await expect(allow).toBeVisible({ timeout: 15_000 });
		await allow.click();
		const pinDisplay = page.getByTestId('pair-pin-display');
		await expect(pinDisplay).toBeVisible({ timeout: 15_000 });
		const pin = ((await pinDisplay.textContent()) || '').replace(/\s/g, '');
		expect(pin).toMatch(/^[A-Z0-9]{6}$/);
		await login.waitForOutput(/Pairing PIN from the browser:/, 30_000);
		login.typeText(pin);
		login.key('Return');
		const done = await login.waitForExit(90_000);
		expect(done.code, done.output).toBe(0);
	} finally {
		await login.dispose();
	}

	const homes = [npmHome, nativeHome];
	const records: CheckRecord[] = [];
	const runNpm = (args: string[], timeoutMs = 60_000): Promise<RunResult> =>
		runCli(apiUrl, args, timeoutMs, { useApiKey: false, record: false, env: npmEnv });
	const runNative = (args: string[], timeoutMs = 60_000): Promise<RunResult> => runRust(binary, nativeEnv, args, timeoutMs);

	const diff: Differential = {
		apiUrl, binary, groupName, records, testInfo, npmHome, nativeHome,
		npm: runNpm,
		native: runNative,
		async check(label, args, options = {}) {
			const mode: Mode = options.mode ?? 'json';
			const withJson = (argv: string[]) => (mode === 'json' && !argv.includes('--json') ? [...argv, '--json'] : argv);
			const timeout = options.timeoutMs ?? 60_000;
			// Backend endpoints are rate limited per minute (e.g. 60/minute for Plan lists, which npm queries per command).
			if (setup.paceMs) await new Promise((resolve) => setTimeout(resolve, setup.paceMs));
			if (options.before) await options.before('npm');
			const fullArgs = withJson(options.argsFor ? options.argsFor('npm') : args);
			const npmResult = await runNpm(fullArgs, timeout);
			if (options.between) await options.between();
			if (options.before) await options.before('native');
			const nativeArgv = options.argsFor ? options.argsFor('native') : (options.nativeArgs ?? args);
			const nativeResult = await runNative(withJson(nativeArgv), timeout);
			const npmOutcome = toOutcome(npmResult, mode, homes, options);
			const nativeOutcome = toOutcome(nativeResult, mode, homes, options);
			const diffs: string[] = [];
			if (npmOutcome.exit !== nativeOutcome.exit) diffs.push(`exit: npm=${npmOutcome.exit} native=${nativeOutcome.exit}`);
			if (npmOutcome.stderrClass !== nativeOutcome.stderrClass) {
				diffs.push(
					`stderr class: npm=${npmOutcome.stderrClass} native=${nativeOutcome.stderrClass} (npm stderr: ${JSON.stringify(npmOutcome.stderrExcerpt)}; native stderr: ${JSON.stringify(nativeOutcome.stderrExcerpt)})`
				);
			}
			deepDiff(npmOutcome.stdout, nativeOutcome.stdout, '$', diffs);
			let verdict: CheckRecord['verdict'] = diffs.length === 0 ? 'pass' : 'fail';
			if (options.expectedGap) {
				const matched = diffs.some((line) => line.includes(options.expectedGap as string));
				verdict = matched ? 'gap' : 'fail';
				if (!matched) diffs.push(`expected gap "${options.expectedGap}" no longer present: remove expectedGap and update the catalog`);
			}
			const record: CheckRecord = { label, args: fullArgs, catalog: options.catalog ?? [], verdict, diffs, npm: npmOutcome, native: nativeOutcome };
			Object.defineProperty(record, 'raw', { value: { npm: npmResult, native: nativeResult }, enumerable: false });
			records.push(record);
			console.log(`DIFFERENTIAL_RESULT ${verdict} ${label}${diffs.length ? ` :: ${diffs.slice(0, 4).join(' | ')}` : ''}`);
			return record;
		}
	};
	return diff;
}

/** Attach the report, remove isolated homes and assert that no check failed. */
async function finishDifferential(diff: Differential): Promise<void> {
	const reportPath = diff.testInfo.outputPath(`cli-native-differential-${diff.groupName}.json`);
	fs.writeFileSync(reportPath, JSON.stringify({ group: diff.groupName, records: diff.records }, null, 2));
	await diff.testInfo.attach(`cli-native-differential-${diff.groupName}`, { path: reportPath, contentType: 'application/json' });
	removeWorkflowCliHome(diff.npmHome);
	if (diff.nativeHome.startsWith(os.tmpdir())) fs.rmSync(diff.nativeHome, { recursive: true, force: true });
	const failed = diff.records.filter((record) => record.verdict === 'fail');
	expect(
		failed.map((record) => `${record.label}: ${record.diffs.slice(0, 6).join(' | ')}`),
		'npm and native CLI must agree on exit code, normalized stdout and stderr class'
	).toEqual([]);
}

module.exports = { classifyStderr, finishDifferential, normalizeJson, setupDifferential };
