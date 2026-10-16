/* eslint-disable @typescript-eslint/no-require-imports */
/** Browser proof contract for the ordinary signed-out welcome. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const PROOF_DOMAIN = 'app.dev.openmates.org';
const PROOF_DEVICE = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10) === 390 ? 'web-phone' : 'web-laptop';
const PROOF_DEVICES = ['web-laptop', 'web-phone'];

const proofContract = defineVideoProof({
	id: 'proof-video-browser-architecture',
	title: 'Explore the OpenMates welcome',
	surface: 'web',
	devices: PROOF_DEVICES,
	domain: PROOF_DOMAIN,
	transcript: [
		{ id: 'welcome', text: 'The new-chat welcome shows Daily Inspiration and the message composer.', checkpoint: 'welcome-visible', devices: PROOF_DEVICES },
		{ id: 'interests', text: 'Choose interests to shape the examples you see.', checkpoint: 'interests-visible', devices: PROOF_DEVICES },
		{ id: 'examples', text: 'Show all real example chats whenever you want to explore.', checkpoint: 'examples-visible', devices: PROOF_DEVICES }
	],
	assertions: [
		{ id: 'welcome.shell.visible', checkpoint: 'welcome-visible', visual: 'The normal Daily Inspiration card and composer are visible inside the chat shell.', devices: PROOF_DEVICES },
		{ id: 'welcome.interests.visible', checkpoint: 'interests-visible', visual: 'The interest selector is visible without a promotional story overlay.', devices: PROOF_DEVICES },
		{ id: 'welcome.examples.visible', checkpoint: 'examples-visible', visual: 'The all-examples grid contains real shared example chats.', devices: PROOF_DEVICES }
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

test.describe('Proof video browser architecture', () => {
	// contract-test: supporting surface=gui.web assertions=landing-onboarding.uses-real-chat-shell,landing-onboarding.guest-examples
	test('records the ordinary guest welcome, interests and real examples', async ({ page }: { page: any }, testInfo: any) => {
		const proof = createVideoProofRuntime(proofContract, {
			device: PROOF_DEVICE,
			attach: testInfo.attach.bind(testInfo),
			captureFrame: () => page.screenshot({ type: 'png' })
		});
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await proof.assert('welcome.shell.visible', async () => {
			await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible({ timeout: 15000 });
			await expect(page.getByTestId('message-editor')).toBeVisible();
			await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0);
		});
		await proof.checkpoint('welcome-visible');

		await proof.action('select-interests', async () => page.getByTestId('guest-interest-select-interests').click());
		await proof.assert('welcome.interests.visible', async () => {
			await expect(page.getByTestId('guest-interest-tags')).toBeVisible();
			await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0);
		});
		await proof.checkpoint('interests-visible');

		await proof.action('show-all-examples', async () => {
			await page.getByTestId('guest-interest-skip').click();
			await page.getByTestId('guest-show-all-examples').click();
		});
		await proof.assert('welcome.examples.visible', async () => {
			const grid = page.getByTestId('guest-all-examples-grid');
			await expect(grid).toBeVisible();
			await expect.poll(() => grid.locator('[data-chat-id^="example-"]').count()).toBeGreaterThan(1);
		});
		await proof.checkpoint('examples-visible');
		await proof.attach();
	});
});
