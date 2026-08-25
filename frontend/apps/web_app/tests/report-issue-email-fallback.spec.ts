/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Verifies the public Report Issue email fallback on deployed web builds.
 * The draft must remain usable during an API outage while including only
 * user-visible report fields and explicitly shared context.
 * Hidden diagnostics must never be copied into the mailto URL.
 */
export {};

const {
	test,
	expect,
	attachConsoleListeners,
	attachNetworkListeners
} = require('./console-monitor');
const { createSignupLogger } = require('./signup-flow-helpers');

const BASE_URL: string = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';

test.describe('Report Issue Email Fallback', () => {
	// contract-test: direct surface=gui.web assertions=settings-ui.composition.canonical-and-accessible,settings-ui.localization.visible-content-resolves
	test('prepares a privacy-bounded support email draft', async ({ page }) => {
		const logCheckpoint = createSignupLogger('REPORT_ISSUE_EMAIL_FALLBACK');
		attachConsoleListeners(page, logCheckpoint);
		attachNetworkListeners(page, logCheckpoint);

		await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
		const settingsToggle = page.locator('#settings-menu-toggle');
		await expect(settingsToggle).toBeVisible({ timeout: 10000 });
		await settingsToggle.click();

		const reportItem = page
			.getByTestId('settings-menu')
			.getByRole('menuitem', { name: /report.*issue|issue.*report|problem.*melden/i })
			.last();
		await expect(reportItem).toBeVisible({ timeout: 10000 });
		await reportItem.click();

		await page.getByTestId('report-issue-title').fill('Messages remain stuck while sending');
		await page.getByTestId('report-issue-user-flow').fill('I opened a chat, wrote a message, and pressed send.');
		await page.getByTestId('report-issue-expected-behaviour').fill('The message should be sent.');
		await page.getByTestId('report-issue-actual-behaviour').fill('The sending indicator never stops.');

		const emailFallback = page.getByTestId('report-issue-email-fallback');
		await expect(emailFallback).toBeVisible();
		await expect(emailFallback).toHaveText('Send an email instead');

		const href = await emailFallback.getAttribute('href');
		expect(href).toBeTruthy();
		const mailto = new URL(href as string);
		expect(mailto.protocol).toBe('mailto:');
		expect(mailto.pathname).toBe('support@openmates.org');
		expect(mailto.searchParams.get('subject')).toBe(
			'[OpenMates issue] Messages remain stuck while sending'
		);

		const body = mailto.searchParams.get('body') || '';
		expect(body.split('\n')[0]).toBe(
			'[ RECOMMENDATION: Add screenshots to this email, to show what is broken ]'
		);
		expect(body).toContain('Short description:\nMessages remain stuck while sending');
		expect(body).toContain('What I did:\nI opened a chat, wrote a message, and pressed send.');
		expect(body).toContain('Expected behavior:\nThe message should be sent.');
		expect(body).toContain('Actual behavior:\nThe sending indicator never stops.');
		expect(body).toContain('Shared chat or embed:\nNot shared');
		expect(body).toContain('Technical context:');
		expect(body).not.toMatch(
			/console_logs|indexeddb_report|last_messages_html|action_history|trace_ids|session_id|picked_element_html|estimated_location/i
		);
		logCheckpoint('Email fallback contains user-visible issue details and excludes hidden diagnostics.');
	});
});
