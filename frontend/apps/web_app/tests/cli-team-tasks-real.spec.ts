/* eslint-disable @typescript-eslint/no-require-imports -- Existing browser helpers expose CommonJS exports. */
export {};
import { existsSync } from 'node:fs';
import type { Page } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const { runCli } = require('./helpers/cli-test-helpers');
const { installRecorderDeps } = require('./cli-tui-proof-helpers');
const {
	createWorkflowCliHome, loginWorkflowCliViaPair, removeWorkflowCliHome,
	parseCliJson, workflowApiUrl, workflowCliEnv
} = require('./helpers/workflow-cli-e2e-helpers');

function captureDiagnostic(result: { code: number | null; stdout: string; stderr: string }): string {
	let status = 'unknown';
	let reason = result.stderr;
	try {
		const envelope = JSON.parse(result.stdout) as { status?: unknown; reason?: unknown };
		if (typeof envelope.status === 'string') status = envelope.status;
		if (typeof envelope.reason === 'string') reason = envelope.reason;
	} catch { /* Successful captures return CLI command output, not a recorder envelope. */ }
	const safeReason = reason.split('\n', 1)[0].slice(0, 400)
		.replace(/\b(?:https?|wss?):\/\/[^\s"'<>]+/gi, '<url>')
		.replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '<email>')
		.replace(/\b(?:token|session|password|api[_-]?key|secret|code|pin)\s*[:=]\s*["']?[^,\s"'&]+/gi, '<credential>')
		.replace(/(?:\/[A-Za-z0-9._~-]+){2,}/g, '<path>')
		.replace(/\b[A-Za-z0-9_-]{24,}\b/g, '<opaque-value>')
		.replace(/\b\d{4,}\b/g, '<number>');
	return `exit=${result.code ?? 'unknown'} status=${status} reason=${safeReason || 'unavailable'}`;
}

async function runUnrecordedCliJson(apiUrl: string, home: string, args: string[], label: string): Promise<any> {
	const result = await runCli(apiUrl, [...args, '--json'], 60000, {
		useApiKey: false, record: false, env: workflowCliEnv(apiUrl, home)
	});
	return parseCliJson(result, label);
}

test.describe('CLI Team Tasks', () => {
	// contract-test: direct surface=cli assertions=teams.context.full-switch-local,tasks.content.client-encrypted,tasks.lifecycle.visible
	test('creates, lists and shows a Team Task through the paired CLI', async ({ page }: { page: Page }, testInfo: any) => {
		test.setTimeout(240000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:teams', 'platform:tasks']);
		const apiUrl = workflowApiUrl();
		const home = createWorkflowCliHome('team-tasks');
		const suffix = `${Date.now()}-${testInfo.workerIndex}`;
		const teamName = `E2E CLI Task Team ${suffix}`;
		const title = `E2E CLI Team Task ${suffix}`;
		let teamId = '';
		let taskId = '';
		let flowError: unknown;
		const cleanupErrors: unknown[] = [];
		try {
			await loginWorkflowCliViaPair(page, apiUrl, home, 'CLI_TEAM_TASKS');
			installRecorderDeps();
			// Capture the first nonsecret CLI operation so failures in later CRUD steps
			// still retain a real terminal recording. Pairing credentials are never recorded.
			const createTeamResult = await runCli(apiUrl, ['teams', 'create', '--name', teamName, '--json'], 60000, {
				useApiKey: false,
				env: { ...workflowCliEnv(apiUrl, home), OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: 'cli-team-tasks-real' }
			});
			if (!createTeamResult.recording?.videoPath || !existsSync(createTeamResult.recording.videoPath)) {
				throw new Error(`Real CLI terminal recording was not captured: ${captureDiagnostic(createTeamResult)}`);
			}
			await testInfo.attach('cli-team-tasks-terminal-video', { path: createTeamResult.recording.videoPath, contentType: 'video/mp4' });
			if (existsSync(createTeamResult.recording.manifestPath)) {
				await testInfo.attach('cli-team-tasks-terminal-manifest', { path: createTeamResult.recording.manifestPath, contentType: 'application/json' });
			}
			if (existsSync(createTeamResult.recording.transcriptPath)) {
				await testInfo.attach('cli-team-tasks-terminal-transcript', { path: createTeamResult.recording.transcriptPath, contentType: 'text/plain' });
			}
			expect(createTeamResult.code, `create disposable Team: ${captureDiagnostic(createTeamResult)}`).toBe(0);
			const createdTeam = parseCliJson(createTeamResult, 'create disposable Team');
			teamId = String(createdTeam.team?.team_id ?? '');
			expect(teamId).toBeTruthy();
			const createdTask = await runUnrecordedCliJson(apiUrl, home,
				['tasks', 'create', '--title', title, '--assign', 'user', '--team', teamId], 'create Team Task');
			taskId = String(createdTask.task?.task_id ?? '');
			expect(taskId).toBeTruthy();
			expect(createdTask.task.title).toBe(title);

			const listResult = await runCli(apiUrl, ['tasks', 'list', '--team', teamId], 60000, {
				useApiKey: false, record: false, env: workflowCliEnv(apiUrl, home)
			});
			expect(listResult.code, listResult.stderr).toBe(0);
			expect(listResult.stdout).toContain(title);

			const shown = await runUnrecordedCliJson(apiUrl, home,
				['tasks', 'show', taskId, '--team', teamId], 'show Team Task');
			expect(shown.task?.title).toBe(title);
			const personal = await runUnrecordedCliJson(apiUrl, home,
				['tasks', 'list', '--personal'], 'list Personal Tasks');
			expect(personal.tasks.some((task: { task_id: string }) => task.task_id === taskId)).toBe(false);
		} catch (error) {
			flowError = error;
		} finally {
			if (taskId) {
				try {
					await runUnrecordedCliJson(apiUrl, home,
						['tasks', 'delete', taskId, '--team', teamId, '--confirm'], 'delete Team Task');
				} catch (error) { cleanupErrors.push(error); }
			}
			if (teamId) {
				try {
					const response = await page.request.delete(`${apiUrl}/v1/teams/${encodeURIComponent(teamId)}`);
					if (!response.ok()) cleanupErrors.push(new Error(`Team cleanup: ${response.status()} ${await response.text()}`));
				} catch (error) { cleanupErrors.push(error); }
			}
			removeWorkflowCliHome(home);
		}
		if (flowError || cleanupErrors.length) {
			const errors = [...(flowError ? [flowError] : []), ...cleanupErrors];
			throw new AggregateError(errors, `CLI Team Task flow or cleanup failed: ${errors.map(String).join('; ')}`);
		}
	});
});
