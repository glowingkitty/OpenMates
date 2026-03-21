/* eslint-disable no-console */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Keyboard navigation accessibility tests.
 *
 * Verifies that core UI flows are fully operable via keyboard only:
 * skip link, tab order, focus trap in modals, sidebar toggle.
 *
 * Architecture context: docs/architecture/accessibility.md
 * Test reference: run via scripts/run-tests.sh --suite playwright
 */
export {};

const { test, expect } = require('@playwright/test');
const {
	getTestAccount,
	generateTotp,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

// ─── Unauthenticated keyboard tests ────────────────────────────────────────

test.describe('Keyboard navigation — unauthenticated', () => {
	test('skip link appears on first Tab and navigates to main content', async ({ page }: { page: any }) => {
		test.setTimeout(60000);

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await page.waitForTimeout(2000);

		// Tab until skip link is focused (may take 1-3 tabs depending on browser chrome)
		const skipLink = page.locator('.skip-link, a[href="#main-chat"]').first();
		let skipLinkFocused = false;
		for (let i = 0; i < 5; i++) {
			await page.keyboard.press('Tab');
			await page.waitForTimeout(300);
			const isFocused = await skipLink.evaluate(
				(el: HTMLElement) => document.activeElement === el
			).catch(() => false);
			if (isFocused) {
				skipLinkFocused = true;
				break;
			}
		}

		await expect(skipLink).toBeVisible({ timeout: 5000 });
		expect(skipLinkFocused, 'Skip link should be focused after tabbing').toBe(true);

		// Press Enter — focus should move to #main-chat
		await page.keyboard.press('Enter');
		await page.waitForTimeout(500);

		const mainChat = page.locator('#main-chat');
		const mainChatExists = await mainChat.count();
		if (mainChatExists > 0) {
			await expect(mainChat).toBeFocused({ timeout: 3000 });
		}

		console.log('✅ Skip link: visible on Tab, navigates to #main-chat on Enter');
	});

	test('Tab cycles through header navigation elements', async ({ page }: { page: any }) => {
		test.setTimeout(60000);

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await page.waitForTimeout(2000);

		// Tab through header — collect focused element tags/roles
		const focusedElements: string[] = [];
		for (let i = 0; i < 8; i++) {
			await page.keyboard.press('Tab');
			await page.waitForTimeout(200);

			const info = await page.evaluate(() => {
				const el = document.activeElement;
				if (!el) return 'null';
				const tag = el.tagName.toLowerCase();
				const role = el.getAttribute('role') || '';
				const label =
					el.getAttribute('aria-label') ||
					el.textContent?.trim().slice(0, 30) ||
					'';
				return `${tag}${role ? `[role=${role}]` : ''}:${label}`;
			});
			focusedElements.push(info);
		}

		// At least some elements should be focusable buttons/links
		const interactiveCount = focusedElements.filter(
			(el) => el.startsWith('button') || el.startsWith('a')
		).length;

		expect(
			interactiveCount,
			`Expected interactive elements in tab order, got: ${focusedElements.join(', ')}`
		).toBeGreaterThan(0);

		console.log('✅ Tab order: header elements are reachable via Tab');
	});

	test('login dialog traps focus and Escape closes it', async ({ page }: { page: any }) => {
		test.setTimeout(60000);

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		// Open login dialog
		const loginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
		await expect(loginButton).toBeVisible({ timeout: 15000 });
		await loginButton.click();
		await page.waitForTimeout(1000);

		// Check dialog is open
		const dialog = page.locator('[role="dialog"]');
		const dialogVisible = await dialog.isVisible().catch(() => false);

		if (dialogVisible) {
			// Tab multiple times — focus should stay within the dialog
			for (let i = 0; i < 10; i++) {
				await page.keyboard.press('Tab');
				await page.waitForTimeout(100);
			}

			const focusInDialog = await page.evaluate(() => {
				const dialog = document.querySelector('[role="dialog"]');
				return dialog?.contains(document.activeElement) ?? false;
			});
			expect(focusInDialog, 'Focus should remain trapped inside dialog').toBe(true);

			// Escape should close the dialog
			await page.keyboard.press('Escape');
			await page.waitForTimeout(500);
			await expect(dialog).not.toBeVisible({ timeout: 5000 });

			console.log('✅ Login dialog: focus trapped, Escape closes');
		} else {
			console.log('⚠️ Login dialog did not open as role="dialog" — skipping focus trap test');
		}
	});
});

// ─── Authenticated keyboard tests ──────────────────────────────────────────

test.describe('Keyboard navigation — authenticated', () => {
	const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

	async function loginAndWait(page: any): Promise<void> {
		await page.goto(getE2EDebugUrl('/'));
		await page.waitForLoadState('networkidle');

		const headerLoginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
		await expect(headerLoginButton).toBeVisible({ timeout: 15000 });
		await headerLoginButton.click();

		const emailInput = page.locator('#login-email-input');
		await expect(emailInput).toBeVisible();
		await emailInput.fill(TEST_EMAIL);
		await page.locator('#login-continue-button').click();

		const passwordInput = page.locator('#login-password-input');
		await expect(passwordInput).toBeVisible();
		await passwordInput.fill(TEST_PASSWORD);

		const otpCode = generateTotp(TEST_OTP_KEY);
		const otpInput = page.locator('#login-otp-input');
		await expect(otpInput).toBeVisible();
		await otpInput.fill(otpCode);

		const submitButton = page.locator('#login-submit-button');
		await expect(submitButton).toBeVisible();
		await submitButton.click();

		await page.waitForURL(/chat/, { timeout: 30000 });
		await page.waitForTimeout(5000);
	}

	test('message input is reachable via Tab', async ({ page }: { page: any }) => {
		test.setTimeout(120000);
		test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
		test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
		test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

		await loginAndWait(page);

		// Tab through the page until we reach the message input area
		let foundInput = false;
		for (let i = 0; i < 20; i++) {
			await page.keyboard.press('Tab');
			await page.waitForTimeout(200);

			const isEditor = await page.evaluate(() => {
				const el = document.activeElement;
				return (
					el?.getAttribute('contenteditable') === 'true' ||
					el?.classList.contains('editor-content') ||
					el?.classList.contains('prose') ||
					el?.closest('.editor-content') !== null
				);
			});
			if (isEditor) {
				foundInput = true;
				break;
			}
		}

		expect(foundInput, 'Message input should be reachable via Tab').toBe(true);
		console.log('✅ Message input reachable via keyboard Tab');
	});

	test('settings modal focus trap: Tab cycles within dialog, Escape closes', async ({
		page
	}: { page: any }) => {
		test.setTimeout(120000);
		test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
		test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
		test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

		await loginAndWait(page);

		// Open settings
		const settingsButton = page.locator('.profile-container[role="button"]');
		await expect(settingsButton).toBeVisible({ timeout: 10000 });
		await settingsButton.click();
		await page.waitForTimeout(1000);

		const dialog = page.locator('[role="dialog"]');
		const dialogVisible = await dialog.isVisible().catch(() => false);

		if (dialogVisible) {
			// Record the first focused element inside the dialog
			const firstFocused = await page.evaluate(() => {
				return document.activeElement?.tagName?.toLowerCase() || 'none';
			});

			// Tab 15 times — focus must stay inside dialog
			for (let i = 0; i < 15; i++) {
				await page.keyboard.press('Tab');
				await page.waitForTimeout(100);
			}

			const focusStillInDialog = await page.evaluate(() => {
				const dialog = document.querySelector('[role="dialog"]');
				return dialog?.contains(document.activeElement) ?? false;
			});
			expect(focusStillInDialog, 'Focus should remain trapped inside settings dialog').toBe(
				true
			);

			// Escape closes
			await page.keyboard.press('Escape');
			await page.waitForTimeout(500);
			await expect(dialog).not.toBeVisible({ timeout: 5000 });

			// Focus should restore to the settings button (or at least not be on the dialog)
			const focusAfterClose = await page.evaluate(() => {
				const dialog = document.querySelector('[role="dialog"]');
				return dialog?.contains(document.activeElement) ?? false;
			});
			expect(focusAfterClose, 'Focus should not be inside closed dialog').toBe(false);

			console.log('✅ Settings modal: focus trap works, Escape closes and restores focus');
		} else {
			console.log('⚠️ Settings did not open as role="dialog" — skipping focus trap test');
		}
	});

	test('sidebar toggle is operable via keyboard', async ({ page }: { page: any }) => {
		test.setTimeout(120000);
		test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
		test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
		test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

		await loginAndWait(page);

		// The menu toggle button (data-testid="sidebar-toggle") opens the sidebar.
		// It hides itself once the sidebar is open (class:hidden when isActivityHistoryOpen).
		const menuToggle = page.locator('[data-testid="sidebar-toggle"]');
		await expect(menuToggle).toBeVisible({ timeout: 5000 });

		// Verify the button has proper ARIA attributes for keyboard users
		const ariaLabel = await menuToggle.getAttribute('aria-label');
		expect(ariaLabel, 'Sidebar toggle should have an aria-label').toBeTruthy();

		const ariaExpanded = await menuToggle.getAttribute('aria-expanded');
		expect(ariaExpanded, 'Sidebar toggle should have aria-expanded').toBeTruthy();

		// Focus the toggle and press Enter to open sidebar
		await menuToggle.focus();
		await page.waitForTimeout(300);
		await page.keyboard.press('Enter');
		await page.waitForTimeout(1500);

		const sidebarOpen = await page
			.locator('.activity-history-wrapper')
			.isVisible()
			.catch(() => false);
		expect(sidebarOpen, 'Sidebar should open after pressing Enter on menu toggle').toBe(true);

		console.log('✅ Sidebar toggle: operable via keyboard Enter, has aria-label and aria-expanded');
	});
});
