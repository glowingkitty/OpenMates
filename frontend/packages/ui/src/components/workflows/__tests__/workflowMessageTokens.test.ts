import { test } from 'node:test';
import assert from 'node:assert/strict';
import { documentToTemplate, templateToDocument, outputCanonicalName, outputToken, WORKFLOW_OUTPUT_NODE } from '../workflowMessageTokens.ts';

const rain = { reference: '$nodes.weather.output.rain_summary', label: 'Weather · Rain summary' };
const count = { reference: '$nodes.news.output.result_count', label: 'News · Number of results' };

// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring,workflows.control.typed-data
test('message templates round trip multiline text and readable atomic output labels', () => {
  const template = 'Good morning! {{steps.weather.rain_summary}}\n\nThere are {{steps.news.result_count}} articles.';
  const doc = templateToDocument(template, [rain, count]);
  assert.equal(documentToTemplate(doc), template);
  const token = doc.content![0].content![1];
  assert.equal(token.type, WORKFLOW_OUTPUT_NODE);
  assert.equal(token.attrs!.displayName, rain.label);
  assert.equal(token.text, undefined);
  assert.equal(token.attrs!.mentionSyntax, '{{steps.weather.rain_summary}}');
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring,workflows.control.typed-data
test('inserting and removing a whole scalar token preserves surrounding user text', () => {
  const doc = templateToDocument('Before after');
  doc.content![0].content = [{ type: 'text', text: 'Before ' }, outputToken(rain), { type: 'text', text: ' after' }];
  assert.equal(documentToTemplate(doc), 'Before {{steps.weather.rain_summary}} after');
  doc.content![0].content!.splice(1, 1);
  assert.equal(documentToTemplate(doc), 'Before  after');
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring,workflows.control.typed-data
test('existing references stay readable even before output metadata is available', () => {
  const doc = templateToDocument('At {{clock.now}}: {{$nodes.weather.output.rain_summary}}');
  const tokens = doc.content![0].content!.filter(node => node.type === WORKFLOW_OUTPUT_NODE);
  assert.ok(tokens.every(node => !String(node.attrs!.displayName).includes('{{') && !String(node.attrs!.displayName).includes('$nodes.')));
  assert.equal(documentToTemplate(doc), 'At {{clock.now}}: {{$nodes.weather.output.rain_summary}}');
  assert.equal(documentToTemplate(templateToDocument('{{$nodes.weather.output.rain_summary}}', [rain])), '{{steps.weather.rain_summary}}');
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.editor.inline-action-variables
test('declared skill outputs display canonical addresses while retaining node-specific storage references', () => {
  const events = { reference: '$nodes.event_search_1.output.results', label: 'My events · Results', appId: 'events', skillId: 'search' };
  const travel = { reference: '$nodes.connections_2.output.results', label: 'Trip search · Results', appId: 'travel', skillId: 'search_connections' };
  assert.equal(outputCanonicalName(events), 'events.search.results');
  assert.equal(outputCanonicalName(travel), 'travel.search-connections.results');
  const eventToken = outputToken(events);
  const travelToken = outputToken(travel);
  assert.equal(eventToken.attrs?.displayName, 'events.search.results');
  assert.equal(eventToken.attrs?.appId, 'events');
  assert.equal(eventToken.attrs?.sourceLabel, events.label);
  assert.equal(eventToken.attrs?.mentionId, events.reference);
  assert.equal(travelToken.attrs?.displayName, 'travel.search-connections.results');
  assert.equal(travelToken.attrs?.mentionSyntax, '{{steps.connections_2.results}}');
  assert.equal(documentToTemplate(templateToDocument('{{steps.event_search_1.results}}', [events])), '{{steps.event_search_1.results}}');
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.editor.inline-action-variables
test('same-skill nodes share the readable address but retain distinct node identities', () => {
  const first = { reference: '$nodes.event_search_1.output.results', label: 'Morning events · Results', appId: 'events', skillId: 'search' };
  const second = { reference: '$nodes.event_search_2.output.results', label: 'Evening events · Results', appId: 'events', skillId: 'search' };
  assert.equal(outputToken(first).attrs?.displayName, outputToken(second).attrs?.displayName);
  assert.notEqual(outputToken(first).attrs?.mentionId, outputToken(second).attrs?.mentionId);
  assert.equal(outputCanonicalName(rain), null);
});
