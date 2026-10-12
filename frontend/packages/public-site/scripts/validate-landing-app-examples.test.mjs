import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { hasCapabilityEvidence, hasNaturalOpening, validateLandingAppExamples } from './validate-landing-app-examples.mjs';

// contract-test: supporting surface=gui.web assertions=marketing-landing.app-metadata-defaults
test('accepts natural requests with real audio or document attachments', () => {
  assert.equal(hasNaturalOpening('Transcribe this recording and summarize the main points.\n[!](embed:recording-id)'), true);
  assert.equal(hasNaturalOpening('[!](embed:document-id)\nExplain the costs in this budget.'), true);
  assert.equal(hasNaturalOpening('Find AI meetups in Berlin next week.'), true);
});

// contract-test: supporting surface=gui.web assertions=marketing-landing.app-metadata-defaults
test('validates registered real examples for numeric public app IDs', () => {
  const root = mkdtempSync(join(tmpdir(), 'landing-example-validator-'));
  const write = (name, content) => {
    const file = join(root, name);
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, content);
  };
  try {
    write('frontend/packages/ui/src/demo_chats/exampleChatData.ts', "import { models } from './data/example_chats/models';");
    write('frontend/packages/ui/src/demo_chats/data/example_chats/models.ts', '// Extracted from shared chat source-id\nconst models = { chat_id: "example-models", embeds: [{\n embed_id: "one", content: "app_id: models3d\\nskill_id: search\\nresult_count: 2\\nstatus: finished" }], metadata: {} };');
    write('frontend/packages/ui/src/i18n/sources/example_chats/models.yml', 'message_1:\n  en: Find printable models of phone stands.\n');
    const model = { id: 'models3d', capability: { type: 'skill', id: 'search' }, example_chat_id: 'example-models' };
    assert.doesNotThrow(() => validateLandingAppExamples(root, [model]));
    assert.throws(() => validateLandingAppExamples(root, [model, { id: 'pdf' }]), /Public landing apps need matching real examples: pdf/);
    assert.throws(() => validateLandingAppExamples(root, [{
      id: 'models3d', capability: { type: 'app', id: 'models3d' }, example_chat_id: 'example-models'
    }]), /does not demonstrate/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// contract-test: supporting surface=gui.web assertions=marketing-landing.app-metadata-defaults
test('example capability evidence rejects an unrelated skill or focus', () => {
  const embed = (content) => `embeds: [\n {\n embed_id: "one", content: "${content.replaceAll('\n', '\\n')}" }\n],\nmetadata: {}`;
  const source = embed('app_id: models3d\nskill_id: search\nresult_count: 2\nstatus: finished');
  assert.equal(hasCapabilityEvidence(source, { id: 'models3d', capability: { type: 'skill', id: 'search' } }), true);
  assert.equal(hasCapabilityEvidence(source, { id: 'models3d', capability: { type: 'skill', id: 'generate' } }), false);
  assert.equal(hasCapabilityEvidence(source, { id: 'models3d', capability: { type: 'focus', id: 'research' } }), false);
  assert.equal(hasCapabilityEvidence(embed('app_id: docs\ntype: document\nstatus: finished\ntitle: Useful document\ndocx_model: actual document body'), {
    id: 'docs', capability: { type: 'artifact', id: 'doc' }, evidence_types: ['doc', 'document']
  }), true);
  assert.equal(hasCapabilityEvidence(embed('app_id: books\nfocus_id: books-book_discussion\nstatus: finished'), {
    id: 'books', capability: { type: 'focus', id: 'book_discussion' }
  }), true);
  assert.equal(hasCapabilityEvidence(embed('app_id: models3d\nskill_id: search\nresult_count: 0\nstatus: finished'), {
    id: 'models3d', capability: { type: 'skill', id: 'search' }
  }), false);
  assert.equal(hasCapabilityEvidence(embed('app_id: models3d\nskill_id: search\nstatus: failed\nerror: unavailable'), {
    id: 'models3d', capability: { type: 'skill', id: 'search' }
  }), false);
  assert.equal(hasCapabilityEvidence(embed('app_id: models3d\nskill_id: search\nstatus: finished'), {
    id: 'models3d', capability: { type: 'skill', id: 'search' }
  }), false);
  assert.equal(hasCapabilityEvidence(embed('app_id: models3d\nskill_id: search\nstatus: finished\ntitle: ""\nurl: ""'), {
    id: 'models3d', capability: { type: 'skill', id: 'search' }
  }), false);
  const failedDomain = embed('app_id: hosting\nskill_id: search_domains\nprovider_status: error\navailability: unknown\ncheck_error: Domain check unavailable\nurl: https://provider.example/error');
  assert.equal(hasCapabilityEvidence(failedDomain, {
    id: 'hosting', capability: { type: 'skill', id: 'search_domains' }
  }), false);
  assert.equal(hasCapabilityEvidence(failedDomain.replace('metadata: {}', '') + '\n' + embed('app_id: hosting\nskill_id: search_domains\navailability: available\nprovider_status: available\nprice: 11.00'), {
    id: 'hosting', capability: { type: 'skill', id: 'search_domains' }
  }), true);
  assert.equal(hasCapabilityEvidence(embed('app_id: docs\ntype: document\nstatus: finished'), {
    id: 'docs', capability: { type: 'artifact', id: 'doc' }, evidence_types: ['document']
  }), false);
  assert.equal(hasCapabilityEvidence(embed('app_id: docs\ntype: document\nstatus: finished\ntitle: ""\ncontent: ""'), {
    id: 'docs', capability: { type: 'artifact', id: 'doc' }, evidence_types: ['document']
  }), false);
  assert.equal(hasCapabilityEvidence(embed('app_id: docs\ntype: document\nstatus: finished\ntitle: A title only'), {
    id: 'docs', capability: { type: 'artifact', id: 'doc' }, evidence_types: ['document']
  }), false);
  const diagram = { id: 'diagrams', capability: { type: 'artifact', id: 'html' }, evidence_types: ['html', 'diagram_html'] };
  assert.equal(hasCapabilityEvidence(embed('app_id: diagrams\nskill_id: html\ntype: diagram_html\nstatus: finished\nhtml_source: <html><body><svg aria-label="Checkout flow"></svg></body></html>'), diagram), true);
  assert.equal(hasCapabilityEvidence(embed('app_id: diagrams\nskill_id: html\ntype: diagram_html\nstatus: finished\nhtml_source: ""'), diagram), false);
  assert.equal(hasCapabilityEvidence(embed('app_id: fitness\nskill_id: search_classes\nresult_count: 0\nstatus: finished') + '\n' + embed('app_id: events\nskill_id: search\nresult_count: 5\nstatus: finished'), {
    id: 'fitness', capability: { type: 'skill', id: 'search_classes' }
  }), false);
});

// contract-test: supporting surface=gui.web assertions=marketing-landing.app-metadata-defaults
test('rejects attachment-only, machine-only, and internal skill instructions', () => {
  for (const opening of [undefined, '', '[!](embed:recording-id)', '```json\n{"embed_id":"x"}\n```', '@events:search Find meetups in Berlin.']) {
    assert.equal(hasNaturalOpening(opening), false);
  }
  assert.equal(hasNaturalOpening('@mate:general_knowledge Summarize my calendar week from these events.'), true);
});
