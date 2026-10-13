/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * CLI Workflow scheduled execution E2E.
 *
 * Creates a near-future one-time Workflow through the CLI, disconnects from web
 * UI actions, and later inspects the run accepted by the backend scheduler.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { CLI_DIST } = require('./helpers/cli-test-helpers');
const { installRecorderDeps } = require('./cli-tui-proof-helpers');
const {
	createWorkflowCliHome,
	deleteWorkflowQuietly,
	loginWorkflowCliViaPair,
	removeWorkflowCliHome,
	runWorkflowCliJson,
	uniqueWorkflowName,
	waitForWorkflowRunListStatus,
	waitForWorkflowRunStatus,
	workflowCliEnv,
	workflowApiUrl,
	writeWorkflowYaml
} = require('./helpers/workflow-cli-e2e-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

function recordScheduledRun(apiUrl: string, homeDir: string, workflowId: string, runId: string, label: string, testInfo: any): Promise<void> {
	const outputDir = testInfo.outputPath(`cli-terminal-${label}`);
	const result = spawnSync('python3', [
		path.resolve(__dirname, '../../../../scripts/cli_video_capture.py'),
		'--output-dir', outputDir, '--target-environment', apiUrl,
		'--display-number', String(200 + Number(process.env.PLAYWRIGHT_WORKER_SLOT || '1')),
		'--timeout-seconds', '90', '--no-response-media',
		'--', 'node', CLI_DIST, 'workflows', 'run-show', workflowId, runId, '--api-url', apiUrl
	], { env: workflowCliEnv(apiUrl, homeDir), encoding: 'utf8', timeout: 120_000 });
	expect(result.status, `Terminal capture failed: ${result.stderr}`).toBe(0);
	const video = path.join(outputDir, 'raw-terminal.mp4');
	expect(fs.existsSync(video), 'Scheduled execution has a real terminal recording').toBe(true);
	return Promise.all([
		testInfo.attach(`openmates-cli-real-terminal-${label}-video`, { path: video, contentType: 'video/mp4' }),
		testInfo.attach(`openmates-cli-real-terminal-${label}-manifest`, { path: path.join(outputDir, 'manifest.json'), contentType: 'application/json' }),
		testInfo.attach(`openmates-cli-real-terminal-${label}-transcript`, { path: path.join(outputDir, 'transcript.txt'), contentType: 'text/plain' })
	]).then(() => undefined);
}

test.describe('CLI Workflows scheduled execution', () => {
	test.setTimeout(420_000);
	test.beforeAll(() => installRecorderDeps());

	// contract-test: direct surface=cli assertions=workflows.schedule.recurrence,workflows.execution.lifecycle-visible,workflows.surface.semantic-parity,cli.surface.semantic-parity
	test('creates a one-time scheduled Workflow and inspects the backend-accepted run', async ({ page }: { page: any }, testInfo: any) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const apiUrl = workflowApiUrl();
		const homeDir = createWorkflowCliHome('workflow-schedule');
		let workflowId: string | undefined;
		try {
			await loginWorkflowCliViaPair(page, apiUrl, homeDir, 'CLI_WORKFLOW_SCHEDULE');
			const runAt = new Date(Date.now() + 90_000).toISOString();
			const dueAt = Math.floor(Date.parse(runAt) / 1000);
			const yamlFile = writeWorkflowYaml(homeDir, 'schedule.yml', `
title: ${uniqueWorkflowName('E2E scheduled workflow')}
description: Near-future one-time scheduled Workflow.
start_when:
  schedule:
    type: once
    at: "${runAt}"
    timezone: Europe/Berlin
steps:
  - id: forecast
    use_app_skill: weather.forecast
    input:
      location: Berlin
      start_date: { $date: today, format: date }
      end_date: { $date: today, format: date }
  - id: report
    send_chat_message:
      title: Scheduled Berlin weather
      message: "Scheduled forecast completed: {{steps.forecast.rain_summary}}"
      blocks:
        - id: weather
          source: $nodes.forecast.output.rain_summary
`);

			const created = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'create', '--file', yamlFile], 'create scheduled workflow');
			workflowId = created.workflow.id;
			expect(created.validation.enable_ready).toBe(true);
			const enabled = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'enable', workflowId], 'enable scheduled workflow');
			expect(enabled.enabled).toBe(true);
			expect(enabled.next_run_at).toBe(dueAt);
			expect(Date.now()).toBeLessThan(Date.parse(runAt));
			expect(await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'runs', workflowId], 'runs before scheduled time')).toEqual([]);

			await page.close();
			const scheduledRun = await waitForWorkflowRunListStatus(apiUrl, homeDir, workflowId, ['queued', 'running', 'completed'], 'scheduled workflow', 240_000);
			const completedRun = scheduledRun.status === 'completed'
				? scheduledRun
				: await waitForWorkflowRunStatus(apiUrl, homeDir, workflowId, scheduledRun.id, ['completed'], 'scheduled workflow completion', 180_000);
			expect(completedRun.trigger_type).toBe('schedule');
			expect(completedRun.started_at).toBeGreaterThanOrEqual(dueAt);
			expect(completedRun.node_runs.some((node: any) => node.node_id === 'forecast' && node.status === 'completed')).toBe(true);
			const exhausted = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'show', workflowId], 'one-time schedule exhausted');
			expect(exhausted.next_run_at).toBeNull();
			// Observe another scanner interval to catch a one-time trigger being requeued.
			await new Promise((resolve) => setTimeout(resolve, 65_000));
			const runs = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'runs', workflowId], 'one-time run count');
			expect(runs.map((run: any) => run.id)).toEqual([completedRun.id]);
			await recordScheduledRun(apiUrl, homeDir, workflowId, completedRun.id, 'one-time-run', testInfo);
		} finally {
			await deleteWorkflowQuietly(apiUrl, homeDir, workflowId);
			removeWorkflowCliHome(homeDir);
		}
	});

	// contract-test: direct surface=cli assertions=workflows.schedule.recurrence,workflows.execution.lifecycle-visible,workflows.surface.semantic-parity,cli.surface.semantic-parity
	test('starts hourly, daily and weekly schedules at the chosen Berlin clock time and advances them', async ({ page }: { page: any }, testInfo: any) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		const apiUrl = workflowApiUrl();
		const homeDir = createWorkflowCliHome('workflow-recurring-schedule');
		const workflows: { id: string; type: string; nextAt: number }[] = [];
		try {
			await loginWorkflowCliViaPair(page, apiUrl, homeDir, 'CLI_WORKFLOW_RECURRING_SCHEDULE');
			// All three schedules are due together, with enough lead time to save/enable each.
			const dueDate = new Date(Math.ceil((Date.now() + 150_000) / 60_000) * 60_000);
			const dueAt = dueDate.getTime() / 1000;
			const parts = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Berlin', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(dueDate);
			const hour = parts.find((part) => part.type === 'hour')!.value;
			const minute = parts.find((part) => part.type === 'minute')!.value;
			const weekday = new Intl.DateTimeFormat('en-US', { timeZone: 'Europe/Berlin', weekday: 'long' }).format(dueDate).toLowerCase();
			for (const type of ['hourly', 'daily', 'weekly']) {
				const fields = type === 'hourly' ? `minute: ${Number(minute)}` : `time: "${hour}:${minute}"${type === 'weekly' ? `\n    weekdays: [${weekday}]` : ''}`;
				const yamlFile = writeWorkflowYaml(homeDir, `${type}.yml`, `
title: ${uniqueWorkflowName(`E2E ${type} schedule`)}
start_when:
  schedule:
    type: ${type}
    timezone: Europe/Berlin
    ${fields}
steps:
  - id: report
    send_chat_message:
      title: Scheduled ${type} reminder
      message: "This ${type} reminder ran at the chosen clock time."
`);
				const created = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'create', '--file', yamlFile], `create ${type} schedule`);
				const id = created.workflow.id;
				workflows.push({ id, type, nextAt: dueAt + (type === 'hourly' ? 3600 : type === 'daily' ? 86_400 : 604_800) });
				expect(created.validation.enable_ready).toBe(true);
				const enabled = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'enable', id], `enable ${type} schedule`);
				expect(enabled.next_run_at).toBe(dueAt);
				expect(Date.now()).toBeLessThan(dueDate.getTime());
				expect(await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'runs', id], `${type} runs before due time`)).toEqual([]);
			}
			await page.close();
			for (const workflow of workflows) {
				const accepted = await waitForWorkflowRunListStatus(apiUrl, homeDir, workflow.id, ['queued', 'running', 'completed'], `${workflow.type} scheduled run`, 240_000);
				const completed = await waitForWorkflowRunStatus(apiUrl, homeDir, workflow.id, accepted.id, ['completed'], `${workflow.type} completion`, 90_000);
				expect(completed.trigger_type).toBe('schedule');
				expect(completed.started_at).toBeGreaterThanOrEqual(dueAt);
				expect(completed.node_runs.some((node: any) => node.node_id === 'report' && node.status === 'completed')).toBe(true);
				const detail = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'show', workflow.id], `${workflow.type} next occurrence`);
				expect(detail.enabled).toBe(true);
				// Calendar days can cross DST. The next time must still be the chosen local clock time.
				const next = new Date(detail.next_run_at * 1000);
				const nextParts = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Berlin', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(next);
				expect(nextParts.find((part) => part.type === 'minute')!.value).toBe(minute);
				if (workflow.type !== 'hourly') expect(nextParts.find((part) => part.type === 'hour')!.value).toBe(hour);
				const elapsed = detail.next_run_at - dueAt;
				if (workflow.type === 'hourly') expect(elapsed).toBe(3600);
				else {
					expect(elapsed).toBeGreaterThanOrEqual(workflow.nextAt - dueAt - 3600);
					expect(elapsed).toBeLessThanOrEqual(workflow.nextAt - dueAt + 3600);
				}
				if (workflow.type === 'weekly') expect(new Intl.DateTimeFormat('en-US', { timeZone: 'Europe/Berlin', weekday: 'long' }).format(next).toLowerCase()).toBe(weekday);
				expect((await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'runs', workflow.id], `${workflow.type} run count`)).map((run: any) => run.id)).toEqual([completed.id]);
				await recordScheduledRun(apiUrl, homeDir, workflow.id, completed.id, `recurring-${workflow.type}`, testInfo);
			}
		} finally {
			for (const workflow of workflows) await deleteWorkflowQuietly(apiUrl, homeDir, workflow.id);
			removeWorkflowCliHome(homeDir);
		}
	});

	// contract-test: direct surface=cli assertions=workflows.schedule.recurring-start,workflows.schedule.recurrence,workflows.execution.lifecycle-visible,workflows.surface.semantic-parity,cli.surface.semantic-parity
	test('keeps a daily workflow dormant until its future start and then runs at the selected time', async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(540_000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		const apiUrl = workflowApiUrl();
		const homeDir = createWorkflowCliHome('workflow-future-start');
		let workflowId: string | undefined;
		try {
			await loginWorkflowCliViaPair(page, apiUrl, homeDir, 'CLI_WORKFLOW_FUTURE_START');
			const clockFor = (date: Date) => new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Berlin', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(date);
			const firstClock = new Date(Math.ceil((Date.now() + 90_000) / 60_000) * 60_000);
			const title = uniqueWorkflowName('E2E daily future start');
			const document = (clock: string, startsAt: string) => `
title: ${title}
start_when:
  schedule:
    type: daily
    time: "${clock}"
    timezone: Europe/Berlin
    starts_at: "${startsAt}"
steps:
  - id: report
    send_chat_message:
      title: Future-start reminder
      message: "Daily checking began only after its selected starting date and time."
`;
			// A start after today's regular clock must skip today's occurrence altogether.
			const startsAt = new Date(firstClock.getTime() + 60_000).toISOString();
			const file = writeWorkflowYaml(homeDir, 'future-start.yml', document(clockFor(firstClock), startsAt));
			const created = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'create', '--file', file], 'create future-start workflow');
			workflowId = created.workflow.id;
			expect(created.validation.enable_ready).toBe(true);
			const enabled = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'enable', workflowId], 'enable future-start workflow');
			expect(enabled.next_run_at).toBeGreaterThanOrEqual(firstClock.getTime() / 1000 + 23 * 3600);
			expect(clockFor(new Date(enabled.next_run_at * 1000))).toBe(clockFor(firstClock));
			expect(enabled.graph.nodes.find((node: any) => node.type === 'schedule_trigger').config.schedule.starts_at).toBe(startsAt);
			const exported = path.join(homeDir, 'future-start.workflow.yml');
			await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'export', workflowId, '--output', exported], 'export future-start workflow');
			expect(fs.readFileSync(exported, 'utf8')).toContain(startsAt);
			await page.close();
			// Keep checking across the original clock and another complete scanner interval.
			while (Date.now() < firstClock.getTime() + 65_000) {
				expect(await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'runs', workflowId], 'future start prevents early occurrence')).toEqual([]);
				await new Promise((resolve) => setTimeout(resolve, 10_000));
			}
			const due = new Date(Math.ceil((Date.now() + 90_000) / 60_000) * 60_000);
			const dueAt = due.getTime() / 1000;
			const nearStart = new Date(due.getTime() - 30_000).toISOString();
			const updatedFile = writeWorkflowYaml(homeDir, 'near-start.yml', document(clockFor(due), nearStart));
			const updated = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'update', workflowId, '--file', updatedFile], 'move start close to now');
			expect(updated.workflow.enabled).toBe(true);
			expect(updated.workflow.next_run_at).toBe(dueAt);
			expect(await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'runs', workflowId], 'no run before new starting time')).toEqual([]);
			const accepted = await waitForWorkflowRunListStatus(apiUrl, homeDir, workflowId, ['queued', 'running', 'completed'], 'future-start scheduled run', 240_000);
			const completed = await waitForWorkflowRunStatus(apiUrl, homeDir, workflowId, accepted.id, ['completed'], 'future-start completion', 90_000);
			expect(completed.trigger_type).toBe('schedule');
			expect(completed.started_at).toBeGreaterThanOrEqual(dueAt);
			expect(completed.node_runs.some((node: any) => node.node_id === 'report' && node.status === 'completed')).toBe(true);
			const detail = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'show', workflowId], 'daily occurrence after future start');
			expect(detail.next_run_at).toBeGreaterThanOrEqual(dueAt + 23 * 3600);
			expect(detail.next_run_at).toBeLessThanOrEqual(dueAt + 25 * 3600);
			expect(clockFor(new Date(detail.next_run_at * 1000))).toBe(clockFor(due));
			expect((await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'runs', workflowId], 'future-start run count')).map((run: any) => run.id)).toEqual([completed.id]);
			await recordScheduledRun(apiUrl, homeDir, workflowId, completed.id, 'future-start-run', testInfo);
		} finally {
			await deleteWorkflowQuietly(apiUrl, homeDir, workflowId);
			removeWorkflowCliHome(homeDir);
		}
	});
});
