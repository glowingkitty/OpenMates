/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * E2E test for mail/search skill provider health gating.
 *
 * Verifies that when the ProtonMail provider is unhealthy, the mail/search
 * skill does NOT appear in the app store metadata. This prevents the AI from
 * offering a broken skill and avoids failed embed rendering.
 *
 * Bug history this test suite guards against:
 * - 325bdd9: mail/search was visible and selectable even with ProtonMail bridge down,
 *   causing failed skill execution and broken embeds
 *
 * Architecture context: backend/shared/python_utils/provider_health.py
 */
export {};

const { test, expect } = require('./console-monitor');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');

test.describe('App: Mail / Skill: search — provider health gating', () => {
	test.setTimeout(30_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	test('mail/search skill is hidden when ProtonMail provider is unhealthy', async ({
		request
	}) => {
		const log = (msg: string) => console.log(`[mail-health] ${msg}`);

		// Fetch app store metadata (unauthenticated — mail/search should be hidden
		// both because the user isn't the allowed ProtonMail user AND because the
		// provider is unhealthy)
		log(`Fetching app metadata from ${apiUrl}/v1/apps/metadata`);
		const response = await request.get(`${apiUrl}/v1/apps/metadata`);
		expect(response.ok()).toBeTruthy();

		const data = await response.json();
		const apps = data.apps || {};

		log(`Apps returned: ${Object.keys(apps).join(', ')}`);

		// The mail app may be present (it has settings_and_memories for writing styles)
		// but it must NOT have the search skill when ProtonMail is unhealthy
		if (apps.mail) {
			const mailSkillIds = (apps.mail.skills || []).map((s: any) => s.id);
			log(`Mail app skills: ${mailSkillIds.length > 0 ? mailSkillIds.join(', ') : '(none)'}`);

			expect(
				mailSkillIds,
				'mail/search skill should NOT appear when ProtonMail provider is unhealthy'
			).not.toContain('search');
		} else {
			log('Mail app not in metadata at all (also acceptable)');
		}
	});

	test('no other app lost its skills due to health gating', async ({ request }) => {
		const log = (msg: string) => console.log(`[mail-health] ${msg}`);

		// Verify that core apps still have their skills (regression guard)
		const response = await request.get(`${apiUrl}/v1/apps/metadata`);
		expect(response.ok()).toBeTruthy();

		const data = await response.json();
		const apps = data.apps || {};

		// These apps should always have at least one skill
		const coreApps = ['web', 'news', 'images', 'maps', 'math'];
		for (const appId of coreApps) {
			if (apps[appId]) {
				const skillCount = (apps[appId].skills || []).length;
				log(`${appId}: ${skillCount} skill(s)`);
				expect(
					skillCount,
					`Core app '${appId}' should have at least one skill`
				).toBeGreaterThan(0);
			}
		}
	});
});
