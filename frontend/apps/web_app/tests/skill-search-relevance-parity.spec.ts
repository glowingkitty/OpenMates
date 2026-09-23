/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Surface contract for optional app-skill relevance ranking.
 *
 * This spec deliberately checks schemas and generated CLI commands without
 * invoking Jev. Real provider/Jev quality probes run directly on dev because
 * they require live AI inference.
 */
export {};

const { test, expect } = require('./console-monitor');
const { deriveApiUrl, runCli } = require('./helpers/cli-test-helpers');

const ELIGIBLE_SKILLS = [
	['web', 'search'],
	['news', 'search'],
	['events', 'search'],
	['home', 'search'],
	['maps', 'search'],
	['shopping', 'search_products'],
	['travel', 'search_stays'],
	['videos', 'search'],
	['fitness', 'search_locations'],
	['fitness', 'search_classes']
] as const;

function resolveSchema(openapi: any, schema: any): any {
	const reference = schema?.$ref;
	if (typeof reference !== 'string' || !reference.startsWith('#/components/schemas/')) {
		return schema;
	}
	return openapi.components?.schemas?.[reference.split('/').pop() || ''];
}

function resolveTypedOption(schema: any, type: string): any {
	return schema?.anyOf?.find((option: any) => option?.type === type) || schema;
}

test.describe('App skills: optional search relevance surface parity', () => {
	test.setTimeout(120_000);

	// contract-test: direct surface=rest_api assertions=app-skills.surface.semantic-parity,app-skills.search-relevance.optional-and-inferred
	test('REST/OpenAPI exposes the optional bounded field on every eligible skill', async ({ request }: { request: any }) => {
		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const response = await request.get(`${apiUrl}/openapi.json`);
		expect(response.ok()).toBe(true);
		const openapi = await response.json();

		for (const [appId, skillId] of ELIGIBLE_SKILLS) {
			const operation = openapi.paths?.[`/v1/apps/${appId}/skills/${skillId}`]?.post;
			expect(operation, `${appId}.${skillId} REST route missing`).toBeTruthy();
			const bodySchema = resolveSchema(
				openapi,
				operation.requestBody?.content?.['application/json']?.schema
			);
			const requestsSchema = resolveSchema(openapi, bodySchema?.properties?.requests);
			const itemSchema = resolveSchema(openapi, requestsSchema?.items);
			const relevanceSchema = resolveTypedOption(
				itemSchema?.properties?.relevance_criteria,
				'string'
			);
			expect(
				relevanceSchema?.maxLength,
				`${appId}.${skillId} relevance_criteria maxLength missing`
			).toBe(1000);
			expect(itemSchema?.required || []).not.toContain('relevance_criteria');
		}
	});

	// contract-test: direct surface=cli assertions=app-skills.surface.semantic-parity,app-skills.search-relevance.optional-and-inferred
	test('typed CLI commands expose --relevance-criteria for every eligible skill', async () => {
		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		for (const [appId, skillId] of ELIGIBLE_SKILLS) {
			const result = await runCli(apiUrl, ['apps', appId, skillId, '--help']);
			expect(result.code, `${appId}.${skillId} help failed: ${result.stderr}`).toBe(0);
			expect(result.stdout).toContain('--relevance-criteria');
		}
	});
});
