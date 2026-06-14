/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified E2E coverage for weather/rain_radar.
 *
 * Phase 0: App metadata exposes Weather / Rain radar.
 * Phase 1: Embed preview renders at /dev/preview/embeds/weather.
 * Phase 2: Fullscreen preview renders interactive timeline controls.
 */
export {};

const { test, expect } = require('./console-monitor');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');

test.describe('App: Weather / Skill: rain_radar', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	test('Phase 0: app store metadata exposes weather rain radar', async ({ request }: { request: any }) => {
		const response = await request.get(`${apiUrl}/v1/apps/metadata`);
		expect(response.ok()).toBeTruthy();

		const data = await response.json();
		const weather = data.apps?.weather;
		expect(weather, 'weather app should appear in app store metadata').toBeTruthy();

		const skillIds = (weather.skills || []).map((skill: { id: string }) => skill.id);
		expect(skillIds).toContain('forecast');
		expect(skillIds).toContain('rain_radar');

		const rainRadar = (weather.skills || []).find((skill: { id: string }) => skill.id === 'rain_radar');
		expect(rainRadar?.description).toBe('apps.weather.rain_radar.description');
	});

	test('Phase 1: embed preview renders through direct component preview', async ({ page }: { page: any }) => {
		const response = await page.goto('/dev/preview/embeds/weather/WeatherRainRadarEmbedPreview', {
			waitUntil: 'networkidle'
		});
		expect(response?.status()).toBe(200);

		await expect(page.getByTestId('render-error')).not.toBeVisible({ timeout: 10_000 });
		await expect(page.getByTestId('weather-rain-radar-preview').first()).toBeVisible();
		await expect(page.getByTestId('weather-rain-radar-still').first()).toBeVisible();
	});

	test('Phase 2: fullscreen preview renders timeline controls', async ({ page }: { page: any }) => {
		const response = await page.goto('/dev/preview/embeds/weather/WeatherRainRadarEmbedFullscreen', {
			waitUntil: 'networkidle'
		});
		expect(response?.status()).toBe(200);

		await expect(page.getByTestId('render-error')).not.toBeVisible({ timeout: 10_000 });
		await expect(page.getByTestId('weather-rain-radar-fullscreen')).toBeVisible();
		await expect(page.getByTestId('weather-rain-radar-timeline')).toBeVisible();
		await expect(page.getByTestId('weather-rain-radar-scrubber')).toBeVisible();
		await expect(page.getByTestId('weather-rain-radar-play-toggle')).toBeVisible();
	});
});
