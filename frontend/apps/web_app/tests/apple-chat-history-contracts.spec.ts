/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Browser-rendered stable chat-history contracts for Apple parity.
 * Captures sanitized DOM order, semantic structure, computed styles, bounds,
 * interaction surfaces, and screenshots from existing public fixtures.
 * Runtime artifacts are consumed by the Apple parity audit and are not fixtures.
 * Spec source: docs/specs/apple-chat-history-full-parity/spec.yml
 */
export {};

const fs = require('fs');
const path = require('path');
const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const CONTRACT_SCHEMA_VERSION = 1;
const OUTPUT_DIR = path.resolve(
	process.cwd(),
	'test-results',
	'apple-ui-contracts',
	'chat-history'
);
// The badge contract belongs to hardcoded example chats, not intro/demo chats.
const EXAMPLE_CHAT_PATH = '/#chat-id=example-artemis-ii-mission';
const AUDIO_SHARED_CHAT_URL = 'https://app.dev.openmates.org/s/zuygP79v#BUw56h';
const SOURCE_QUOTE_SHARED_CHAT_URL = 'https://app.dev.openmates.org/s/aUc6RjnR#bIiNzh';

const DIMENSIONS = [
	{
		id: 'iphone-light-ltr',
		device: 'iphone',
		width: 390,
		height: 844,
		theme: 'light',
		direction: 'ltr'
	},
	{
		id: 'iphone-dark-rtl',
		device: 'iphone',
		width: 390,
		height: 844,
		theme: 'dark',
		direction: 'rtl'
	},
	{
		id: 'ipad-light-ltr',
		device: 'ipad',
		width: 1024,
		height: 1366,
		theme: 'light',
		direction: 'ltr'
	},
	{
		id: 'ipad-dark-rtl',
		device: 'ipad',
		width: 1024,
		height: 1366,
		theme: 'dark',
		direction: 'rtl'
	},
	{
		id: 'macos-light-ltr',
		device: 'macos',
		width: 1440,
		height: 900,
		theme: 'light',
		direction: 'ltr'
	},
	{
		id: 'macos-dark-rtl',
		device: 'macos',
		width: 1440,
		height: 900,
		theme: 'dark',
		direction: 'rtl'
	}
] as const;

const STYLE_PROPERTIES = [
	'display',
	'position',
	'width',
	'min-width',
	'max-width',
	'height',
	'min-height',
	'align-items',
	'justify-content',
	'gap',
	'margin-top',
	'margin-right',
	'margin-bottom',
	'margin-left',
	'padding-top',
	'padding-right',
	'padding-bottom',
	'padding-left',
	'border-radius',
	'background-color',
	'color',
	'font-family',
	'font-size',
	'font-weight',
	'line-height',
	'box-shadow',
	'overflow',
	'direction',
	'opacity'
];

function sanitizeText(value: string): string {
	return value
		.replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, '<EMAIL>')
		.replace(/https?:\/\/\S+/g, '<URL>')
		.replace(/\s+/g, ' ')
		.trim()
		.slice(0, 500);
}

async function applyAppearance(
	page: any,
	theme: 'light' | 'dark',
	direction: 'ltr' | 'rtl'
): Promise<void> {
	const history = page.getByTestId('chat-history-container');
	await expect(history).toBeVisible({ timeout: 45_000 });
	await history.evaluate(
		(element: HTMLElement, appearance: { theme: string; direction: string }) => {
			element.ownerDocument.documentElement.dir = appearance.direction;
			element.ownerDocument.documentElement.dataset.theme = appearance.theme;
		},
		{ theme, direction }
	);
	await expect
		.poll(() =>
			history.evaluate(
				(element: HTMLElement) => element.ownerDocument.documentElement.dataset.theme ?? 'light'
			)
		)
		.toBe(theme);
}

async function captureTestIdCollection(
	page: any,
	testId: string
): Promise<Record<string, unknown>[]> {
	const locator = page.getByTestId(testId);
	return locator.evaluateAll(
		(elements: HTMLElement[], options: { testId: string; styleProperties: string[] }) => {
			const round = (value: number) => Math.round(value * 100) / 100;
			const sanitize = (value: string) =>
				value
					.replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, '<EMAIL>')
					.replace(/https?:\/\/\S+/g, '<URL>')
					.replace(/\s+/g, ' ')
					.trim()
					.slice(0, 500);
			return elements.map((element, index) => {
				const computed = window.getComputedStyle(element);
				const computedStyle: Record<string, string> = {};
				for (const property of options.styleProperties) {
					computedStyle[property] = computed.getPropertyValue(property);
				}
				const rect = element.getBoundingClientRect();
				const descendants = Array.from(element.getElementsByTagName('*'));
				return {
					index,
					testId: options.testId,
					tagName: element.tagName.toLowerCase(),
					role: element.getAttribute('role'),
					ariaLabel: element.getAttribute('aria-label'),
					visibleText: sanitize(element.textContent ?? ''),
					childTestIds: descendants
						.map((child) => child.getAttribute('data-testid'))
						.filter((value): value is string => Boolean(value)),
					semanticTags: descendants
						.map((child) => child.tagName.toLowerCase())
						.filter((tag) =>
							[
								'h1',
								'h2',
								'h3',
								'p',
								'ul',
								'ol',
								'li',
								'table',
								'pre',
								'code',
								'a',
								'blockquote',
								'button'
							].includes(tag)
						),
					computedStyle,
					boundingBox: {
						x: round(rect.x),
						y: round(rect.y),
						width: round(rect.width),
						height: round(rect.height)
					}
				};
			});
		},
		{ testId, styleProperties: STYLE_PROPERTIES }
	);
}

async function captureDocumentOrder(page: any): Promise<Record<string, unknown>[]> {
	const content = page.getByTestId('chat-history-content');
	await expect(content).toBeVisible({ timeout: 45_000 });
	return content.evaluate((element: HTMLElement) => {
		const sanitize = (value: string) =>
			value
				.replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, '<EMAIL>')
				.replace(/https?:\/\/\S+/g, '<URL>')
				.replace(/\s+/g, ' ')
				.trim()
				.slice(0, 240);
		return [element, ...Array.from(element.getElementsByTagName('*'))]
			.filter((node) => node.hasAttribute('data-testid'))
			.map((node, index) => ({
				index,
				testId: node.getAttribute('data-testid'),
				tagName: node.tagName.toLowerCase(),
				role: node.getAttribute('role'),
				text: sanitize(node.textContent ?? '')
			}));
	});
}

async function captureClearance(page: any): Promise<Record<string, unknown>> {
	const messages = page
		.getByTestId('message-user')
		.or(page.getByTestId('message-assistant'))
		.or(page.getByTestId('message-system'));
	const finalMessage = messages.last();
	await expect(finalMessage).toBeVisible({ timeout: 45_000 });
	const obstruction = page
		.getByTestId('message-field')
		.or(page.getByTestId('new-chat-cta-fullwidth'))
		.first();
	await expect(obstruction).toBeVisible({ timeout: 20_000 });
	const messageBox = await finalMessage.boundingBox();
	const obstructionBox = await obstruction.boundingBox();
	expect(messageBox).not.toBeNull();
	expect(obstructionBox).not.toBeNull();
	return {
		finalMessageBottom: Math.round((messageBox!.y + messageBox!.height) * 100) / 100,
		obstructionTop: Math.round(obstructionBox!.y * 100) / 100,
		visibleAboveObstruction: messageBox!.y < obstructionBox!.y
	};
}

async function captureHistoryState(
	page: any,
	stateId: string,
	description: string,
	requiredTestIds: string[],
	screenshotPath: string
): Promise<Record<string, unknown>> {
	for (const testId of requiredTestIds) {
		await expect(page.getByTestId(testId).first(), `${stateId}: ${testId}`).toBeVisible({
			timeout: 45_000
		});
	}
	const elements: Record<string, unknown> = {};
	for (const testId of requiredTestIds) {
		elements[testId] = await captureTestIdCollection(page, testId);
	}
	await page.getByTestId('chat-history-container').screenshot({ path: screenshotPath });
	return {
		id: stateId,
		description,
		documentOrder: await captureDocumentOrder(page),
		elements,
		clearance: await captureClearance(page),
		screenshotPath
	};
}

test.describe('Apple stable chat-history web contracts', () => {
	for (const dimension of DIMENSIONS) {
		test(`captures ${dimension.id} stable history manifest`, async ({ page }) => {
			test.setTimeout(300_000);
			await page.setViewportSize({ width: dimension.width, height: dimension.height });
			const dimensionDir = path.join(OUTPUT_DIR, dimension.id);
			fs.mkdirSync(dimensionDir, { recursive: true });
			const states = [];

			await page.goto(getE2EDebugUrl(EXAMPLE_CHAT_PATH), { waitUntil: 'networkidle' });
			await applyAppearance(page, dimension.theme, dimension.direction);
			states.push(
				await captureHistoryState(
					page,
					'example-stable',
					'Synthetic public example chat with stable rendered message history.',
					[
						'chat-history-container',
						'chat-history-content',
						'chat-header-banner',
						'chat-header-title',
						'example-chat-badge',
						'message-assistant',
						'mate-profile',
						'mate-message-content',
						'new-chat-cta-fullwidth'
					],
					path.join(dimensionDir, 'example-stable.png')
				)
			);

			await page.reload({ waitUntil: 'networkidle' });
			await applyAppearance(page, dimension.theme, dimension.direction);
			states.push(
				await captureHistoryState(
					page,
					'example-restored',
					'The same public example history after a browser reload.',
					[
						'chat-history-container',
						'chat-history-content',
						'chat-header-banner',
						'message-assistant',
						'mate-message-content',
						'new-chat-cta-fullwidth'
					],
					path.join(dimensionDir, 'example-restored.png')
				)
			);

			await page.goto(AUDIO_SHARED_CHAT_URL, { waitUntil: 'networkidle' });
			await applyAppearance(page, dimension.theme, dimension.direction);
			states.push(
				await captureHistoryState(
					page,
					'public-shared-audio',
					'Public shared history with finished sent-audio preview and transcript.',
					[
						'chat-history-container',
						'chat-history-content',
						'chat-header-banner',
						'shared-chat-badge',
						'message-user',
						'message-assistant',
						'embed-preview',
						'recording-preview',
						'new-chat-cta-fullwidth'
					],
					path.join(dimensionDir, 'public-shared-audio.png')
				)
			);

			await page.goto(SOURCE_QUOTE_SHARED_CHAT_URL, { waitUntil: 'networkidle' });
			await applyAppearance(page, dimension.theme, dimension.direction);
			const sourceQuote = page.getByTestId('source-quote-block').first();
			await expect(sourceQuote).toBeVisible({ timeout: 45_000 });
			states.push(
				await captureHistoryState(
					page,
					'public-shared-source-quote',
					'Public shared history with a verified source quote in document order.',
					[
						'chat-history-container',
						'chat-history-content',
						'chat-header-banner',
						'shared-chat-badge',
						'message-assistant',
						'source-quote-block',
						'embed-preview',
						'new-chat-cta-fullwidth'
					],
					path.join(dimensionDir, 'public-shared-source-quote.png')
				)
			);
			await sourceQuote.click();
			await expect(page.getByTestId('embed-fullscreen-overlay').last()).toBeVisible({
				timeout: 30_000
			});
			states.push({
				id: 'source-quote-fullscreen-highlight',
				description:
					'Verified source quote opens dedicated fullscreen content with highlighted source text.',
				elements: {
					'embed-fullscreen-overlay': await captureTestIdCollection(
						page,
						'embed-fullscreen-overlay'
					),
					'embed-source-text-highlight': await captureTestIdCollection(
						page,
						'embed-source-text-highlight'
					)
				},
				screenshotPath: path.join(dimensionDir, 'source-quote-fullscreen-highlight.png')
			});
			await page
				.getByTestId('embed-fullscreen-overlay')
				.last()
				.screenshot({
					path: path.join(dimensionDir, 'source-quote-fullscreen-highlight.png')
				});

			const contract = {
				schemaVersion: CONTRACT_SCHEMA_VERSION,
				surface: 'chat-history',
				dimension,
				states,
				visibleTextPolicy: sanitizeText(
					'Synthetic/public fixture text only; URLs and emails are redacted.'
				)
			};
			const outputPath = path.join(OUTPUT_DIR, `chat-history.${dimension.id}.generated.json`);
			fs.writeFileSync(outputPath, `${JSON.stringify(contract, null, 2)}\n`, 'utf8');
			expect(states).toHaveLength(5);
			expect(outputPath).toContain(`chat-history.${dimension.id}.generated.json`);
		});
	}
});
