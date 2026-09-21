import { test } from 'node:test';
import assert from 'node:assert/strict';
import { documentToTemplate, templateToDocument, outputToken, WORKFLOW_OUTPUT_NODE } from '../workflowMessageTokens.ts';

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
