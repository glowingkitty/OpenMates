/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Native Rust CLI as the remote-access source HOST, real stack, no AI inference.
 * Assertions: projects.surface.semantic-parity, projects.files.private-path-deny,
 * projects.files.expected-base (Rust remote-access host, lane R2 first slice).
 *
 * The Rust binary runs `openmates remote-access --path <disposable folder>` and serves
 * the folder. Existing requesters then:
 *   - list and read it through the Rust CLI (`projects files list|read`),
 *   - read it through the npm CLI (cross-implementation requester),
 *   - are refused a built-in private file (.env),
 *   - create and update a file through the npm Workflow remote-copy path
 *     (`workflows add-to-project --remote-copy` -> create_file,
 *      `workflows update --file` -> update_file) on an owned, inference-free chat
 *     with the Project focus active.
 * Not proven here: --enable-commands / --task-cache (explicit Rust-host errors, unit
 * tested), copy/move entries (unsupported_operation) and the npm-host deletion.
 */
export {};
import type { TestInfo } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');
const { rustEnv } = require('./helpers/rust-cli-terminal');
const { seedViaPairedCli } = require('./helpers/owned-encrypted-embed-fixture');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

const { email, password, otpKey } = getTestAccount();

function parse(result: { stdout: string }): any {
	return JSON.parse(result.stdout);
}

/** Resolve once the host prints a lifecycle line with this state (JSON mode). */
function waitForHostState(host: any, state: string, output: { text: string }, timeoutMs = 90_000): Promise<void> {
	return new Promise((resolve, reject) => {
		const timer = setTimeout(() => reject(new Error(`remote-access host never reached ${state}:\n${output.text.slice(-2000)}`)), timeoutMs);
		const check = () => {
			for (const line of output.text.split('\n')) {
				try {
					const event = JSON.parse(line);
					if (event.type === 'remote_access_lifecycle' && event.state === state) {
						clearTimeout(timer);
						resolve();
						return;
					}
				} catch {
					// Partial or non-JSON lines are ignored until the next chunk.
				}
			}
		};
		host.stdout.on('data', check);
		host.on('exit', (code: number | null) => {
			clearTimeout(timer);
			reject(new Error(`remote-access host exited early (${code}):\n${output.text.slice(-2000)}`));
		});
	});
}

test.describe('CLI native: remote-access host', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: direct surface=cli assertions=projects.surface.semantic-parity,projects.files.private-path-deny,projects.files.expected-base
	test('Rust host serves list, read, create and update to existing requesters', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'remote-access-host');
		const folder = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'om-rust-host-')));
		fs.writeFileSync(path.join(folder, 'README.md'), '# Rust host fixture\nhello from the Rust host\n');
		fs.mkdirSync(path.join(folder, 'src'));
		fs.writeFileSync(path.join(folder, 'src', 'notes.txt'), 'notes\n');
		fs.writeFileSync(path.join(folder, '.env'), 'SECRET=never-leaves-the-host\n');
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const env = rustEnv(diff.nativeHome, diff.apiUrl, baseUrl);
		const output = { text: '' };
		let host: any = null;
		let projectId = '';
		let workflowId = '';
		try {
			host = spawn(diff.binary, ['remote-access', '--path', folder, '--personal', '--project', 'new',
				'--write-policy', 'apply_and_show', '--json'], { env, stdio: ['ignore', 'pipe', 'pipe'] });
			host.stdout.on('data', (chunk: Buffer) => (output.text += chunk.toString()));
			host.stderr.on('data', (chunk: Buffer) => (output.text += chunk.toString()));
			await waitForHostState(host, 'connected', output);

			const store = JSON.parse(fs.readFileSync(path.join(env.OPENMATES_STATE_DIR, 'remote-sources.json'), 'utf8'));
			const record = store.sources.find((source: any) => source.rootPath === folder);
			expect(record, 'the Rust host records the association in remote-sources.json').toBeTruthy();
			projectId = record.projectId;
			const sourceId = record.sourceId;
			expect(fs.statSync(path.join(env.OPENMATES_STATE_DIR, 'remote-sources.json')).mode & 0o777).toBe(0o600);

			// Rust requester: list and read.
			const listed = await diff.native(['projects', 'files', 'list', projectId, '--source', sourceId, '--personal', '--json'], 90_000);
			expect(listed.code, listed.stderr).toBe(0);
			expect(listed.stdout).toContain('README.md');
			expect(listed.stdout).toContain('src');
			expect(listed.stdout).not.toContain('.env');
			const read = await diff.native(['projects', 'files', 'read', projectId, 'README.md', '--source', sourceId, '--personal', '--json'], 90_000);
			expect(read.code, read.stderr).toBe(0);
			expect(read.stdout).toContain('hello from the Rust host');

			// npm requester against the Rust host.
			const npmRead = await diff.npm(['projects', 'files', 'read', projectId, 'src/notes.txt', '--source', sourceId, '--personal', '--json'], 90_000);
			expect(npmRead.code, npmRead.stderr).toBe(0);
			expect(npmRead.stdout).toContain('notes');
			const privateRead = await diff.native(['projects', 'files', 'read', projectId, '.env', '--source', sourceId, '--personal', '--json'], 90_000);
			expect(privateRead.code).not.toBe(0);
			expect(privateRead.stdout + privateRead.stderr).not.toContain('never-leaves-the-host');

			// Writes: an owned chat (no inference) with the Project focus active.
			const seed = seedViaPairedCli(diff.apiUrl, diff.npmHome, 'event');
			const focus = await diff.native(['projects', 'settings', projectId, 'focus', 'activate', '--chat', seed.chatId, '--personal', '--json'], 90_000);
			expect(focus.code, focus.stderr).toBe(0);
			const graph = { version: 2, trigger_node_id: null, edges: [],
				nodes: [{ id: 'message', type: 'send_chat_message', config: { title: 'Rust host note', message: 'Original host message' } }] };
			const workflow = await diff.npm(['workflows', 'create', '--title', 'Rust host file', '--graph', JSON.stringify(graph), '--json']);
			expect(workflow.code, workflow.stderr).toBe(0);
			const created = parse(workflow);
			workflowId = created.id ?? created.workflow?.id;
			expect(workflowId).toBeTruthy();

			const saved = await diff.npm(['workflows', workflowId, 'add-to-project', projectId, '--remote-copy', '--source', sourceId,
				'--remote-folder', 'src', '--source-chat', seed.chatId, '--json'], 120_000);
			expect(saved.code, saved.stderr).toBe(0);
			const remoteFile = parse(saved).remote_file;
			expect(remoteFile.status, JSON.stringify(remoteFile)).toBe('saved');
			const written = path.join(folder, remoteFile.path);
			const original = fs.readFileSync(written, 'utf8');
			expect(original).toContain('Original host message');

			const yamlPath = path.join(diff.npmHome, 'rust-host-update.workflow.yml');
			// The saved file is the portable export (for `workflows import`); `workflows update`
			// takes authoring YAML, so the edit is written in that form with the same title.
			fs.writeFileSync(yamlPath, [
				'title: Rust host file',
				'steps:',
				'  - id: message',
				'    send_chat_message:',
				'      title: Rust host note',
				'      message: Updated host message',
				''].join('\n'));
			const updated = await diff.npm(['workflows', 'update', workflowId, '--file', yamlPath, '--source-chat', seed.chatId, '--json'], 120_000);
			expect(updated.code, updated.stderr).toBe(0);
			const saves = parse(updated).remote_file_saves;
			expect(saves.some((entry: any) => entry.status === 'saved'), JSON.stringify(saves)).toBeTruthy();
			await expect.poll(() => fs.readFileSync(written, 'utf8')).toContain('Updated host message');
		} finally {
			if (host && host.exitCode === null) {
				const exited = new Promise((resolve) => host.once('exit', resolve));
				host.kill('SIGINT');
				await Promise.race([exited, new Promise((resolve) => setTimeout(resolve, 15_000))]);
				if (host.exitCode === null) host.kill('SIGKILL');
			}
			await testInfo.attach('remote-access-host-output', { body: output.text.slice(-20_000), contentType: 'text/plain' });
			if (workflowId) await diff.npm(['workflows', 'delete', workflowId, '--yes', '--json']);
			if (projectId) await diff.native(['projects', 'delete', projectId, '--confirm', projectId, '--json']);
			fs.rmSync(folder, { recursive: true, force: true });
			await finishDifferential(diff);
		}
	});
});
