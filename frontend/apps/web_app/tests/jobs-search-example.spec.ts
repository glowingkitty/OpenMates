// playwright-account: not_required reason=public_logged_out_example_admission
// contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
/* eslint-disable @typescript-eslint/no-require-imports -- Shared browser helpers use CommonJS. */
/** Logged-out playback of the real CLI-created German Jobs Search example. */
import type { Page } from '@playwright/test';
import { admitLandingExample } from './landing-app-example-admission';
import { jobProviderLabel } from '../../../packages/ui/src/components/embeds/jobs/jobsEmbedData';
import englishMessages from '../../../packages/ui/src/i18n/locales/en.json';
import { ALL_EXAMPLE_CHATS } from '../../../packages/ui/src/demo_chats/exampleChatData';
const { test, expect } = require('./helpers/cookie-audit');
const {
	closeFullscreen,
	openFullscreen,
	verifySearchGrid
} = require('./helpers/embed-test-helpers');

const slug = 'jobs-in-germany';
const providers = ['arbeitnow', 'arbeitsagentur', 'eighty_thousand_hours', 'hard_problems'];
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
	const parents = example!.embeds.filter(
		(embed) =>
			embed.type === 'app_skill_use' &&
			field(embed.content, 'app_id') === 'jobs' &&
			field(embed.content, 'skill_id') === 'search'
	);
	expect(
		parents.length,
		'The real transcript must contain successful German searches'
	).toBeGreaterThan(0);
	const groups = parents.map((parent) => {
		const children = example!.embeds.filter(
			(embed) =>
				embed.type === 'job_result' &&
				(embed.parent_embed_id === parent.embed_id || parent.embed_ids?.includes(embed.embed_id))
		);
		expect(field(parent.content, 'status')).toBe('finished');
		expect(field(parent.content, 'country')).toBe('DE');
		expect(children.length, 'Every saved result must remain attached to its search').toBe(
			Number(field(parent.content, 'result_count'))
		);
		expect(parent.embed_ids).toHaveLength(children.length);
		for (const child of children) {
			expect(parent.embed_ids).toContain(child.embed_id);
			expect(field(child.content, 'title')).toBeTruthy();
			expect(providers).toContain(field(child.content, 'provider'));
			expect(field(child.content, 'country')).toBe('DE');
			httpsUrl(field(child.content, 'url'));
		}
		return { parent, children };
	});
	const actualProviders = [
		...new Set(
			groups.flatMap(({ children }) => children.map((child) => field(child.content, 'provider')))
		)
	].sort();
	expect(
		actualProviders,
		'The real example must show results from all four German sources'
	).toEqual(providers);
	expect(example!.metadata.app_skill_examples).toContain('jobs.search');
	expect(
		example!.follow_up_suggestions.length,
		'Follow-ups must be saved real model output'
	).toBeGreaterThan(0);
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
	const sourceMessage = example!.messages.find((message) => message.role === 'assistant')!;
	const activity = page
		.getByTestId('chat-history-content')
		.locator(`[data-message-id="${sourceMessage.id}"]`)
		.getByTestId('assistant-activity-group');
	const toggle = activity.getByTestId('assistant-activity-toggle');
	await expect(toggle).toContainText('Jobs');
	await expect(toggle).toHaveAttribute('aria-expanded', 'false');
	await toggle.click();
	await expect(toggle).toHaveAttribute('aria-expanded', 'true');
	await expect(activity.getByTestId('assistant-activity-body')).toBeVisible();
}

async function inspectDesignComparison(page: Page): Promise<void> {
	const sourceMessage = example!.messages.filter((message) => message.role === 'assistant').at(-1)!;
	const webActivity = page
		.getByTestId('chat-history-content')
		.locator(`[data-message-id="${sourceMessage.id}"]`)
		.getByTestId('assistant-activity-group');
	const toggle = webActivity.getByTestId('assistant-activity-toggle');
	if ((await toggle.getAttribute('aria-expanded')) === 'false') await toggle.click();
	for (const embed of example!.embeds.filter(
		(item) => item.type === 'app_skill_use' && field(item.content, 'app_id') === 'web'
	)) {
		const preview = page.locator(
			`[data-testid="embed-preview"][data-embed-id="${embed.embed_id}"]`
		);
		await expect(preview).toBeVisible();
		const fullscreen = await openFullscreen(page, preview);
		await expect(fullscreen.locator('.result-content')).toHaveCount(1);
		await expect(fullscreen.locator('.markdown-content')).not.toBeEmpty();
		await closeFullscreen(page, fullscreen);
	}
	const sheet = example!.embeds.find((item) => item.type === 'sheet');
	expect(sheet, 'The real follow-up includes a comparison table').toBeDefined();
	const preview = page
		.locator(`[data-testid="embed-preview"][data-embed-id="${sheet!.embed_id}"]`)
		.filter({ visible: true })
		.first();
	await expect(preview).toBeVisible();
	const fullscreen = await openFullscreen(page, preview);
	await expect(fullscreen.locator('.sheet-fullscreen')).toBeVisible();
	await expect(fullscreen).toContainText('voize');
	await expect(fullscreen).toContainText('stiftung ear');
	await expect(fullscreen).toContainText('C1');
	await expect(fullscreen.locator('thead')).not.toContainText('embed:');
	await expect(fullscreen.locator('.col-header-text')).toHaveText([
		'Aspect', 'voize – Senior Product Designer', 'stiftung ear – UI/UX Design (m/w/d)'
	]);
	await closeFullscreen(page, fullscreen);
	// This example has no published speech fixture; guests must not see a broken action.
	await expect(page.getByTestId('assistant-message-speak')).toHaveCount(0);
}

for (const [viewport, size] of [
	['phone', { width: 390, height: 844 }],
	['laptop', { width: 1440, height: 1000 }]
] as const) {
	// contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity,public-example-chats.admission.reviewed-complete,marketing-landing.interactive-rail
	test(`real German Jobs example shows search and source details on ${viewport}`, async ({
		page,
		request
	}: any, testInfo: any) => {
		test.setTimeout(300_000);
		const groups = fixtureJobs();
		expect((await request.get('/example/jobs-in-sweden')).status()).toBe(404);
		await admitLandingExample(page, request, testInfo, 'jobs', example!, viewport);
		const response = await request.get(`/example/${slug}`);
		expect(response.status()).toBe(200);
		const html = await response.text();
		expect(html).toContain(example!.chat_id);
		expect(html).not.toContain('vault:v1:');

		await page.setViewportSize(size);
		await page.goto(`/example/${slug}`, { waitUntil: 'domcontentloaded' });
		await expectTranscriptVisible(page);
		await expandSavedJobsActivity(page);
		await testInfo.attach(`jobs-example-${viewport}-chat`, {
			body: await page.screenshot(),
			contentType: 'image/png'
		});

		for (const { parent, children } of groups) {
			const parentPreview = page.locator(
				`[data-testid="embed-preview"][data-embed-id="${parent.embed_id}"][data-app-id="jobs"][data-skill-id="search"][data-status="finished"]`
			);
			await expect(parentPreview.getByTestId('jobs-search-preview')).toBeVisible({
				timeout: 30_000
			});
			const parentOverlay = await openFullscreen(page, parentPreview);
			await expect(parentOverlay).toHaveAttribute('data-testid', 'jobs-search-fullscreen', {
				timeout: 15_000
			});
			const cards = await verifySearchGrid(parentOverlay, children.length, 30_000);
			await expect(cards).toHaveCount(children.length);
			await expect(cards.first().getByTestId('jobs-result-card')).toBeVisible();
			await testInfo.attach(`jobs-example-${viewport}-${parent.embed_id}-results`, {
				body: await page.screenshot(),
				contentType: 'image/png'
			});

			// Open each result cited in the actual answer, including impact-board listings.
			const transcript = example!.messages
				.map((message) => {
					const translated = message.content
						.split('.')
						.reduce<any>((value, key) => value?.[key], englishMessages);
					return typeof translated === 'string'
						? translated
						: (translated?.text ?? message.content);
				})
				.join('\n');
			for (const child of children.filter((result) => {
				const ref = field(result.content, 'embed_ref');
				return (
					transcript.includes(`embed:${result.embed_id}`) ||
					Boolean(ref && transcript.includes(`embed:${ref}`))
				);
			})) {
				const childId = child.embed_id;
				const title = field(child.content, 'title')!;
				const resultCard = cards.filter({ hasText: title }).first();
				await expect(resultCard).toContainText(title);
				await resultCard.click();
				const detail = page.getByTestId('jobs-result-fullscreen');
				await expect(detail).toBeVisible({ timeout: 15_000 });
				await expect(detail).toContainText(title);
				await expect(detail).toContainText(jobProviderLabel(field(child.content, 'provider'))!);
				if (viewport === 'phone') {
					const body = detail.getByTestId('jobs-detail-body');
					const company = detail.getByTestId('jobs-company-value');
					await expect(body).toBeVisible();
					await expect(company).toBeVisible();
					await expect
						.poll(async () => (await body.boundingBox())?.width ?? 0)
						.toBeGreaterThan(300);
					await expect
						.poll(async () => (await company.boundingBox())?.width ?? 0)
						.toBeGreaterThan(200);
					await expect
						.poll(async () => (await company.boundingBox())?.height ?? Infinity)
						.toBeLessThan(100);
				}
				if (field(child.content, 'remote') === null) {
					await expect(detail.getByTestId('jobs-remote-badge')).toHaveCount(0);
				}
				if (
					field(child.content, 'salary_min') === null &&
					field(child.content, 'salary_max') === null
				) {
					await expect(detail.getByTestId('jobs-salary')).toHaveCount(0);
				}
				const sourceLink = detail.getByTestId('jobs-source-link');
				await sourceLink.scrollIntoViewIfNeeded();
				await expect(sourceLink).toBeVisible();
				await expect(sourceLink).toHaveAttribute('rel', 'noopener noreferrer');
				await expect(detail.getByTestId('jobs-source-link')).toHaveAttribute(
					'href',
					httpsUrl(field(child.content, 'url'))
				);
				await testInfo.attach(`jobs-example-${viewport}-${parent.embed_id}-${childId}-detail`, {
					body: await page.screenshot(),
					contentType: 'image/png'
				});
				const applyUrl = field(child.content, 'apply_url');
				if (applyUrl && httpsUrl(applyUrl) !== httpsUrl(field(child.content, 'url'))) {
					await expect(detail.getByTestId('jobs-apply-link')).toHaveAttribute(
						'href',
						httpsUrl(applyUrl)
					);
				} else {
					await expect(detail.getByTestId('jobs-apply-link')).toHaveCount(0);
				}
				await closeFullscreen(page, detail);
				await expect(parentOverlay).toBeVisible();
			}
			await closeFullscreen(page, parentOverlay);
		}
		await inspectDesignComparison(page);
		await page.reload({ waitUntil: 'domcontentloaded' });
		await expectTranscriptVisible(page);
		await expandSavedJobsActivity(page);
		for (const { parent, children } of groups) {
			const parentPreview = page.locator(
				`[data-testid="embed-preview"][data-embed-id="${parent.embed_id}"]`
			);
			await expect(parentPreview.getByTestId('jobs-search-preview')).toBeVisible({
				timeout: 30_000
			});
			const parentOverlay = await openFullscreen(page, parentPreview);
			await expect(parentOverlay).toHaveAttribute('data-testid', 'jobs-search-fullscreen', {
				timeout: 15_000
			});
			const cards = await verifySearchGrid(parentOverlay, children.length, 30_000);
			await expect(cards).toHaveCount(children.length);
			await closeFullscreen(page, parentOverlay);
		}
	});
}
