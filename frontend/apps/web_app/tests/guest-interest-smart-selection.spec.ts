/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const storageKey = 'openmates.guest_interest_tags.v1';
const retiredIntroChatIds = ['demo-for-everyone', 'demo-for-developers', 'demo-who-develops-openmates'];
const selectedTags = ['software_development', 'privacy_personal_data', 'automation_workflows', 'project_management'];

async function openGuestWelcome(page: any) {
	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('guest-interest-select-interests')).toBeVisible({ timeout: 15000 });
	await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible({ timeout: 15000 });
}

async function visibleExampleIds(page: any): Promise<string[]> {
	return page.locator('[data-testid="resume-chat-large-card"], [data-testid="resume-chat-card"]').evaluateAll(
		(nodes: Element[]) => nodes.map((node) => node.getAttribute('data-chat-id') || '').filter((id) => id.startsWith('example-'))
	);
}

test.describe('Guest interests and real example chats', () => {
	// contract-test: direct surface=gui.web assertions=landing-onboarding.uses-real-chat-shell,landing-onboarding.guest-examples,daily-inspiration.guest-isolated,public-example-chats.catalog.discoverable
	test('four interests rank real examples and remain in session storage', async ({ page }: { page: any }) => {
		await openGuestWelcome(page);
		await expect(page.getByTestId('guest-show-all-examples')).toBeVisible();
		await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0);
		await expect.poll(() => visibleExampleIds(page)).not.toEqual([]);
		await page.getByTestId('guest-interest-select-interests').click();
		await expect(page.getByTestId('guest-interest-tags')).toBeVisible();
		await expect(page.getByTestId('interest-tag-plan_trips')).toHaveAttribute('data-app-id', 'travel');
		await expect(page.getByTestId('guest-interest-continue')).toHaveCount(0);
		for (const tag of selectedTags) {
			const button = page.getByTestId(`interest-tag-${tag}`);
			await button.scrollIntoViewIfNeeded();
			await button.click();
			await expect(button).toHaveAttribute('data-interest-active', 'true');
		}
		await expect(page.getByTestId('guest-interest-continue')).toBeVisible();
		await page.getByTestId('guest-interest-continue').click();
		await expect(page.getByTestId('guest-interest-tags')).toHaveCount(0);
		await expect.poll(() => visibleExampleIds(page)).not.toEqual([]);
		const rankedIds = await visibleExampleIds(page);
		expect(new Set(rankedIds).size).toBe(rankedIds.length);
		const storage = await page.evaluate((key: string) => ({ session: sessionStorage.getItem(key), local: localStorage.getItem(key) }), storageKey);
		expect(storage.local).toBeNull();
		for (const tag of selectedTags) expect(storage.session).toContain(tag);
		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('guest-interest-select-interests')).toBeVisible({ timeout: 15000 });
		await page.getByTestId('guest-interest-select-interests').click();
		for (const tag of selectedTags) await expect(page.getByTestId(`interest-tag-${tag}`)).toHaveAttribute('data-interest-active', 'true');
	});

	// contract-test: direct surface=gui.web assertions=landing-onboarding.legacy-intros-retired,landing-onboarding.uses-real-chat-shell
	test('retired intro links return to the ordinary welcome', async ({ page }: { page: any }) => {
		await page.goto(getE2EDebugUrl('/intro/who-develops-openmates'), { waitUntil: 'domcontentloaded' });
		await expect.poll(() => new URL(page.url()).pathname).toBe('/');
		for (const id of retiredIntroChatIds) {
			await page.goto(getE2EDebugUrl(`/#chat-id=${id}`), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('active-chat-container')).toBeVisible({ timeout: 15000 });
			await expect.poll(() => page.evaluate(() => window.location.hash)).toBe('');
			await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0);
			await expect(page.locator(`[data-chat-id="${id}"]`)).toHaveCount(0);
		}
	});

	// contract-test: supporting surface=gui.web assertions=landing-onboarding.uses-real-chat-shell,landing-onboarding.guest-examples
	test('composer opens and closes before interest selection', async ({ page }: { page: any }) => {
		await openGuestWelcome(page);
		await expect(page.getByTestId('guest-interest-tags')).toHaveCount(0);
		await page.getByTestId('message-editor').click();
		await expect(page.getByTestId('message-field')).toHaveAttribute('data-focused', 'true');
		await expect(page.getByTestId('input-dismiss-button')).toHaveText('Cancel');
		await page.getByTestId('input-dismiss-button').click();
		await expect(page.getByTestId('message-field')).toHaveAttribute('data-focused', 'false');
		await expect(page.getByTestId('guest-interest-select-interests')).toBeVisible();
		await expect(page.getByTestId('guest-show-all-examples')).toBeVisible();
	});
});
