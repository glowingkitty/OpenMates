import { test } from 'node:test';
import assert from 'node:assert/strict';
import { workflowSkillInputSummary } from '../workflowSkillSummary';

const strings = { in: 'in', to: 'to' };

// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring,workflows.control.typed-data
test('summarizes event and travel searches from their canonical request shapes', () => {
  assert.equal(
    workflowSkillInputSummary('events', 'search', {
      requests: [{ query: 'AI meetups', location: 'Hamburg' }],
    }, strings),
    'AI meetups in Hamburg',
  );
  assert.equal(
    workflowSkillInputSummary('travel', 'search_connections', {
      requests: [{ legs: [{ origin: 'Berlin', destination: 'Bangkok', date: '2026-10-10' }] }],
    }, strings),
    'Berlin to Bangkok',
  );
  assert.equal(
    workflowSkillInputSummary('travel', 'search_stays', {
      requests: [{ query: 'Hotels in Lisbon', check_in_date: '2026-10-10', check_out_date: '2026-10-14' }],
    }, strings),
    'Hotels in Lisbon · 2026-10-10 – 2026-10-14',
  );
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring,workflows.control.typed-data
test('uses localized connectors and explicit summaries for weather, news, and home', () => {
  assert.equal(
    workflowSkillInputSummary('events', 'search', { query: 'Design', location: 'Berlin' }, { in: 'in', to: 'nach' }),
    'Design in Berlin',
  );
  assert.equal(
    workflowSkillInputSummary('weather', 'forecast', { location: 'Paris', start_date: '2026-10-01', end_date: '2026-10-03' }, strings),
    'Paris · 2026-10-01 – 2026-10-03',
  );
  assert.equal(workflowSkillInputSummary('news', 'search', { requests: [{ query: 'EU AI Act' }] }, strings), 'EU AI Act');
  assert.equal(workflowSkillInputSummary('home', 'search', { requests: [{ query: 'Hamburg' }] }, strings), 'Hamburg');
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring,workflows.control.typed-data
test('falls back to at most two meaningful scalar fields', () => {
  assert.equal(
    workflowSkillInputSummary('travel', 'get_flight', { flight_number: 'LH2472', departure_date: '2026-09-20', providers: ['private'] }, strings),
    'LH2472 · 2026-09-20',
  );
  assert.equal(
    workflowSkillInputSummary('custom', 'lookup', { query: 'Coffee', location: 'Cologne', note: 'unused' }, { in: 'near', to: 'to' }),
    'Coffee near Cologne',
  );
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring,workflows.control.typed-data
test('never exposes secrets, identifiers, objects, arrays, or JSON text', () => {
  assert.equal(
    workflowSkillInputSummary('custom', 'lookup', {
      access_token: 'secret-token',
      apiKey: 'another-secret',
      user_id: 'private-id',
      password: 'hunter2',
      metadata: { private: true },
      results: ['private'],
      payload: '{"private":true}',
      subject: 'Public subject',
    }, strings),
    'Public subject',
  );
  assert.equal(workflowSkillInputSummary('custom', 'lookup', { api_key: 'secret', request_id: 'private' }, strings), '');
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring,workflows.control.typed-data
test('returns an empty summary without usable values and truncates long text', () => {
  assert.equal(workflowSkillInputSummary('events', 'search', { requests: [{}] }, strings), '');
  const summary = workflowSkillInputSummary('news', 'search', { requests: [{ query: 'A'.repeat(200) }] }, strings);
  assert.equal(summary, `${'A'.repeat(47)}…`);
});
