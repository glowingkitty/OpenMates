/*
Purpose: End-to-end smoke test of login + send chat on LIVE production.
         Uses a pre-existing persistent test account (no signup, no payment),
         so it does not pollute prod with new users every hour.
Architecture: Part of the hourly prod smoke suite (OPE-76). Complements
              prod-smoke-signup-giftcard-chat.spec.ts which exercises the
              cold-boot flow — this spec instead catches regressions in the
              login + WebSocket chat pipeline for a stable account.
Tests: N/A (this file is the Playwright E2E test entrypoint).

Required env vars (set by .github/workflows/prod-smoke.yml from repo secrets):
- PLAYWRIGHT_TEST_BASE_URL — prod base URL (https://app.openmates.org)
- OPENMATES_TEST_ACCOUNT_EMAIL / _PASSWORD / _OTP_KEY — persistent prod test account
*/
/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
const { test, expect } = require('@playwright/test');

const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	waitForAssistantResponse,
	deleteActiveChat
} = require('../helpers/chat-test-helpers');

const PROD_BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || '';

test.beforeAll(() => {
	if (!PROD_BASE_URL) {
		throw new Error('PLAYWRIGHT_TEST_BASE_URL must be set for prod-smoke specs.');
	}
	// Guard against pointing this at dev — loud failure is better than silent
	// "smoke passing" on the wrong environment.
	if (/localhost|dev\./i.test(PROD_BASE_URL)) {
		throw new Error(
			`PLAYWRIGHT_TEST_BASE_URL looks like a dev URL (${PROD_BASE_URL}). ` +
				'Prod smoke specs must run against production.'
		);
	}
});

test('prod login + new chat + AI response', async ({ page }: { page: any }) => {
	test.slow();
	// Prod WebSocket setup + AI response can take longer than dev's mocked
	// path — 4 min is comfortable margin without being a timeout sink.
	test.setTimeout(240000);

	const log = (msg: string) => console.log(`[prod-smoke-login-chat] ${msg}`);

	// 1. Log in with the persistent prod test account.
	await loginToTestAccount(page, log);
	log('Login completed.');

	// 2. Start a new chat so we don't contaminate an existing one.
	await startNewChat(page, log);
	log('Started new chat.');

	// 3. Send a fixed deterministic prompt. We intentionally pick something that
	// does NOT require tool calls — pure text-generation keeps this test fast
	// and independent of skill/provider availability.
	const PROMPT = 'Reply with just the word: PONG';
	await sendMessage(page, PROMPT, log);
	log('Message sent.');

	// 4. Wait for the assistant message to appear. waitForAssistantResponse
	// only checks visibility; we additionally wait for the message to contain
	// non-empty content as a sanity check that streaming actually started.
	const assistantMessages = await waitForAssistantResponse(page, 120000);
	const last = assistantMessages.last();
	await expect(last).toBeVisible({ timeout: 120000 });
	await expect(last).not.toBeEmpty({ timeout: 60000 });
	log('Assistant response received and non-empty.');

	// 5. Best-effort cleanup so the test account doesn't accumulate chat rows
	// forever. Failure is non-fatal — the helper already swallows errors.
	await deleteActiveChat(page, log);
	log('Cleanup attempted.');
});
