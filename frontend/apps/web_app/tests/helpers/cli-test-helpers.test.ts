/**
 * Unit tests for shared CLI Playwright helpers.
 *
 * These checks keep helper exports and URL derivation deterministic without
 * spawning the OpenMates CLI or touching real account credentials. Product CLI
 * behavior remains covered by the Playwright specs that import these helpers.
 */

// contract-test-file: tooling

/* eslint-disable @typescript-eslint/no-require-imports */

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const {CLI_DIST, createOpenmatesCliRecordingBin, deriveApiUrl, extractCliProofFrame, runCliProof} = require('./cli-test-helpers.ts');

test('exports CLI proof helper', () => {
	assert.equal(typeof runCliProof, 'function');
});

test('extracts a PNG checkpoint frame from a CLI recording', () => {
	const png = Buffer.from([0x89, 0x50, 0x4e, 0x47]);
	let invocation;
	const frame = extractCliProofFrame('/tmp/raw-terminal.mp4', (command, args, options) => {
		invocation = {command, args, options};
		return {
		status: 0,
		stdout: png,
		stderr: Buffer.alloc(0)
		};
	});

	assert.equal(frame, png);
	assert.equal(invocation.command, 'ffmpeg');
	assert.deepEqual(invocation.args, [
		'-v', 'error', '-sseof', '-0.1', '-i', '/tmp/raw-terminal.mp4',
		'-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', 'pipe:1'
	]);
	assert.equal(invocation.options.encoding, null);
});

test('derives dev API URL from dev app URL', () => {
	assert.equal(deriveApiUrl('https://app.dev.openmates.org'), 'https://api.dev.openmates.org');
});

test('creates openmates recording wrapper before capture', () => {
	const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'openmates-cli-recording-'));
	try {
		const binDir = createOpenmatesCliRecordingBin(tmp);
		const wrapper = path.join(binDir, 'openmates');
		const source = fs.readFileSync(wrapper, 'utf8');
		assert.match(source, /^#!\/usr\/bin\/env sh\n/);
		assert.match(source, /exec node /);
		assert.match(source, /"\$@"/);
		assert.ok(source.includes(CLI_DIST));
	} finally {
		fs.rmSync(tmp, {recursive: true, force: true});
	}
});
