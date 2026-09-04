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
const { captureTestThumbnail, defineTestThumbnail } = require('./helpers/test-thumbnail');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const BASE_URL: string = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const IS_PROOF_CAPTURE = Number.isFinite(PROOF_VIDEO_WIDTH) && PROOF_VIDEO_WIDTH > 0;
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';
const REPORT_ISSUE_THUMBNAIL = defineTestThumbnail({
	id: 'report-issue-form',
	focus: [
		{ testId: 'report-issue-title' },
		{ testId: 'report-issue-email-fallback' }
	]
});

async function captureBrowserProofFrame(page: any): Promise<Buffer> {
	return page.screenshot({ type: 'png' });
}

const proofContract = defineVideoProof({
	id: 'report-issue-email-fallback',
	title: 'Report issue support email fallback',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'report-issue-open',
			text: 'Open Settings and choose Report Issue to describe the problem.',
			checkpoint: 'report-issue-open',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'fallback-visible',
			text: 'The Report Issue screen offers Send an email instead below the normal submit button.',
			checkpoint: 'fallback-visible',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'issue-details-entered',
			text: 'The short description field keeps the issue text while the email fallback remains available.',
			checkpoint: 'issue-details-entered',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'report-issue.screen.visible',
			checkpoint: 'report-issue-open',
			visual: 'The Report Issue settings screen is visible with its title, guidance, and Submit Issue button.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'report-issue.email-fallback.visible',
			checkpoint: 'fallback-visible',
			visual: 'The Send an email instead fallback link is visible below Submit Issue without clipping or overlap.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'report-issue.short-description.visible',
			checkpoint: 'issue-details-entered',
			visual: 'The short description field contains the entered issue summary on the Report Issue screen.',
			devices: ['web-laptop', 'web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

test.describe('Report Issue Email Fallback', () => {
	// contract-test: direct surface=gui.web assertions=settings-ui.composition.canonical-and-accessible,settings-ui.localization.visible-content-resolves
	test('prepares a privacy-bounded support email draft', async ({ page }, testInfo) => {
		const proof = createVideoProofRuntime(proofContract, {
			device: PROOF_DEVICE,
			attach: testInfo.attach.bind(testInfo),
			captureFrame: () => captureBrowserProofFrame(page)
		});
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

		await proof.assert('report-issue.screen.visible', async () => {
			await expect(page.getByTestId('report-issue-email-fallback')).toBeVisible({ timeout: 10000 });
		});
		await proof.checkpoint('report-issue-open');

		const titleInput = page.getByTestId('report-issue-title');
		await titleInput.fill('Messages remain stuck while sending');
		await proof.assert('report-issue.short-description.visible', async () => {
			await expect(titleInput).toHaveValue('Messages remain stuck while sending');
		});
		await proof.checkpoint('issue-details-entered');

		const emailFallback = page.getByTestId('report-issue-email-fallback');
		await expect(emailFallback).toBeVisible();
		await expect(emailFallback).toHaveText('Send an email instead');
		await proof.assert('report-issue.email-fallback.visible', async () => {
			await expect(emailFallback).toBeVisible();
			await expect(emailFallback).toHaveText('Send an email instead');
		});
		await captureTestThumbnail(page, testInfo, REPORT_ISSUE_THUMBNAIL);
		await proof.checkpoint('fallback-visible');
		if (IS_PROOF_CAPTURE) {
			await page.waitForTimeout(1500);
		}

		await page.getByTestId('report-issue-user-flow').fill('I opened a chat, wrote a message, and pressed send.');
		await page.getByTestId('report-issue-expected-behaviour').fill('The message should be sent.');
		await page.getByTestId('report-issue-actual-behaviour').fill('The sending indicator never stops.');

		await emailFallback.evaluate((element: HTMLElement) => {
			element.scrollIntoView({ block: 'center' });
		});
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
		await proof.attach();
	});
});
