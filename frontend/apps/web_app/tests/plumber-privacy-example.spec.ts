/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Public proof for the real plumber conversation and approved fictional contacts.
 * Verifies replacement and reveal/hide on the transcript and mail fullscreen.
 * No account login, original account mappings, AI requests, or audio are used.
 * Caption checkpoints are the source for phone/laptop proof-video review.
 * Architecture: demo_chats/exampleChatStore.ts registers public PII sidecars.
 */
export {};

const { test, expect } = require('@playwright/test');
const { openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const CHAT_ID = 'example-plumber-message-email-phone';
const EXAMPLE_PATH = '/example/plumber-message-email-phone-privacy';
const EMAIL = 'lena.hoffmann@example.com';
const PHONE = '+1 202-555-0147';
const DEVICES = ['web-phone', 'web-laptop'];
const PROFILES = [
	{ device: 'web-phone', width: 390, height: 844 },
	{ device: 'web-laptop', width: 1440, height: 900 }
];
const contract = defineVideoProof({
	id: 'plumber-privacy-example', title: 'Protect email and phone in a plumber message',
	surface: 'web', domain: 'app.dev.openmates.org', devices: DEVICES,
	transcript: [
		{ id: 'protected', checkpoint: 'protected', devices: DEVICES, text: 'This real plumber request replaces the fictional email and phone with placeholders.' },
		{ id: 'revealed', checkpoint: 'revealed', devices: DEVICES, text: 'Reveal the two approved fictional contact details with the privacy control.' },
		{ id: 'draft', checkpoint: 'draft', devices: DEVICES, text: 'The mail draft preserves the repair request and lets you hide the contact details again.' }
	],
	assertions: [
		{ id: 'protected', checkpoint: 'protected', devices: DEVICES, visual: 'The plumber request visibly contains email and phone placeholders.' },
		{ id: 'revealed', checkpoint: 'revealed', devices: DEVICES, visual: 'The request visibly reveals only the approved fictional email and phone.' },
		{ id: 'draft', checkpoint: 'draft', devices: DEVICES, visual: 'Mail fullscreen shows the repair request with both contacts replaced again.' }
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1200, maximumHoldMs: 6000 }
});

for (const profile of PROFILES) {
	// contract-test: supporting surface=gui.web assertions=pii.message.owner-local-reveal,pii.embed.owner-local-reveal-sync,public-example-chats.transcript.safe-rendering
	test(`${profile.device} protects approved fictional plumber contacts`, async ({ browser, baseURL }, testInfo) => {
		test.setTimeout(90000);
		const context = await browser.newContext({
			baseURL, viewport: { width: profile.width, height: profile.height },
			recordVideo: { dir: 'test-results/proof-video-source/plumber-privacy-example', size: { width: profile.width, height: profile.height } }
		});
		const page = await context.newPage();
		const proof = createVideoProofRuntime(contract, {
			device: profile.device, attach: testInfo.attach.bind(testInfo),
			captureFrame: () => page.screenshot({ type: 'png' })
		});
		try {
			await page.goto(getE2EDebugUrl(EXAMPLE_PATH), { waitUntil: 'domcontentloaded' });
			await expect(page.getByText('Internal Error', { exact: true })).toHaveCount(0);
			await page.goto(getE2EDebugUrl(`/#chat-id=${CHAT_ID}`), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('example-chat-badge')).toBeVisible({ timeout: 30000 });
			const request = page.getByTestId('user-message-content').first();
			const toggle = page.getByTestId('chat-pii-toggle');
			await expect(toggle).toBeVisible();
			await proof.assert('protected', async () => {
				await expect(request).toContainText('[EMAIL_1_com]');
				await expect(request).toContainText('[PHONE_1_147]');
				await expect(request).not.toContainText(EMAIL);
			});
			await request.scrollIntoViewIfNeeded();
			await proof.checkpoint('protected');
			await proof.action('reveal-contacts', () => toggle.click());
			await proof.assert('revealed', async () => {
				await expect(request).toContainText(EMAIL);
				await expect(request).toContainText(PHONE);
			});
			await request.scrollIntoViewIfNeeded();
			await proof.checkpoint('revealed');
			const preview = page.getByTestId('embed-preview').first();
			const fullscreen = await openFullscreen(page, preview);
			await expect(fullscreen).toContainText(EMAIL);
			await expect(fullscreen).toContainText(PHONE);
			await fullscreen.getByTestId('embed-pii-toggle').click();
			await proof.assert('draft', async () => {
				await expect(fullscreen).toContainText('[EMAIL_1_com]');
				await expect(fullscreen).toContainText('[PHONE_1_147]');
				await expect(fullscreen).toContainText('tomorrow afternoon');
				await expect(fullscreen).not.toContainText(EMAIL);
			});
			await proof.checkpoint('draft');
			await closeFullscreen(page, fullscreen);
			await expect(request).toContainText('[EMAIL_1_com]');
			await page.reload({ waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('example-chat-badge')).toBeVisible({ timeout: 30000 });
			const suggestion = page.getByTestId('follow-up-suggestion-item').first();
			await expect(suggestion).toBeVisible();
			// Public follow-ups open signup for guests; they do not create a draft.
			// See ActiveChat.handleFollowUpSuggestionClick and the review checklist.
			await suggestion.click();
			await expect(page.getByRole('button', { name: 'Sign up', exact: true })).toBeVisible();
			await expect(page.getByRole('button', { name: /^Continue with v/ })).toBeVisible();
			await proof.attach();
		} finally {
			const video = page.video();
			await context.close();
			if (video) await testInfo.attach(`plumber-privacy-${profile.device}`, { path: await video.path(), contentType: 'video/webm' });
		}
	});
}
