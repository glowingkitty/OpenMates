/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified E2E coverage for weather/forecast.
 *
 * Phase 0: App metadata exposes Weather / Forecast.
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

test.describe('App: Weather / Skill: forecast', () => {
	test.setTimeout(180_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	test('Phase 0: app store metadata exposes weather forecast', async ({ request }: { request: any }) => {
		const response = await request.get(`${apiUrl}/v1/apps/metadata`);
		expect(response.ok()).toBeTruthy();

		const data = await response.json();
		const weather = data.apps?.weather;
		expect(weather, 'weather app should appear in app store metadata').toBeTruthy();

		const skillIds = (weather.skills || []).map((skill: { id: string }) => skill.id);
		expect(skillIds).toContain('forecast');
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
		expectForecastPayload(berlinParsed, 'Bright Sky');

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
			await expect(weatherParent.getByTestId('weather-forecast-preview')).toBeVisible({ timeout: 15_000 });
			const fullscreen = await openFullscreen(page, weatherParent);
			const grid = fullscreen.getByTestId('weather-forecast-fullscreen-grid');
			await expect(grid).toBeVisible({ timeout: 30_000 });
			await expect(grid.getByTestId('weather-day-preview').first()).toBeVisible({ timeout: 30_000 });
			await closeFullscreen(page, fullscreen);
		} else {
			await expect(weatherDay).toBeVisible({ timeout: 15_000 });
			await expect(weatherDay.getByTestId('weather-day-temperature')).toBeVisible({ timeout: 15_000 });
		}

		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'weather-forecast');
	});
});
