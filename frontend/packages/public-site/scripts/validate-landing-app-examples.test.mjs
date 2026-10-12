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
    write('frontend/packages/ui/src/demo_chats/data/example_chats/models.ts', '// Extracted from shared chat source-id\nconst models = { chat_id: "example-models", content: "app_id: models3d\\nskill_id: search" };');
    write('frontend/packages/ui/src/i18n/sources/example_chats/models.yml', 'message_1:\n  en: Find printable models of phone stands.\n');
    const model = { id: 'models3d', capability: { type: 'skill', id: 'search' }, example_chat_id: 'example-models' };
    assert.doesNotThrow(() => validateLandingAppExamples(root, [model]));
    assert.throws(() => validateLandingAppExamples(root, [model, { id: 'pdf' }]), /Public landing apps need matching real examples: pdf/);
    assert.throws(() => validateLandingAppExamples(root, [{
      id: 'models3d', capability: { type: 'app', id: 'models3d' }, example_chat_id: 'example-models',
      source_evidence: { request_excerpt: 'Summarize my finances from statements', rationale: 'Reviewed ordinary app request for a financial summary.' }
    }]), /reviewed app-level landing source evidence does not match opening/i);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// contract-test: supporting surface=gui.web assertions=marketing-landing.app-metadata-defaults
test('example capability evidence rejects an unrelated skill or focus', () => {
  const source = 'content: "app_id: models3d\\nskill_id: search"';
  assert.equal(hasCapabilityEvidence(source, { id: 'models3d', capability: { type: 'skill', id: 'search' } }), true);
  assert.equal(hasCapabilityEvidence(source, { id: 'models3d', capability: { type: 'skill', id: 'generate' } }), false);
  assert.equal(hasCapabilityEvidence(source, { id: 'models3d', capability: { type: 'focus', id: 'research' } }), false);
  assert.equal(hasCapabilityEvidence('content: "app_id: docs\\ntype: document"', {
    id: 'docs', capability: { type: 'artifact', id: 'doc' }, evidence_types: ['doc', 'document']
  }), true);
  assert.equal(hasCapabilityEvidence('content: "app_id: books\\nfocus_id: books-book_discussion"', {
    id: 'books', capability: { type: 'focus', id: 'book_discussion' }
  }), true);
});

// contract-test: supporting surface=gui.web assertions=marketing-landing.app-metadata-defaults
test('rejects attachment-only, machine-only, and internal skill instructions', () => {
  for (const opening of [undefined, '', '[!](embed:recording-id)', '```json\n{"embed_id":"x"}\n```', '@events:search Find meetups in Berlin.']) {
    assert.equal(hasNaturalOpening(opening), false);
  }
  assert.equal(hasNaturalOpening('@mate:general_knowledge Summarize my calendar week from these events.'), true);
});
