/* eslint-disable @typescript-eslint/no-require-imports */
/** Public-provider regression coverage; assistant inference is verified on dev. */
export {};

const { test, expect } = require('./console-monitor');
const { deriveApiUrl, runCli, parseCliJson, expectCliSuccess } = require('./helpers/cli-test-helpers');

test.describe('Fitness class search request regression', () => {
	test.setTimeout(120_000);

	// contract-test: direct surface=cli assertions=app-skills.surface.semantic-parity,app-skills.execution.registered-validated
	test('activity names, numeric IDs, and nullable optional filters preserve three multi-day request groups', async () => {
		expect(process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'CI must provision an API key').toBeTruthy();
		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const requests = [
			{ id: 'dance', city: 'Berlin', category: 'dance', query: 'Dance, Contemporary', attendance_mode: 'onsite', days: 3, limit: 2 },
			{ id: 'yoga', city: 'Berlin', category: '40002', min_spots: null, query: 'Yoga, Pilates', attendance_mode: 'onsite', days: 3, limit: 2 },
			{ id: 'dance-numeric', city: 'Berlin', category: '40005', min_spots: 1, query: 'Dance, Contemporary', attendance_mode: 'onsite', days: 3, limit: 2 }
		];
		const result = await runCli(apiUrl, [
			'apps', 'fitness', 'search_classes', '--input', JSON.stringify({ requests }),
			'--disable-prompt-injection-protection', '--json'
		], 90_000, { record: true, env: { OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: 'skill-fitness-class-search' } });
		expectCliSuccess(result);
		const parsed = parseCliJson(result);
		expect(parsed.success).toBe(true);
		expect(parsed.data?.provider).toBe('Urban Sports Club');
		const groups = parsed.data?.results;
		expect(groups).toHaveLength(3);
		expect(groups.map((group: any) => group.id)).toEqual(['dance', 'yoga', 'dance-numeric']);
		for (const group of groups) {
			expect(group.error).toBeUndefined();
			expect(group.filters.days).toBe(3);
			expect(group.filters.min_spots).toBe(1);
			expect(group.result_count).toBeGreaterThan(0);
			expect(group.result_count).toBeLessThanOrEqual(2);
			expect(group.results).toHaveLength(group.result_count);
			for (const item of group.results) {
				expect(item.attendance_mode).toBe('onsite');
				expect(item.spots_left).toBeGreaterThanOrEqual(1);
				expect(item.category?.toLowerCase()).toBe(group.id.startsWith('dance') ? 'dancing' : 'yoga');
			}
		}
	});
});
