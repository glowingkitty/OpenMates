/* eslint-disable @typescript-eslint/no-require-imports */
/** Real key-free Jobs Search through an isolated CLI Workflow run. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const fs = require('node:fs');
const { installRecorderDeps } = require('./cli-tui-proof-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const {
	createWorkflowCliHome,
	deleteWorkflowQuietly,
	loginWorkflowCliViaPair,
	removeWorkflowCliHome,
	runWorkflowCli,
	runWorkflowCliJson,
	uniqueWorkflowName,
	waitForWorkflowRunStatus,
	workflowApiUrl,
	writeWorkflowYaml
} = require('./helpers/workflow-cli-e2e-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.describe('Jobs Search in Workflows', () => {
	test.setTimeout(300_000);

	// contract-test: direct surface=cli assertions=workflows.actions.skill-contract,workflows.control.typed-data,workflows.control.for-each
	test('runs JobTech Search and exposes flat job fields to a later loop check', async ({ page }: { page: any }, testInfo: any) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const apiUrl = workflowApiUrl();
		const homeDir = createWorkflowCliHome('workflow-jobs-search');
		let workflowId: string | undefined;
		try {
			await loginWorkflowCliViaPair(page, apiUrl, homeDir, 'CLI_WORKFLOW_JOBS_SEARCH');
			const capabilities = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'capabilities'], 'Jobs capability discovery');
			const jobs = capabilities.find((capability: any) => capability.id === 'jobs.search');
			expect(jobs?.enabled).toBe(true);
			expect(jobs.metadata.workflow.execution_mode).toBe('sync');
			expect(jobs.metadata.workflow.test_allowed).toBe(true);
			expect(jobs.metadata.output_schema.properties.results.type).toBe('array');
			expect(jobs.metadata.output_schema.properties.results.items.properties.country.type).toBe('string');

			const yamlFile = writeWorkflowYaml(homeDir, 'jobs-search.yml', `
title: ${uniqueWorkflowName('E2E Jobs Search workflow')}
description: Find Swedish developer jobs and inspect typed results.
start_when:
  manual: {}
steps:
  - id: jobs
    use_app_skill: jobs.search
    input:
      requests:
        - id: sweden
          query: utvecklare
          country: SE
          provider: JobTech
          limit: 2
  - id: each_job
    for_each:
      items: $nodes.jobs.output.results
      max_items: 2
      do:
        - id: country_check
          check:
            left: $items.each_job.item.country
            op: eq
            right: SE
  - id: report
    send_chat_message:
      title: Swedish developer jobs
      message: "Found {{steps.jobs.result_count}} Swedish developer jobs."
`);

			const created = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'create', '--file', yamlFile], 'create Jobs Search workflow');
			workflowId = created.workflow.id;
			expect(created.validation.enable_ready).toBe(true);
			const acceptedRun = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'run', workflowId, '--idempotency-key', `${workflowId}-jobs`], 'run Jobs Search workflow', 120_000);
			const completedRun = await waitForWorkflowRunStatus(apiUrl, homeDir, workflowId, acceptedRun.id, ['completed'], 'Jobs Search workflow', 180_000);
			installRecorderDeps();
			const recorded = await runWorkflowCli(apiUrl, homeDir,
				['workflows', 'run-show', workflowId, acceptedRun.id, '--json'], 30_000,
				{ OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: 'cli-workflows-jobs-search-real.spec.ts', LIBGL_ALWAYS_SOFTWARE: 'true', GALLIUM_DRIVER: 'llvmpipe' });
			expect(recorded.code, `Recorded Jobs run-show failed: ${recorded.stderr}`).toBe(0);
			expect(recorded.recording, 'Real terminal recording required').toBeTruthy();
			expect(fs.existsSync(recorded.recording.videoPath), 'Terminal video is missing').toBe(true);
			expect(fs.existsSync(recorded.recording.manifestPath), 'Terminal manifest is missing').toBe(true);
			await testInfo.attach('openmates-cli-real-terminal-video', { path: recorded.recording.videoPath, contentType: 'video/mp4' });
			await testInfo.attach('openmates-cli-real-terminal-manifest', { path: recorded.recording.manifestPath, contentType: 'application/json' });
			expect(JSON.parse(recorded.stdout).id).toBe(completedRun.id);

			const search = completedRun.node_runs.find((node: any) => node.node_id === 'jobs')?.output_summary;
			expect(search?.success).toBe(true);
			expect(search?.partial).toBe(search?.warnings.length > 0);
			expect(search?.result_count).toBeGreaterThan(0);
			expect(search?.result_count).toBe(search?.results.length);
			expect(search?.raw.results[0].id).toBe('sweden');
			for (const job of search.results) {
				expect(job.title).toEqual(expect.any(String));
				expect(job.title.length).toBeGreaterThan(0);
				expect(job.country).toBe('SE');
				expect(job.provider).toBe('jobtech');
				expect(job.url).toMatch(/^https:\/\//);
				expect(job.canonical_url).toMatch(/^https:\/\//);
				expect(job.source_id).toEqual(expect.any(String));
			}
			const loop = completedRun.node_runs.find((node: any) => node.node_id === 'each_job')?.output_summary;
			expect(loop?.item_count).toBe(search.result_count);
			expect(loop?.completed_count).toBe(search.result_count);
			expect(loop?.results).toHaveLength(search.result_count);
			for (const item of loop.results) expect(item.outputs.country_check.matched).toBe(true);
			expect(completedRun.node_runs.find((node: any) => node.node_id === 'report')?.status).toBe('completed');
		} finally {
			await deleteWorkflowQuietly(apiUrl, homeDir, workflowId);
			removeWorkflowCliHome(homeDir);
		}
	});
});
