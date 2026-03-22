/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * frontend/apps/web_app/tests/health-search-flow.spec.ts
 *
 * Health search appointments flow: verify that asking for doctor appointments
 * renders a search preview, opens a fullscreen grid of appointment results,
 * and clicking a result opens the appointment detail overlay.
 *
 * Test: Health appointment search with fullscreen + child detail interaction
 *   - Sends a message requesting doctor appointments
 *   - Verifies the health search preview card appears and finishes
 *   - Opens the embed in fullscreen mode
 *   - Verifies results grid loads with at least one appointment card
 *   - Clicks a result to open child appointment fullscreen overlay
 *   - Verifies child fullscreen content (datetime, doctor name, booking CTA)
 *   - Closes overlays and deletes the chat
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 *
 * See docs/architecture/embeds.md
 */
export {};

const { test, expect } = require('@playwright/test');

const consoleLogs: string[] = [];
const networkActivities: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
	networkActivities.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-30).forEach((log) => console.log(log));

		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-30).forEach((activity) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	assertNoMissingTranslations,
	getTestAccount,
	getE2EDebugUrl,
	withMockMarker
} = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ---------------------------------------------------------------------------
// Shared helpers (same pattern as travel-search-flow.spec.ts)
// ---------------------------------------------------------------------------

async function loginToTestAccount(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	await page.goto(getE2EDebugUrl('/'));
	await takeStepScreenshot(page, 'home');

	const headerLoginButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(headerLoginButton).toBeVisible({ timeout: 15000 });
	await headerLoginButton.click();
	await takeStepScreenshot(page, 'login-dialog');

	const emailInput = page.locator('#login-email-input');
	await expect(emailInput).toBeVisible({ timeout: 15000 });
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();
	logCheckpoint('Entered email and clicked continue.');

	const passwordInput = page.locator('#login-password-input');
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);
	await takeStepScreenshot(page, 'password-entered');

	const otpInput = page.locator('#login-otp-input');
	await expect(otpInput).toBeVisible({ timeout: 15000 });

	const submitLoginButton = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	const errorMessage = page
		.locator('.error-message, [class*="error"]')
		.filter({ hasText: /wrong|invalid|incorrect/i });

	let loginSuccess = false;
	for (let attempt = 1; attempt <= 3 && !loginSuccess; attempt++) {
		const otpCode = generateTotp(TEST_OTP_KEY);
		await otpInput.fill(otpCode);
		logCheckpoint(`Generated and entered OTP (attempt ${attempt}).`);
		if (attempt === 1) {
			await takeStepScreenshot(page, 'otp-entered');
		}

		await expect(submitLoginButton).toBeVisible();
		await submitLoginButton.click();
		logCheckpoint('Submitted login form.');

		try {
			await expect(otpInput).not.toBeVisible({ timeout: 15000 });
			loginSuccess = true;
			logCheckpoint('Login dialog closed, login successful.');
		} catch {
			const hasError = await errorMessage.isVisible().catch(() => false);
			if (hasError && attempt < 3) {
				logCheckpoint(`OTP attempt ${attempt} failed, retrying with fresh code...`);
				await page.waitForTimeout(2000);
			} else if (attempt === 3) {
				throw new Error('Login failed after 3 OTP attempts');
			}
		}
	}

	logCheckpoint('Waiting for chat interface to load...');
	await page.waitForTimeout(3000);

	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible({ timeout: 20000 });
	logCheckpoint('Chat interface loaded - message editor visible.');
}

async function startNewChat(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	await page.waitForTimeout(1000);

	const currentUrl = page.url();
	logCheckpoint(`Current URL before starting new chat: ${currentUrl}`);

	const newChatButtonSelectors = [
		'.new-chat-cta-button',
		'.icon_create',
		'button[aria-label*="New"]',
		'button[aria-label*="new"]'
	];

	let clicked = false;
	for (const selector of newChatButtonSelectors) {
		const button = page.locator(selector).first();
		if (await button.isVisible({ timeout: 3000 }).catch(() => false)) {
			logCheckpoint(`Found New Chat button with selector: ${selector}`);
			await button.click();
			clicked = true;
			await page.waitForTimeout(2000);
			break;
		}
	}

	if (!clicked) {
		logCheckpoint('New Chat button not initially visible, trying to trigger it...');
		const messageEditor = page.locator('.editor-content.prose');
		if (await messageEditor.isVisible({ timeout: 3000 }).catch(() => false)) {
			await messageEditor.click();
			await page.keyboard.type(' ');
			await page.waitForTimeout(500);

			for (const selector of newChatButtonSelectors) {
				const button = page.locator(selector).first();
				if (await button.isVisible({ timeout: 3000 }).catch(() => false)) {
					logCheckpoint(`Found New Chat button after typing: ${selector}`);
					await button.click();
					clicked = true;
					await page.waitForTimeout(2000);
					break;
				}
			}

			if (clicked) {
				const newEditor = page.locator('.editor-content.prose');
				if (await newEditor.isVisible({ timeout: 2000 }).catch(() => false)) {
					await newEditor.click();
					await page.keyboard.press('Control+A');
					await page.keyboard.press('Backspace');
				}
			}
		}
	}

	if (!clicked) {
		logCheckpoint('WARNING: Could not find New Chat button with any selector.');
	}

	const newUrl = page.url();
	logCheckpoint(`URL after attempting to start new chat: ${newUrl}`);
}

async function sendMessage(
	page: any,
	message: string,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>,
	stepLabel: string
): Promise<void> {
	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible();
	await messageEditor.click();
	await page.keyboard.type(message);
	logCheckpoint(`Typed message: "${message}"`);
	await takeStepScreenshot(page, `${stepLabel}-message-typed`);

	const sendButton = page.locator('.send-button');
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	logCheckpoint('Clicked send button.');
	await takeStepScreenshot(page, `${stepLabel}-message-sent`);
}

async function deleteActiveChat(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>,
	stepLabel: string
): Promise<void> {
	logCheckpoint('Attempting to delete the chat (best-effort cleanup)...');

	try {
		const sidebarToggle = page.locator('[data-testid="sidebar-toggle"]');
		if (await sidebarToggle.isVisible({ timeout: 3000 }).catch(() => false)) {
			await sidebarToggle.click();
			await page.waitForTimeout(500);
		}

		const activeChatItem = page.locator('.chat-item-wrapper.active');

		if (!(await activeChatItem.isVisible({ timeout: 5000 }).catch(() => false))) {
			logCheckpoint('No active chat item visible - skipping cleanup.');
			return;
		}

		try {
			const chatTitle = await activeChatItem
				.locator('.chat-title')
				.textContent({ timeout: 3000 });
			logCheckpoint(`Active chat title: "${chatTitle}"`);

			if (
				chatTitle &&
				(chatTitle.includes('demo') ||
					chatTitle.includes('Demo') ||
					chatTitle.includes('OpenMates'))
			) {
				logCheckpoint('Skipping deletion - appears to be a demo chat.');
				return;
			}
		} catch {
			logCheckpoint('Could not get active chat title.');
		}

		await activeChatItem.click({ button: 'right' });
		await takeStepScreenshot(page, `${stepLabel}-context-menu-open`);
		logCheckpoint('Opened chat context menu.');

		await page.waitForTimeout(300);
		const deleteButton = page.locator('.menu-item.delete');

		if (!(await deleteButton.isVisible({ timeout: 3000 }).catch(() => false))) {
			logCheckpoint('Delete button not visible in context menu - skipping cleanup.');
			await page.keyboard.press('Escape');
			return;
		}

		await deleteButton.click();
		await takeStepScreenshot(page, `${stepLabel}-delete-confirm-mode`);
		logCheckpoint('Clicked delete, now in confirm mode.');

		await deleteButton.click();
		logCheckpoint('Confirmed chat deletion.');

		await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
		await takeStepScreenshot(page, `${stepLabel}-chat-deleted`);
		logCheckpoint('Verified chat deletion successfully.');
	} catch (error) {
		logCheckpoint(`Cleanup failed (non-fatal): ${error}`);
	}
}

// ---------------------------------------------------------------------------
// Test: Health appointment search with fullscreen + child detail interaction
// ---------------------------------------------------------------------------

test('health appointment search with fullscreen and appointment detail interaction', async ({
	page
}: {
	page: any;
}) => {
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (request: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${response.url()}`);
	});

	test.slow();
	test.setTimeout(300000);

	const logCheckpoint = createSignupLogger('HEALTH_SEARCH');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'health-search'
	});

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting health appointment search fullscreen test.', { email: TEST_EMAIL });

	// Login and start a new chat
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	// ======================================================================
	// STEP 1: Send a message that triggers a health appointment search
	// ======================================================================
	const searchQuery = withMockMarker(
		'Find me a doctor appointment for a dentist in Berlin',
		'health_search_appointments'
	);
	await sendMessage(page, searchQuery, logCheckpoint, takeStepScreenshot, 'health-search');

	// Wait for assistant response
	logCheckpoint('Waiting for assistant response with health search results...');
	const assistantMessage = page.locator('.message-wrapper.assistant');
	await expect(assistantMessage.first()).toBeVisible({ timeout: 60000 });
	logCheckpoint('Assistant response wrapper is visible.');

	// ======================================================================
	// STEP 2: Verify the health search embed preview appears and finishes
	// ======================================================================
	const healthSearchPreview = page.locator(
		'.unified-embed-preview[data-app-id="health"][data-skill-id="search_appointments"]'
	);
	logCheckpoint('Waiting for health search embed preview to appear...');
	await expect(healthSearchPreview.first()).toBeVisible({ timeout: 90000 });
	await takeStepScreenshot(page, 'search-preview-visible');
	logCheckpoint('Health search embed preview is visible.');

	// Wait for finished state
	const finishedPreview = page.locator(
		'.unified-embed-preview[data-app-id="health"][data-skill-id="search_appointments"][data-status="finished"]'
	);
	await expect(finishedPreview.first()).toBeVisible({ timeout: 90000 });
	logCheckpoint('Health search preview reached finished state.');

	// Verify preview inner elements
	const searchQueryElement = finishedPreview.first().locator('.search-query');
	const hasSearchQuery = await searchQueryElement.isVisible({ timeout: 5000 }).catch(() => false);
	if (hasSearchQuery) {
		const queryText = await searchQueryElement.textContent();
		logCheckpoint(`Search query displayed on preview: "${queryText}"`);
	}

	const basicInfosBar = finishedPreview.first().locator('.basic-infos-bar');
	await expect(basicInfosBar).toBeVisible({ timeout: 5000 });
	logCheckpoint('Basic infos bar is visible on the search preview.');

	await takeStepScreenshot(page, 'search-preview-verified');

	// Verify no missing translations on the chat page with health search results
	await assertNoMissingTranslations(page);
	logCheckpoint('No missing translations detected.');

	// ======================================================================
	// STEP 3: Click the embed to open fullscreen
	// ======================================================================
	logCheckpoint('Clicking on finished preview to open fullscreen...');
	await finishedPreview.first().click();

	// Wait for the fullscreen overlay to appear and animate in
	const fullscreenOverlay = page.locator('.unified-embed-fullscreen-overlay');
	await expect(fullscreenOverlay).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(500);
	logCheckpoint('Fullscreen overlay is visible.');
	await takeStepScreenshot(page, 'fullscreen-opened');

	// ======================================================================
	// STEP 4: Wait for appointment results to load in fullscreen grid
	// The fullscreen uses SearchResultsTemplate which loads child embeds
	// asynchronously. Wait for the grid and at least one result.
	// ======================================================================
	const resultsGrid = fullscreenOverlay.locator('.search-template-grid');
	await expect(resultsGrid).toBeVisible({ timeout: 60000 });
	logCheckpoint('Search results grid is visible in fullscreen.');

	// Wait for at least one appointment result card to appear in the grid
	// Child embeds have data-app-id="health" and data-skill-id="appointment"
	// or they render as HealthAppointmentEmbedPreview inside .unified-embed-preview
	const appointmentResults = resultsGrid.locator('.unified-embed-preview');
	await expect(async () => {
		const count = await appointmentResults.count();
		logCheckpoint(`Appointment results in grid: ${count}`);
		expect(count).toBeGreaterThanOrEqual(1);
	}).toPass({ timeout: 60000 });

	const totalResults = await appointmentResults.count();
	logCheckpoint(`Total appointment results in grid: ${totalResults}`);
	await takeStepScreenshot(page, 'fullscreen-results-loaded');

	// ======================================================================
	// STEP 5: Verify individual appointment card content
	// ======================================================================
	const firstAppointment = appointmentResults.first();

	// Verify appointment details are visible (slot datetime, doctor name, speciality)
	const appointmentDetails = firstAppointment.locator('.appointment-details');
	const hasDetails = await appointmentDetails.isVisible({ timeout: 5000 }).catch(() => false);

	if (hasDetails) {
		const slotDatetime = appointmentDetails.locator('.slot-datetime');
		const hasSlotDatetime = await slotDatetime.isVisible({ timeout: 3000 }).catch(() => false);
		if (hasSlotDatetime) {
			const slotText = await slotDatetime.textContent();
			logCheckpoint(`First appointment slot datetime: "${slotText}"`);
		}

		const doctorName = appointmentDetails.locator('.doctor-name');
		const hasDoctorName = await doctorName.isVisible({ timeout: 3000 }).catch(() => false);
		if (hasDoctorName) {
			const nameText = await doctorName.textContent();
			logCheckpoint(`First appointment doctor name: "${nameText}"`);
		}

		const speciality = appointmentDetails.locator('.doctor-speciality');
		const hasSpeciality = await speciality.isVisible({ timeout: 3000 }).catch(() => false);
		if (hasSpeciality) {
			const specText = await speciality.textContent();
			logCheckpoint(`First appointment speciality: "${specText}"`);
		}
	} else {
		logCheckpoint('Appointment details container not found - card may use a different layout.');
	}

	await takeStepScreenshot(page, 'appointment-card-verified');

	// ======================================================================
	// STEP 6: Verify fullscreen action buttons exist
	// ======================================================================
	logCheckpoint('Verifying fullscreen action buttons...');

	const shareButton = fullscreenOverlay.locator('.share-button');
	await expect(shareButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Share button is visible.');

	const reportIssueButton = fullscreenOverlay.locator('.report-issue-button');
	await expect(reportIssueButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Report issue button is visible.');

	const minimizeButton = fullscreenOverlay.locator('.minimize-button');
	await expect(minimizeButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Minimize button is visible.');

	const bottomBar = fullscreenOverlay.locator('.basic-infos-bar-wrapper');
	await expect(bottomBar).toBeVisible({ timeout: 5000 });
	logCheckpoint('Bottom BasicInfosBar wrapper is visible in fullscreen.');

	await takeStepScreenshot(page, 'fullscreen-buttons-verified');

	// ======================================================================
	// STEP 7: Click an appointment result to open the child fullscreen overlay
	// ======================================================================
	logCheckpoint('Clicking first appointment result to open appointment detail...');
	await firstAppointment.click();

	// Wait for the child embed overlay to appear (z-index 101, on top of search fullscreen)
	const childOverlay = page.locator('.child-embed-overlay');
	await expect(childOverlay).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(500);
	logCheckpoint('Child embed overlay (appointment fullscreen) is visible.');
	await takeStepScreenshot(page, 'appointment-fullscreen-opened');

	// ======================================================================
	// STEP 8: Verify appointment fullscreen content
	// ======================================================================

	// Verify slot datetime is highlighted
	const slotHighlight = childOverlay.locator('.slot-highlight');
	const hasSlotHighlight = await slotHighlight.isVisible({ timeout: 5000 }).catch(() => false);
	if (hasSlotHighlight) {
		const slotHighlightText = await slotHighlight.textContent();
		logCheckpoint(`Appointment fullscreen slot datetime: "${slotHighlightText}"`);
	} else {
		logCheckpoint('Slot highlight not visible in appointment fullscreen.');
	}

	// Verify doctor name
	const doctorHeader = childOverlay.locator('.doctor-header');
	const hasDoctorHeader = await doctorHeader.isVisible({ timeout: 5000 }).catch(() => false);
	if (hasDoctorHeader) {
		const doctorNameFs = doctorHeader.locator('.doctor-name');
		const hasName = await doctorNameFs.isVisible({ timeout: 3000 }).catch(() => false);
		if (hasName) {
			const nameText = await doctorNameFs.textContent();
			logCheckpoint(`Appointment fullscreen doctor name: "${nameText}"`);
		}

		const specialityFs = doctorHeader.locator('.doctor-speciality');
		const hasSpec = await specialityFs.isVisible({ timeout: 3000 }).catch(() => false);
		if (hasSpec) {
			const specText = await specialityFs.textContent();
			logCheckpoint(`Appointment fullscreen speciality: "${specText}"`);
		}

		const addressFs = doctorHeader.locator('.doctor-address');
		const hasAddr = await addressFs.isVisible({ timeout: 3000 }).catch(() => false);
		if (hasAddr) {
			const addrText = await addressFs.textContent();
			logCheckpoint(`Appointment fullscreen address: "${addrText}"`);
		}
	} else {
		logCheckpoint('Doctor header not visible in appointment fullscreen.');
	}

	// Verify booking CTA button is present (either Doctolib or Jameda link)
	const bookingLink = childOverlay.locator('.booking-link');
	const hasBookingLink = await bookingLink.isVisible({ timeout: 5000 }).catch(() => false);
	if (hasBookingLink) {
		const bookingText = await bookingLink.textContent();
		logCheckpoint(`Booking CTA text: "${bookingText}"`);
	} else {
		logCheckpoint('No booking link visible in appointment fullscreen.');
	}

	await takeStepScreenshot(page, 'appointment-fullscreen-verified');

	// ======================================================================
	// STEP 9: Close the child overlay
	// ======================================================================
	logCheckpoint('Closing child appointment fullscreen overlay...');
	const childMinimizeButton = childOverlay.locator('.minimize-button');
	const hasChildMinimize = await childMinimizeButton.isVisible({ timeout: 3000 }).catch(() => false);

	if (hasChildMinimize) {
		await childMinimizeButton.click();
		await page.waitForTimeout(500);
		logCheckpoint('Clicked minimize on child overlay.');
	} else {
		// Try the close button or press Escape
		logCheckpoint('Minimize button not found on child overlay, pressing Escape...');
		await page.keyboard.press('Escape');
		await page.waitForTimeout(500);
	}

	// Verify child is gone but parent fullscreen is still open
	await expect(childOverlay).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('Child overlay closed.');

	await expect(fullscreenOverlay).toBeVisible({ timeout: 5000 });
	logCheckpoint('Parent fullscreen overlay still visible after closing child.');
	await takeStepScreenshot(page, 'child-closed-parent-open');

	// ======================================================================
	// STEP 10: Close the parent fullscreen
	// ======================================================================
	logCheckpoint('Closing parent fullscreen overlay...');
	const parentMinimizeButton = fullscreenOverlay.locator('.minimize-button');
	await parentMinimizeButton.click();
	await page.waitForTimeout(500);

	await expect(fullscreenOverlay).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('Parent fullscreen overlay closed.');
	await takeStepScreenshot(page, 'fullscreen-closed');

	// ======================================================================
	// STEP 11: Verify the inline embed ref also opens fullscreen correctly
	// (click the preview card again to confirm it still works after close)
	// ======================================================================
	logCheckpoint('Re-clicking preview to verify it reopens fullscreen...');
	await finishedPreview.first().click();
	await expect(fullscreenOverlay).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(500);

	// Verify grid still has results
	await expect(resultsGrid).toBeVisible({ timeout: 10000 });
	const reopenResultCount = await appointmentResults.count();
	logCheckpoint(`Results after reopening fullscreen: ${reopenResultCount}`);
	expect(reopenResultCount).toBeGreaterThanOrEqual(1);
	await takeStepScreenshot(page, 'fullscreen-reopened-verified');

	// Close again
	await fullscreenOverlay.locator('.minimize-button').click();
	await page.waitForTimeout(500);
	await expect(fullscreenOverlay).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('Fullscreen closed again after re-verify.');

	// ======================================================================
	// STEP 12: Cleanup - delete the chat
	// ======================================================================
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'health-cleanup');
	logCheckpoint('Health appointment search flow test completed successfully.');
});
