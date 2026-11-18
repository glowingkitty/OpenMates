/* eslint-disable @typescript-eslint/no-require-imports -- spec helpers are CommonJS, shared with other specs */
/**
 * Project Timeline tab (web, Rust client core build) plus the native CLI, real
 * isolated stack, no AI inference.
 * Assertions: projects.history.native-commits.
 *
 * What this proves: the CLI creates a hosted Project file, commits it and changes
 * it again; `projects timeline` lists the change newest first; the web Project
 * view's Timeline tab shows the commit and the file versions, expands the commit
 * to its file, asks before restoring, and the restore writes the committed text
 * as a new user version and records a user commit that names its source (read
 * back through the CLI).
 * Not proven here: relink of a deleted file (core unit tests), Team Projects and
 * Apple (ProjectTimelineUITests).
 */
export {};
import type { TestInfo } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');
const { parseJson, pickString } = require('./helpers/cli-native-fixtures');
const { seedViaPairedCli } = require('./helpers/owned-encrypted-embed-fixture');
const { naturalProjectName } = require('./helpers/project-names');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const { email, password, otpKey } = getTestAccount();
const FILE = 'web-app/recipes.js';
const MESSAGE = 'Add pancake recipe';
const DEVICE = 'web-laptop';

function patch(from: string, to: string): string {
	return `--- a/${FILE}\n+++ b/${FILE}\n@@ -1 +1 @@\n-${from}\n+${to}\n`;
}

function proofFor(page: any, testInfo: TestInfo) {
	const devices = [DEVICE];
	const contract = defineVideoProof({
		id: 'project-timeline-restore',
		title: 'Restore a Project commit from the Timeline tab',
		surface: 'web',
		devices: [DEVICE],
		domain: 'app.dev.openmates.org',
		transcript: [
			{ id: 'timeline-listed', text: 'The Project Timeline tab lists the latest file change above the commit.', checkpoint: 'timeline-listed', devices },
			{ id: 'restore-confirm', text: 'Opening the commit shows its file and asks before restoring it.', checkpoint: 'restore-confirm', devices },
			{ id: 'restored', text: 'The restore finishes and the Timeline shows the new restore commit.', checkpoint: 'restored', devices },
		],
		assertions: [
			{ id: 'projects.history.native-commits.timeline-listed', checkpoint: 'timeline-listed', visual: 'The Timeline tab shows a version 2 row of web-app/recipes.js above the "Add pancake recipe" commit.', devices },
			{ id: 'projects.history.native-commits.restore-confirm', checkpoint: 'restore-confirm', visual: 'The expanded commit lists web-app/recipes.js and shows the restore confirmation.', devices },
			{ id: 'projects.history.native-commits.restored', checkpoint: 'restored', visual: 'A success status is shown and a commit restored from the original commit is at the top.', devices },
		],
		tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
	});
	return createVideoProofRuntime(contract, {
		device: DEVICE,
		attach: testInfo.attach.bind(testInfo),
		captureFrame: () => page.screenshot({ type: 'png' }),
	});
}

test.describe('Project Timeline', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: direct surface=gui.web assertions=projects.history.native-commits
	test('timeline lists commits and versions and restores a commit from the web', async ({ page }: { page: any }, testInfo: TestInfo) => {
		test.setTimeout(600_000);
		const diff = await setupDifferential(page, testInfo, 'project-timeline');
		let projectId = '';
		let chatId = '';
		const run = async (args: string[]) => {
			const result = await diff.native(args);
			expect(result.code, `${args.join(' ')}\n${result.stderr}`).toBe(0);
			return parseJson(result);
		};
		const read = () => run(['projects', 'hosted', 'read', projectId, FILE, '--json']);
		const shot = async (name: string) => testInfo.attach(name, { body: await page.screenshot(), contentType: 'image/png' });
		try {
			const created = await run(['projects', 'create', naturalProjectName('Recipe manager'), '--write-policy', 'apply_and_show', '--personal', '--json']);
			projectId = pickString(created, ['project_id', 'projectId', 'id']);
			expect(projectId).not.toBe('');
			chatId = seedViaPairedCli(diff.apiUrl, diff.npmHome, 'event').chatId;
			await run(['projects', 'settings', projectId, 'focus', 'activate', '--chat', chatId, '--json']);

			await run(['projects', 'hosted', 'create', projectId, FILE, '--chat', chatId, '--text', 'const recipes = ["pancakes"];\n', '--json']);
			const commit = await run(['projects', 'commit', projectId, '--message', MESSAGE, '--chat', chatId, '--json']);
			const commitId: string = commit.commit.commit_id;
			const v1 = await read();
			await run(['projects', 'hosted', 'update', projectId, FILE, v1.expected_base, '--chat', chatId,
				`--text=${patch('const recipes = ["pancakes"];', 'const recipes = [];')}`, '--json']);
			expect((await read()).content).toBe('const recipes = [];\n');

			// CLI: newest first, the later version above the commit, the commit names its message.
			const cliTimeline = await run(['projects', 'timeline', projectId, '--json']);
			const kinds = cliTimeline.entries.map((entry: any) => entry.kind);
			expect(kinds[0]).toBe('file_version');
			expect(cliTimeline.entries[0].version).toBe(2);
			expect(cliTimeline.entries[0].path).toBe(FILE);
			const cliCommit = cliTimeline.entries.find((entry: any) => entry.kind === 'commit');
			expect(cliCommit.commit_id).toBe(commitId);
			expect(cliCommit.commit_message).toBe(MESSAGE);
			expect(kinds.indexOf('commit')).toBeGreaterThan(0);

			const proof = proofFor(page, testInfo);
			await page.setViewportSize({ width: 1440, height: 1000 });
			await page.goto(`/projects/${encodeURIComponent(projectId)}`, { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('project-workspace-header')).toBeVisible({ timeout: 60_000 });
			await page.getByTestId('project-tab-timeline').click();
			const panel = page.getByTestId('project-timeline-panel');
			const rows = panel.locator('[data-testid^="project-timeline-entry-"]');
			const commitRow = rows.filter({ hasText: MESSAGE }).first();
			await proof.assert('projects.history.native-commits.timeline-listed', async () => {
				await expect(commitRow).toBeVisible({ timeout: 60_000 });
				await expect(rows.first()).toHaveAttribute('data-kind', 'file_version');
				await expect(rows.first()).toContainText(FILE);
				await expect(rows.first()).toContainText('v2');
			});
			await proof.checkpoint('timeline-listed');
			await shot('timeline-listed');

			await proof.assert('projects.history.native-commits.restore-confirm', async () => {
				await commitRow.locator('[data-testid^="project-timeline-commit-toggle-"]').click();
				await expect(commitRow.locator('[data-testid^="project-timeline-commit-files-"]')).toContainText(FILE);
				await commitRow.locator('[data-testid^="project-timeline-restore-"]').click();
				await expect(page.getByTestId('project-timeline-restore-confirm')).toBeVisible();
			});
			await proof.checkpoint('restore-confirm');
			await shot('timeline-restore-confirm');

			await page.getByTestId('project-timeline-restore-confirm').click();
			await proof.assert('projects.history.native-commits.restored', async () => {
				// Success reloads page 1, so the restore commit tops the list and names its source.
				await expect(rows.first()).toHaveAttribute('data-kind', 'commit', { timeout: 60_000 });
				await expect(rows.first()).toContainText(commitId.slice(0, 7));
			});
			await proof.checkpoint('restored');
			await shot('timeline-restored');
			await proof.attach();

			const after = await read();
			expect(after.content).toBe('const recipes = ["pancakes"];\n');
			expect(after.revision).toBe(3);
			const later = await run(['projects', 'timeline', projectId, '--json']);
			const restoreCommit = later.entries.find((entry: any) => entry.kind === 'commit');
			expect(restoreCommit.commit_id).not.toBe(commitId);
			expect(restoreCommit.author).toBe('user');
			const shown = await run(['projects', 'commits', 'show', projectId, restoreCommit.commit_id, '--json']);
			expect(JSON.stringify(shown)).toContain(commitId);
		} finally {
			if (projectId) await diff.native(['projects', 'delete', projectId, '--confirm', projectId, '--json']);
			if (chatId) await diff.native(['chats', 'delete', chatId, '--yes']);
			await finishDifferential(diff);
		}
	});
});
