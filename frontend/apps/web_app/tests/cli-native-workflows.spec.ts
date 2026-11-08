/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Native vs npm CLI: Workflow commands, read-only plus the full authoring lifecycle
 * (create -> show -> export -> validate -> update -> enable -> disable -> history -> runs -> delete).
 * Each CLI creates and deletes its own throwaway Workflow (unique title, far-future
 * one-time schedule, never enabled for longer than one check); ids are normalized.
 * Error paths: delete without --yes, unknown input session, run-show with two positionals.
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

const { email, password, otpKey } = getTestAccount();

const UNKNOWN_ID = '00000000-0000-4000-8000-000000000000';

function workflowYaml(title: string): string {
	return `title: ${title}
description: Differential lifecycle fixture.
start_when:
  schedule:
    type: once
    at: "2031-01-01T09:00:00.000Z"
    timezone: Europe/Berlin
steps:
  - id: forecast
    use_app_skill: weather.forecast
    input:
      location: Berlin
      start_date: { $date: today, format: date }
      end_date: { $date: today, format: date }
`;
}

function workflowId(raw: { stdout: string }): string {
	const parsed = JSON.parse(raw.stdout.trim());
	return (parsed.workflow ?? parsed).id as string;
}

test.describe('CLI native differential: workflows', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('workflows read commands match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'workflows');
		try {
			await diff.check('workflows (help)', ['workflows'], { mode: 'exit', catalog: ['workflows'] });
			await diff.check('workflows list', ['workflows', 'list'], { structureOnly: true, catalog: ['workflows list'] });
			await diff.check('workflows capabilities', ['workflows', 'capabilities'], { structureOnly: true, catalog: ['workflows capabilities'] });
			await diff.check('workflows help-app', ['workflows', 'help-app', 'web.search'], { structureOnly: true, catalog: ['workflows help-app'] });
			await diff.check('workflows input-show unknown session', ['workflows', 'input-show', UNKNOWN_ID], {
				mode: 'exit',
				catalog: ['workflows input-show']
			});
			await diff.check('workflows delete without --yes', ['workflows', 'delete', UNKNOWN_ID], {
				mode: 'exit',
				catalog: ['workflows delete']
			});
			await diff.check('workflows run-show unknown run', ['workflows', 'run-show', UNKNOWN_ID, UNKNOWN_ID], {
				mode: 'exit',
				catalog: ['workflows run-show']
			});
		} finally {
			await finishDifferential(diff);
		}
	});

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('workflows authoring lifecycle matches the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'workflows-lifecycle');
		const created: Array<{ cli: 'npm' | 'native'; id: string }> = [];
		try {
			const dir = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'wf-diff-'));
			const npmFile = path.join(dir, 'npm.workflow.yml');
			const nativeFile = path.join(dir, 'native.workflow.yml');
			fs.writeFileSync(npmFile, workflowYaml(uniqueWorkflowName('Diff npm')), 'utf8');
			fs.writeFileSync(nativeFile, workflowYaml(uniqueWorkflowName('Diff native')), 'utf8');

			await diff.check('workflows validate', ['workflows', 'validate', '--file', npmFile], {
				nativeArgs: ['workflows', 'validate', '--file', nativeFile],
				ignoreKeys: ['title'],
				catalog: ['workflows validate']
			});

			const createRecord = await diff.check('workflows create (yaml)', ['workflows', 'create', '--file', npmFile], {
				nativeArgs: ['workflows', 'create', '--file', nativeFile],
				structureOnly: true,
				catalog: ['workflows create']
			});
			const npmId = workflowId(createRecord.raw.npm);
			created.push({ cli: 'npm', id: npmId });
			const nativeId = workflowId(createRecord.raw.native);
			created.push({ cli: 'native', id: nativeId });

			const pair = (verb: string[], extra: string[] = [], nativeExtra: string[] = extra) => ({
				args: ['workflows', ...verb.slice(0, 1), npmId, ...extra],
				nativeArgs: ['workflows', ...verb.slice(0, 1), nativeId, ...nativeExtra]
			});

			let step = pair(['show']);
			await diff.check('workflows show', step.args, { nativeArgs: step.nativeArgs, structureOnly: true, catalog: ['workflows show'] });

			const npmExport = path.join(dir, 'npm-export.workflow.yml');
			const nativeExport = path.join(dir, 'native-export.workflow.yml');
			step = pair(['export'], ['--output', npmExport], ['--output', nativeExport]);
			await diff.check('workflows export', step.args, {
				nativeArgs: step.nativeArgs,
				structureOnly: true,
				catalog: ['workflows export']
			});
			expectExported(npmExport, nativeExport);

			fs.writeFileSync(npmFile, workflowYaml(uniqueWorkflowName('Diff npm updated')), 'utf8');
			fs.writeFileSync(nativeFile, workflowYaml(uniqueWorkflowName('Diff native updated')), 'utf8');
			step = pair(['update'], ['--file', npmFile], ['--file', nativeFile]);
			await diff.check('workflows update', step.args, {
				nativeArgs: step.nativeArgs,
				structureOnly: true,
				ignoreKeys: ['history', 'remote_file_saves'],
				catalog: ['workflows update']
			});

			step = pair(['enable']);
			// The weather fixture is not enable-ready: both CLIs must reject it the same way.
			await diff.check('workflows enable (rejected draft)', step.args, { nativeArgs: step.nativeArgs, mode: 'exit' });
			step = pair(['disable']);
			await diff.check('workflows disable', step.args, { nativeArgs: step.nativeArgs, structureOnly: true, catalog: ['workflows disable'] });

			step = pair(['history']);
			await diff.check('workflows history', step.args, { nativeArgs: step.nativeArgs, structureOnly: true, catalog: ['workflows history'] });
			step = pair(['runs']);
			await diff.check('workflows runs', step.args, { nativeArgs: step.nativeArgs, structureOnly: true, catalog: ['workflows runs'] });

			await diff.check('workflows run-show unknown run on real workflow', ['workflows', 'run-show', npmId, UNKNOWN_ID], {
				nativeArgs: ['workflows', 'run-show', nativeId, UNKNOWN_ID],
				mode: 'exit'
			});

			step = pair(['delete'], ['--yes']);
			await diff.check('workflows delete', step.args, { nativeArgs: step.nativeArgs, structureOnly: true, catalog: ['workflows delete'] });
			created.length = 0;

			// Direct --title/--graph creation (the original native gap): each CLI uses its own title.
			const graph = JSON.stringify({
				version: 2,
				trigger_node_id: 'manual',
				nodes: [{ id: 'manual', type: 'manual_trigger' }],
				edges: []
			});
			const graphCreate = await diff.check(
				'workflows create (title/graph)',
				['workflows', 'create', '--title', uniqueWorkflowName('Diff graph npm'), '--graph', graph],
				{
					nativeArgs: ['workflows', 'create', '--title', uniqueWorkflowName('Diff graph native'), '--graph', graph],
					structureOnly: true,
					catalog: ['workflows create']
				}
			);
			const graphNpmId = workflowId(graphCreate.raw.npm);
			created.push({ cli: 'npm', id: graphNpmId });
			const graphNativeId = workflowId(graphCreate.raw.native);
			created.push({ cli: 'native', id: graphNativeId });
			// A manual-trigger-only graph is enable-ready, so enable succeeds for both CLIs.
			await diff.check('workflows enable', ['workflows', 'enable', graphNpmId], {
				nativeArgs: ['workflows', 'enable', graphNativeId],
				structureOnly: true,
				catalog: ['workflows enable']
			});
			await diff.check('workflows disable (graph workflow)', ['workflows', 'disable', graphNpmId], {
				nativeArgs: ['workflows', 'disable', graphNativeId],
				structureOnly: true
			});
			await diff.check('workflows delete (graph workflow)', ['workflows', 'delete', graphNpmId, '--yes'], {
				nativeArgs: ['workflows', 'delete', graphNativeId, '--yes'],
				structureOnly: true
			});
			created.length = 0;
		} finally {
			// Clean up fixtures left behind by a failed check so the account stays tidy.
			for (const entry of created) {
				await (entry.cli === 'npm' ? diff.npm : diff.native)(['workflows', 'delete', entry.id, '--yes', '--json']);
			}
			await finishDifferential(diff);
		}
	});
});

/** Compares the exported documents as parsed YAML (indentation style is not semantic); only the unique title may differ. */
function expectExported(npmFile: string, nativeFile: string): void {
	const { parse } = require('yaml');
	const load = (file: string) => {
		const document = parse(fs.readFileSync(file, 'utf8'));
		document.workflow.title = '<title>';
		// Mapping key order is not semantic: compare with recursively sorted keys.
		const sorted = (value: any): any =>
			Array.isArray(value)
				? value.map(sorted)
				: value && typeof value === 'object'
					? Object.fromEntries(Object.keys(value).sort().map((key) => [key, sorted(value[key])]))
					: value;
		return JSON.stringify(sorted(document));
	};
	const npmText = load(npmFile);
	const nativeText = load(nativeFile);
	if (npmText !== nativeText) {
		throw new Error(`Exported Workflow YAML differs (title ignored).\nnpm:\n${npmText}\nnative:\n${nativeText}`);
	}
}
