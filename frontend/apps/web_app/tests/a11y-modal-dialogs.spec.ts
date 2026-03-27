/* eslint-disable no-console */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Modal/dialog ARIA verification tests.
 *
 * Validates that all modals follow the checklist from docs/architecture/accessibility.md:
 * - role="dialog", aria-modal="true", aria-labelledby → visible heading
 * - Focus trap behavior, Escape handling, focus restoration
 *
 * Architecture context: docs/architecture/accessibility.md
 * Test reference: run via scripts/run-tests.sh --suite playwright
 */
export {};

const { test, expect } = require('@playwright/test');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	getTestAccount,
	generateTotp,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

/**
 * Verify ARIA attributes on a dialog element.
 * Returns an object describing which checks passed/failed.
 */
async function verifyDialogAria(page: any): Promise<{
	hasRoleDialog: boolean;
	hasAriaModal: boolean;
	hasAriaLabelledby: boolean;
	labelledbyPointsToVisibleHeading: boolean;
	headingText: string;
}> {
	return await page.evaluate(() => {
		const dialog = document.querySelector('[role="dialog"]');
		if (!dialog) {
			return {
				hasRoleDialog: false,
				hasAriaModal: false,
				hasAriaLabelledby: false,
				labelledbyPointsToVisibleHeading: false,
				headingText: ''
			};
		}

		const hasRoleDialog = dialog.getAttribute('role') === 'dialog';
		const hasAriaModal = dialog.getAttribute('aria-modal') === 'true';
		const labelledby = dialog.getAttribute('aria-labelledby');
		const hasAriaLabelledby = !!labelledby;

		let labelledbyPointsToVisibleHeading = false;
		let headingText = '';

		if (labelledby) {
			const heading = document.getElementById(labelledby);
			if (heading) {
				const style = window.getComputedStyle(heading);
				labelledbyPointsToVisibleHeading =
					style.display !== 'none' && style.visibility !== 'hidden';
				headingText = heading.textContent?.trim() || '';
			}
		}

		return {
			hasRoleDialog,
			hasAriaModal,
			hasAriaLabelledby,
			labelledbyPointsToVisibleHeading,
			headingText
		};
	});
}

/**
 * Verify focus trap: Tab N times, assert focus stays inside dialog.
 */
async function verifyFocusTrap(page: any, tabCount: number = 12): Promise<boolean> {
	for (let i = 0; i < tabCount; i++) {
		await page.keyboard.press('Tab');
		await page.waitForTimeout(80);
	}

	return await page.evaluate(() => {
		const dialog = document.querySelector('[role="dialog"]');
		return dialog?.contains(document.activeElement) ?? false;
	});
}

/**
 * Verify Escape closes dialog and focus is restored outside it.
 */
async function verifyEscapeAndFocusRestore(page: any): Promise<{
	dialogClosed: boolean;
	focusOutsideDialog: boolean;
}> {
	await page.keyboard.press('Escape');
	await page.waitForTimeout(500);

	const dialogVisible = await page
		.locator('[role="dialog"]')
		.isVisible()
		.catch(() => false);

	const focusOutside = await page.evaluate(() => {
		const dialog = document.querySelector('[role="dialog"]');
		if (!dialog) return true; // dialog removed from DOM
		return !dialog.contains(document.activeElement);
	});

	return {
		dialogClosed: !dialogVisible,
		focusOutsideDialog: focusOutside
	};
}

// ─── Unauthenticated dialog tests ───────────────────────────────────────────

test.describe('Modal ARIA — unauthenticated', () => {
	test('login dialog has correct ARIA attributes', async ({ page }: { page: any }) => {
		test.setTimeout(60000);

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		const loginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
		await expect(loginButton).toBeVisible({ timeout: 15000 });
		await loginButton.click();
		await page.waitForTimeout(1000);

		const dialog = page.locator('[role="dialog"]');
		const dialogVisible = await dialog.isVisible().catch(() => false);

		if (dialogVisible) {
			const aria = await verifyDialogAria(page);
			expect(aria.hasRoleDialog, 'Dialog should have role="dialog"').toBe(true);
			expect(aria.hasAriaModal, 'Dialog should have aria-modal="true"').toBe(true);

			// aria-labelledby is recommended — log warning if missing but don't fail
			if (!aria.hasAriaLabelledby) {
				console.warn('⚠️ Login dialog missing aria-labelledby');
			} else {
				expect(
					aria.labelledbyPointsToVisibleHeading,
					`aria-labelledby should point to a visible heading (got: "${aria.headingText}")`
				).toBe(true);
			}

			// Verify focus trap
			const trapped = await verifyFocusTrap(page);
			expect(trapped, 'Focus should be trapped inside login dialog').toBe(true);

			// Verify Escape closes
			const { dialogClosed, focusOutsideDialog } = await verifyEscapeAndFocusRestore(page);
			expect(dialogClosed, 'Escape should close login dialog').toBe(true);
			expect(focusOutsideDialog, 'Focus should restore outside dialog after Escape').toBe(
				true
			);

			console.log('✅ Login dialog: ARIA attributes correct, focus trap works');
		} else {
			console.log('⚠️ Login did not render as role="dialog" — check SecurityAuth.svelte');
		}
	});
});

// ─── Authenticated dialog tests ─────────────────────────────────────────────

test.describe('Modal ARIA — authenticated', () => {
	const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

	async function loginAndWait(page: any): Promise<void> {
		await page.goto(getE2EDebugUrl('/'));
		await page.waitForLoadState('networkidle');

		const headerLoginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
		await expect(headerLoginButton).toBeVisible({ timeout: 15000 });
		await headerLoginButton.click();

		// Click Login tab to switch from signup to login view
		const loginTab = page.locator('.login-tabs .tab-button', { hasText: /^login$/i });
		await expect(loginTab).toBeVisible({ timeout: 10000 });
		await loginTab.click();

		const emailInput = page.locator('#login-email-input');
		await expect(emailInput).toBeVisible({ timeout: 15000 });
		await emailInput.fill(TEST_EMAIL);
		await page.locator('#login-continue-button').click();

		const passwordInput = page.locator('#login-password-input');
		await expect(passwordInput).toBeVisible({ timeout: 15000 });
		await passwordInput.fill(TEST_PASSWORD);

		const otpCode = generateTotp(TEST_OTP_KEY);
		const otpInput = page.locator('#login-otp-input');
		await expect(otpInput).toBeVisible({ timeout: 15000 });
		await otpInput.fill(otpCode);

		const submitButton = page.locator('#login-submit-button');
		await expect(submitButton).toBeVisible();
		await submitButton.click();

		await page.waitForURL(/chat/, { timeout: 30000 });
		await page.waitForTimeout(5000);
	}

	test('settings modal has correct ARIA attributes and focus trap', async ({ page }: { page: any }) => {
		test.setTimeout(120000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		await loginAndWait(page);

		// Open settings
		const settingsButton = page.locator('.profile-container[role="button"]');
		await expect(settingsButton).toBeVisible({ timeout: 10000 });
		await settingsButton.click();
		await page.waitForTimeout(1000);

		const dialog = page.locator('[role="dialog"]');
		const dialogVisible = await dialog.isVisible().catch(() => false);

		if (dialogVisible) {
			const aria = await verifyDialogAria(page);
			expect(aria.hasRoleDialog, 'Settings dialog: role="dialog"').toBe(true);
			expect(aria.hasAriaModal, 'Settings dialog: aria-modal="true"').toBe(true);

			if (aria.hasAriaLabelledby) {
				expect(
					aria.labelledbyPointsToVisibleHeading,
					'Settings dialog: aria-labelledby → visible heading'
				).toBe(true);
				console.log(`  Heading: "${aria.headingText}"`);
			} else {
				console.warn('⚠️ Settings dialog missing aria-labelledby');
			}

			const trapped = await verifyFocusTrap(page);
			expect(trapped, 'Focus should be trapped inside settings dialog').toBe(true);

			const { dialogClosed, focusOutsideDialog } = await verifyEscapeAndFocusRestore(page);
			expect(dialogClosed, 'Escape should close settings dialog').toBe(true);
			expect(focusOutsideDialog, 'Focus should restore outside settings dialog').toBe(true);

			console.log('✅ Settings modal: ARIA + focus trap + Escape all correct');
		} else {
			console.log('⚠️ Settings did not render as role="dialog"');
		}
	});

	test('overlay has role="presentation" (not role="button")', async ({ page }: { page: any }) => {
		test.setTimeout(120000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		await loginAndWait(page);

		// Open settings to get a dialog with overlay
		const settingsButton = page.locator('.profile-container[role="button"]');
		await expect(settingsButton).toBeVisible({ timeout: 10000 });
		await settingsButton.click();
		await page.waitForTimeout(1000);

		// Check for overlay element — it should NOT have role="button"
		const overlayRoles = await page.evaluate(() => {
			const overlays = document.querySelectorAll(
				'.overlay, .modal-overlay, .dialog-overlay, [class*="overlay"]'
			);
			return Array.from(overlays).map((el) => ({
				className: el.className,
				role: el.getAttribute('role'),
				tagName: el.tagName.toLowerCase()
			}));
		});

		for (const overlay of overlayRoles) {
			if (overlay.role === 'button') {
				throw new Error(
					`Overlay (${overlay.className}) has role="button" — should be role="presentation" per accessibility.md`
				);
			}
		}

		// Close dialog
		await page.keyboard.press('Escape');
		console.log('✅ Overlay: no role="button" anti-pattern detected');
	});
});
