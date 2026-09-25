import { test } from 'node:test';
import assert from 'node:assert/strict';
import { workflowValue, valueEntries, outputFields, valueType, readableScalar, exampleValue, presentedFields } from '../workflowValuePresentation';

// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring,workflows.control.typed-data
test('nested and encoded workflow data remain structured values instead of JSON text', () => {
  const data = { temperature: 20, rain_expected: false, hourly: [{ time: '12:00', precipitation: 1.2 }] };
  assert.deepEqual(workflowValue(JSON.stringify(data)), data);
  assert.deepEqual(workflowValue('```json\n' + JSON.stringify(data) + '\n```'), data);
  assert.equal(valueType({ type: 'integer' }), 'number');
  assert.equal(valueType({ type: 'string', format: 'date' }), 'date');
  assert.equal(valueType({ type: 'array' }), 'list');
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring,workflows.message.standard
test('internal embed instructions and transport identities are absent from readable workflow content', () => {
  assert.equal(workflowValue('Your news\n\n```json\n{"type":"news_article","embed_id":"private-id"}\n```'), 'Your news');
  const results = [{ title: 'An event', date_start: '2026-09-21' }];
  assert.deepEqual(valueEntries({ results, events: results, embed_ids: ['private-id'], task_id: 'task', hashed_user_id: 'hash', encrypted_payload: 'cipher', result_count: 1 }).map(([key]) => key), ['results', 'result_count']);
  assert.deepEqual(outputFields({ results: { type: 'array' }, articles: { type: 'array' }, result_count: { type: 'integer' } }).map(([key]) => key), ['results', 'result_count']);
  assert.equal(readableScalar('$nodes.weather.output.rain_probability'), 'Weather · Rain Probability');
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring,workflows.control.typed-data
test('nested output examples come from declared schema values without inventing unavailable fields', () => {
  assert.deepEqual(exampleValue({ type: 'object', properties: { rain: { type: 'boolean', example: false }, temperatures: { type: 'array', items: { type: 'number', example: 18 } }, unknown: { type: 'string' } } }), { rain: false, temperatures: [18] });
  assert.equal(exampleValue({ type: 'string' }), undefined);
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring,workflows.control.typed-data
test('explicit skill field selection keeps unspecified fields behind Show all', () => {
  const fields = presentedFields({
    result_count: { type: 'integer', 'x-ui': { basic: true } },
    results: { type: 'array', items: { type: 'object' }, 'x-ui': { basic: true } },
    url: { type: 'string' },
    title: { type: 'string', 'x-ui': { basic: false } },
  }, 1);
  assert.deepEqual(fields.basic.map(([key]) => key), ['result_count', 'results']);
  assert.deepEqual(fields.advanced.map(([key]) => key), ['url', 'title']);
});
