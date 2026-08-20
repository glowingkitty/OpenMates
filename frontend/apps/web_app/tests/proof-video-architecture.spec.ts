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

const PROOF_DOMAIN_BADGE_ID = 'openmates-proof-domain-badge';
const PROOF_DOMAIN = 'app.dev.openmates.org';

async function captureBrowserProofFrame(page: any, domain: string): Promise<Buffer> {
	await page.evaluate(({badgeId, value}: {badgeId: string; value: string}) => {
		document.getElementById(badgeId)?.remove();
		const badge = document.createElement('div');
		badge.id = badgeId;
		badge.textContent = `● ${value}`;
		badge.style.cssText = 'position:fixed;top:8px;left:50%;transform:translateX(-50%);z-index:2147483647;padding:7px 18px;border:1px solid rgba(90,90,100,.35);border-radius:10px;background:rgba(248,248,250,.94);box-shadow:0 2px 10px rgba(22,24,31,.16);color:#34343a;font:16px Arial,sans-serif;';
		document.body.appendChild(badge);
	}, {badgeId: PROOF_DOMAIN_BADGE_ID, value: domain});
	try {
		return await page.screenshot({type: 'png'});
	} finally {
		await page.evaluate((badgeId: string) => document.getElementById(badgeId)?.remove(), PROOF_DOMAIN_BADGE_ID);
	}
}

const proofContract = defineVideoProof({
	id: 'proof-video-browser-architecture',
	title: 'Explore the OpenMates welcome stories',
	surface: 'web',
	devices: ['web-laptop'],
	domain: PROOF_DOMAIN,
	transcript: [
		{
			id: 'welcome',
			text: 'The OpenMates welcome screen introduces the product inside a browser showing the deployed domain.',
			checkpoint: 'welcome-visible',
			devices: ['web-laptop']
		},
		{
			id: 'actionable',
			text: 'Select the next story to see how OpenMates turns requests into actionable results.',
			checkpoint: 'actionable-visible',
			devices: ['web-laptop']
		},
		{
			id: 'privacy',
			text: 'Advance once more to see the privacy and safety story presented in the same welcome interface.',
			checkpoint: 'privacy-visible',
			devices: ['web-laptop']
		}
	],
	assertions: [
		{
			id: 'welcome.shell.visible',
			checkpoint: 'welcome-visible',
			visual: 'The OpenMates welcome interface is fully visible without clipping or loading errors.',
			devices: ['web-laptop']
		},
		{
			id: 'welcome.actionable.visible',
			checkpoint: 'actionable-visible',
			visual: 'The Actionable story heading and its illustrated result remain inside the welcome card.',
			devices: ['web-laptop']
		},
		{
			id: 'welcome.privacy.visible',
			checkpoint: 'privacy-visible',
			visual: 'The Privacy and safety story is visible with no overlapping or truncated content.',
			devices: ['web-laptop']
		}
	],
	tutorial: {readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000}
});

test.describe('Proof video browser architecture', () => {
	// contract-test: supporting surface=gui.web assertions=landing-onboarding.uses-real-chat-shell,landing-onboarding.coordinated-story-progress
	test('records a fast spec-owned welcome tutorial timeline', async ({page}: {page: any}, testInfo: any) => {
		const proof = createVideoProofRuntime(proofContract, {
			device: 'web-laptop',
			attach: testInfo.attach.bind(testInfo),
			captureFrame: () => captureBrowserProofFrame(page, PROOF_DOMAIN)
		});

		await page.goto(getE2EDebugUrl('/?landing-header-motion'), {waitUntil: 'domcontentloaded'});
		await proof.assert('welcome.shell.visible', async () => {
			await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({timeout: 15000});
		});
		await proof.checkpoint('welcome-visible');

		await proof.action('open-actionable-story', async () => {
			await page.getByTestId('daily-inspiration-next').click();
		});
		await proof.assert('welcome.actionable.visible', async () => {
			await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable.', {timeout: 5000});
		});
		await proof.checkpoint('actionable-visible');

		await proof.action('open-privacy-story', async () => {
			await page.getByTestId('daily-inspiration-next').click();
		});
		await proof.assert('welcome.privacy.visible', async () => {
			await expect(page.getByTestId('daily-inspiration-banner')).toHaveAttribute('data-current-inspiration-id', 'openmates-privacy-safety');
		});
		await proof.checkpoint('privacy-visible');
		await proof.attach();
	});
});
