/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Native Rust CLI: assistant-created Project commands (`projects created`,
 * `projects undo-create`), real stack, no AI inference.
 * Assertion: projects.creation.assistant-inferred (docs/plans/cloud-project-development, P10).
 *
 * What this proves: the commands only ever act on a Project the assistant created
 * for the chat. A user-created Project must survive `undo-create` untouched, and a
 * chat without a creation record reports "no created project".
 * Not proven here: the inference-driven path ("build me a recipe web app" ->
 * project_create_requested -> created Project + active focus in the same turn). The
 * server only emits the request after Stage-one routing and a Jev decision, so that
 * flow is verified on dev with real inference; request handling itself is covered by
 * the core unit tests (client/project_create_request_tests.rs).
 */
export {};
import type { TestInfo } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');
const { parseJson, pickString } = require('./helpers/cli-native-fixtures');

const { email, password, otpKey } = getTestAccount();
const UNKNOWN_CHAT = '00000000-0000-4000-8000-000000000000';

test.describe('CLI native: assistant-created Project commands', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=projects.creation.assistant-inferred
	test('created/undo-create never touch a Project the assistant did not create', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'project-create-request');
		let projectId = '';
		try {
			const created = await diff.native(['projects', 'create', 'Create request guard', '--slug', `create-request-guard-${Date.now()}`, '--write-policy', 'apply_and_show', '--personal', '--json']);
			expect(created.code).toBe(0);
			projectId = pickString(parseJson(created), ['project_id', 'projectId', 'id']) || '';
			expect(projectId).not.toBe('');

			const none = await diff.native(['projects', 'created', '--chat', UNKNOWN_CHAT, '--json']);
			expect(none.code).not.toBe(0);
			const refused = await diff.native(['projects', 'undo-create', '--chat', UNKNOWN_CHAT, '--json']);
			expect(refused.code).not.toBe(0);

			const missingChat = await diff.native(['projects', 'undo-create']);
			expect(missingChat.code).not.toBe(0);
			expect(missingChat.stderr).toContain('--chat');

			const still = await diff.native(['projects', 'show', projectId, '--json']);
			expect(still.code).toBe(0);
		} finally {
			if (projectId) await diff.native(['projects', 'delete', projectId, '--confirm', projectId, '--json']);
			await finishDifferential(diff);
		}
	});
});
