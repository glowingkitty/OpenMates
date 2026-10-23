import { expect, test } from './helpers/cookie-audit';
import { deriveApiUrl } from './helpers/cli-test-helpers';

function resolve(openapi: any, schema: any): any {
  return schema?.$ref ? openapi.components.schemas[schema.$ref.split('/').pop()] : schema;
}

// contract-test: supporting surface=rest_api assertions=maps-search.compatibility.regular-search
test('maps REST schema exposes optional hard closing-time inputs', async ({ request }) => {
  const api = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
  const response = await request.get(`${api}/openapi.json`);
  expect(response.ok()).toBe(true);
  const openapi = await response.json();
  const operation = openapi.paths['/v1/apps/maps/skills/search'].post;
  const body = resolve(openapi, operation.requestBody.content['application/json'].schema);
  const item = resolve(openapi, body.properties.requests.items);
  const until = item.properties.openUntil;
  const date = item.properties.openOn;
  const stringSchema = (field: any) => field.anyOf?.find((option: any) => option.type === 'string') || field;
  expect(stringSchema(until).pattern).toContain('[0-5]');
  expect(stringSchema(date).pattern).toBe('^\\d{4}-\\d{2}-\\d{2}$');
  expect(item.required || []).not.toContain('openUntil');
  expect(item.required || []).not.toContain('openOn');
  expect(until.description).toContain('Unknown hours are excluded');
});
