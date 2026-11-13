/* eslint-disable @typescript-eslint/no-require-imports */
// proof-video: not_required reason=visual_smoke_not_needed (CLI JSON contract; native login is recorded in a real terminal)
/**
 * Native Rust CLI: hosted Project files and commit restore through the core
 * hosted writer (`projects hosted *`, `projects commit`, `projects commits restore`),
 * real stack, no AI inference.
 * Assertions: projects.files.hosted-ciphertext-commit, projects.files.exact-patch,
 * projects.history.native-commits.
 *
 * What this proves: a file created from a focused chat is committed as an encrypted
 * revision, an exact patch against its base hash applies, a stale base and a second
 * create are refused, and restoring a commit writes the committed text as a new
 * revision and records a restore commit.
 * Not proven here: the assistant job path (project_file_jobs), always_ask approval
 * and team Projects.
 */
export {};
import type { TestInfo } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');
const { parseJson, pickString } = require('./helpers/cli-native-fixtures');
const { seedViaPairedCli } = require('./helpers/owned-encrypted-embed-fixture');

const { email, password, otpKey } = getTestAccount();
const FILE = 'src/app.py';

function patch(from: string, to: string): string {
	return `--- a/${FILE}\n+++ b/${FILE}\n@@ -1 +1 @@\n-${from}\n+${to}\n`;
}

test.describe('CLI native: hosted Project files', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=projects.files.hosted-ciphertext-commit,projects.files.exact-patch,projects.history.native-commits
	test('create, patch, read, commit, change again and restore a hosted file', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'project-hosted-files');
		let projectId = '';
		let chatId = '';
		const run = async (args: string[]) => {
			const result = await diff.native(args);
			expect(result.code, `${args.join(' ')}\n${result.stderr}`).toBe(0);
			return parseJson(result);
		};
		const read = () => run(['projects', 'hosted', 'read', projectId, FILE, '--json']);
		try {
			const created = await run(['projects', 'create', 'Hosted files', '--slug', `hosted-files-${Date.now()}`, '--write-policy', 'apply_and_show', '--personal', '--json']);
			projectId = pickString(created, ['project_id', 'projectId', 'id']);
			expect(projectId).not.toBe('');
			// A drafts-only chat is local to the client; Project focus resolves the chat on the
			// server, so use an owned, server-known chat (seeded without inference).
			chatId = seedViaPairedCli(diff.apiUrl, diff.npmHome, 'event').chatId;
			expect(chatId).not.toBe('');

			const unfocused = await diff.native(['projects', 'hosted', 'create', projectId, FILE, '--chat', chatId, '--text', 'print(1)\n', '--json']);
			expect(unfocused.code).not.toBe(0);
			expect(unfocused.stdout + unfocused.stderr).toContain('project_focus_required');
			await run(['projects', 'settings', projectId, 'focus', 'activate', '--chat', chatId, '--json']);

			const first = await run(['projects', 'hosted', 'create', projectId, FILE, '--chat', chatId, '--text', 'print(1)\n', '--json']);
			expect(first.created).toBe(true);
			expect(first.revision).toBe(1);
			const again = await diff.native(['projects', 'hosted', 'create', projectId, FILE, '--chat', chatId, '--text', 'x\n', '--json']);
			expect(again.code).not.toBe(0);
			expect(again.stdout + again.stderr).toContain('file_exists');

			const v1 = await read();
			expect(v1.content).toBe('print(1)\n');
			const v2 = await run(['projects', 'hosted', 'update', projectId, FILE, v1.expected_base, '--chat', chatId, `--text=${patch('print(1)', 'print(2)')}`, '--json']);
			expect(v2.revision).toBe(2);
			const stale = await diff.native(['projects', 'hosted', 'update', projectId, FILE, v1.expected_base, '--chat', chatId, `--text=${patch('print(1)', 'print(9)')}`, '--json']);
			expect(stale.code).not.toBe(0);
			expect(stale.stdout + stale.stderr).toContain('stale_base');
			const listed = await run(['projects', 'hosted', 'list', projectId, '--json']);
			expect(JSON.stringify(listed)).toContain(FILE);

			const commit = await run(['projects', 'commit', projectId, '--message', 'print 2', '--chat', chatId, '--json']);
			const commitId = commit.commit.commit_id;
			expect(commit.commit.files[0].embed_version).toBe(2);

			const current = await read();
			expect(current.content).toBe('print(2)\n');
			await run(['projects', 'hosted', 'update', projectId, FILE, current.expected_base, '--chat', chatId, `--text=${patch('print(2)', 'print(3)')}`, '--json']);
			expect((await read()).content).toBe('print(3)\n');

			const plan = await run(['projects', 'commits', 'restore', projectId, commitId, '--dry-run', '--json']);
			expect(plan.applied).toBe(false);
			expect(plan.changed_files).toBe(1);
			const restored = await run(['projects', 'commits', 'restore', projectId, commitId, '--chat', chatId, '--json']);
			expect(restored.applied).toBe(true);
			expect(restored.written).toHaveLength(1);
			expect(restored.commit.restored_from_commit_id).toBe(commitId);
			expect(restored.commit.files[0].embed_version).toBe(4);
			const after = await read();
			expect(after.content).toBe('print(2)\n');
			expect(after.revision).toBe(4);
		} finally {
			if (projectId) await diff.native(['projects', 'delete', projectId, '--confirm', projectId, '--json']);
			if (chatId) await diff.native(['chats', 'delete', chatId, '--yes']);
			await finishDifferential(diff);
		}
	});
});
