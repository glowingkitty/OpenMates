// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed
/**
 * Signed-out composer states on the isolated MessageInput preview.
 *
 * A signed-out visitor sees an active Send, or Sign up / Log in with a visible
 * reason, or a short loading state while guest access is checked. A disabled
 * Send must never render, whatever the status endpoint, storage or demo flags do.
 * Spec: specifications/features/message-input/specification.yml
 * (message-input.signed-out-two-states).
 */
import type { Page, Route, TestInfo } from '@playwright/test';
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const OPEN = { active: true, can_send_text: true, reason: null };
const EXHAUSTED = { active: false, can_send_text: false, reason: 'per_identity_exhausted' };

type StatusMode = { kind: 'json'; body: Record<string, unknown>; delayMs?: number } | { kind: 'error' } | { kind: 'hang' };

async function mockGuestStatus(page: Page, mode: StatusMode) {
	await page.route('**/v1/settings/server-status', (route) => route.fulfill({ json: {
		is_self_hosted: false, payment_enabled: true, server_edition: 'development', ai_models_configured: true,
		anonymous_free_usage: mode.kind === 'json' ? mode.body : OPEN,
	} }));
	await page.route('**/v1/anonymous/free-usage/status**', async (route: Route) => {
		if (mode.kind === 'hang') return; // never answers
		if (mode.kind === 'error') return route.fulfill({ status: 503, json: { detail: 'unavailable' } });
		if (mode.delayMs) await new Promise((resolve) => setTimeout(resolve, mode.delayMs));
		await route.fulfill({ json: mode.body });
	});
}

/** Record any disabled Send that renders at any moment, not just at assertion time. */
async function watchForDisabledSend(page: Page) {
	await page.addInitScript(() => {
		const seen: string[] = [];
		(window as typeof window & { __disabledSendSeen?: string[] }).__disabledSendSeen = seen;
		const check = () => {
			for (const el of document.querySelectorAll<HTMLButtonElement>(
				'[data-testid="composer-send-button"], [data-action="send-message"]'
			)) {
				if (el.disabled || el.getAttribute('aria-disabled') === 'true') seen.push(el.outerHTML.slice(0, 160));
			}
		};
		new MutationObserver(check).observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ['disabled', 'aria-disabled'] });
	});
}

async function expectNoDisabledSendSeen(page: Page) {
	expect(await page.evaluate(() => (window as typeof window & { __disabledSendSeen?: string[] }).__disabledSendSeen ?? [])).toEqual([]);
}

async function openSignedOutComposer(page: Page, init?: () => void) {
	await watchForDisabledSend(page);
	if (init) await page.addInitScript(init);
	const params = new URLSearchParams({ theme: 'light', background: '#dbeafe', width: '600', chrome: '0' });
	await page.goto(`/dev/preview/enter_message/MessageInput?${params}`);
	await waitForComponentPreview(page);
	await page.getByTestId('message-field').click();
	await page.getByTestId('message-editor').locator('[contenteditable="true"]').first().fill('Capital of France?');
}

async function attach(testInfo: TestInfo, page: Page, name: string) {
	await testInfo.attach(name, { body: await page.getByTestId('component-preview-canvas').screenshot(), contentType: 'image/png' });
}

test.describe('Signed-out composer states', () => {
	test.use({ viewport: { width: 680, height: 700 } });

	// contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
	test('shows a short loading state while access is checked, then an active Send', async ({ page }, testInfo) => {
		await mockGuestStatus(page, { kind: 'json', body: OPEN, delayMs: 2500 });
		await openSignedOutComposer(page);
		const loading = page.getByTestId('composer-send-loading');
		await expect(loading).toBeVisible();
		await expect(loading).toHaveAttribute('role', 'status');
		await expect(page.getByTestId('composer-account-cta')).toHaveCount(0);
		await attach(testInfo, page, 'guest-loading');
		const send = page.getByTestId('action-buttons').getByTestId('composer-send-button');
		await expect(send).toBeVisible({ timeout: 10_000 });
		await expect(send).toBeEnabled();
		// Loading leaves at once, so it never shows next to the resolved control.
		expect(await loading.count()).toBe(0);
		await expect(page.getByTestId('guest-access-reason')).toHaveCount(0);
		await attach(testInfo, page, 'guest-send');
		await expectNoDisabledSendSeen(page);
	});

	// contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
	test('offers Sign up with a reason when the access check fails', async ({ page }, testInfo) => {
		await mockGuestStatus(page, { kind: 'error' });
		await openSignedOutComposer(page);
		const cta = page.getByTestId('composer-account-cta');
		await expect(cta).toBeVisible({ timeout: 10_000 });
		await expect(cta).toHaveAttribute('data-action', 'sign-up-to-send');
		await expect(page.getByTestId('guest-access-reason')).toHaveAttribute('data-reason', 'status_unavailable');
		await expect(page.getByTestId('guest-access-reason')).not.toBeEmpty();
		await attach(testInfo, page, 'guest-status-failed');
		await expectNoDisabledSendSeen(page);
	});

	// contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
	test('resolves a hanging access check to Sign up instead of loading forever', async ({ page }, testInfo) => {
		test.setTimeout(60_000);
		await mockGuestStatus(page, { kind: 'hang' });
		await openSignedOutComposer(page);
		await expect(page.getByTestId('composer-send-loading')).toBeVisible();
		await expect(page.getByTestId('composer-account-cta')).toBeVisible({ timeout: 12_000 });
		expect(await page.getByTestId('composer-send-loading').count()).toBe(0);
		await expect(page.getByTestId('guest-access-reason')).toHaveAttribute('data-reason', 'status_unavailable');
		await attach(testInfo, page, 'guest-status-hang-resolved');
		// A retry on refocus stays on Sign up until it succeeds; it never loops back to loading.
		await page.evaluate(() => {
			const w = window as typeof window & { __loadingSeenAgain?: number };
			w.__loadingSeenAgain = 0;
			new MutationObserver(() => {
				if (document.querySelector('[data-testid="composer-send-loading"]')) w.__loadingSeenAgain! += 1;
			}).observe(document, { subtree: true, childList: true });
		});
		await page.mouse.click(4, 4);
		await page.getByTestId('message-field').click();
		await expect(page.getByTestId('composer-account-cta')).toBeVisible();
		await page.waitForTimeout(9_000); // longer than one access-check timeout
		await expect(page.getByTestId('composer-account-cta')).toBeVisible();
		expect(await page.evaluate(() => (window as typeof window & { __loadingSeenAgain?: number }).__loadingSeenAgain)).toBe(0);
		await expectNoDisabledSendSeen(page);
	});

	// contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
	test('offers Log in with a reason to a browser that has logged in before', async ({ page }, testInfo) => {
		await mockGuestStatus(page, { kind: 'json', body: OPEN });
		await openSignedOutComposer(page, () => localStorage.setItem('openmates:last-auth-method', 'email'));
		await expect(page.getByTestId('composer-account-cta')).toBeVisible();
		await expect(page.getByTestId('composer-account-cta')).toContainText(/log\s?in/i);
		await expect(page.getByTestId('guest-access-reason')).toHaveAttribute('data-reason', 'logged_in_before');
		await expect(page.getByTestId('action-buttons').getByTestId('composer-send-button')).toHaveCount(0);
		await attach(testInfo, page, 'guest-logged-in-before');
		await expectNoDisabledSendSeen(page);
	});

	// contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
	test('names an exhausted allowance as the reason for Sign up', async ({ page }, testInfo) => {
		await mockGuestStatus(page, { kind: 'json', body: EXHAUSTED });
		await openSignedOutComposer(page);
		await expect(page.getByTestId('composer-account-cta')).toBeVisible();
		await expect(page.getByTestId('guest-access-reason')).toHaveAttribute('data-reason', 'usage_limit');
		await attach(testInfo, page, 'guest-usage-limit');
		await expectNoDisabledSendSeen(page);
	});

	// contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
	test('a leftover demo flag does not turn Send into a visual-only or disabled control', async ({ page }, testInfo) => {
		await mockGuestStatus(page, { kind: 'json', body: OPEN });
		await openSignedOutComposer(page, () => localStorage.setItem('demo_mode_enabled', 'true'));
		const send = page.getByTestId('action-buttons').getByTestId('composer-send-button');
		await expect(send).toBeVisible();
		await expect(send).toBeEnabled();
		await attach(testInfo, page, 'guest-demo-flag-send');
		await expectNoDisabledSendSeen(page);
	});

	for (const knownDevice of [false, true]) {
		for (const action of ['record', 'files'] as const) {
			// contract-test: direct surface=gui.web assertions=message-input.signed-out-action-access
			test(`blocks ${action} before media starts on a ${knownDevice ? 'known' : 'new'} device`, async ({ page }, testInfo) => {
				// Files are account-only, even while free text and dictation are available.
				await mockGuestStatus(page, { kind: 'json', body: action === 'record' ? EXHAUSTED : OPEN });
				await page.addInitScript(() => {
					const starts: string[] = [];
					const destinations: string[] = [];
					Object.assign(window, { starts, destinations });
					for (const name of ['openLoginInterface', 'openSignupInterface']) {
						window.addEventListener(name, () => destinations.push(name));
					}
					navigator.mediaDevices.getUserMedia = async () => {
						starts.push('microphone');
						throw new Error('A blocked action requested the microphone');
					};
					new MutationObserver(() => {
						if (document.querySelector('[data-testid="record-overlay"]')) starts.push('recording');
					}).observe(document, { childList: true, subtree: true });
				});
				const choosers: string[] = [];
				page.on('filechooser', () => choosers.push('filechooser'));
				await openSignedOutComposer(page, knownDevice
					? () => localStorage.setItem('openmates:last-auth-method', 'email') : undefined);
				if (knownDevice || action === 'record') {
					await expect(page.getByTestId('composer-account-cta')).toHaveText(knownDevice ? /^log\s?in$/i : 'Sign up');
					await expect(page.getByTestId('guest-access-reason')).toHaveAttribute('data-reason', knownDevice ? 'logged_in_before' : 'usage_limit');
				} else {
					await expect(page.getByTestId('composer-send-button')).toBeEnabled();
				}
				await attach(testInfo, page, `guest-${action}-${knownDevice ? 'known' : 'new'}`);
				if (action === 'record') {
					await page.getByTestId('record-audio-button').click();
				} else {
					await page.getByTestId('composer-attachment-menu-button').click();
					await page.getByTestId('composer-attachment-files').click();
				}
				const observed = () => page.evaluate(() => {
					const state = window as typeof window & { starts: string[]; destinations: string[] };
					return { starts: state.starts, destinations: state.destinations };
				});
				await expect.poll(observed).toEqual({
					starts: [],
					destinations: [knownDevice ? 'openLoginInterface' : 'openSignupInterface'],
				});
				expect(choosers).toEqual([]);
			});
		}
	}
});
