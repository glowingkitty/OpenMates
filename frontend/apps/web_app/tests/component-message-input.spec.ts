/**
 * Focused deployed checks for standalone MessageInput component rendering.
 * Keeps composer visual regressions separate from the full preview workflow.
 * Uses the chrome-free component route as the deterministic render surface.
 * Full chat-flow coverage remains in the broader composer specifications.
 */
import { expect, test } from './helpers/cookie-audit';
import type { Locator } from '@playwright/test';
import { waitForComponentPreview } from './helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';
const VIEWPORT_EDGE_TOLERANCE_PX = 1;

const MESSAGE_INPUT_PROOF = defineVideoProof({
	id: 'message-input-component-states',
	title: 'MessageInput component states',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'minimized-state',
			text: 'The minimized composer shows only its AI affordance and microphone.',
			checkpoint: 'minimized',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'expanded-state',
			text: 'Focusing expands the composer and keeps its controls and microphone guidance in view.',
			checkpoint: 'expanded',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'speech-toggle-off',
			text: 'Speech starts muted on a transparent control.',
			checkpoint: 'speech-toggle-off',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'speech-toggle-on',
			text: 'Clicking speech displays the audio glyph.',
			checkpoint: 'speech-toggle-on',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'hover-state',
			text: 'Hovering adds a gentle selector shadow.',
			checkpoint: 'model-selector-hovered',
			devices: ['web-laptop']
		},
		{
			id: 'model-menu-state',
			text: 'The selector opens the model menu.',
			checkpoint: 'model-menu-open',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'model-row-selection',
			text: 'Clicking a model row selects it while opening details.',
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
			id: 'message-input.layout.responsive-parity',
			checkpoint: 'expanded',
			visual: 'After a denied microphone press, the complete warning notification stays within the viewport.',
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
	for (const { viewportWidth, fieldWidth } of [
		{ viewportWidth: 390, fieldWidth: 330 },
		{ viewportWidth: 1280, fieldWidth: 680 }
	]) {
		// contract-test: direct surface=gui.web assertions=message-input.actions.visibility,message-input.layout.responsive-parity
		test(`minimizes a draft and offers expansion only when it scrolls at ${viewportWidth}px`, async ({ page }) => {
			await page.setViewportSize({ width: viewportWidth, height: 844 });
			const params = new URLSearchParams({
				theme: 'dark', background: '#dbeafe', width: String(fieldWidth), chrome: '0', variant: 'inlineCompact'
			});
			await page.goto(`/dev/preview/enter_message/MessageInput?${params}`);
			await waitForComponentPreview(page);
			const field = page.getByTestId('message-field');
			const editor = page.getByTestId('message-editor').locator('.ProseMirror');
			await expect(field).toBeVisible();
			await field.click();
			const draft = 'What events are upcoming in Berlin this week? Include the venue, date and time for each event.';
			await editor.fill(draft);
			await expect(field).toHaveAttribute('data-focused', 'true');
			await page.mouse.click(4, 4);
			await expect(field).toHaveAttribute('data-focused', 'false');
			await expect.poll(() => field.evaluate((element) => element.getBoundingClientRect().height)).toBe(48);
			const summary = page.getByTestId('message-draft-summary-text');
			await expect(summary).toBeVisible();
			await expect(summary).toHaveText(draft);
			await expect(summary).toHaveCSS('text-overflow', 'ellipsis');
			await expect(summary).toHaveCSS('white-space', 'nowrap');
			const bounds = await summary.evaluate((element) => ({
				width: element.clientWidth, textWidth: element.scrollWidth,
				right: element.getBoundingClientRect().right, viewport: window.innerWidth
			}));
			expect(bounds.width).toBeGreaterThan(0);
			expect(bounds.textWidth).toBeGreaterThan(bounds.width);
			expect(bounds.right).toBeLessThanOrEqual(bounds.viewport);
			await expect(page.getByTestId('action-buttons')).toHaveCount(0);
			await page.screenshot({ path: test.info().outputPath(`message-input-minimized-draft-${viewportWidth}.png`) });
			await field.click();
			await expect(field).toHaveAttribute('data-focused', 'true');
			await expect(summary).toHaveCount(0);
			await expect(editor).toHaveText(draft);
			await expect.poll(() => field.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(180);
			const actions = page.getByTestId('action-buttons');
			await expect(actions).toBeVisible();
			const expand = page.getByTestId('message-expand-button');
			const scrollable = field.locator('.scrollable-content');
			await expect.poll(() => scrollable.evaluate((element) => element.scrollHeight <= element.clientHeight)).toBe(true);
			await expect(expand).toHaveCount(0);
			const focusedBounds = await editor.evaluate((element) => {
				const fieldElement = element.closest('[data-testid="message-field"]')!;
				const field = fieldElement.getBoundingClientRect();
				const actions = fieldElement.querySelector('[data-testid="action-buttons"]')!.getBoundingClientRect();
				const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
				const textRects: DOMRect[] = [];
				while (walker.nextNode()) {
					const range = document.createRange();
					range.selectNodeContents(walker.currentNode);
					textRects.push(...Array.from(range.getClientRects()).filter((rect) => rect.width > 0 && rect.height > 0));
				}
				return { textRects: textRects.length, textTop: Math.min(...textRects.map((rect) => rect.top)),
					textBottom: Math.max(...textRects.map((rect) => rect.bottom)),
					textLeft: Math.min(...textRects.map((rect) => rect.left)),
					textRight: Math.max(...textRects.map((rect) => rect.right)),
					fieldTop: field.top, fieldLeft: field.left, fieldRight: field.right,
					actionsTop: actions.top };
			});
			expect(focusedBounds.textRects).toBeGreaterThan(0);
			expect(focusedBounds.textTop).toBeGreaterThanOrEqual(focusedBounds.fieldTop);
			expect(focusedBounds.textLeft).toBeGreaterThanOrEqual(focusedBounds.fieldLeft);
			expect(focusedBounds.textRight).toBeLessThanOrEqual(focusedBounds.fieldRight);
			expect(focusedBounds.textBottom).toBeLessThanOrEqual(focusedBounds.actionsTop);
			await page.screenshot({ path: test.info().outputPath(`message-input-focused-draft-${viewportWidth}.png`) });

			const longDraft = Array.from({ length: 24 }, (_, index) => `Draft line ${index + 1}: details for upcoming events in Berlin.`).join('\n');
			await editor.fill(longDraft);
			await expect.poll(() => scrollable.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
			await expect(expand).toBeVisible();
			// Bring the first visible lines beside the control into view before checking the gutter.
			await editor.press('ControlOrMeta+Home');
			const overflowBounds = await editor.evaluate((element) => {
				const fieldElement = element.closest('[data-testid="message-field"]')!;
				const expand = fieldElement.querySelector('[data-testid="message-expand-button"]')!.getBoundingClientRect();
				const scrollable = fieldElement.querySelector('.scrollable-content')!.getBoundingClientRect();
				const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
				const textRects: DOMRect[] = [];
				while (walker.nextNode()) {
					const range = document.createRange();
					range.selectNodeContents(walker.currentNode);
					textRects.push(...Array.from(range.getClientRects()).filter((rect) => rect.width > 0 && rect.height > 0
						&& rect.top < scrollable.bottom && rect.bottom > scrollable.top));
				}
				return { visibleLines: textRects.length, textRight: Math.max(...textRects.map((rect) => rect.right)),
					textTop: Math.min(...textRects.map((rect) => rect.top)), expandLeft: expand.left, expandBottom: expand.bottom,
					overlapsExpand: textRects.some((rect) => rect.left < expand.right && rect.right > expand.left
						&& rect.top < expand.bottom && rect.bottom > expand.top) };
			});
			expect(overflowBounds.visibleLines).toBeGreaterThan(0);
			expect(overflowBounds.overlapsExpand).toBe(false);
			expect(overflowBounds.textRight).toBeLessThanOrEqual(overflowBounds.expandLeft - 8);
			expect(overflowBounds.textTop).toBeLessThan(overflowBounds.expandBottom);
			await page.screenshot({ path: test.info().outputPath(`message-input-overflow-draft-${viewportWidth}.png`) });
			await editor.fill(draft);
			await expect(expand).toHaveCount(0);
			await editor.fill(longDraft);
			await expect(expand).toBeVisible();
			await expand.click();
			await expect(field).toHaveClass(/fullscreen-expanded/);
			await editor.fill(draft);
			await expect.poll(() => scrollable.evaluate((element) => element.scrollHeight <= element.clientHeight)).toBe(true);
			await expect(expand).toBeVisible();
			await expect(expand).toHaveClass(/icon_minimize/);
			await expand.click();
			await expect(field).not.toHaveClass(/fullscreen-expanded/);
			await expect(expand).toHaveCount(0);
			await expect(editor).toHaveText(draft);
		});
	}

	// contract-test: direct surface=gui.web assertions=message-input.actions.visibility,message-input.layout.responsive-parity,assistant-speech.preference.chat-scoped-default-off,ai-model-routing.composer.mention-to-exact-selection,ai-model-routing.composer.responsive-actions
	test('moves from minimized to expanded interactive states', async ({ page }, testInfo) => {
		await page.addInitScript(() => {
			const originalQuery = navigator.permissions.query.bind(navigator.permissions);
			Object.defineProperty(navigator.permissions, 'query', {
				configurable: true,
				value: (descriptor: PermissionDescriptor) => descriptor.name === 'microphone'
					? Promise.resolve({ state: 'denied', onchange: null } as PermissionStatus)
					: originalQuery(descriptor)
			});
		});
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

		await page.goto(`/dev/preview/enter_message/MessageInputNotificationPreview?${params}`, {
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
		await proof.assert('message-input.layout.responsive-parity', async () => {
			await page.getByTestId('record-audio-button').click();
			const warning = page.getByText('Microphone blocked - enable it in browser settings', { exact: true });
			await expect(warning).toBeVisible();
			await expect(page.getByTestId('notification').filter({ hasText: 'Microphone blocked' })).toBeVisible();
			// Measure the actual rendered notification text, not just its container.
			const bounds = await warning.evaluate((element) => {
				const range = document.createRange();
				range.selectNodeContents(element);
				const text = range.getBoundingClientRect();
				const pill = element.getBoundingClientRect();
				return { left: Math.min(text.left, pill.left), right: Math.max(text.right, pill.right), viewport: window.innerWidth };
			});
			expect(bounds.left, 'Microphone guidance must not overflow the left viewport edge').toBeGreaterThanOrEqual(-VIEWPORT_EDGE_TOLERANCE_PX);
			expect(bounds.right, 'Complete microphone guidance must fit within the right viewport edge').toBeLessThanOrEqual(bounds.viewport + VIEWPORT_EDGE_TOLERANCE_PX);
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
		const firstModelIcon = modelMenu.getByTestId('composer-model-icon').first();
		const firstModelCapability = modelMenu.getByTestId('composer-model-capability').first();
		const [iconBox, capabilityBox] = await Promise.all([
			firstModelIcon.boundingBox(),
			firstModelCapability.boundingBox()
		]);
		expect(iconBox).not.toBeNull();
		expect(capabilityBox).not.toBeNull();
		expect(Math.abs(capabilityBox!.x + capabilityBox!.width / 2 - (iconBox!.x + iconBox!.width))).toBeLessThanOrEqual(1);
		expect(Math.abs(capabilityBox!.y + capabilityBox!.height / 2 - (iconBox!.y + iconBox!.height))).toBeLessThanOrEqual(1);
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
