/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

// The isolated CI workflow selects WebKit for this spec. This touch/viewport
// profile exercises its parallel tab lifecycle on an iPad-size surface.
test.use({ viewport: { width: 1024, height: 1366 }, hasTouch: true });

// contract-test: direct surface=gui.web assertions=public-example-chats.navigation.static-public-link,public-example-chats.transcript.safe-rendering
test('three iPad-size example tabs survive concurrent open and reload', async ({ page, context, browserName }: { page: any; context: any; browserName: string }) => {
	test.setTimeout(90_000);
	expect(browserName, 'This regression must run in the WebKit engine').toBe('webkit');
	const cases = [
		{ id: 'example-berlin-english-speaking-gp', focus: false },
		{ id: 'example-books-after-left-hand', focus: true },
		{ id: 'example-buck-converters-24v-5v', focus: false }
	];
	const pages = [page, await context.newPage(), await context.newPage()];
	const crashed = new Set<number>();
	pages.forEach((tab: any, index: number) => tab.on('crash', () => crashed.add(index)));
	await Promise.all(pages.map((tab: any) => tab.addInitScript(() => {
		if (location.protocol !== 'http:' && location.protocol !== 'https:') return;
		const key = '__example_multitab_boot_count';
		sessionStorage.setItem(key, String(Number(sessionStorage.getItem(key) || '0') + 1));
	})));
	const bootCount = (tab: any) => tab.evaluate(() => Number(sessionStorage.getItem('__example_multitab_boot_count')));
	const exampleContent = (tab: any, index: number) => cases[index].focus
		? tab.getByRole('button', { name: "Activated 'Book discussion'" })
		: tab.getByTestId('embed-preview').first();

	await Promise.all(pages.map((tab: any, index: number) =>
		tab.goto(getE2EDebugUrl(`/#chat-id=${cases[index].id}`), { waitUntil: 'domcontentloaded' })
	));
	for (let index = 0; index < pages.length; index += 1) {
		await expect(pages[index].getByTestId('example-chat-badge')).toBeVisible({ timeout: 25_000 });
		await expect(exampleContent(pages[index], index)).toBeVisible({ timeout: 25_000 });
		expect(await bootCount(pages[index]), `example tab ${index + 1} booted unexpectedly`).toBe(1);
	}

	await pages[1].reload({ waitUntil: 'domcontentloaded' });
	await expect(pages[1]).toHaveURL(new RegExp(`#chat-id=${cases[1].id}$`));
	await expect(pages[1].getByTestId('example-chat-badge')).toBeVisible({ timeout: 25_000 });
	await expect(exampleContent(pages[1], 1)).toBeVisible({ timeout: 25_000 });
	for (let index = 0; index < pages.length; index += 1) {
		expect(crashed.has(index), `example tab ${index + 1} crashed`).toBe(false);
		await expect(pages[index].getByTestId('example-chat-badge')).toBeVisible();
		expect(await bootCount(pages[index]), `example tab ${index + 1} reloaded unexpectedly`).toBe(index === 1 ? 2 : 1);
	}
});
