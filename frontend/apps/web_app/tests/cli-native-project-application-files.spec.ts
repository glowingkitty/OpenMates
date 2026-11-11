/* eslint-disable @typescript-eslint/no-require-imports */
// proof-video: not_required reason=visual_smoke_not_needed (CLI JSON contract; native login is recorded in a real terminal)
/**
 * Native Rust CLI: application files become Project files (plan
 * cloud-project-development P11, contract
 * docs/plans/cloud-project-development/contracts/project-embed-adoption.md),
 * real stack. The reply comes from the committed `application_preview`
 * TEST_MOCK fixture on the real API/AI worker (no provider inference).
 * Assertions: projects.files.application-single-source, projects.files.adopt-embed,
 * projects.files.rename-delete.
 *
 * What this proves: with an active Project focus, a turn that produces an
 * application embed with child code files makes the core adopt each finished
 * child at `web-app/<path>` and the application itself (send outcome rows all
 * `adopted`); the hosted listing shows those files (and never the application
 * folder link as a file), the files keep a path-derived non-`text` language,
 * and `projects hosted rename` / `delete` change the listing while the embed
 * stays readable.
 * Not proven here: the assistant `project_rename_file` / `project_delete_file`
 * job path (covered by core unit tests and backend pytest), always_ask approval,
 * test-result adoption and Team Projects.
 */
export {};
import type { TestInfo } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount, withMockMarker } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');
const { parseJson, pickString } = require('./helpers/cli-native-fixtures');

const { email, password, otpKey } = getTestAccount();
const FOLDER = 'web-app';
const APP_FILE = `${FOLDER}/src/App.svelte`;
const MANIFEST = `${FOLDER}/package.json`;
const RENAMED = `${FOLDER}/src/Main.svelte`;

type Adoption = { embed_id?: string; kind?: string; path?: string | null; status?: string; code?: string };

/** Every `language` value anywhere in a decoded embed detail. */
function languages(value: unknown, out: string[] = []): string[] {
	if (Array.isArray(value)) value.forEach((entry) => languages(entry, out));
	else if (value && typeof value === 'object') {
		for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
			if (key === 'language' && typeof entry === 'string') out.push(entry);
			else languages(entry, out);
		}
	}
	return out;
}

function listedPaths(listing: any): string[] {
	const rows = Array.isArray(listing?.entries) ? listing.entries : [];
	return rows.map((row: any) => String(row?.path ?? '')).filter(Boolean);
}

test.describe('CLI native: application files as Project files', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=projects.files.application-single-source,projects.files.adopt-embed,projects.files.rename-delete
	test('adopt application files into the focused Project, then rename and delete one', async ({ page }: { page: any }, testInfo: TestInfo) => {
		test.setTimeout(900_000);
		expect(process.env.E2E_USE_MOCKS, 'Committed fixture replies only; never paid inference').toBeTruthy();
		// A protocol failure of a send then names its phase and last frame type on
		// stderr (opt-in, no payload content), which the failure message prints.
		process.env.OPENMATES_TEST_SEND_PHASE_DIAGNOSTIC = '1';
		const diff = await setupDifferential(page, testInfo, 'project-application-files');
		let projectId = '';
		let chatId = '';
		const run = async (args: string[], timeoutMs?: number) => {
			const result = await diff.native(args, timeoutMs);
			expect(result.code, `${args.join(' ')}\nstderr: ${result.stderr}\nstdout: ${String(result.stdout).slice(-1500)}`).toBe(0);
			return parseJson(result);
		};
		const marked = (text: string, fixture: string, speed?: string) => {
			const value = withMockMarker(text, fixture, speed);
			expect(value).toContain('<<<TEST_MOCK:');
			return value;
		};
		const list = async () => listedPaths(await run(['projects', 'hosted', 'list', projectId, '--json']));
		try {
			const created = await run(['projects', 'create', 'Application files', '--slug', `application-files-${Date.now()}`, '--write-policy', 'apply_and_show', '--personal', '--json']);
			projectId = pickString(created, ['project_id', 'projectId', 'id']);
			expect(projectId).not.toBe('');

			// Project focus resolves the chat on the server, so the chat must exist
			// there first: one ordinary mocked turn creates it.
			const opened = await run(['chats', 'new', marked('@Gemini-3.8-Flash Capital of Germany?', 'chat_flow_capital'), '--json'], 180_000);
			chatId = pickString(opened, ['chatId', 'chat_id']);
			expect(chatId).toMatch(/^[0-9a-f-]{36}$/);
			await run(['projects', 'settings', projectId, 'focus', 'activate', '--chat', chatId, '--json']);

			// The application turn: the fixture waits ~30 s before streaming.
			const turn = await run(['chats', 'send', '--chat', chatId, marked('Create a tiny Svelte recipe manager application with package.json and src/App.svelte.', 'application_preview'), '--json'], 420_000);
			expect(turn.status).toBe('completed');
			const adoptions: Adoption[] = turn.projectEmbedAdoptions ?? turn.project_embed_adoptions ?? [];
			expect(adoptions.length, JSON.stringify(adoptions)).toBeGreaterThanOrEqual(3);
			for (const row of adoptions) expect(row.status, JSON.stringify(row)).toBe('adopted');
			const files = adoptions.filter((row) => row.kind === 'file');
			expect(files.map((row) => row.path).sort()).toEqual([`${FOLDER}/index.html`, MANIFEST, APP_FILE, `${FOLDER}/src/main.ts`].sort());
			const application = adoptions.filter((row) => row.kind === 'application');
			expect(application).toHaveLength(1);
			expect(application[0].path).toBe(FOLDER);

			// The listing shows the adopted files, never the application folder link.
			const listed = await list();
			expect(listed).toEqual(expect.arrayContaining([MANIFEST, APP_FILE]));
			expect(listed).not.toContain(FOLDER);

			// The adopted file is the chat's embed, readable through the Project.
			const read = await run(['projects', 'hosted', 'read', projectId, APP_FILE, '--json']);
			expect(String(read.content)).toContain('Recipe Manager');
			const appEmbed = files.find((row) => row.path === APP_FILE)?.embed_id ?? '';
			expect(read.embed_id).toBe(appEmbed);
			// Language follows the extension, not a fixed `text`.
			const detail = await run(['embeds', 'show', appEmbed, '--json'], 60_000);
			const langs = languages(detail);
			expect(langs.length, JSON.stringify(detail).slice(0, 400)).toBeGreaterThan(0);
			expect(langs).not.toContain('text');

			// Rename keeps the embed and moves the link; the old path disappears.
			const renamed = await run(['projects', 'hosted', 'rename', projectId, APP_FILE, RENAMED, '--chat', chatId, '--json']);
			expect(renamed.renamed).toBe(true);
			expect(renamed.path).toBe(RENAMED);
			expect(renamed.embed_id).toBe(appEmbed);
			let after = await list();
			expect(after).toContain(RENAMED);
			expect(after).not.toContain(APP_FILE);
			expect((await run(['projects', 'hosted', 'read', projectId, RENAMED, '--json'])).embed_id).toBe(appEmbed);

			// Renaming onto a linked path is refused as a path conflict.
			const clash = await diff.native(['projects', 'hosted', 'rename', projectId, RENAMED, MANIFEST, '--chat', chatId, '--json']);
			expect(clash.code).not.toBe(0);
			expect(clash.stdout + clash.stderr).toContain('path_conflict');

			// Delete removes only the link.
			const deleted = await run(['projects', 'hosted', 'delete', projectId, MANIFEST, '--chat', chatId, '--json']);
			expect(deleted.deleted).toBe(true);
			after = await list();
			expect(after).not.toContain(MANIFEST);
			expect(after).toContain(RENAMED);
		} finally {
			if (projectId) await diff.native(['projects', 'delete', projectId, '--confirm', projectId, '--json']);
			if (chatId) await diff.native(['chats', 'delete', chatId, '--yes']);
			await finishDifferential(diff);
		}
	});
});
