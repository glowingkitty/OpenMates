/**
 * Unit tests for deterministic spec-owned Playwright thumbnail framing.
 *
 * The geometry tests stay browser-independent so fixed output sizing and
 * focus/context behavior can be verified without running an E2E spec locally.
 */

// contract-test-file: tooling

/* eslint-disable @typescript-eslint/no-require-imports */

const assert = require('node:assert/strict');
const test = require('node:test');
const {captureTestThumbnail, computeThumbnailClip, defineTestThumbnail, scaleThumbnail} = require('./test-thumbnail.ts');

const ONE_PIXEL_PNG = Buffer.from(
	'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
	'base64'
);

test('defines a fixed 1280x800 thumbnail contract', () => {
	const definition = defineTestThumbnail({
		id: 'signup',
		focus: [{testId: 'login-tabs'}],
		padding: 48
	});

	assert.deepEqual(definition.output, {width: 1280, height: 800});
	assert.equal(definition.aspectRatio, '16:10');
	assert.deepEqual(defineTestThumbnail(definition), definition);
});

test('keeps a small control centered inside a bounded context window', () => {
	const clip = computeThumbnailClip({
		viewport: {width: 1280, height: 720},
		focusBounds: [{x: 590, y: 340, width: 100, height: 40}],
		contextBounds: [],
		padding: {top: 48, right: 48, bottom: 48, left: 48}
	});

	assert.deepEqual(clip, {x: 320, y: 160, width: 640, height: 400});
});

test('expands around multiple UI elements while preserving 16:10', () => {
	const clip = computeThumbnailClip({
		viewport: {width: 1280, height: 720},
		focusBounds: [{x: 500, y: 180, width: 280, height: 120}],
		contextBounds: [{x: 430, y: 140, width: 420, height: 380}],
		padding: {top: 40, right: 40, bottom: 40, left: 40}
	});

	assert.equal(clip.width / clip.height, 16 / 10);
	assert.ok(clip.x <= 390);
	assert.ok(clip.x + clip.width >= 890);
	assert.ok(clip.y <= 100);
	assert.ok(clip.y + clip.height >= 560);
});

test('shifts an edge crop into the viewport without changing its size', () => {
	const clip = computeThumbnailClip({
		viewport: {width: 1280, height: 720},
		focusBounds: [{x: 1160, y: 620, width: 80, height: 40}],
		contextBounds: [],
		padding: {top: 48, right: 48, bottom: 48, left: 48}
	});

	assert.deepEqual(clip, {x: 640, y: 320, width: 640, height: 400});
});

test('scales captured PNG bytes to the canonical output resolution', () => {
	const thumbnail = scaleThumbnail(ONE_PIXEL_PNG);

	assert.equal(thumbnail.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
	assert.equal(thumbnail.readUInt32BE(16), 1280);
	assert.equal(thumbnail.readUInt32BE(20), 800);
});

test('captures a cropped thumbnail without mutating the recorded viewport', async () => {
	let scrollCalls = 0;
	let screenshotOptions: Record<string, unknown> | null = null;
	const attachments: string[] = [];
	const locator = {
		waitFor: async () => undefined,
		scrollIntoViewIfNeeded: async () => { scrollCalls += 1; },
		boundingBox: async () => ({x: 590, y: 340, width: 100, height: 40})
	};
	const page = {
		viewportSize: () => ({width: 1280, height: 720}),
		getByTestId: () => ({first: () => locator}),
		screenshot: async (options: Record<string, unknown>) => {
			screenshotOptions = options;
			return ONE_PIXEL_PNG;
		}
	};
	const testInfo = {
		attach: async (name: string) => { attachments.push(name); }
	};

	await captureTestThumbnail(page, testInfo, {
		id: 'stable-frame',
		focus: [{testId: 'target'}]
	});

	assert.equal(scrollCalls, 0);
	assert.deepEqual(screenshotOptions, {
		type: 'png',
		clip: {x: 320, y: 160, width: 640, height: 400},
		scale: 'css'
	});
	assert.deepEqual(attachments, ['openmates-test-thumbnail', 'openmates-test-thumbnail-metadata']);
});
