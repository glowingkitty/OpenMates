// playwright-account: not_required reason=signed_out_guest_production_smoke
// proof-video: not_required reason=visual_smoke_not_needed
/*
Purpose: Hourly production check that a signed-out visitor in a fresh browser
         gets an active Send in the web composer, that Send sends, and that an
         assistant reply appears. A disabled or greyed Send, a Sign up button
         in place of Send, or a send that never reaches the server fails it.
Architecture: Runs in the free-hourly suite of .github/workflows/prod-smoke.yml
              (after the reachability spec) and in the update-prod-server
              post-deploy checks. Uses the guest allowance: one short message.
Spec: specifications/features/message-input/specification.yml
      (message-input.signed-out-two-states).
*/
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
const { test, expect } = require('../helpers/cookie-audit');

const PROD_BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
test.beforeAll(() => {
	if (!PROD_BASE_URL) throw new Error('PLAYWRIGHT_TEST_BASE_URL must be set for prod-smoke specs.');
});

// contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
test('prod signed-out web send: active Send sends and gets a reply', async ({ page }: { page: any }, testInfo: any) => {
	test.setTimeout(150_000);
	await page.addInitScript(() => {
		const seen: string[] = [];
		(window as any).__disabledSendSeen = seen;
		const check = () => {
			for (const el of document.querySelectorAll('[data-testid="composer-send-button"], [data-action="send-message"]')) {
				if ((el as HTMLButtonElement).disabled && !(window as any).__sendClicked) seen.push(el.outerHTML.slice(0, 160));
			}
		};
		new MutationObserver(check).observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ['disabled'] });
	});
	const streamRequests: string[] = [];
	page.on('request', (request: any) => {
		if (request.url().includes('/v1/anonymous/chat/stream')) streamRequests.push(request.url());
	});

	await page.goto('/', { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('header-login-signup-btn')).toBeAttached({ timeout: 30_000 });
	const newChatCta = page.getByTestId('new-chat-cta-fullwidth');
	if (await newChatCta.isVisible().catch(() => false)) await newChatCta.click();

	const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
	await page.getByTestId('message-field').first().click();
	await editor.click();
	await editor.pressSequentially('What is the capital of France? Answer in one word.');

	// Signed out, only Send or Sign up / Log in may resolve; Sign up here means guest chat is broken.
	// A control leaving through its Svelte out-transition stays in the DOM for ~150 ms marked
	// `inert`; only the live control counts, so a Sign up -> Send crossfade is not a strict-mode
	// failure (prod run 43756020772). The settled control must still be Send.
	const send = page.locator('[data-action="send-message"]:not([inert])').first();
	const accountCta = page.locator('[data-action="sign-up-to-send"]:not([inert])').first();
	await expect(send.or(accountCta)).toBeVisible({ timeout: 20_000 });
	if (await accountCta.isVisible().catch(() => false)) {
		testInfo.annotations.push({ type: 'guest-sign-up-flash', description: 'Sign up showed before the guest composer settled' });
	}
	await testInfo.attach('guest-composer-before-send', { body: await page.screenshot(), contentType: 'image/png' });
	await expect(accountCta, 'a fresh signed-out browser must get Send, not Sign up').toHaveCount(0, { timeout: 10_000 });
	await expect(send).toBeVisible();
	await expect(send).toBeEnabled();
	expect(await page.evaluate(() => (window as any).__disabledSendSeen), 'no disabled Send before sending').toEqual([]);
	// After the click a send that never starts is caught by the request poll below.
	await page.evaluate(() => { (window as any).__sendClicked = true; });
	await send.click();

	await expect.poll(() => streamRequests.length, { message: 'Send must reach the guest chat endpoint', timeout: 30_000 }).toBeGreaterThan(0);
	const reply = page.getByTestId('message-assistant').last();
	await expect(reply).toBeVisible({ timeout: 90_000 });
	await expect(reply).toContainText(/paris/i, { timeout: 90_000 });
	await testInfo.attach('guest-reply', { body: await page.screenshot(), contentType: 'image/png' });
});
