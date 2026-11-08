/**
 * Native vs npm CLI: the `plans` lifecycle (create, start..done refusals, archive, delete, chat attach,
 * project linking). Reads, edits and dependencies are cli-native-plans.spec.ts.
 *
 * Not covered (native gaps, commands stay unverified): `plans activate|approve|attach` need a chat and
 * `plans ask` needs AI inference, neither available in CI (`chats new` times out waiting for the AI);
 * `plans create` and the refused start/resume/complete/done transitions differ in stderr class (see gaps below).
 * Harness: helpers/cli-native-differential.ts (npm CLI vs native Rust binary, same account).
 *
 * One-way state transitions give each CLI its own identical fresh fixture (`argsFor`), so only
 * the per-fixture `short_id` and the optimistic-lock `version` counter are ignored.
 */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
import type { TestInfo } from '@playwright/test';

const { test } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');
const { VOLATILE, createFixtures, logAbort, npmJson, perSide } = require('./helpers/cli-native-plans-fixtures');

const { email, password, otpKey } = getTestAccount();

type Side = 'npm' | 'native';

test.describe('CLI native differential: plans lifecycle', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('plan lifecycle commands match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'plans-lifecycle', { paceMs: 4_000 });
		const fx = await createFixtures(diff, 'lifecycle');
		try {
			const base = await fx.plan('Differential base plan');
			// A second Plan with an existing title is refused with HTTP 409, so each CLI creates its own title.
			// Titles carry a timestamp so a retried attempt never hits the duplicate-title HTTP 409.
			await diff.check('plans create', [], { argsFor: (side: Side) => ['plans', 'create', '--title', `Differential created plan ${side} ${Date.now()}`, '--goal', 'Created goal', '--project', fx.projectId], ignoreKeys: [...VOLATILE, 'title', 'slug'], catalog: ['plans create'] });
			const fresh = perSide(() => fx.plan('Differential transition plan'));
			// The backend starts a Plan only after a human approves a revision in the web app, so a CI Plan can
			// never leave todo: start/pause/resume/complete/done are refused (HTTP 400) and compare the error outcome.
			const todo = perSide(() => fx.plan('Differential transition plan'));
			const transition = (label: string, source: ReturnType<typeof perSide<string>>, argv: (id: string) => string[], catalog: string[], options: Record<string, unknown> = {}) =>
				diff.check(label, [], { before: source.before, argsFor: (side: Side) => argv(source.get(side)), ignoreKeys: [...VOLATILE, 'title', 'slug'], catalog, ...options });
			const refused = { mode: 'exit' };
			// Native reports the refused HTTP status as a generic SDK error: same exit code, different stderr class.
			const statusGap = { ...refused, expectedGap: 'stderr class: npm=http-client-error native=other' };
			await transition('plans start', todo, (id) => ['plans', 'start', id], ['plans start'], statusGap);
			await transition('plans pause', todo, (id) => ['plans', 'pause', id], ['plans pause'], refused);
			await transition('plans resume', todo, (id) => ['plans', 'resume', id], ['plans resume'], statusGap);
			// npm reports the unparseable 200 completion body as "failed with HTTP 200" (class other); native as validation.
			const completeGap = { ...refused, expectedGap: 'stderr class: npm=other native=validation' };
			await transition('plans complete', todo, (id) => ['plans', 'complete', id], ['plans complete'], completeGap);
			await transition('plans done', todo, (id) => ['plans', 'done', id], ['plans done'], completeGap);
			await transition('plans archive', fresh, (id) => ['plans', 'archive', id], ['plans archive']);
			// The opaque encrypted history snapshot refs are produced per client and cannot match byte for byte.
			await transition('plans delete', fresh, (id) => ['plans', 'delete', id, '--confirm'], ['plans delete'], { ignoreKeys: [...VOLATILE, 'title', 'slug', 'encrypted_before_ref', 'encrypted_after_ref'] });
			// npm exits 1 for the missing --confirm, native treats it as a usage error (exit 2).
			await diff.check('plans delete without --confirm', ['plans', 'delete', base], { mode: 'exit', expectedGap: 'exit: npm=1 native=2' });

			const second = await npmJson(diff, ['projects', 'create', `Diff plans second ${Date.now()}`, '--write-policy', 'apply_and_show'], 'create second project');
			const secondId: string = second.projectId ?? second.project_id ?? second.project?.project_id;
			try {
				await transition('plans add-to-project', fresh, (id) => ['plans', id, 'add-to-project', secondId], ['plans add-to-project']);
				const linked = perSide(async () => { const id = await fx.plan('Differential transition plan'); await npmJson(diff, ['plans', id, 'add-to-project', secondId], 'link second project'); return id; });
				await transition('plans remove-from-project', linked, (id) => ['plans', id, 'remove-from-project', secondId], ['plans remove-from-project']);
			} finally {
				await diff.npm(['projects', 'delete', secondId, '--confirm', secondId, '--json']);
			}
		} catch (error) {
			logAbort(error);
		} finally {
			await fx.cleanup();
			await finishDifferential(diff);
		}
	});
});
