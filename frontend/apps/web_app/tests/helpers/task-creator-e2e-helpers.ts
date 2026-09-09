/* eslint-disable @typescript-eslint/no-require-imports -- Existing E2E helpers use CommonJS. */
/**
 * Genuine Codex creator setup for the isolated Task browser flow.
 * Pairs the tested CLI with the same browser account and invokes real creation.
 * A runner-owned Codex thread must already exist in its running local daemon.
 * Never manufactures lifecycle receipts, copies shared state, or starts agents.
 * Source/account/runtime provenance is supplied by the reviewed CI harness.
 */
export {};

const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { CLI_DIST } = require('./cli-test-helpers');
const {
	createWorkflowCliHome, removeWorkflowCliHome,
	loginWorkflowCliViaPair, runWorkflowCli
} = require('./workflow-cli-e2e-helpers');

async function createRunnerCodexEligibility(page: import('@playwright/test').Page): Promise<void> {
	const base = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'http://invalid');
	if (base.origin !== 'http://localhost:5173') {
		throw new Error('Task creator setup requires the admitted runner-owned frontend at localhost:5173.');
	}
	const thread = process.env.OPENMATES_TASK_TEST_CODEX_THREAD_ID || '';
	if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(thread)) {
		throw new Error('Runner must supply OPENMATES_TASK_TEST_CODEX_THREAD_ID for a genuine local Codex thread; receipt fabrication is forbidden.');
	}
	const candidateCli = path.resolve(__dirname, '../../../../packages/openmates-cli/dist/cli.js');
	if (!fs.existsSync(candidateCli) || fs.realpathSync(CLI_DIST) !== fs.realpathSync(candidateCli)) {
		throw new Error('Task creator setup requires the CLI built from this tested candidate checkout.');
	}
	const cliHome = createWorkflowCliHome('task-creator');
	try {
		await loginWorkflowCliViaPair(page, 'http://localhost:8000', cliHome, 'TASK_CREATOR');
		const result = await runWorkflowCli('http://localhost:8000', cliHome, [
			// Retries use the same real account; each creation must have its own slug.
			'tasks', 'create', '--title', `Runner Codex eligibility fixture ${randomUUID()}`,
			'--as-assignee', '--external-chat', `codex:${thread}`, '--json'
		], 60_000, {CODEX_THREAD_ID: thread});
		// Do not emit decrypted CLI output or account/session material in artifacts.
		if (result.code !== 0) {
			throw new Error(`Genuine Codex Task creation failed (exit ${result.code}); inspect runner-private CLI diagnostics and local Codex availability.`);
		}
	} finally {
		removeWorkflowCliHome(cliHome);
	}
}

module.exports = { createRunnerCodexEligibility };
