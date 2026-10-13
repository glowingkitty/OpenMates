// playwright-account: not_required reason=public_logged_out_example_admission
// contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
/* eslint-disable @typescript-eslint/no-require-imports -- Shared browser helpers use CommonJS. */
/** Logged-out playback of the real CLI-created Swedish Jobs Search example. */
import type { Page } from '@playwright/test';
import { ALL_EXAMPLE_CHATS } from '../../../packages/ui/src/demo_chats/exampleChatData';
const { test, expect } = require('./helpers/cookie-audit');
const { closeFullscreen, openFullscreen, verifySearchGrid } = require('./helpers/embed-test-helpers');

const slug = 'jobs-in-sweden';
const example = ALL_EXAMPLE_CHATS.find((chat) => chat.slug === slug);

function field(content: string, name: string): string | null {
	const value = content.match(new RegExp(`^${name}:\\s*(.*)$`, 'm'))?.[1]?.trim();
	if (!value || value === 'null' || value === '~') return null;
	return value.replace(/^['"]|['"]$/g, '');
}

function httpsUrl(value: string | null): string {
	expect(value).toMatch(/^https:\/\//);
	return new URL(value!).href;
}

function fixtureJobs() {
	expect(example, 'The admitted Jobs example must come from the real CLI transcript').toBeDefined();
	const parents = example!.embeds.filter((embed) =>
		embed.type === 'app_skill_use'
		&& field(embed.content, 'app_id') === 'jobs'
		&& field(embed.content, 'skill_id') === 'search'
	);
	expect(parents, 'The real transcript searched both Malmö and Stockholm').toHaveLength(2);
	const groups = parents.map((parent) => {
		const children = example!.embeds.filter((embed) =>
			embed.type === 'job_result'
			&& (embed.parent_embed_id === parent.embed_id || parent.embed_ids?.includes(embed.embed_id))
		);
		expect(field(parent.content, 'provider')).toBe('jobtech');
		expect(field(parent.content, 'country')).toBe('SE');
		expect(children.length, 'Every saved result must remain attached to its search').toBe(Number(field(parent.content, 'result_count')));
		expect(parent.embed_ids).toHaveLength(children.length);
		for (const child of children) {
			expect(parent.embed_ids).toContain(child.embed_id);
			expect(field(child.content, 'title')).toBeTruthy();
			expect(field(child.content, 'provider')).toBe('jobtech');
			expect(field(child.content, 'country')).toBe('SE');
			httpsUrl(field(child.content, 'url'));
		}
		return { parent, children };
	});
	expect(groups.flatMap(({ children }) => children), 'The real transcript contains all ten listings').toHaveLength(10);
	expect(groups.map(({ parent }) => field(parent.content, 'location')).sort()).toEqual(['Malmö', 'Stockholm']);
	return groups;
}

async function expectTranscriptVisible(page: Page): Promise<void> {
	expect(example).toBeDefined();
	await expect(page).toHaveURL(new RegExp(`#chat-id=${example!.chat_id}$`), { timeout: 15_000 });
	const userMessages = example!.messages.filter((message) => message.role === 'user');
	const assistantMessages = example!.messages.filter((message) => message.role === 'assistant');
	expect(userMessages.length).toBeGreaterThan(0);
	expect(assistantMessages.length).toBeGreaterThan(0);
	await expect(page.getByTestId('user-message-content').first()).toBeVisible({ timeout: 30_000 });
	await expect(page.getByTestId('message-assistant').first()).toBeVisible({ timeout: 30_000 });
	await expect(page.getByTestId('user-message-content')).toHaveCount(userMessages.length);
	await expect(page.getByTestId('message-assistant')).toHaveCount(assistantMessages.length);
	await expect(page.locator('body')).not.toContainText('vault_key_id');
	await expect(page.locator('body')).not.toContainText('"type": "app_skill_use"');
}

async function expandSavedJobsActivity(page: Page): Promise<void> {
	const activity = page.getByTestId('assistant-activity-group');
	const toggle = activity.getByTestId('assistant-activity-toggle');
	await expect(toggle).toContainText('Jobs');
	await expect(toggle).toHaveAttribute('aria-expanded', 'false');
	await toggle.click();
	await expect(toggle).toHaveAttribute('aria-expanded', 'true');
	await expect(activity.getByTestId('assistant-activity-body')).toBeVisible();
}

for (const [viewport, size] of [
	['phone', { width: 390, height: 844 }],
	['laptop', { width: 1440, height: 1000 }]
] as const) {
	// contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
	test(`real Swedish Jobs example shows search and source details on ${viewport}`, async ({ page, request }: any, testInfo: any) => {
		test.setTimeout(180_000);
		const groups = fixtureJobs();
		const response = await request.get(`/example/${slug}`);
		expect(response.status()).toBe(200);
		const html = await response.text();
		expect(html).toContain(example!.chat_id);
		expect(html).not.toContain('vault:v1:');

		await page.setViewportSize(size);
		await page.goto(`/example/${slug}`, { waitUntil: 'domcontentloaded' });
		await expectTranscriptVisible(page);
		await expandSavedJobsActivity(page);
		await testInfo.attach(`jobs-example-${viewport}-chat`, { body: await page.screenshot(), contentType: 'image/png' });

		for (const { parent, children } of groups) {
			const parentPreview = page.locator(
				`[data-testid="embed-preview"][data-embed-id="${parent.embed_id}"][data-app-id="jobs"][data-skill-id="search"][data-status="finished"]`
			);
			await expect(parentPreview.getByTestId('jobs-search-preview')).toBeVisible({ timeout: 30_000 });
			const parentOverlay = await openFullscreen(page, parentPreview);
			await expect(parentOverlay.getByTestId('jobs-search-fullscreen')).toBeVisible({ timeout: 15_000 });
			const cards = await verifySearchGrid(parentOverlay, children.length, 30_000);
			await expect(cards).toHaveCount(children.length);
			await expect(cards.first().getByTestId('jobs-result-card')).toBeVisible();
			await testInfo.attach(`jobs-example-${viewport}-${field(parent.content, 'location')}-results`, { body: await page.screenshot(), contentType: 'image/png' });

			// The answer links its first two listings in each city; inspect those exact saved results.
			for (const childId of parent.embed_ids!.slice(0, 2)) {
				const child = children.find((result) => result.embed_id === childId)!;
				const title = field(child.content, 'title')!;
				const resultCard = cards.filter({ hasText: title }).first();
				await expect(resultCard).toContainText(title);
				await resultCard.click();
				const detail = page.getByTestId('jobs-result-fullscreen');
				await expect(detail).toBeVisible({ timeout: 15_000 });
				await expect(detail).toContainText(title);
				await expect(detail).toContainText(/JobTech/i);
				if (field(child.content, 'remote') === null) {
					await expect(detail.getByTestId('jobs-remote-badge')).toHaveCount(0);
				}
				if (field(child.content, 'salary_min') === null && field(child.content, 'salary_max') === null) {
					await expect(detail.getByTestId('jobs-salary')).toHaveCount(0);
				}
				const sourceLink = detail.getByTestId('jobs-source-link');
				await sourceLink.scrollIntoViewIfNeeded();
				await expect(sourceLink).toBeVisible();
				await expect(sourceLink).toHaveAttribute('rel', 'noopener noreferrer');
				await expect(detail.getByTestId('jobs-source-link')).toHaveAttribute('href', httpsUrl(field(child.content, 'url')));
				await testInfo.attach(`jobs-example-${viewport}-${field(parent.content, 'location')}-${childId}-detail`, { body: await page.screenshot(), contentType: 'image/png' });
				const applyUrl = field(child.content, 'apply_url');
				if (applyUrl && httpsUrl(applyUrl) !== httpsUrl(field(child.content, 'url'))) {
					await expect(detail.getByTestId('jobs-apply-link')).toHaveAttribute('href', httpsUrl(applyUrl));
				} else {
					await expect(detail.getByTestId('jobs-apply-link')).toHaveCount(0);
				}
				const detailOverlay = detail.locator('xpath=ancestor::*[@data-testid="embed-fullscreen-overlay"][1]');
				await closeFullscreen(page, detailOverlay);
				await expect(parentOverlay.getByTestId('jobs-search-fullscreen')).toBeVisible();
			}
			await closeFullscreen(page, parentOverlay);
		}
		await page.reload({ waitUntil: 'domcontentloaded' });
		await expectTranscriptVisible(page);
		await expandSavedJobsActivity(page);
		for (const { parent, children } of groups) {
			const parentPreview = page.locator(`[data-testid="embed-preview"][data-embed-id="${parent.embed_id}"]`);
			await expect(parentPreview.getByTestId('jobs-search-preview')).toBeVisible({ timeout: 30_000 });
			const parentOverlay = await openFullscreen(page, parentPreview);
			await expect(parentOverlay.getByTestId('jobs-search-fullscreen')).toBeVisible({ timeout: 15_000 });
			const cards = await verifySearchGrid(parentOverlay, children.length, 30_000);
			await expect(cards).toHaveCount(children.length);
			await closeFullscreen(page, parentOverlay);
		}
	});
}
