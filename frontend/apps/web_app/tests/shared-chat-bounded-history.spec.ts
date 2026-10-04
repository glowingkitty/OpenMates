/* eslint-disable @typescript-eslint/no-require-imports */
export {};
const { test, expect } = require('./helpers/cookie-audit');

// contract-test: direct surface=gui.web assertions=storage.cold.discoverable-bounded
test('shared chat opens one message page and requests older history only after Load more', async ({ page }: { page: any }) => {
	const sharedChatUrl = process.env.OPENMATES_CI_SHARED_CHAT_URL;
	if (!sharedChatUrl) throw new Error('Fresh shared-chat archive fixture is required');
	let olderReads = 0;
	let legacyFullReads = 0;
	page.on('request', (request: any) => {
		if (/\/v1\/share\/chat\/[^/]+$/.test(new URL(request.url()).pathname)) legacyFullReads += 1;
	});
	await page.route(/\/v1\/share\/chat\/[^/]+\/messages(?:\?.*)?$/, async (route: any) => {
		const url = new URL(route.request().url());
		if (url.searchParams.has('before_message_id')) {
			olderReads += 1;
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
				messages: [], has_more: false, next_before_timestamp: null, next_before_message_id: null
			}) });
			return;
		}
		const response = await route.fetch();
		const body = await response.json();
		const first = typeof body.messages?.[0] === 'string' ? JSON.parse(body.messages[0]) : body.messages?.[0];
		if (!first?.created_at || !(first.message_id || first.client_message_id || first.id)) {
			throw new Error('Shared fixture needs a real first encrypted message');
		}
		await route.fulfill({ response, json: {
			...body, has_more: true, next_before_timestamp: first.created_at,
			next_before_message_id: first.message_id || first.client_message_id || first.id
		} });
	});

	await page.goto(sharedChatUrl);
	await expect(page).toHaveURL(/#chat-id=/, { timeout: 45000 });
	const more = page.getByTestId('shared-message-load-more');
	await expect(more).toBeVisible({ timeout: 15000 });
	expect(olderReads).toBe(0);
	expect(legacyFullReads).toBe(0);
	await more.click();
	await expect.poll(() => olderReads).toBe(1);
});
