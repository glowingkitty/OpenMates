/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Native vs npm CLI: teams commands (except Team direct messages, owned by the messaging lane,
 * and payment commands such as add-credits / bank-transfer create, checked only for usage errors).
 * Harness: helpers/cli-native-differential.ts (npm CLI vs native Rust binary, same account).
 * Each CLI creates its own throwaway Team (create -> read -> update -> delete).
 */
export {};
import type { TestInfo } from '@playwright/test';

const fs = require('node:fs');
const path = require('node:path');
const { test } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');
const { bothIds, pickId } = require('./helpers/cli-native-fixtures');

const { email, password, otpKey } = getTestAccount();
const UNKNOWN = '00000000-0000-4000-8000-000000000000';
const TEAM_KEYS = ['team_id', 'teamId', 'id'];
// Per-Team random ciphertexts, key wraps and hashes differ between the two CLIs' own Teams.
const VOLATILE = ['slug', 'encrypted_name', 'encrypted_description', 'encrypted_profile_image_metadata', 'encrypted_team_key', 'hashed_team_id'];
// 1x1 transparent PNG.
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=', 'base64');

test.describe('CLI native differential: teams', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('team commands match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'teams');
		const cleanup: Array<() => Promise<unknown>> = [];
		try {
			await diff.check('teams help', ['teams'], { mode: 'exit', catalog: ['teams'] });
			await diff.check('teams list', ['teams', 'list'], { structureOnly: true, catalog: ['teams list'] });
			const userId = pickId(await diff.npm(['whoami', '--json']), ['user_id', 'userId', 'id']) || UNKNOWN;

			// Create one Team per CLI.
			// Team slugs are unique, so each CLI gets its own slug (ignored in the comparison).
			const createArgs = (slug: string) => ['teams', 'create', '--name', 'Differential team', '--slug', slug, '--description', 'npm vs native'];
			const created = await diff.check('teams create', createArgs(`differential-npm-${Date.now()}`), { nativeArgs: createArgs(`differential-native-${Date.now()}`), ignoreKeys: VOLATILE, catalog: ['teams create'] });
			const team = bothIds(created, TEAM_KEYS);
			if (team.npm) cleanup.push(() => diff.npm(['teams', 'delete', team.npm, '--yes', '--json']));
			if (team.native) cleanup.push(() => diff.native(['teams', 'delete', team.native, '--yes', '--json']));
			const t = team.npm || UNKNOWN;
			const homes = { npm: diff.npmHome, native: diff.nativeHome };
			for (const home of Object.values(homes)) fs.writeFileSync(path.join(home, 'avatar.png'), PNG);

			// Read (npm Team on both CLIs).
			await diff.check('teams show', ['teams', 'show', t], { ignoreKeys: VOLATILE, catalog: ['teams show'] });
			await diff.check('teams billing', ['teams', 'billing', t], { catalog: ['teams billing'] });
			await diff.check('teams billing address show', ['teams', 'billing', 'address', 'show', t], { catalog: ['teams billing address'] });
			await diff.check('teams billing bank-transfer list', ['teams', 'billing', 'bank-transfer', 'list', t], { catalog: ['teams billing bank-transfer list'] });
			await diff.check('teams billing bank-transfer status (unknown order)', ['teams', 'billing', 'bank-transfer', 'status', t, UNKNOWN], { catalog: ['teams billing bank-transfer status'] });
			await diff.check('teams billing bank-transfer create (missing --credits)', ['teams', 'billing', 'bank-transfer', 'create', t], { mode: 'exit', catalog: ['teams billing bank-transfer create'], expectedGap: 'exit: npm=1 native=2' });
			await diff.check('teams add-credits (missing team)', ['teams', 'add-credits'], { mode: 'exit', catalog: ['teams add-credits'], expectedGap: 'exit: npm=1 native=2' });
			await diff.check('teams storage', ['teams', 'storage', t], { catalog: ['teams storage'] });
			await diff.check('teams storage notice', ['teams', 'storage', 'notice', t, '--limit', '5'], { catalog: ['teams storage notice'] });
			await diff.check('teams usage', ['teams', 'usage', t], { catalog: ['teams usage'] });
			await diff.check('teams access-requests', ['teams', 'access-requests', t, '--status', 'all'], { catalog: ['teams access-requests'] });
			for (const group of ['member', 'members']) {
				await diff.check(`teams ${group} list`, ['teams', group, 'list', t], { catalog: [`teams ${group} list`] });
				await diff.check(`teams ${group} show`, ['teams', group, 'show', t, userId], { catalog: [`teams ${group} show`] });
			}
			await diff.check('teams profile get', ['teams', 'profile', 'get', t], { catalog: ['teams profile get'] });
			await diff.check('teams profile show', ['teams', 'profile', 'show', t], { catalog: ['teams profile show'] });

			// Update (each CLI its own Team).
			const mutate = (label: string, build: (id: string, home: string) => string[], catalog: string[], extra: Record<string, unknown> = {}) =>
				diff.check(label, build(t, homes.npm), { nativeArgs: build(team.native || UNKNOWN, homes.native), ignoreKeys: VOLATILE, catalog, ...extra });
			await mutate('teams update', (id) => ['teams', 'update', id, '--description', 'updated by differential'], ['teams update']);
			await mutate('teams profile edit', (id) => ['teams', 'profile', 'edit', id, '--name', 'Differential owner'], ['teams profile edit']);
			await mutate('teams profile-image generated', (id) => ['teams', 'profile-image', 'generated', id, '--icon', 'star', '--background-color', '#3366ff'], ['teams profile-image generated']);
			await mutate('teams profile-image upload', (id, home) => ['teams', 'profile-image', 'upload', id, '--file', path.join(home, 'avatar.png')], ['teams profile-image upload'], { structureOnly: true, expectedGap: 'stderr class: npm=other native=validation' });
			await mutate('teams profile-image get', (id, home) => ['teams', 'profile-image', 'get', id, '--output', path.join(home, 'avatar-out.png')], ['teams profile-image get']);
			await mutate('teams invite', (id) => ['teams', 'invite', id, '--email', 'differential-invitee@example.com', '--role', 'member'], ['teams invite'], { structureOnly: true });
			await mutate('teams role (unknown user)', (id) => ['teams', 'role', id, '--user', UNKNOWN, '--role', 'viewer'], ['teams role']);
			await mutate('teams remove-member (unknown user)', (id) => ['teams', 'remove-member', id, '--user', UNKNOWN], ['teams remove-member']);
			await mutate('teams approve-access (unknown request)', (id) => ['teams', 'approve-access', id, UNKNOWN], ['teams approve-access']);
			await mutate('teams reject-access (unknown request)', (id) => ['teams', 'reject-access', id, UNKNOWN], ['teams reject-access']);
			await diff.check('teams accept-invite (unknown invite)', ['teams', 'accept-invite', UNKNOWN], { catalog: ['teams accept-invite'] });
			await diff.check('teams decline-invite (unknown invite)', ['teams', 'decline-invite', UNKNOWN], { catalog: ['teams decline-invite'] });
			await mutate('teams move (unknown project)', (id) => ['teams', 'move', id, '--type', 'project', '--id', UNKNOWN, '--yes'], ['teams move'], { expectedGap: 'stderr class: npm=http-not-found native=other' });
			await mutate('teams switch', (id) => ['teams', 'switch', id], ['teams switch']);
			await mutate('teams personal', () => ['teams', 'personal'], ['teams personal']);
			await mutate('teams switch-to', (id) => ['teams', id, 'switch-to'], ['teams switch-to']);
			await diff.check('teams personal (restore)', ['teams', 'personal'], { catalog: ['teams personal'] });

			// Export -> import into a new Team -> delete the imported Team.
			await mutate('teams export', (id, home) => ['teams', 'export', id, '--output', path.join(home, 'team-export.json')], ['teams export'], { structureOnly: true });
			const imported = await mutate('teams import', (_id, home) => ['teams', 'import', '--file', path.join(home, 'team-export.json'), '--new-team-name', home === homes.npm ? 'Differential import npm' : 'Differential import native'], ['teams import'], { structureOnly: true });
			const importedTeam = bothIds(imported, TEAM_KEYS);
			if (importedTeam.npm) cleanup.push(() => diff.npm(['teams', 'delete', importedTeam.npm, '--yes', '--json']));
			if (importedTeam.native) cleanup.push(() => diff.native(['teams', 'delete', importedTeam.native, '--yes', '--json']));

			// Delete.
			await mutate('teams delete', (id) => ['teams', 'delete', id, '--yes'], ['teams delete'], { expectedGap: 'exit: npm=null native=1' });
			await mutate('teams show (deleted)', (id) => ['teams', 'show', id], ['teams show']);
		} finally {
			for (const undo of cleanup) await undo();
			await diff.npm(['teams', 'personal', '--json']);
			await finishDifferential(diff);
		}
	});
});
