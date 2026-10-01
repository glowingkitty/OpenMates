/** Audio speech model metadata uses the real isolated API without provider inference. */
import { test, expect } from './console-monitor';
import { deriveApiUrl } from './helpers/cli-test-helpers';

test.describe('Audio speech model selection', () => {
	// contract-test: direct surface=rest_api assertions=audio-speak.surface-parity,audio-speak.provider.explicit-selection,audio-speak.request.validated
	test('OpenAPI exposes v4 and v4 Turbo speech selection', async ({ request }) => {
		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const response = await request.get(`${apiUrl}/openapi.json`);
		expect(response.ok()).toBeTruthy();
		const openapi = await response.json();
		const resolveSchema = (schema: any): any => schema?.$ref
			? openapi.components.schemas[schema.$ref.split('/').pop()]
			: schema;
		const operation = openapi.paths['/v1/apps/audio/skills/speak'].post;
		const body = resolveSchema(operation.requestBody.content['application/json'].schema);
		const item = resolveSchema(resolveSchema(body.properties.requests).items);
		const model = resolveSchema(item.properties.model);
		const modelValues = model.anyOf?.map(resolveSchema).find((option: any) => option.type === 'string') || model;
		expect(modelValues.enum).toEqual([
			'eleven_v3', 'eleven_multilingual_v2', 'eleven_flash_v2_5', 'eleven_v4', 'eleven_v4_turbo'
		]);
		expect(model.default).toBe('eleven_v3');
		expect(item.properties.speed.description).toContain('v4 Turbo require 1.0');
	});
});
