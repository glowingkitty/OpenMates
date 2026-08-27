/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Deployed architecture proof for deterministic browser tutorial generation.
 *
 * The test runs at normal speed and attaches its complete spec-owned transcript,
 * paired assertions, and checkpoints for Remotion post-processing.
 */

export {};

const {test, expect} = require('./helpers/cookie-audit');
const {getE2EDebugUrl} = require('./signup-flow-helpers');
const {createVideoProofRuntime, defineVideoProof} = require('./helpers/video-proof');

const PROOF_DOMAIN = 'app.dev.openmates.org';
const PROOF_DEVICE = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10) === 390 ? 'web-phone' : 'web-laptop';
const PROOF_DEVICES = ['web-laptop', 'web-phone'];

async function captureBrowserProofFrame(page: any): Promise<Buffer> {
	return page.screenshot({type: 'png'});
}

async function waitForFiniteVisualMotion(page: any, testId: string): Promise<void> {
	await page.getByTestId(testId).evaluate(async (element: Element) => {
		const finiteAnimations = element.getAnimations({subtree: true}).filter((animation) => {
			const endTime = animation.effect?.getComputedTiming().endTime;
			return typeof endTime === 'number' && Number.isFinite(endTime);
		});
		await Promise.all(finiteAnimations.map((animation) => animation.finished.catch(() => undefined)));
	});
}

const proofContract = defineVideoProof({
	id: 'proof-video-browser-architecture',
	title: 'Explore the OpenMates welcome stories',
	surface: 'web',
	devices: PROOF_DEVICES,
	domain: PROOF_DOMAIN,
	transcript: [
		{
			id: 'welcome',
			text: 'The OpenMates welcome screen introduces the product inside a browser showing the deployed domain.',
			checkpoint: 'welcome-visible',
			devices: PROOF_DEVICES
		},
		{
			id: 'actionable',
			text: 'Select the next story to see how OpenMates turns requests into actionable results.',
			checkpoint: 'actionable-visible',
			devices: PROOF_DEVICES
		},
		{
			id: 'privacy',
			text: 'Advance once more to see the privacy and safety story presented in the same welcome interface.',
			checkpoint: 'privacy-visible',
			devices: PROOF_DEVICES
		}
	],
	assertions: [
		{
			id: 'welcome.shell.visible',
			checkpoint: 'welcome-visible',
			visual: 'The OpenMates welcome interface is fully visible in the expanded browser welcome card with no loading errors.',
			devices: PROOF_DEVICES
		},
		{
			id: 'welcome.actionable.visible',
			checkpoint: 'actionable-visible',
			visual: 'The Actionable story heading and its illustrated result remain inside the welcome card.',
			devices: PROOF_DEVICES
		},
		{
			id: 'welcome.privacy.visible',
			checkpoint: 'privacy-visible',
			visual: 'The Privacy and safety story is visible while the intentional neighboring card preview stays at the edge without covering the primary content.',
			devices: PROOF_DEVICES
		}
	],
	tutorial: {readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000}
});

test.describe('Proof video browser architecture', () => {
	// contract-test: supporting surface=gui.web assertions=landing-onboarding.uses-real-chat-shell,landing-onboarding.coordinated-story-progress
	test('records a fast spec-owned welcome tutorial timeline', async ({page}: {page: any}, testInfo: any) => {
		const proof = createVideoProofRuntime(proofContract, {
			device: PROOF_DEVICE,
			attach: testInfo.attach.bind(testInfo),
			captureFrame: () => captureBrowserProofFrame(page)
		});

		await page.goto(getE2EDebugUrl('/?landing-header-motion'), {waitUntil: 'domcontentloaded'});
		await expect.poll(() => page.evaluate(() => ({
			colorScheme: document.documentElement.style.colorScheme,
			prefersDark: window.matchMedia('(prefers-color-scheme: dark)').matches
		}))).toEqual(PROOF_DEVICE === 'web-phone'
			? {colorScheme: 'dark', prefersDark: true}
			: {colorScheme: 'light', prefersDark: false});
		await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({timeout: 15000});
		await waitForFiniteVisualMotion(page, 'landing-intro-expanded');
		await proof.assert('welcome.shell.visible', async () => {
			await expect(page.getByTestId('landing-intro-expanded')).toBeVisible();
		});
		await proof.checkpoint('welcome-visible');

		await proof.action('open-actionable-story', async () => {
			await page.getByTestId('daily-inspiration-next').click();
		});
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable.', {timeout: 5000});
		await expect(page.getByTestId('guest-slide-content')).toHaveAttribute('data-guest-heading-phase', 'demo', {timeout: 5000});
		await expect(page.getByTestId('landing-actionable-event-demo')).toBeVisible();
		await waitForFiniteVisualMotion(page, 'guest-slide-content');
		await proof.assert('welcome.actionable.visible', async () => {
			await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable.');
			await expect(page.getByTestId('landing-actionable-event-demo')).toBeVisible();
		});
		await proof.checkpoint('actionable-visible');

		await proof.action('open-privacy-story', async () => {
			await page.getByTestId('daily-inspiration-next').click();
		});
		await expect(page.getByTestId('daily-inspiration-banner')).toHaveAttribute('data-current-inspiration-id', 'openmates-privacy-safety');
		await expect(page.getByTestId('guest-slide-content')).toHaveAttribute('data-guest-heading-phase', 'demo', {timeout: 5000});
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Privacy & safety', {timeout: 5000});
		await waitForFiniteVisualMotion(page, 'guest-slide-content');
		await proof.assert('welcome.privacy.visible', async () => {
			await expect(page.getByTestId('daily-inspiration-banner')).toHaveAttribute('data-current-inspiration-id', 'openmates-privacy-safety');
			await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Privacy & safety');
		});
		await proof.checkpoint('privacy-visible');
		await proof.attach();
	});
});
