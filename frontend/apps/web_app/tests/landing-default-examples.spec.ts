// Focused guest catalog regression, isolated from the broader app-load suite.
// It verifies the public default order, guest controls and retired SEO pages.
// Real private chats and live app skill execution are outside this flow.
import { expect, test } from './helpers/cookie-audit';
import { getE2EDebugUrl } from './signup-flow-helpers';
import landingDefaults from '../../../packages/ui/src/generated/landingExampleChats.generated.json';
import catalogExpectations from '../../../packages/ui/src/demo_chats/__tests__/fixtures/curatedExampleExpectations.json';

// playwright-account: not_required reason=isolated_public_guest_catalog
// contract-test: direct surface=gui.web assertions=landing-onboarding.uses-real-chat-shell,landing-onboarding.guest-examples,marketing-landing.example-catalog-alignment
test('default guest examples match landing order and preserve a curated catalog', async ({ page, request }) => {
		test.setTimeout(60_000);
		await page.setViewportSize({ width: 1280, height: 800 });
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible();
		await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0);
		const bannerHeight = (await page.getByTestId('daily-inspiration-banner').boundingBox())?.height ?? 0;
		expect(bannerHeight).toBeGreaterThan(0);
		expect(bannerHeight).toBeLessThanOrEqual(420);
		await expect(page.getByTestId('guest-interest-select-interests')).toBeVisible();
		await expect(page.getByTestId('guest-show-all-examples')).toBeVisible();
		await expect(page.getByTestId('resume-chat-card').first()).toBeVisible();
		const beforeSlide = await page.getByTestId('resume-chat-card').evaluateAll((cards: HTMLElement[]) =>
			cards.map((card) => card.dataset.chatId).filter(Boolean)
		);
		expect(beforeSlide).toEqual(landingDefaults.map(example => example.chatId));
		await page.getByTestId('daily-inspiration-next').click();
		const afterSlide = await page.getByTestId('resume-chat-card').evaluateAll((cards: HTMLElement[]) =>
			cards.map((card) => card.dataset.chatId).filter(Boolean)
		);
		expect(afterSlide).toEqual(beforeSlide);
		await page.getByTestId('guest-show-all-examples').click();
		const allGrid = page.getByTestId('guest-all-examples-grid');
		await expect(allGrid.getByTestId('resume-chat-large-card').first()).toBeVisible();
		for (const example of catalogExpectations.retiredExamples) {
			await expect(allGrid.locator(`[data-chat-id="${example.chatId}"]`)).toHaveCount(0);
		}
		for (let offset = 0; offset < catalogExpectations.retiredExamples.length; offset += 8) {
			const batch = catalogExpectations.retiredExamples.slice(offset, offset + 8);
			const responses = await Promise.all(batch.map(example => request.get(`/example/${example.slug}`)));
			responses.forEach((response, index) => expect(response.status(), batch[index].slug).toBe(404));
		}
});
