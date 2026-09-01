/**
 * Unit tests for spec-owned proof-video contracts and timelines.
 *
 * These tests keep tutorial metadata deterministic and presentation pacing out
 * of Playwright execution. They run with Node's TypeScript stripping support.
 * Product behavior remains covered by the proof-enabled Playwright specs.
 */

// contract-test-file: tooling

/* eslint-disable @typescript-eslint/no-require-imports */

const assert = require('node:assert/strict');
const test = require('node:test');
const {createVideoProofRuntime, defineVideoProof} = require('./video-proof.ts');

const definition = () => defineVideoProof({
	id: 'welcome-proof',
	title: 'Open the welcome experience',
	surface: 'web',
	devices: ['web-laptop'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'welcome-visible',
			text: 'The OpenMates welcome experience is visible inside the browser.',
			checkpoint: 'welcome-visible',
			devices: ['web-laptop']
		}
	],
	assertions: [
		{
			id: 'welcome.shell.visible',
			checkpoint: 'welcome-visible',
			visual: 'The welcome interface is fully visible without clipping or loading indicators.',
			devices: ['web-laptop']
		}
	],
	tutorial: {
		readingWordsPerSecond: 2.5,
		minimumHoldMs: 1200,
		maximumHoldMs: 5000
	}
});

test('defines a complete canonical proof contract', () => {
	const first = definition();
	const second = definition();
	assert.deepEqual(first, second);
	assert.equal(first.domain, 'app.dev.openmates.org');
});

test('rejects assertions without visual review text', () => {
	const invalid = definition() as any;
	invalid.assertions[0].visual = '';
	assert.throws(() => defineVideoProof(invalid), /visual/);
});

test('records fast actions assertions and checkpoints without presentation waits', async () => {
	let now = 1000;
	const attached: Array<{name: string; body: Buffer; contentType: string}> = [];
	const runtime = createVideoProofRuntime(definition(), {
		now: () => now,
		device: 'web-laptop',
		attach: async (name, options) => attached.push({name, ...options}),
		captureFrame: async () => { throw new Error('checkpoint capture must be deferred'); }
	});

	await runtime.action('open-welcome', async () => {
		now = 1120;
	});
	await runtime.assert('welcome.shell.visible', async () => {
		now = 1140;
	});
	await runtime.checkpoint('welcome-visible');
	await runtime.attach();

	assert.equal(attached.length, 1);
	assert.equal(attached[0].name, 'openmates-proof-timeline');
	const payload = JSON.parse(attached[0].body.toString('utf8'));
	assert.equal(payload.schema_version, 2);
	assert.equal(payload.contract.id, 'welcome-proof');
	assert.deepEqual(payload.events.map((event: any) => event.kind), ['action', 'assertion', 'checkpoint']);
	assert.equal(payload.events[0].start_ms, 0);
	assert.equal(payload.events[0].end_ms, 120);
	assert.equal(payload.assertion_results[0].status, 'passed');
	assert.equal(payload.checkpoint_frames[0].checkpoint, 'welcome-visible');
	assert.equal(payload.checkpoint_frames[0].at_ms, 140);
	assert.equal(payload.checkpoint_frames[0].captured_at_epoch_ms, 1140);
	assert.equal('sha256' in payload.checkpoint_frames[0], false);
	assert.equal('presentation_wait_ms' in payload, false);
});

test('refuses to attach when declared checkpoints or assertions were not reached', async () => {
	const runtime = createVideoProofRuntime(definition(), {
		now: () => 1000,
		device: 'web-laptop',
		attach: async () => undefined,
		captureFrame: async () => Buffer.from('synthetic png')
	});

	await assert.rejects(runtime.attach(), /welcome\.shell\.visible/);
});
