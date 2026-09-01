/**
 * Focused deployed checks for standalone MessageInput component rendering.
 * Keeps composer visual regressions separate from the full preview workflow.
 * Uses the chrome-free component route as the deterministic render surface.
 * Full chat-flow coverage remains in the broader composer specifications.
 */
import { expect, test } from './helpers/cookie-audit';

// contract-test-file: tooling
// playwright-account: not_required reason=isolated_component_preview

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';

const MESSAGE_INPUT_PROOF = defineVideoProof({
	id: 'message-input-component-states',
	title: 'MessageInput component states',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'minimized-state',
			text: 'The minimized message field shows its grey AI affordance and microphone without expanded controls.',
			checkpoint: 'minimized',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'expanded-state',
			text: 'Focusing the message field expands the composer and reveals its action controls.',
			checkpoint: 'expanded',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'hover-state',
			text: 'Hovering the model selector adds only the intended gentle interaction shadow.',
			checkpoint: 'model-selector-hovered',
			devices: ['web-laptop']
		},
		{
			id: 'model-menu-state',
			text: 'Clicking the model selector opens the model selection menu inside the isolated component.',
			checkpoint: 'model-menu-open',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'message-input.minimized-controls',
			checkpoint: 'minimized',
			visual: 'The minimized composer has the empty-state AI affordance and microphone, with no expanded action row.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'message-input.expanded-controls',
			checkpoint: 'expanded',
			visual: 'The expanded composer shows one action row and no duplicate empty-state microphone.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'message-input.hover-shadow',
			checkpoint: 'model-selector-hovered',
			visual: 'The hovered model selector has a subtle shadow while neighboring controls remain visually stable.',
			devices: ['web-laptop']
		},
		{
			id: 'message-input.model-menu',
			checkpoint: 'model-menu-open',
			visual: 'The model selection menu is open, readable, and contained within the component viewport.',
			devices: ['web-laptop', 'web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

test.describe('MessageInput component preview', () => {
	test('moves from minimized to expanded interactive states', async ({ page }, testInfo) => {
		const proof = createVideoProofRuntime(MESSAGE_INPUT_PROOF, {
			device: PROOF_DEVICE,
			attach: testInfo.attach.bind(testInfo)
		});
		const params = new URLSearchParams({
			theme: 'light',
			background: '#dbeafe',
			width: '680',
			chrome: '0'
		});

		await page.goto(`/dev/preview/enter_message/MessageInput?${params}`, {
			waitUntil: 'networkidle'
		});
		await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute(
			'data-preview-ready',
			'true'
		);

		const messageField = page.getByTestId('message-field');
		await proof.assert('message-input.minimized-controls', async () => {
			await expect(messageField).toBeVisible();
			await expect(page.getByTestId('guest-cta-mic-button')).toBeVisible();
			await expect(page.getByTestId('action-buttons')).toHaveCount(0);
			await expect(page.getByTestId('record-audio-button')).toHaveCount(0);
		});
		await proof.checkpoint('minimized');

		await proof.action('focus-message-field', async () => messageField.click());
		await proof.assert('message-input.expanded-controls', async () => {
			await expect(page.getByTestId('action-buttons')).toBeVisible();
			await expect(page.getByTestId('record-audio-button')).toBeVisible();
			await expect(page.getByTestId('guest-cta-mic-button')).toHaveCount(0);
			await expect(page.getByTestId('composer-model-selector')).toBeVisible();
		});
		await proof.checkpoint('expanded');

		const selector = page.getByTestId('composer-model-selector');
		if (PROOF_DEVICE === 'web-laptop') {
			await proof.action('hover-model-selector', async () => selector.hover());
			await proof.assert('message-input.hover-shadow', async () => {
				await expect
					.poll(() => selector.evaluate((element) => window.getComputedStyle(element).filter))
					.toContain('drop-shadow');
			});
			await proof.checkpoint('model-selector-hovered');
		}

		await proof.action('open-model-menu', async () => selector.click());
		await proof.assert('message-input.model-menu', async () => {
			await expect(page.getByTestId('composer-model-selector-menu')).toBeVisible();
		});
		await proof.checkpoint('model-menu-open');
		await proof.attach();
	});
});
