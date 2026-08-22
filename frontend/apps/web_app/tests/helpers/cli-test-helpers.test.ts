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
const test = require('node:test');
const {deriveApiUrl, runCliProof} = require('./cli-test-helpers.ts');

test('exports CLI proof helper', () => {
	assert.equal(typeof runCliProof, 'function');
});

test('derives dev API URL from dev app URL', () => {
	assert.equal(deriveApiUrl('https://app.dev.openmates.org'), 'https://api.dev.openmates.org');
});
