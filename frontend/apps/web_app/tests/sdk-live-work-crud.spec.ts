/* eslint-disable @typescript-eslint/no-require-imports */
// proof-video: not_required reason=visual_smoke_not_needed (headless SDK library processes; no browser UI)
/**
 * Live-backend cross-language SDK harness: the public Rust (`openmates::sdk`),
 * npm (`openmates/sdk`) and Python (`openmates`) libraries, API-key auth only,
 * against the real disposable isolated CI backend and a fresh account. No
 * mocks or synthetic peers: one language writes client-encrypted Projects,
 * Tasks and Plans, the other two decrypt and list them, a second language
 * updates and a third deletes, and every language confirms each step. Workspace
 * history and SDK docs reads are compared across all three. Each test attaches
 * a per-capability/per-language report (`sdk-live-work-report.json`).
 *
 * Drivers: packages/openmates-rust/examples/sdk-live-work-conformance.rs (built
 * in this job with cargo --locked), tests/sdk-conformance/runners/sdk-live-work.mjs
 * (built npm dist) and tests/sdk-conformance/runners/sdk-live-work.py (editable
 * pip install). Each driver reads a JSON batch on stdin and never reads CLI state.
 */
export {};
import type { TestInfo } from '@playwright/test';

const { test, expect } = require('./console-monitor');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');

const ROOT = path.resolve(__dirname, '../../../..');
const TOOLCHAIN = '1.98.1';
const RUST_EXAMPLE = 'sdk-live-work-conformance';
const LANGS = ['rust', 'npm', 'python'] as const;
type Lang = (typeof LANGS)[number];
type Family = 'projects' | 'tasks' | 'plans';
type Op = { family: string; op: string; id?: string; input?: Record<string, unknown> };
type Result = { ok: boolean; value?: any; error?: string; detail?: string };
const ACCESS: Record<Lang, string> = { rust: 'rust', npm: 'npm', python: 'pip' };
const DEVICE: Record<Lang, string> = {
	rust: 'sdk-live-work-e2e-rust',
	npm: 'sdk-live-work-e2e-npm',
	python: 'sdk-live-work-e2e-pip'
};
const HISTORY_TYPE: Record<Family, string> = { projects: 'project', tasks: 'task', plans: 'plan' };
const FAMILIES: Family[] = ['projects', 'tasks', 'plans'];
const CAPABILITY: Record<Family, string> = { projects: 'sdk.projects', tasks: 'sdk.tasks', plans: 'sdk.plans' };

const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
const apiKey = process.env.OPENMATES_TEST_ACCOUNT_API_KEY;
let rustBinary = '';

function spawnChecked(command: string, args: string[], options: Record<string, unknown>, label: string) {
	const result = spawnSync(command, args, { cwd: ROOT, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, ...options });
	const stderr = String(result.stderr || '');
	const errors = stderr.split('\n\n').filter((block: string) => /^error(\[|:)/m.test(block)).join('\n\n');
	expect(result.status, `${label} exited ${result.status ?? result.signal}\n${(errors || stderr).slice(-4000)}`).toBe(0);
	return result;
}

/** Compile the exact checked-out Rust SDK driver; never part of flow timings. */
function buildRustDriver(testInfo: TestInfo): string {
	const started = Date.now();
	const env = { ...process.env, CARGO_INCREMENTAL: '0', CARGO_TERM_COLOR: 'never' };
	spawnChecked('rustup', ['toolchain', 'install', TOOLCHAIN, '--profile', 'minimal'], { env, timeout: 300_000 }, 'rustup');
	const targetDir = path.join(ROOT, 'target');
	spawnChecked('cargo', [`+${TOOLCHAIN}`, 'build', '--locked', '-p', 'openmates-sdk', '--example', RUST_EXAMPLE, '--target-dir', targetDir],
		{ env, timeout: 2_400_000 }, 'cargo build Rust SDK live driver');
	testInfo.annotations.push({ type: 'rust-sdk-build', description: `cargo build ${Math.round((Date.now() - started) / 1000)}s` });
	const binary = path.join(targetDir, 'debug', 'examples', RUST_EXAMPLE);
	expect(fs.existsSync(binary), 'Rust driver binary missing after build').toBe(true);
	return binary;
}

function installPythonSdk(): void {
	spawnChecked('python3', ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '-e',
		path.join(ROOT, 'packages/openmates-python')], { env: process.env, timeout: 300_000 }, 'pip SDK install');
}

/** Run one ordered operation batch through one language's public SDK. */
function drive(lang: Lang, operations: Op[]): Result[] {
	const [command, args] = lang === 'rust'
		? [rustBinary, []]
		: lang === 'npm'
			? ['node', [path.join(ROOT, 'tests/sdk-conformance/runners/sdk-live-work.mjs')]]
			: ['python3', [path.join(ROOT, 'tests/sdk-conformance/runners/sdk-live-work.py')]];
	const result = spawnChecked(command as string, args as string[], {
		input: JSON.stringify({ operations }),
		timeout: 240_000,
		env: {
			...process.env,
			OPENMATES_API_KEY: apiKey,
			OPENMATES_API_URL: apiUrl,
			OPENMATES_DEVICE_ID: DEVICE[lang],
			PYTHONPATH: path.join(ROOT, 'packages/openmates-python')
		}
	}, `${lang} SDK driver`);
	const parsed = JSON.parse(String(result.stdout).trim());
	expect(Array.isArray(parsed) && parsed.length === operations.length, `${lang} driver result count`).toBe(true);
	return parsed;
}

/** Approve exactly the fixture key's registration for this SDK device. */
function approveFixtureDevice(accessType: string, deviceId: string): void {
	const program = `import { OpenMatesClient } from './frontend/packages/openmates-cli/dist/cli-internal-client.js';
		const client = new OpenMatesClient({ apiUrl: process.env.OPENMATES_API_URL });
		if (!client.hasSession()) throw new Error('Fresh owner session is missing');
		const keys = await client.listApiKeys();
		const fixture = (keys.api_keys || []).filter(key => key.name === 'Disposable CI fixture');
		if (fixture.length !== 1) throw new Error('Fresh fixture API key is not unique');
		const current = await client.settingsGet('api-key-devices');
		const matches = (current.devices || []).filter(device =>
			device.api_key_id === fixture[0].id &&
			device.access_type === process.env.OPENMATES_DEVICE_ACCESS &&
			device.machine_identifier === process.env.OPENMATES_DEVICE_IDENTITY);
		if (matches.length !== 1) throw new Error('Fixture device registration is not unique');
		if (!matches[0].approved_at) await client.settingsPost('api-key-devices/' + matches[0].id + '/approve', {});
		const verified = await client.settingsGet('api-key-devices');
		if (!(verified.devices || []).some(device => device.id === matches[0].id && device.approved_at))
			throw new Error('Fixture device approval failed');
		console.log(JSON.stringify({ approved: true }));`;
	const result = spawnChecked('node', ['--input-type=module', '-e', program], {
		timeout: 60_000,
		env: { ...process.env, OPENMATES_API_URL: apiUrl, OPENMATES_DEVICE_ACCESS: accessType, OPENMATES_DEVICE_IDENTITY: deviceId }
	}, `${accessType} fixture device approval`);
	expect(JSON.parse(String(result.stdout).trim()).approved).toBe(true);
}

const sortedStrings = (value: unknown) => (Array.isArray(value) ? value.map(String).sort() : []);
/** First present field: Rust/Python return wire (snake_case) names, npm its public camelCase names. */
const pick = (r: any, snake: string, camel: string) => r?.[snake] ?? r?.[camel];
/** Decrypted, language-neutral view of each record. */
const SUMMARY: Record<Family, (r: any) => Record<string, unknown>> = {
	projects: (r) => ({ id: pick(r, 'project_id', 'projectId'), name: r?.name, description: r?.description }),
	tasks: (r) => ({ id: pick(r, 'task_id', 'taskId'), title: r?.title, description: r?.description, labels: sortedStrings(r?.labels), linked_project_ids: sortedStrings(pick(r, 'linked_project_ids', 'linkedProjectIds')) }),
	plans: (r) => ({ id: pick(r, 'plan_id', 'planId'), title: r?.title, goal: r?.goal, linked_project_ids: sortedStrings(pick(r, 'linked_project_ids', 'linkedProjectIds')) })
};
/** Failure text: stable class plus the driver's non-secret detail, when given. */
const why = (r: Result) => (r.ok ? '' : `${r.error}${r.detail ? ` (${r.detail})` : ''}`);
const expected = (family: Family, id: string, input: Record<string, unknown>) => {
	if (family === 'projects') return { id, name: input.name, description: input.description };
	if (family === 'tasks') return { id, title: input.title, description: input.description, labels: sortedStrings(input.labels), linked_project_ids: sortedStrings(input.linked_project_ids) };
	return { id, title: input.title, goal: input.goal, linked_project_ids: sortedStrings(input.linked_project_ids) };
};

/** Collects per-capability, per-language outcomes and every mismatch. */
class Report {
	results: Record<string, Record<string, Record<string, string>>> = {};
	failures: string[] = [];
	check(capability: string, lang: string, step: string, ok: boolean, detail = ''): boolean {
		const entry = ((this.results[capability] ??= {})[lang] ??= {});
		entry[step] = ok ? 'pass' : `fail${detail ? `: ${detail}` : ''}`;
		if (!ok) this.failures.push(`${capability} ${lang} ${step}${detail ? `: ${detail}` : ''}`);
		return ok;
	}
	note(capability: string, lang: string, step: string, value: string): void {
		((this.results[capability] ??= {})[lang] ??= {})[step] = value;
	}
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

function readBatch(ids: Record<Family, string>, withHistory: boolean): Op[] {
	const ops: Op[] = [];
	for (const family of FAMILIES) ops.push({ family, op: 'show', id: ids[family] });
	for (const family of FAMILIES) ops.push({ family, op: 'list' });
	if (withHistory) {
		for (const family of FAMILIES) ops.push({ family: 'history', op: 'list', input: { object_type: HISTORY_TYPE[family], object_id: ids[family], limit: 50 } });
	}
	return ops;
}

/**
 * Every language must decrypt the same records through show and list.
 * Workspace history is compared as a live outcome: all three languages must
 * return the same change-set ids, or the same refusal class. The backend
 * currently refuses API keys on /v1/workspace/history (403
 * developer_api_access_not_classified); that refusal is recorded as a
 * capability gap, never as history support.
 */
function verifyReads(report: Report, step: string, ids: Record<Family, string>, want: Record<Family, Record<string, unknown>>, withHistory: boolean) {
	const history: Partial<Record<Family, Record<string, unknown>>> = {};
	for (const lang of LANGS) {
		const results = drive(lang, readBatch(ids, withHistory));
		FAMILIES.forEach((family, index) => {
			const shown = results[index];
			const got = shown.ok ? SUMMARY[family](shown.value) : why(shown);
			report.check(CAPABILITY[family], lang, `${step}.show`, shown.ok && same(got, want[family]), same(got, want[family]) ? '' : JSON.stringify(got));
			const listed = results[3 + index];
			const row = listed.ok && Array.isArray(listed.value) ? listed.value.find((r: any) => SUMMARY[family](r).id === ids[family]) : undefined;
			const rowSummary = row ? SUMMARY[family](row) : listed.ok ? 'absent' : why(listed);
			report.check(CAPABILITY[family], lang, `${step}.list`, Boolean(row) && same(rowSummary, want[family]), row && same(rowSummary, want[family]) ? '' : JSON.stringify(rowSummary));
			if (withHistory) {
				const entry = results[6 + index];
				const outcome = entry.ok && Array.isArray(entry.value)
					? { ok: true, change_sets: entry.value.map((c: any) => String(c.change_set_id ?? c.id)).sort() }
					: { ok: false, error: entry.error };
				(history[family] ??= {})[lang] = outcome;
				report.note('sdk.history', lang, `${family}.${step}.list`, entry.ok ? `ok:${(outcome as any).change_sets.length}` : `refused:${why(entry)}`);
			}
		});
	}
	if (withHistory) {
		for (const family of FAMILIES) {
			const byLang = history[family] ?? {};
			report.check('sdk.history', 'all', `${family}.${step}.same-outcome`, same(byLang.rust, byLang.npm) && same(byLang.npm, byLang.python), JSON.stringify(byLang));
		}
	}
}

/** One writer creates, the next language updates, the third deletes. */
async function crossLanguageLifecycle(writer: Lang, testInfo: TestInfo) {
	const report = new Report();
	const updater = LANGS[(LANGS.indexOf(writer) + 1) % 3];
	const deleter = LANGS[(LANGS.indexOf(writer) + 2) % 3];
	const nonce = `${writer}-${Date.now().toString(36)}`;
	// npm and Python always create with write_mode "always_ask" (ignoring any
	// input); the Rust SDK requires an explicit mode, so every language is sent
	// the same explicit value. The Rust-only requirement is a recorded gap.
	const projectInput = { name: `Live ${writer} project ${nonce}`, description: `Written by the ${writer} SDK (${nonce}).`, write_mode: 'always_ask' };
	const ids = {} as Record<Family, string>;
	const inputs = {} as Record<Family, Record<string, unknown>>;
	// Steps run in an inner function so an early stop still reaches the report
	// attachment and the final failures assertion below.
	const steps = () => {
		const [project] = drive(writer, [{ family: 'projects', op: 'create', input: projectInput }]);
		ids.projects = project.ok ? String(SUMMARY.projects(project.value).id ?? '') : '';
		inputs.projects = projectInput;
		if (!report.check('sdk.projects', writer, 'create', project.ok && same(SUMMARY.projects(project.value), expected('projects', ids.projects, projectInput)), project.ok ? JSON.stringify(SUMMARY.projects(project.value)) : why(project))) return;
		inputs.tasks = { title: `Live ${writer} task ${nonce}`, description: `Task written by ${writer}.`, labels: ['live', `w-${writer}`], linked_project_ids: [ids.projects] };
		inputs.plans = { title: `Live ${writer} plan ${nonce}`, goal: `Plan goal written by ${writer}.`, linked_project_ids: [ids.projects] };
		const [task, plan] = drive(writer, [
			{ family: 'tasks', op: 'create', input: inputs.tasks },
			{ family: 'plans', op: 'create', input: inputs.plans }
		]);
		ids.tasks = task.ok ? String(SUMMARY.tasks(task.value).id ?? '') : '';
		ids.plans = plan.ok ? String(SUMMARY.plans(plan.value).id ?? '') : '';
		const taskOk = report.check('sdk.tasks', writer, 'create', task.ok && same(SUMMARY.tasks(task.value), expected('tasks', ids.tasks, inputs.tasks)), task.ok ? JSON.stringify(SUMMARY.tasks(task.value)) : why(task));
		const planOk = report.check('sdk.plans', writer, 'create', plan.ok && same(SUMMARY.plans(plan.value), expected('plans', ids.plans, inputs.plans)), plan.ok ? JSON.stringify(SUMMARY.plans(plan.value)) : why(plan));
		if (!taskOk || !planOk) return;

		const want = {} as Record<Family, Record<string, unknown>>;
		for (const family of FAMILIES) want[family] = expected(family, ids[family], inputs[family]);
		verifyReads(report, 'read-created', ids, want, false);

		const patches: Record<Family, Record<string, unknown>> = {
			projects: { name: `Live ${writer} project renamed by ${updater} ${nonce}`, description: `Updated by the ${updater} SDK.` },
			tasks: { title: `Live ${writer} task retitled by ${updater} ${nonce}`, description: `Task updated by ${updater}.`, labels: ['live', `u-${updater}`] },
			plans: { title: `Live ${writer} plan retitled by ${updater} ${nonce}`, goal: `Plan goal updated by ${updater}.` }
		};
		const updated = drive(updater, FAMILIES.map((family) => ({ family, op: 'update', id: ids[family], input: patches[family] })));
		FAMILIES.forEach((family, index) => {
			want[family] = { ...want[family], ...expected(family, ids[family], { ...inputs[family], ...patches[family] }) };
			const got = updated[index].ok ? SUMMARY[family](updated[index].value) : why(updated[index]);
			report.check(CAPABILITY[family], updater, 'update', updated[index].ok && same(got, want[family]), JSON.stringify(got));
		});
		verifyReads(report, 'read-updated', ids, want, true);

		const deleted = drive(deleter, [
			{ family: 'tasks', op: 'delete', id: ids.tasks },
			{ family: 'plans', op: 'delete', id: ids.plans },
			{ family: 'projects', op: 'delete', id: ids.projects }
		]);
		(['tasks', 'plans', 'projects'] as Family[]).forEach((family, index) => {
			report.check(CAPABILITY[family], deleter, 'delete', deleted[index].ok, why(deleted[index]));
		});
		for (const lang of LANGS) {
			const results = drive(lang, readBatch(ids, false));
			FAMILIES.forEach((family, index) => {
				const shown = results[index];
				report.check(CAPABILITY[family], lang, 'read-deleted.show-refused', !shown.ok, shown.ok ? 'still readable' : '');
				if (!shown.ok) report.note(CAPABILITY[family], lang, 'read-deleted.show-error-class', why(shown));
				const listed = results[3 + index];
				const present = listed.ok && Array.isArray(listed.value) && listed.value.some((r: any) => SUMMARY[family](r).id === ids[family]);
				report.check(CAPABILITY[family], lang, 'read-deleted.list-absent', listed.ok && !present, listed.ok ? (present ? 'still listed' : '') : why(listed));
			});
		}
	};
	try {
		steps();
	} finally {
		const body = JSON.stringify({ writer, updater, deleter, ids, results: report.results, failures: report.failures }, null, 2);
		await testInfo.attach('sdk-live-work-report.json', { body, contentType: 'application/json' });
		console.log(`[sdk-live-work] writer=${writer} ${body}`);
	}
	expect(report.failures, `writer=${writer} cross-language mismatches`).toEqual([]);
}

test.describe.serial('Live cross-language SDK work data', () => {
	test.skip(!apiKey, 'OPENMATES_TEST_ACCOUNT_API_KEY required');

	// eslint-disable-next-line no-empty-pattern -- Playwright requires a destructured fixture argument before testInfo.
	test.beforeAll(async ({}, testInfo: TestInfo) => {
		test.setTimeout(2_900_000);
		rustBinary = buildRustDriver(testInfo);
		installPythonSdk();
		for (const lang of LANGS) {
			const [probe] = drive(lang, [{ family: 'probe', op: 'chats' }]);
			if (probe.ok) continue;
			// Only the pending-device refusal may be repaired by approval.
			expect(probe.error, `${lang} unapproved-device probe`).toBe('forbidden');
			approveFixtureDevice(ACCESS[lang], DEVICE[lang]);
			const [approved] = drive(lang, [{ family: 'probe', op: 'chats' }]);
			expect(approved.ok, `${lang} probe after device approval`).toBe(true);
		}
	});

	// contract-test: direct surface=sdks.rust assertions=sdk.encryption.local-only,sdk.surface.semantic-parity,sdk.auth.approved-api-key-device
	// eslint-disable-next-line no-empty-pattern -- Playwright requires an object pattern for unused fixtures.
	test('Rust-written Projects, Tasks and Plans are decrypted, updated and deleted by npm and pip', async ({}, testInfo: TestInfo) => {
		test.setTimeout(600_000);
		await crossLanguageLifecycle('rust', testInfo);
	});

	// contract-test: direct surface=sdks.npm assertions=sdk.encryption.local-only,sdk.surface.semantic-parity,sdk.auth.approved-api-key-device
	// eslint-disable-next-line no-empty-pattern -- Playwright requires an object pattern for unused fixtures.
	test('npm-written Projects, Tasks and Plans are decrypted, updated and deleted by pip and Rust', async ({}, testInfo: TestInfo) => {
		test.setTimeout(600_000);
		await crossLanguageLifecycle('npm', testInfo);
	});

	// contract-test: direct surface=sdks.pip assertions=sdk.encryption.local-only,sdk.surface.semantic-parity,sdk.auth.approved-api-key-device
	// eslint-disable-next-line no-empty-pattern -- Playwright requires an object pattern for unused fixtures.
	test('pip-written Projects, Tasks and Plans are decrypted, updated and deleted by Rust and npm', async ({}, testInfo: TestInfo) => {
		test.setTimeout(600_000);
		await crossLanguageLifecycle('python', testInfo);
	});

	// contract-test: direct surface=sdks.rust assertions=sdk.surface.semantic-parity
	// eslint-disable-next-line no-empty-pattern -- Playwright requires an object pattern for unused fixtures.
	test('SDK docs list has the same live outcome in Rust, npm and pip', async ({}, testInfo: TestInfo) => {
		test.setTimeout(180_000);
		const outcomes: Record<string, unknown> = {};
		for (const lang of LANGS) {
			const [docs] = drive(lang, [{ family: 'docs', op: 'list' }]);
			outcomes[lang] = docs.ok ? { ok: true, keys: Object.keys(docs.value ?? {}).sort() } : { ok: false, error: docs.error };
		}
		const body = JSON.stringify({ capability: 'sdk.docs', outcomes }, null, 2);
		await testInfo.attach('sdk-live-docs-report.json', { body, contentType: 'application/json' });
		console.log(`[sdk-live-work] docs ${body}`);
		expect(outcomes.npm, 'npm docs outcome matches Rust').toEqual(outcomes.rust);
		expect(outcomes.python, 'pip docs outcome matches Rust').toEqual(outcomes.rust);
	});
});
