/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Native vs npm CLI: Workflow input sessions, run control, history restore, import,
 * save-as-reusable and Project linking. No AI credits: input/ask/respond that would start an
 * assistant are only exercised on their missing-argument / unknown-id error paths; runs use a
 * manual-trigger graph with no steps. Each CLI creates and deletes its own throwaway Workflow
 * and Project. Skipped on purpose (AI/credits/provider keyed): workflows ask, input (start),
 * step-test, run-once (needs a source chat).
 * Harness: helpers/cli-native-differential.ts (npm CLI vs native Rust binary, same account).
 */
export {};
import type { TestInfo } from '@playwright/test';

const fs = require('node:fs');
const path = require('node:path');
const { test } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');
const { uniqueWorkflowName } = require('./helpers/workflow-cli-e2e-helpers');
const { bothIds } = require('./helpers/cli-native-fixtures');

const { email, password, otpKey } = getTestAccount();

const UNKNOWN_ID = '00000000-0000-4000-8000-000000000000';

function manualGraph(): string {
	return JSON.stringify({
		version: 2,
		trigger_node_id: 'manual',
		nodes: [{ id: 'manual', type: 'manual_trigger' }],
		edges: []
	});
}

function workflowId(raw: { stdout: string }): string {
	const parsed = JSON.parse(raw.stdout.trim());
	return (parsed.workflow ?? parsed).id as string;
}

test.describe('CLI native differential: workflows (input, runs, history, import, projects)', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('workflows input/run/step error paths match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'workflows-errors');
		try {
			const exit = (label: string, args: string[], catalog: string[], expectedGap?: string) =>
				diff.check(label, args, { mode: 'exit', catalog, ...(expectedGap ? { expectedGap } : {}) });
			await exit('workflows input-show (missing id)', ['workflows', 'input-show'], ['workflows input-show']);
			await exit('workflows input-events unknown', ['workflows', 'input-events', UNKNOWN_ID], ['workflows input-events']);
			await exit('workflows input-events (missing id)', ['workflows', 'input-events'], ['workflows input-events']);
			await exit('workflows input-follow-up unknown', ['workflows', 'input-follow-up', UNKNOWN_ID, 'hello'], ['workflows input-follow-up']);
			await exit('workflows input-follow-up (missing text)', ['workflows', 'input-follow-up', UNKNOWN_ID], ['workflows input-follow-up']);
			await exit('workflows input-stop unknown', ['workflows', 'input-stop', UNKNOWN_ID], ['workflows input-stop']);
			await exit('workflows input-stop (missing id)', ['workflows', 'input-stop'], ['workflows input-stop']);
			await exit('workflows input-undo unknown', ['workflows', 'input-undo', UNKNOWN_ID], ['workflows input-undo']);
			await exit('workflows input-undo (missing id)', ['workflows', 'input-undo'], ['workflows input-undo']);
			await exit('workflows input (missing text)', ['workflows', 'input'], ['workflows input']);
			await exit('workflows run unknown', ['workflows', 'run', UNKNOWN_ID, '--idempotency-key', 'diff-key'], ['workflows run']);
			await exit('workflows run (missing id)', ['workflows', 'run'], ['workflows run']);
			await exit('workflows run (missing key)', ['workflows', 'run', UNKNOWN_ID], ['workflows run']);
			await exit('workflows run-cancel unknown', ['workflows', 'run-cancel', UNKNOWN_ID, UNKNOWN_ID], ['workflows run-cancel']);
			await exit('workflows run-cancel (missing run)', ['workflows', 'run-cancel', UNKNOWN_ID], ['workflows run-cancel']);
			await exit('workflows run-delete unknown', ['workflows', 'run-delete', UNKNOWN_ID, UNKNOWN_ID, '--yes'], ['workflows run-delete']);
			await exit('workflows run-delete (no --yes)', ['workflows', 'run-delete', UNKNOWN_ID, UNKNOWN_ID], ['workflows run-delete']);
			await exit('workflows run-once (missing graph)', ['workflows', 'run-once', '--title', 'x'], ['workflows run-once']);
			await exit('workflows respond unknown', ['workflows', 'respond', UNKNOWN_ID, UNKNOWN_ID, 'step'], ['workflows respond']);
			await exit('workflows respond (missing step)', ['workflows', 'respond', UNKNOWN_ID, UNKNOWN_ID], ['workflows respond']);
			await exit('workflows restore unknown', ['workflows', 'restore', UNKNOWN_ID, '--entry', UNKNOWN_ID], ['workflows restore']);
			// npm prints a `Usage:` line (class usage); native prints the generic missing-positional wording (class other).
			await exit('workflows restore (missing id)', ['workflows', 'restore'], ['workflows restore'], 'stderr class: npm=usage native=other');
			await exit('workflows save-as-reusable unknown', ['workflows', 'save-as-reusable', UNKNOWN_ID, '--idempotency-key', 'diff-key'], ['workflows save-as-reusable']);
			await exit('workflows save-as-reusable (missing key)', ['workflows', 'save-as-reusable', UNKNOWN_ID], ['workflows save-as-reusable']);
			await exit('workflows step-preview unknown', ['workflows', 'step-preview', UNKNOWN_ID, 'step'], ['workflows step-preview']);
			// npm names step-test --yes in both messages (class confirmation-required); native uses the generic wording.
			await exit('workflows step-preview (missing step)', ['workflows', 'step-preview', UNKNOWN_ID], ['workflows step-preview'], 'stderr class: npm=confirmation-required native=other');
			await exit('workflows step-test (missing step)', ['workflows', 'step-test', UNKNOWN_ID], ['workflows step-test'], 'stderr class: npm=confirmation-required native=other');
			await exit('workflows import (missing file)', ['workflows', 'import'], ['workflows import']);
			await exit('workflows add-to-project unknown', ['workflows', UNKNOWN_ID, 'add-to-project', UNKNOWN_ID], ['workflows add-to-project'], 'stderr class: npm=http-not-found native=other');
			await exit('workflows remove-from-project unknown', ['workflows', UNKNOWN_ID, 'remove-from-project', UNKNOWN_ID], ['workflows remove-from-project']);
		} finally {
			await finishDifferential(diff);
		}
	});

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('workflows run, history restore, import and project links match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'workflows-extra');
		const cleanup: Array<() => Promise<unknown>> = [];
		try {
			const dir = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'wf-extra-'));
			const create = async (label: string) => {
				const record = await diff.check(`workflows create (${label})`, ['workflows', 'create', '--title', uniqueWorkflowName('Extra npm'), '--graph', manualGraph()], {
					nativeArgs: ['workflows', 'create', '--title', uniqueWorkflowName('Extra native'), '--graph', manualGraph()],
					structureOnly: true
				});
				const ids = { npm: workflowId(record.raw.npm), native: workflowId(record.raw.native) };
				cleanup.push(() => diff.npm(['workflows', 'delete', ids.npm, '--yes', '--json']));
				cleanup.push(() => diff.native(['workflows', 'delete', ids.native, '--yes', '--json']));
				return ids;
			};
			const both = (label: string, verb: string[], ids: { npm: string; native: string }, extra: string[], catalog: string[], options: Record<string, unknown> = {}) =>
				diff.check(label, ['workflows', verb[0], ids.npm, ...verb.slice(1), ...extra], {
					nativeArgs: ['workflows', verb[0], ids.native, ...verb.slice(1), ...extra],
					catalog,
					...options
				});

			const wf = await create('fixture');

			// Runs: a manual test run of a trigger-only graph is free and deterministic.
			const run = await both('workflows run (test mode)', ['run'], wf, ['--idempotency-key', 'diff-run-key', '--mode', 'test'], ['workflows run'], {
				structureOnly: true
			});
			let runIds: { npm: string; native: string } | null = null;
			try {
				const npmRun = JSON.parse(run.raw.npm.stdout.trim());
				const nativeRun = JSON.parse(run.raw.native.stdout.trim());
				runIds = { npm: npmRun.run_id ?? npmRun.id, native: nativeRun.run_id ?? nativeRun.id };
			} catch {
				runIds = null;
			}
			if (runIds?.npm && runIds?.native) {
				await diff.check('workflows run-show', ['workflows', 'run-show', wf.npm, runIds.npm], {
					nativeArgs: ['workflows', 'run-show', wf.native, runIds.native],
					structureOnly: true,
					catalog: ['workflows run-show']
				});
				await diff.check('workflows run-cancel (finished run)', ['workflows', 'run-cancel', wf.npm, runIds.npm], {
					nativeArgs: ['workflows', 'run-cancel', wf.native, runIds.native],
					structureOnly: true,
					catalog: ['workflows run-cancel']
				});
				await diff.check('workflows run-delete', ['workflows', 'run-delete', wf.npm, runIds.npm, '--yes'], {
					nativeArgs: ['workflows', 'run-delete', wf.native, runIds.native, '--yes'],
					structureOnly: true,
					catalog: ['workflows run-delete']
				});
			}

			// History restore with each CLI's own history entry.
			const history = await both('workflows history', ['history'], wf, ['--limit', '10'], [], { structureOnly: true });
			const entry = bothIds(history, ['entry_id', 'history_entry_id', 'id']);
			await diff.check('workflows restore', ['workflows', 'restore', wf.npm, '--entry', entry.npm || UNKNOWN_ID, '--state', 'before'], {
				nativeArgs: ['workflows', 'restore', wf.native, '--entry', entry.native || UNKNOWN_ID, '--state', 'before'],
				structureOnly: true,
				catalog: ['workflows restore']
			});
			await diff.check('workflows restore (unknown entry)', ['workflows', 'restore', wf.npm, '--entry', UNKNOWN_ID], {
				nativeArgs: ['workflows', 'restore', wf.native, '--entry', UNKNOWN_ID],
				mode: 'exit'
			});

			await both('workflows step-preview (unknown step)', ['step-preview', 'nope'], wf, [], ['workflows step-preview'], { mode: 'exit' });
			await both('workflows run-delete (unknown run on real workflow)', ['run-delete', UNKNOWN_ID], wf, ['--yes'], [], { mode: 'exit' });

			// save-as-reusable on a saved workflow.
			await both('workflows save-as-reusable', ['save-as-reusable'], wf, ['--idempotency-key', 'diff-reusable-key'], ['workflows save-as-reusable'], {
				structureOnly: true
			});

			// Import: each CLI re-imports its own export of the fixture Workflow.
			const npmFile = path.join(dir, 'npm.workflow.yml');
			const nativeFile = path.join(dir, 'native.workflow.yml');
			await diff.check('workflows export (for import)', ['workflows', 'export', wf.npm, '--output', npmFile], {
				nativeArgs: ['workflows', 'export', wf.native, '--output', nativeFile],
				structureOnly: true
			});
			const imported = await diff.check('workflows import', ['workflows', 'import', '--file', npmFile], {
				nativeArgs: ['workflows', 'import', '--file', nativeFile],
				structureOnly: true,
				catalog: ['workflows import']
			});
			try {
				const ids = { npm: workflowId(imported.raw.npm), native: workflowId(imported.raw.native) };
				cleanup.push(() => diff.npm(['workflows', 'delete', ids.npm, '--yes', '--json']));
				cleanup.push(() => diff.native(['workflows', 'delete', ids.native, '--yes', '--json']));
			} catch {
				// import failed on both sides; the check above already reports the diff.
			}

			// Project links: each CLI uses its own throwaway Project.
			const projectArgs = (slug: string) => ['projects', 'create', 'Workflow link project', '--slug', slug, '--write-policy', 'always_ask', '--personal'];
			const created = await diff.check('projects create (fixture)', projectArgs('wf-link-npm'), {
				nativeArgs: projectArgs('wf-link-native'),
				ignoreKeys: ['slug', 'short_id']
			});
			const project = bothIds(created, ['project_id', 'projectId', 'id']);
			if (project.npm) cleanup.push(() => diff.npm(['projects', 'delete', project.npm, '--confirm', project.npm, '--json']));
			if (project.native) cleanup.push(() => diff.native(['projects', 'delete', project.native, '--confirm', project.native, '--json']));
			if (project.npm && project.native) {
				await diff.check('workflows add-to-project', ['workflows', wf.npm, 'add-to-project', project.npm], {
					nativeArgs: ['workflows', wf.native, 'add-to-project', project.native],
					structureOnly: true,
					catalog: ['workflows add-to-project']
				});
				await diff.check('workflows remove-from-project', ['workflows', wf.npm, 'remove-from-project', project.npm], {
					nativeArgs: ['workflows', wf.native, 'remove-from-project', project.native],
					structureOnly: true,
					catalog: ['workflows remove-from-project']
				});
			}
		} finally {
			for (const fn of cleanup.reverse()) await fn().catch(() => undefined);
			await finishDifferential(diff);
		}
	});
});
