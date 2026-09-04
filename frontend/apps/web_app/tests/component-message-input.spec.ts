/**
 * Focused deployed checks for standalone MessageInput component rendering.
 * Keeps composer visual regressions separate from the full preview workflow.
 * Uses the chrome-free component route as the deterministic render surface.
 * Full chat-flow coverage remains in the broader composer specifications.
 */
import { expect, test } from './helpers/cookie-audit';
import type { Locator } from '@playwright/test';

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
			id: 'speech-toggle-off',
			text: 'The speech control starts with a visible mute glyph and no square background.',
			checkpoint: 'speech-toggle-off',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'speech-toggle-on',
			text: 'Clicking the speech control immediately replaces the mute glyph with the audio glyph.',
			checkpoint: 'speech-toggle-on',
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
		},
		{
			id: 'model-row-selection',
			text: 'Clicking a model row selects that exact model while opening its details.',
			checkpoint: 'model-row-selected',
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
			id: 'assistant-speech.preference.chat-scoped-default-off',
			checkpoint: 'speech-toggle-off',
			visual: 'The off state renders one visible mute glyph on a transparent icon button.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'message-input.actions.visibility',
			checkpoint: 'speech-toggle-on',
			visual: 'The on state immediately renders one visible audio glyph on the same transparent icon button.',
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
		},
		{
			id: 'message-input.model-row-selection',
			checkpoint: 'model-row-selected',
			visual: 'The composer visibly identifies the exact model selected by clicking its model row.',
			devices: ['web-laptop', 'web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

test.describe('MessageInput component preview', () => {
	// contract-test: direct surface=gui.web assertions=message-input.actions.visibility,assistant-speech.preference.chat-scoped-default-off,ai-model-routing.composer.mention-to-exact-selection,ai-model-routing.composer.responsive-actions
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

		const speechToggle = page.getByTestId('assistant-speech-toggle');
		const mutedGlyph = speechToggle.getByTestId('assistant-speech-muted-icon');
		const audioGlyph = speechToggle.getByTestId('assistant-speech-audio-icon');
		await proof.assert('assistant-speech.preference.chat-scoped-default-off', async () => {
			await expectSpeechToggleState(speechToggle, mutedGlyph, audioGlyph, false);
		});
		await proof.checkpoint('speech-toggle-off');

		await proof.action('enable-assistant-speech', async () => speechToggle.click());
		await proof.assert('message-input.actions.visibility', async () => {
			await expectSpeechToggleState(speechToggle, mutedGlyph, audioGlyph, true);
			await expect(page.getByTestId('assistant-speech-toggle-status')).toHaveText('Speech turned on');
		});
		await proof.checkpoint('speech-toggle-on');

		await proof.action('disable-assistant-speech', async () => speechToggle.click());
		await expectSpeechToggleState(speechToggle, mutedGlyph, audioGlyph, false);

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

		const modelMenu = page.getByTestId('composer-model-selector-menu');
		await modelMenu.getByTestId('composer-model-provider-label').first().click();
		const firstModelName = modelMenu.getByTestId('composer-model-name').first();
		const selectedModelName = (await firstModelName.textContent())?.trim();
		expect(selectedModelName).toBeTruthy();
		await proof.action('select-model-row', async () => firstModelName.click());
		await proof.assert('message-input.model-row-selection', async () => {
			await expect.poll(async () => selector.getAttribute('aria-label')).toContain(selectedModelName!);
		});
		await proof.checkpoint('model-row-selected');
		await proof.attach();
	});
});

async function expectSpeechToggleState(
	toggle: Locator,
	mutedGlyph: Locator,
	audioGlyph: Locator,
	enabled: boolean
): Promise<void> {
	await expect(toggle).toHaveAttribute('aria-pressed', String(enabled));
	await expect(toggle).toHaveAccessibleName(enabled ? 'Turn off speaking' : 'Speak responses');
	await expect(toggle).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
	await expect(enabled ? audioGlyph : mutedGlyph).toHaveAttribute('data-visible', 'true');
	await expect(enabled ? mutedGlyph : audioGlyph).toHaveAttribute('data-visible', 'false');
	const visibleGlyph = enabled ? audioGlyph : mutedGlyph;
	const glyph = await visibleGlyph.evaluate((element) => {
		const bounds = element.getBoundingClientRect();
		return { width: bounds.width, height: bounds.height };
	});
	await expect(visibleGlyph.locator('path')).not.toHaveCount(0);
	await expect.poll(() => visibleGlyph.evaluate((element) => getComputedStyle(element).opacity)).toBe('1');
	expect(glyph.width).toBeGreaterThanOrEqual(20);
	expect(glyph.height).toBeGreaterThanOrEqual(20);
}
