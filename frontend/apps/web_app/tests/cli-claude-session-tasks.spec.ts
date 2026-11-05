/* eslint-disable @typescript-eslint/no-require-imports -- Existing browser helpers expose CommonJS exports. */
// proof-video: not_required reason=cli_helper
/**
 * CLI E2E: a Claude Code session links OpenMates Tasks to its own conversation.
 *
 * Runs the real paired CLI against the disposable backend. Proves that
 * `--external-chat claude:<session-uuid>` is created only from the matching
 * CLAUDE_CODE_SESSION_ID, is stored as an encrypted external-chat context with
 * provider `claude` (not as a Claude assignee identity), can be filtered by the
 * same session, is rejected from a different session, and is released only by
 * its owning session.
 * Specification: specifications/features/tasks/specification.yml
 */
export {};
import { randomUUID } from 'node:crypto';
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

type CliResult = { code: number | null; stdout: string; stderr: string };

function sessionEnv(apiUrl: string, home: string, sessionId: string | undefined): Record<string, string | undefined> {
	// Remove any inherited agent identity so only the simulated session applies.
	return { ...workflowCliEnv(apiUrl, home), CODEX_THREAD_ID: undefined, CODEX_SESSION_ID: undefined, CLAUDE_CODE_SESSION_ID: sessionId };
}

async function runJson(apiUrl: string, home: string, sessionId: string | undefined, args: string[], label: string): Promise<any> {
	const result = await runCli(apiUrl, [...args, '--json'], 60000, { useApiKey: false, record: false, env: sessionEnv(apiUrl, home, sessionId) });
	return parseCliJson(result, label);
}

async function runRaw(apiUrl: string, home: string, sessionId: string | undefined, args: string[]): Promise<CliResult> {
	return runCli(apiUrl, args, 60000, { useApiKey: false, record: false, env: sessionEnv(apiUrl, home, sessionId) });
}

test.describe('CLI Claude Code session Tasks', () => {
	// contract-test: direct surface=cli assertions=tasks.external-chat.encrypted-context,tasks.conversation.single-owner-claim,tasks.surface.semantic-parity
	test('links, filters and releases a Task only from its own Claude Code session', async ({ page }: { page: Page }, testInfo: any) => {
		test.setTimeout(240000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:tasks']);
		const apiUrl = workflowApiUrl();
		const home = createWorkflowCliHome('claude-session-tasks');
		const sessionId = randomUUID();
		const otherSessionId = randomUUID();
		const title = `E2E Claude session Task ${Date.now()}-${testInfo.workerIndex}`;
		const chatTitle = 'E2E Claude Code session';
		let taskId = '';
		let flowError: unknown;
		const cleanupErrors: unknown[] = [];
		try {
			await loginWorkflowCliViaPair(page, apiUrl, home, 'CLI_CLAUDE_SESSION_TASKS');
			installRecorderDeps();

			// Recorded: create and link the Task from inside the matching session.
			const createResult = await runCli(apiUrl, [
				'tasks', 'create', '--title', title, '--assign', 'user',
				'--external-chat', `claude:${sessionId}`, '--external-chat-title', chatTitle, '--json'
			], 60000, {
				useApiKey: false,
				env: { ...sessionEnv(apiUrl, home, sessionId), OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: 'cli-claude-session-tasks' }
			});
			if (!createResult.recording?.videoPath || !existsSync(createResult.recording.videoPath)) {
				throw new Error(`Real CLI terminal recording was not captured (exit=${createResult.code})`);
			}
			await testInfo.attach('cli-claude-session-tasks-terminal-video', { path: createResult.recording.videoPath, contentType: 'video/mp4' });
			if (existsSync(createResult.recording.transcriptPath)) {
				await testInfo.attach('cli-claude-session-tasks-terminal-transcript', { path: createResult.recording.transcriptPath, contentType: 'text/plain' });
			}
			expect(createResult.code, createResult.stderr).toBe(0);
			const created = parseCliJson(createResult, 'create Claude-linked Task');
			taskId = String(created.task?.task_id ?? '');
			expect(taskId).toBeTruthy();
			expect(created.task.external_chat).toEqual({ provider: 'claude', id: sessionId, title: chatTitle });
			// A Claude link is conversation context only, never an assignee identity.
			expect(created.task.assignee_type).toBe('user');
			expect(created.task.assignee_identity ?? null).toBeNull();

			// Filtering by the same session finds it; another session's filter does not.
			const own = await runJson(apiUrl, home, sessionId, ['tasks', 'list', '--external-chat', `claude:${sessionId}`], 'list own session Tasks');
			expect(own.tasks.map((task: { task_id: string }) => task.task_id)).toContain(taskId);
			const other = await runJson(apiUrl, home, otherSessionId, ['tasks', 'list', '--external-chat', `claude:${otherSessionId}`], 'list other session Tasks');
			expect(other.tasks.map((task: { task_id: string }) => task.task_id)).not.toContain(taskId);

			// Linking a session from outside it, or a non-UUID id, is rejected before any write.
			const foreign = await runRaw(apiUrl, home, otherSessionId,
				['tasks', 'create', '--title', `${title} foreign`, '--external-chat', `claude:${sessionId}`]);
			expect(foreign.code).not.toBe(0);
			expect(`${foreign.stdout}\n${foreign.stderr}`).toMatch(/CLAUDE_CODE_SESSION_ID/);
			const invalid = await runRaw(apiUrl, home, sessionId,
				['tasks', 'create', '--title', `${title} invalid`, '--external-chat', 'claude:ses_not_a_uuid']);
			expect(invalid.code).not.toBe(0);

			// Only the owning session may release the link.
			const foreignRelease = await runRaw(apiUrl, home, otherSessionId, ['tasks', 'release', taskId]);
			expect(foreignRelease.code).not.toBe(0);
			const released = await runJson(apiUrl, home, sessionId, ['tasks', 'release', taskId], 'release own Task');
			expect(released.task?.external_chat ?? null).toBeNull();
		} catch (error) {
			flowError = error;
		} finally {
			if (taskId) {
				try {
					await runJson(apiUrl, home, sessionId, ['tasks', 'delete', taskId, '--confirm'], 'delete Claude-linked Task');
				} catch (error) { cleanupErrors.push(error); }
			}
			removeWorkflowCliHome(home);
		}
		if (flowError || cleanupErrors.length) {
			const errors = [...(flowError ? [flowError] : []), ...cleanupErrors];
			throw new AggregateError(errors, `CLI Claude session Task flow or cleanup failed: ${errors.map(String).join('; ')}`);
		}
	});
});
