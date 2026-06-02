/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified E2E coverage for weather/forecast.
 *
 * Phase 0: App metadata exposes Weather / Forecast.
 * Phase 1: Embed preview renders at /dev/preview/embeds/weather.
 * Phase 2: CLI direct skill command returns one weather_day per requested day.
 * Phase 3: CLI chat send triggers weather forecast.
 * Phase 4: Web UI chat triggers forecast embed with fullscreen day cards.
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
	verifyEmbedPreviewPage,
	waitForEmbedFinished,
	openFullscreen,
	closeFullscreen
} = require('./helpers/embed-test-helpers');

function getForecastResults(parsed: any): any[] {
	return parsed.data?.results || parsed.results || [];
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

	test('Phase 1: embed preview renders at /dev/preview/embeds/weather', async ({ page }: { page: any }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'weather', log);
		await expect(page.getByTestId('weather-forecast-preview').first()).toBeVisible();
	});

	test('Phase 2: CLI apps weather forecast returns daily child results', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'OPENMATES_TEST_ACCOUNT_API_KEY required.');

		const result = await runCli(
			apiUrl,
			[
				'apps', 'weather', 'forecast',
				'--input', JSON.stringify({ location: 'Berlin', days: 2 }),
				'--json'
			],
			60_000
		);

		expectCliSuccess(result, 'weather/forecast CLI');
		const parsed = parseCliJson(result);
		expect(parsed.success).toBe(true);

		const results = getForecastResults(parsed);
		expect(results.length).toBe(2);
		expect(results.every((day) => day.type === 'weather_day')).toBeTruthy();
		expect(results.every((day) => Array.isArray(day.hourly) && day.hourly.length > 0)).toBeTruthy();
		expect(parsed.data?.provider).toContain('Bright Sky');
	});

	test('Phase 3: CLI chats new triggers weather forecast', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'OPENMATES_TEST_ACCOUNT_API_KEY required.');

		const message = withLiveMockMarker('Show me a 2 day weather forecast for Berlin', 'weather_forecast_cli');
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
			withLiveMockMarker('Show me a 2 day weather forecast for Berlin', 'weather_forecast_web'),
			logCheckpoint,
			takeStepScreenshot,
			'weather-forecast'
		);

		const embed = await waitForEmbedFinished(page, 'weather', 'forecast', 120_000);
		await expect(embed.getByTestId('weather-forecast-preview')).toBeVisible({ timeout: 15_000 });

		const fullscreen = await openFullscreen(page, embed);
		const grid = fullscreen.getByTestId('weather-forecast-fullscreen-grid');
		await expect(grid).toBeVisible({ timeout: 30_000 });
		await expect(grid.getByTestId('weather-day-preview').first()).toBeVisible({ timeout: 30_000 });

		await closeFullscreen(page, fullscreen);
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'weather-forecast');
	});
});
