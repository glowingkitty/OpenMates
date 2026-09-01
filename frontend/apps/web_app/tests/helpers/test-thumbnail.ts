/**
 * Fixed-resolution, spec-owned thumbnail capture for Playwright tests.
 *
 * Specs declare stable test IDs for the visual focus and optional surrounding
 * context. This helper computes a bounded 16:10 crop, captures it, and scales
 * it without distortion to the canonical 1280x800 thumbnail artifact.
 */

/* eslint-disable @typescript-eslint/no-require-imports */

import type {Locator, Page, TestInfo} from '@playwright/test';

const {spawnSync} = require('node:child_process');

const OUTPUT_WIDTH = 1280;
const OUTPUT_HEIGHT = 800;
const MIN_SOURCE_WIDTH = 640;
const MIN_SOURCE_HEIGHT = 400;
const THUMBNAIL_ATTACHMENT_NAME = 'openmates-test-thumbnail';
const THUMBNAIL_METADATA_ATTACHMENT_NAME = 'openmates-test-thumbnail-metadata';
const FFMPEG_MAX_BUFFER_BYTES = 32 * 1024 * 1024;

interface ThumbnailTarget {
	testId: string;
	occurrence?: 'first' | 'last' | number;
}

interface ThumbnailPadding {
	top: number;
	right: number;
	bottom: number;
	left: number;
}

interface TestThumbnailDefinition {
	id: string;
	focus: ThumbnailTarget[];
	context?: ThumbnailTarget[];
	padding?: number | Partial<ThumbnailPadding>;
	aspectRatio?: '16:10';
	output?: {width: 1280; height: 800};
}

interface Bounds {
	x: number;
	y: number;
	width: number;
	height: number;
}

function requireText(value: unknown, label: string): asserts value is string {
	if (typeof value !== 'string' || !value.trim()) throw new Error(`Test thumbnail ${label} must be non-empty`);
}

function validateTargets(targets: unknown, label: string): asserts targets is ThumbnailTarget[] {
	if (!Array.isArray(targets) || targets.length === 0) throw new Error(`Test thumbnail ${label} targets are required`);
	for (const target of targets) {
		requireText(target?.testId, `${label} testId`);
		if (
			target.occurrence !== undefined &&
			target.occurrence !== 'first' &&
			target.occurrence !== 'last' &&
			!(Number.isInteger(target.occurrence) && target.occurrence >= 0)
		) {
			throw new Error(`Test thumbnail ${label} occurrence must be first, last, or a non-negative index`);
		}
	}
}

function normalizePadding(value: number | Partial<ThumbnailPadding> | undefined): ThumbnailPadding {
	if (typeof value === 'number') {
		if (!(value >= 0)) throw new Error('Test thumbnail padding must be non-negative');
		return {top: value, right: value, bottom: value, left: value};
	}
	const padding = {
		top: value?.top ?? 48,
		right: value?.right ?? 48,
		bottom: value?.bottom ?? 48,
		left: value?.left ?? 48
	};
	if (Object.values(padding).some((item) => !(item >= 0))) {
		throw new Error('Test thumbnail padding must be non-negative');
	}
	return padding;
}

function defineTestThumbnail(input: TestThumbnailDefinition) {
	const value = structuredClone(input);
	requireText(value.id, 'id');
	validateTargets(value.focus, 'focus');
	if (value.context !== undefined) {
		if (!Array.isArray(value.context)) throw new Error('Test thumbnail context targets must be a list');
		if (value.context.length > 0) validateTargets(value.context, 'context');
	}
	if (value.aspectRatio !== undefined && value.aspectRatio !== '16:10') {
		throw new Error('Test thumbnail aspectRatio must be 16:10');
	}
	if (
		value.output !== undefined &&
		(value.output.width !== OUTPUT_WIDTH || value.output.height !== OUTPUT_HEIGHT)
	) {
		throw new Error(`Test thumbnail output must be ${OUTPUT_WIDTH}x${OUTPUT_HEIGHT}`);
	}
	return {
		...value,
		context: value.context ?? [],
		padding: normalizePadding(value.padding),
		aspectRatio: '16:10' as const,
		output: {width: OUTPUT_WIDTH, height: OUTPUT_HEIGHT} as const
	};
}

function unionBounds(bounds: Bounds[]): Bounds {
	if (bounds.length === 0) throw new Error('Test thumbnail bounds are required');
	const left = Math.min(...bounds.map((item) => item.x));
	const top = Math.min(...bounds.map((item) => item.y));
	const right = Math.max(...bounds.map((item) => item.x + item.width));
	const bottom = Math.max(...bounds.map((item) => item.y + item.height));
	return {x: left, y: top, width: right - left, height: bottom - top};
}

function largestFrame(viewport: {width: number; height: number}): {width: number; height: number} {
	let height = Math.floor(viewport.height / 5) * 5;
	let width = (height * 8) / 5;
	if (width > viewport.width) {
		width = Math.floor(viewport.width / 8) * 8;
		height = (width * 5) / 8;
	}
	return {width, height};
}

function frameForBounds(required: Bounds, maximum: {width: number; height: number}) {
	let width = Math.max(MIN_SOURCE_WIDTH, required.width);
	let height = Math.max(MIN_SOURCE_HEIGHT, required.height);
	if (width / height > 16 / 10) {
		height = Math.ceil(width * 10 / 16 / 5) * 5;
		width = height * 16 / 10;
	} else {
		height = Math.ceil(height / 5) * 5;
		width = height * 16 / 10;
	}
	if (width > maximum.width || height > maximum.height) return maximum;
	return {width, height};
}

function constrainPosition(preferred: number, requiredStart: number, requiredEnd: number, size: number, limit: number) {
	const includeMin = requiredEnd - size;
	const includeMax = requiredStart;
	const includingRequired = Math.max(includeMin, Math.min(includeMax, preferred));
	return Math.max(0, Math.min(limit - size, includingRequired));
}

function computeThumbnailClip({
	viewport,
	focusBounds,
	contextBounds,
	padding
}: {
	viewport: {width: number; height: number};
	focusBounds: Bounds[];
	contextBounds: Bounds[];
	padding: ThumbnailPadding;
}): Bounds {
	const focus = unionBounds(focusBounds);
	const combined = unionBounds([...focusBounds, ...contextBounds]);
	const required = {
		x: combined.x - padding.left,
		y: combined.y - padding.top,
		width: combined.width + padding.left + padding.right,
		height: combined.height + padding.top + padding.bottom
	};
	const maximum = largestFrame(viewport);
	if (!(maximum.width > 0 && maximum.height > 0)) throw new Error('Test thumbnail viewport is too small');
	const frame = frameForBounds(required, maximum);
	const focusCenterX = focus.x + focus.width / 2;
	const focusCenterY = focus.y + focus.height / 2;
	const x = constrainPosition(focusCenterX - frame.width / 2, required.x, required.x + required.width, frame.width, viewport.width);
	const y = constrainPosition(focusCenterY - frame.height / 2, required.y, required.y + required.height, frame.height, viewport.height);
	return {x: Math.round(x), y: Math.round(y), width: Math.round(frame.width), height: Math.round(frame.height)};
}

function targetLocator(page: Page, target: ThumbnailTarget): Locator {
	const locator = page.getByTestId(target.testId);
	if (target.occurrence === 'last') return locator.last();
	if (typeof target.occurrence === 'number') return locator.nth(target.occurrence);
	return locator.first();
}

async function targetLocators(page: Page, targets: ThumbnailTarget[]): Promise<Locator[]> {
	const locators = targets.map((target) => targetLocator(page, target));
	for (const locator of locators) await locator.waitFor({state: 'visible', timeout: 10_000});
	return locators;
}

async function locatorBounds(locators: Locator[], targets: ThumbnailTarget[]): Promise<Bounds[]> {
	const bounds: Bounds[] = [];
	for (let index = 0; index < locators.length; index += 1) {
		const locator = locators[index];
		const box = await locator.boundingBox();
		if (!box) throw new Error(`Test thumbnail target is not measurable: ${targets[index].testId}`);
		bounds.push(box);
	}
	return bounds;
}

function scaleThumbnail(source: Buffer, clip?: ThumbnailClip): Buffer {
	const cropFilter = clip ? `crop=${clip.width}:${clip.height}:${clip.x}:${clip.y},` : '';
	const result = spawnSync(
		'ffmpeg',
		[
			'-hide_banner', '-loglevel', 'error', '-f', 'image2pipe', '-i', 'pipe:0',
			'-vf', `${cropFilter}scale=${OUTPUT_WIDTH}:${OUTPUT_HEIGHT}:flags=lanczos`,
			'-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', 'pipe:1'
		],
		{input: source, maxBuffer: FFMPEG_MAX_BUFFER_BYTES}
	);
	if (result.status !== 0 || !result.stdout?.length) {
		throw new Error(`Test thumbnail scaling failed: ${String(result.stderr || '').trim() || 'ffmpeg returned no image'}`);
	}
	return result.stdout;
}

async function captureTestThumbnail(page: Page, testInfo: TestInfo, input: TestThumbnailDefinition): Promise<void> {
	const definition = defineTestThumbnail(input);
	const viewport = page.viewportSize();
	if (!viewport) throw new Error('Test thumbnail capture requires a fixed Playwright viewport');
	const focusLocators = await targetLocators(page, definition.focus);
	const contextLocators = await targetLocators(page, definition.context);
	const focusBounds = await locatorBounds(focusLocators, definition.focus);
	const contextBounds = await locatorBounds(contextLocators, definition.context);
	const clip = computeThumbnailClip({viewport, focusBounds, contextBounds, padding: definition.padding});
	const source = await page.screenshot({
		type: 'png',
		scale: 'css'
	});
	const thumbnail = scaleThumbnail(source, clip);
	await testInfo.attach(THUMBNAIL_ATTACHMENT_NAME, {body: thumbnail, contentType: 'image/png'});
	await testInfo.attach(THUMBNAIL_METADATA_ATTACHMENT_NAME, {
		body: Buffer.from(JSON.stringify({schema_version: 1, definition, viewport, clip})),
		contentType: 'application/json'
	});
}

module.exports = {captureTestThumbnail, computeThumbnailClip, defineTestThumbnail, scaleThumbnail};
