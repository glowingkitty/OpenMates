import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { after, before, test } from 'node:test';
import { chromium, type Browser } from '@playwright/test';
import { inspectOfflineRecipeHeader } from './offline-recipe-header';

// contract-test-file: infrastructure
let browser: Browser;

before(async () => {
	browser = await chromium.launch({ executablePath: process.env.LOCAL_TEST_CHROMIUM || undefined });
});
after(async () => { await browser?.close(); });

test('verifies variable-driven color and inherited Lexend on the actual header', async () => {
	const latest = `<!doctype html><style>
		:root { --header-color: #d00000; --recipe-font: "Lexend Deca", sans-serif }
		body { font-family: var(--recipe-font) }
		header { background: var(--header-color) }
	</style><body><header>Recipe name</header><main><article><header>Section name</header></article></main></body>`;
	assert.deepEqual(await inspectOfflineRecipeHeader(browser, latest),
		{ blue: false, red: true, lexend: true, hasLexend: true });

	const original = `<body style="--base: #0055ff; font: 16px sans-serif">
		<header style="background: var(--base)">Original header</header></body>`;
	assert.deepEqual(await inspectOfflineRecipeHeader(browser, original),
		{ blue: true, red: false, lexend: false, hasLexend: false });
});

test('ignores the right colors and fonts on the wrong element and never executes or fetches saved markup', async () => {
	let requests = 0;
	const server = createServer((_request, response) => { requests++; response.end(); });
	await new Promise<void>(resolve => { server.listen(0, '127.0.0.1', resolve); });
	try {
		const address = server.address();
		assert.ok(address && typeof address !== 'string');
		const endpoint = 'http://127.0.0.1:' + address.port;
		const altered = `<header>Actual header</header>
			<main style="background:#d00000;font-family:'Lexend Deca'">Styled decoy</main>
			<script>document.querySelector('header').style.cssText =
				"background:#d00000;font-family:'Lexend Deca'";</script>
			<iframe src="${endpoint}/frame"></iframe><img src="${endpoint}/image">
			<link rel="stylesheet" href="${endpoint}/style">
			<style>@import url('${endpoint}/import');</style>`;
		assert.deepEqual(await inspectOfflineRecipeHeader(browser, altered),
			{ blue: false, red: false, lexend: false, hasLexend: false });
		assert.equal(requests, 0);
	} finally {
		await new Promise<void>(resolve => { server.close(() => resolve()); });
	}
});
