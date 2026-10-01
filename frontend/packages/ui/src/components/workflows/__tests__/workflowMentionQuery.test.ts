import { test } from 'node:test';
import assert from 'node:assert/strict';
import { workflowMentionQuery, matchesWorkflowVariableQuery } from '../workflowMentionQuery.ts';

// contract-test: supporting surface=gui.web assertions=workflows-ui.editor.inline-action-variables
test('partial mentions retain the complete replacement span and stop at prose boundaries', () => {
  assert.deepEqual(workflowMentionQuery('Summarize @Events.results'), { text: '@Events.results', query: 'Events.results', length: 15 });
  assert.deepEqual(workflowMentionQuery('@'), { text: '@', query: '', length: 1 });
  assert.equal(workflowMentionQuery('someone@example.com'), null);
  assert.equal(workflowMentionQuery('Summarize @Events tomorrow'), null);
  assert.equal(workflowMentionQuery('Summarize \ufffc'), null);
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.editor.inline-action-variables
test('queries match action and field word prefixes across dotted paths', () => {
  assert.equal(matchesWorkflowVariableQuery('Events | Search · Results', 'E'), true);
  assert.equal(matchesWorkflowVariableQuery('Weather | Get forecast', 'E'), false);
  assert.equal(matchesWorkflowVariableQuery('Travel | Search connections · Result count', 'travel.count'), true);
  assert.equal(matchesWorkflowVariableQuery('Events | Search · Results', 'events.price'), false);
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.editor.inline-action-variables
test('fully qualified queries select the matching app, skill and field path', () => {
  const label = 'Events | Search · Results';
  assert.equal(matchesWorkflowVariableQuery(label, 'events.search.results', 'events.search.results'), true);
  assert.equal(matchesWorkflowVariableQuery(label, 'events.search.res', 'events.search.results'), true);
  assert.equal(matchesWorkflowVariableQuery(label, 'events.search.results', 'events.search.result_count'), false);
  assert.equal(matchesWorkflowVariableQuery(label, 'travel.search.results', 'events.search.results'), false);
  assert.equal(matchesWorkflowVariableQuery('Travel | Search connections · Results', 'travel.search-connections.results', 'travel.search-connections.results'), true);
});
