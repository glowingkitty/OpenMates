/**
 * Passkey login cancellation regression coverage.
 * Holds the browser credential request open so the loading UI remains observable.
 * Verifies users can switch to email/password or trusted-device pair login.
 * The API initiation response is mocked; no account credentials are required.
 */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { createStepScreenshotter, getE2EDebugUrl } = require('./signup-flow-helpers');
const { openSignupInterface } = require('./helpers/chat-test-helpers');

// contract-test: direct surface=gui.web assertions=auth.login.passkey-alternative-methods
test('keeps alternative login methods available while passkey login is pending', async ({ page }: { page: any }) => {
	const takeScreenshot = createStepScreenshotter(console.log, {
		filenamePrefix: 'passkey-login-alternatives'
	});

	await page.addInitScript(() => {
		const testWindow = window as Window & { __passkeyAbortCount?: number };
		testWindow.__passkeyAbortCount = 0;
		Object.defineProperty(navigator.credentials, 'get', {
			configurable: true,
			value: ({ mediation, signal }: { mediation?: string; signal?: AbortSignal }) => {
				if (mediation === 'conditional') {
					return Promise.reject(new DOMException('Conditional UI disabled for this test', 'NotAllowedError'));
				}

				return new Promise((_resolve, reject) => {
					signal?.addEventListener(
						'abort',
						() => {
							testWindow.__passkeyAbortCount = (testWindow.__passkeyAbortCount ?? 0) + 1;
							reject(new DOMException('Passkey request cancelled', 'AbortError'));
						},
						{ once: true }
					);
				});
			}
		});
	});

	await page.route('**/auth/passkey/assertion/initiate', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				success: true,
				challenge: 'AQIDBA',
				rp: { id: new URL(page.url()).hostname },
				timeout: 60000,
				userVerification: 'required',
				allowCredentials: [],
				extensions: { prf: { eval: { first: 'AQIDBA' } } }
			})
		});
	});

	await page.goto(getE2EDebugUrl('/'));
	await openSignupInterface(page);
	await page.getByTestId('tab-login').click();
	await page.getByTestId('login-passkey-button').click();

	const useEmailButton = page.getByTestId('login-use-email-button');
	const pairLoginButton = page.getByTestId('login-pair-button');
	await expect(page.getByText(/logging in with passkey/i)).toBeVisible();
	await expect(useEmailButton).toHaveText(/login with e-mail \+ password/i);
	await expect(useEmailButton.getByTestId('login-use-email-icon')).toBeVisible();
	await expect(pairLoginButton).toBeVisible();
	await takeScreenshot(page, 'laptop');

	await useEmailButton.click();
	await expect(page.getByText(/logging in with passkey/i)).not.toBeVisible();
	await expect(page.getByTestId('login-email-input')).toBeVisible();
	await expect.poll(() => page.evaluate(() => (window as Window & { __passkeyAbortCount?: number }).__passkeyAbortCount)).toBe(1);

	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto(getE2EDebugUrl('/'));
	await openSignupInterface(page);
	await page.getByTestId('tab-login').click();
	await page.getByTestId('login-passkey-button').click();
	await expect(useEmailButton).toBeInViewport();
	await expect(pairLoginButton).toBeInViewport();
	await takeScreenshot(page, 'mobile');
	await pairLoginButton.click();
	await expect(page.getByText(/logging in with passkey/i)).not.toBeVisible();
	await expect.poll(() => page.evaluate(() => (window as Window & { __passkeyAbortCount?: number }).__passkeyAbortCount)).toBe(1);
});
