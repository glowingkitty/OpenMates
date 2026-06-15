/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified E2E coverage for weather/forecast.
 *
 * Phase 0: App metadata exposes Weather / Get forecast.
 * Phase 1: Embed preview renders at /dev/preview/embeds/weather.
 * Phase 2: CLI direct skill command returns one weather_day per requested day for Germany and international cities.
 * Phase 3: CLI chat send triggers weather forecast.
 * Phase 4: Web UI chat triggers weather forecast and renders weather embed output.
 */
export {};

const { test, expect } = require('./console-monitor');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	getE2EDebugUrl,
	withLiveMockMarker
} = require('./signup-flow-helpers');
const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	deleteActiveChat
} = require('./helpers/chat-test-helpers');
const { deriveApiUrl, runCli, parseCliJson, expectCliSuccess } = require('./helpers/cli-test-helpers');
const {
	openFullscreen,
	closeFullscreen
} = require('./helpers/embed-test-helpers');

function getForecastResults(parsed: any): any[] {
	return parsed.data?.results || parsed.results || [];
}

function expectForecastPayload(parsed: any, expectedProvider: string): void {
	const results = getForecastResults(parsed);
	expect(results.length).toBe(2);
	expect(results.every((day) => day.type === 'weather_day')).toBeTruthy();
	expect(results.every((day) => Array.isArray(day.hourly) && day.hourly.length > 0)).toBeTruthy();
	expect(parsed.data?.provider).toContain(expectedProvider);
}

const linkedExampleChatCases = [
	{
		appId: 'images',
		skillId: 'generate',
		chatId: 'example-privacy-website-hero-background',
		titlePattern: /privacy|website|hero|background/i
	},
	{
		appId: 'electronics',
		skillId: 'search_components',
		chatId: 'example-buck-converters-24v-5v',
		titlePattern: /buck|converter|24v|5v/i
	},
	{
		appId: 'nutrition',
		skillId: 'search_recipes',
		chatId: 'example-chickpea-spinach-protein-dinners',
		titlePattern: /chickpea|spinach|protein|dinners/i
	},
	{
		appId: 'home',
		skillId: 'search',
		chatId: 'example-furnished-apartments-berlin',
		titlePattern: /furnished|apartments|Berlin/i
	}
];

async function expectImageLoaded(locator: any, label = 'image'): Promise<void> {
	await expect(locator).toBeVisible({ timeout: 15_000 });
	await expect(async () => {
		const loaded = await locator.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0);
		expect(loaded, `${label} should finish loading`).toBe(true);
	}).toPass({ timeout: 15_000 });
}

test.describe('App: Weather / Skill: forecast', () => {
	test.setTimeout(180_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	test('Phase 0: Apps metadata exposes weather forecast', async ({ request }: { request: any }) => {
		const response = await request.get(`${apiUrl}/v1/apps/metadata`);
		expect(response.ok()).toBeTruthy();

		const data = await response.json();
		const nutrition = data.apps?.nutrition;
		expect(nutrition, 'nutrition app should appear in Apps metadata').toBeTruthy();

		const nutritionSkillIds = (nutrition.skills || []).map((skill: { id: string }) => skill.id);
		expect(nutritionSkillIds).toContain('search_recipes');

		const weather = data.apps?.weather;
		expect(weather, 'weather app should appear in Apps metadata').toBeTruthy();

		const skillIds = (weather.skills || []).map((skill: { id: string }) => skill.id);
		expect(skillIds).toContain('forecast');

		const forecast = (weather.skills || []).find((skill: { id: string }) => skill.id === 'forecast');
		expect(forecast?.description).toBe('apps.weather.forecast.description');
		expect(forecast?.description).not.toContain('app_skills.apps.weather.forecast');
	});

	test('Phase 1: embed preview renders through direct component preview', async ({ page }: { page: any }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		const response = await page.goto('/dev/preview/embeds/weather/WeatherForecastEmbedPreview', {
			waitUntil: 'networkidle'
		});
		expect(response?.status()).toBe(200);
		log('Navigated to direct WeatherForecastEmbedPreview route');

		await expect(page.getByTestId('render-error')).not.toBeVisible({ timeout: 10_000 });
		await expect(page.getByTestId('weather-forecast-preview').first()).toBeVisible();
	});

	test('Phase 1b: Apps weather linked example chat has translations, provider icons, and opens the chat', async ({ page }: { page: any }) => {
		test.setTimeout(120_000);
		await page.setViewportSize({ width: 1600, height: 900 });

		await page.goto(getE2EDebugUrl('/#settings/apps/weather/skill/forecast'), {
			waitUntil: 'domcontentloaded'
		});
		await page.waitForLoadState('networkidle');

		const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
		await expect(settingsMenu).toBeVisible({ timeout: 15_000 });
		await expect(settingsMenu).toHaveAttribute('data-active-view', 'apps/weather/skill/forecast', {
			timeout: 15_000
		});

		await expect(settingsMenu).toContainText('Get forecast', { timeout: 15_000 });
		await expect(settingsMenu).toContainText('Get daily and hourly weather forecasts.', { timeout: 15_000 });
		const settingsText = await settingsMenu.innerText();
		expect(settingsText).not.toContain('[T:');
		expect(settingsText).not.toContain('app_skills.apps.weather');

		await expect(settingsMenu.locator('[data-testid="skill-provider-item"][data-provider-name="Deutscher Wetterdienst (DWD)"]').first()).toBeVisible({ timeout: 15_000 });
		await expect(settingsMenu.locator('[data-testid="skill-provider-item"][data-provider-name="Open-Meteo"]').first()).toBeVisible({ timeout: 15_000 });
		await expectImageLoaded(settingsMenu.locator('[data-testid="settings-provider-logo"][data-provider-name="Deutscher Wetterdienst (DWD)"]').first(), 'DWD provider logo');
		await expectImageLoaded(settingsMenu.locator('[data-testid="settings-provider-logo"][data-provider-name="Open-Meteo"]').first(), 'Open-Meteo provider logo');

		const exampleChatCard = settingsMenu.locator('[data-testid="app-store-example-chat-card"][data-app-id="weather"][data-skill-id="forecast"]').first();
		await expect(exampleChatCard).toBeVisible({ timeout: 15_000 });
		await expect(exampleChatCard).toHaveClass(/resume-chat-large-card/);
		await expect(exampleChatCard.getByTestId('resume-large-title')).toContainText(/weather|bike|commute|Berlin/i);
		await expect(exampleChatCard.getByTestId('resume-large-title')).not.toContainText('[T:');
		await expect(exampleChatCard.getByTestId('resume-large-orbs')).toBeVisible({ timeout: 15_000 });

		await exampleChatCard.click();
		await expect(page.getByTestId('chat-history-container')).toBeVisible({ timeout: 15_000 });
		await expect(page.locator('[data-testid="settings-menu"].visible')).toBeVisible({ timeout: 15_000 });
	});

	test('Phase 1b mobile: Apps example chat closes settings on narrow viewports', async ({ page }: { page: any }) => {
		test.setTimeout(120_000);
		await page.setViewportSize({ width: 390, height: 844 });

		await page.goto(getE2EDebugUrl('/#settings/apps/weather/skill/forecast'), {
			waitUntil: 'domcontentloaded'
		});
		await page.waitForLoadState('networkidle');

		const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
		await expect(settingsMenu).toBeVisible({ timeout: 15_000 });

		const exampleChatCard = settingsMenu.locator('[data-testid="app-store-example-chat-card"][data-app-id="weather"][data-skill-id="forecast"]').first();
		await expect(exampleChatCard).toBeVisible({ timeout: 15_000 });

		await exampleChatCard.click();
		await expect(page).toHaveURL(/#chat-id=example-berlin-weather-bike-commute/, { timeout: 15_000 });
		await expect(page.getByTestId('chat-history-container')).toBeVisible({ timeout: 15_000 });
		await expect(page.locator('[data-testid="settings-menu"].visible')).toHaveCount(0, { timeout: 15_000 });
	});

	test('Phase 1c: Apps linked example chat uses the large continue-card preview and opens the chat', async ({ page }: { page: any }) => {
		test.setTimeout(120_000);
		await page.setViewportSize({ width: 1600, height: 900 });

		await page.goto(getE2EDebugUrl('/#settings/apps/travel/skill/search_connections'), {
			waitUntil: 'domcontentloaded'
		});
		await page.waitForLoadState('networkidle');

		const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
		await expect(settingsMenu).toBeVisible({ timeout: 15_000 });
		await expect(settingsMenu).toHaveAttribute('data-active-view', 'apps/travel/skill/search_connections', {
			timeout: 15_000
		});

		const exampleChatCard = settingsMenu.locator('[data-testid="app-store-example-chat-card"][data-app-id="travel"][data-skill-id="search_connections"]').first();
		await expect(exampleChatCard).toBeVisible({ timeout: 15_000 });
		await expect(exampleChatCard).toHaveClass(/resume-chat-large-card/);
		await expect(exampleChatCard.getByTestId('resume-large-title')).toContainText(/flight|Bangkok/i);
		await expect(exampleChatCard.getByTestId('resume-large-title')).not.toContainText('[T:');
		await expect(exampleChatCard.getByTestId('resume-large-orbs')).toBeVisible({ timeout: 15_000 });

		await exampleChatCard.click();
		await expect(page.getByTestId('chat-history-container')).toBeVisible({ timeout: 15_000 });
		await expect(page.locator('[data-testid="settings-menu"].visible')).toBeVisible({ timeout: 15_000 });
	});

	test('Phase 1d: representative Apps linked example chats are visible and open', async ({ page }: { page: any }) => {
		test.setTimeout(180_000);
		await page.setViewportSize({ width: 1600, height: 900 });

		for (const example of linkedExampleChatCases) {
			const settingsPath = `/?example-card=${example.appId}-${example.skillId}#settings/apps/${example.appId}/skill/${example.skillId}`;
			await page.goto(getE2EDebugUrl(settingsPath), {
				waitUntil: 'domcontentloaded'
			});
			await page.waitForLoadState('networkidle');

			const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
			await expect(settingsMenu).toBeVisible({ timeout: 15_000 });
			await expect(settingsMenu).toHaveAttribute('data-active-view', `apps/${example.appId}/skill/${example.skillId}`, {
				timeout: 15_000
			});

			const exampleChatCard = settingsMenu.locator(`[data-testid="app-store-example-chat-card"][data-app-id="${example.appId}"][data-skill-id="${example.skillId}"]`).first();
			await expect(exampleChatCard).toBeVisible({ timeout: 15_000 });
			await expect(exampleChatCard).toHaveClass(/resume-chat-large-card/);
			await expect(exampleChatCard.getByTestId('resume-large-title')).toContainText(example.titlePattern);
			await expect(exampleChatCard.getByTestId('resume-large-title')).not.toContainText('[T:');
			await expect(exampleChatCard.getByTestId('resume-large-orbs')).toBeVisible({ timeout: 15_000 });

			await exampleChatCard.click();
			await expect(page.getByTestId('chat-history-container')).toBeVisible({ timeout: 15_000 });
			await expect(page.locator('[data-testid="settings-menu"].visible')).toBeVisible({ timeout: 15_000 });
		}
	});

	test('Phase 2: CLI apps weather forecast returns daily child results for Germany and international cities', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'OPENMATES_TEST_ACCOUNT_API_KEY required.');

		const berlinResult = await runCli(
			apiUrl,
			[
				'apps', 'weather', 'forecast',
				'--input', JSON.stringify({ location: 'Berlin', days: 2 }),
				'--json'
			],
			60_000
		);

		expectCliSuccess(berlinResult, 'weather/forecast CLI Berlin');
		const berlinParsed = parseCliJson(berlinResult);
		expect(berlinParsed.success).toBe(true);
		expectForecastPayload(berlinParsed, 'Deutscher Wetterdienst');

		const tokyoResult = await runCli(
			apiUrl,
			[
				'apps', 'weather', 'forecast',
				'--input', JSON.stringify({ location: 'Tokyo', days: 2 }),
				'--json'
			],
			60_000
		);

		expectCliSuccess(tokyoResult, 'weather/forecast CLI Tokyo');
		const tokyoParsed = parseCliJson(tokyoResult);
		expect(tokyoParsed.success).toBe(true);
		expectForecastPayload(tokyoParsed, 'Open-Meteo');
	});

	test('Phase 3: CLI chats new triggers weather forecast', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'OPENMATES_TEST_ACCOUNT_API_KEY required.');

		const message = withLiveMockMarker(
			'Use weather.forecast to show me a 2 day weather forecast for Berlin',
			'weather_forecast_cli'
		);
		const result = await runCli(apiUrl, ['chats', 'new', message, '--json'], 90_000);
		expectCliSuccess(result, 'CLI chat weather forecast');

		const parsed = parseCliJson(result);
		expect(parsed).toBeTruthy();
		if (parsed.chat_id) {
			await runCli(apiUrl, ['chats', 'delete', parsed.chat_id, '--yes'], 15_000);
		}
	});

	test('Phase 4: Web chat triggers weather forecast with embed', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-weather-forecast');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		await sendMessage(
			page,
			withLiveMockMarker('Use weather.forecast to show me a 2 day weather forecast for Berlin', 'weather_forecast_web'),
			logCheckpoint,
			takeStepScreenshot,
			'weather-forecast'
		);

		const weatherParent = page.locator(
			'[data-testid="embed-preview"][data-app-id="weather"][data-skill-id="forecast"]'
		).first();
		const weatherDay = page.getByTestId('weather-day-preview').first();

		await expect(async () => {
			const parentVisible = await weatherParent.isVisible().catch(() => false);
			const dayVisible = await weatherDay.isVisible().catch(() => false);
			expect(parentVisible || dayVisible, 'weather forecast or day embed should render').toBeTruthy();
		}).toPass({ timeout: 180_000 });

		if (await weatherParent.isVisible().catch(() => false)) {
			await expect(weatherParent).toHaveAttribute('data-status', 'finished', { timeout: 180_000 });
			await expect(weatherParent.getByTestId('weather-forecast-preview')).toBeVisible({ timeout: 15_000 });
			await expect(weatherParent).toContainText('Get forecast', { timeout: 15_000 });
			await expect(weatherParent).toContainText('via Deutscher Wetterdienst', { timeout: 15_000 });
			await expect(weatherParent.locator('[data-testid="app-icon-circle"][data-app-icon="weather"]')).toBeVisible({ timeout: 15_000 });
			const fullscreen = await openFullscreen(page, weatherParent);
			const grid = fullscreen.getByTestId('search-template-grid');
			await expect(grid).toBeVisible({ timeout: 30_000 });
			const firstDay = grid.locator('[data-testid="embed-preview"][data-skill-id="weather_day"]').first();
			await expect(firstDay).toBeVisible({ timeout: 30_000 });
			await expect(firstDay.locator('[data-testid="app-icon-circle"][data-app-icon="weather"]')).toBeVisible({ timeout: 30_000 });
			await firstDay.click();
			await expect(grid).toHaveAttribute('data-selected-index', '0', { timeout: 15_000 });
			await expect(page.getByTestId('weather-day-fullscreen')).toBeVisible({ timeout: 15_000 });
			await closeFullscreen(page, fullscreen);
		} else {
			await expect(weatherDay).toBeVisible({ timeout: 15_000 });
			await expect(weatherDay.getByTestId('weather-day-temperature')).toBeVisible({ timeout: 15_000 });
		}

		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'weather-forecast');
	});
});
