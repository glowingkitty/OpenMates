import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { hasNaturalOpening, validateLandingAppExamples } from './validate-landing-app-examples.mjs';

// contract-test: supporting surface=gui.web assertions=marketing-landing.hero-app-rail
test('accepts natural requests with real audio or document attachments', () => {
  assert.equal(hasNaturalOpening('Transcribe this recording and summarize the main points.\n[!](embed:recording-id)'), true);
  assert.equal(hasNaturalOpening('[!](embed:document-id)\nExplain the costs in this budget.'), true);
  assert.equal(hasNaturalOpening('Find AI meetups in Berlin next week.'), true);
});

// contract-test: supporting surface=gui.web assertions=marketing-landing.hero-app-rail
test('validates registered real examples for numeric public app IDs', () => {
  const root = mkdtempSync(join(tmpdir(), 'landing-example-validator-'));
  const write = (name, content) => {
    const file = join(root, name);
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, content);
  };
  try {
    write('frontend/packages/public-site/src/components/landing/landingPageContent.ts', "export const landingAppExamples: Record<string, string> = {\n  models3d: 'example-models',\n};");
    write('frontend/packages/ui/src/demo_chats/exampleChatData.ts', "import { models } from './data/example_chats/models';");
    write('frontend/packages/ui/src/demo_chats/data/example_chats/models.ts', '// Extracted from shared chat source-id\nconst models = { chat_id: "example-models" };');
    write('frontend/packages/ui/src/i18n/sources/example_chats/models.yml', 'message_1:\n  en: Find printable models of phone stands.\n');
    assert.doesNotThrow(() => validateLandingAppExamples(root, new Set(['models3d'])));
    assert.throws(() => validateLandingAppExamples(root, new Set(['models3d', 'pdf'])), /Public landing apps need matching real examples: pdf/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// contract-test: supporting surface=gui.web assertions=marketing-landing.hero-app-rail
test('rejects attachment-only, machine-only, and internal skill instructions', () => {
  for (const opening of [undefined, '', '[!](embed:recording-id)', '```json\n{"embed_id":"x"}\n```', '@events:search Find meetups in Berlin.']) {
    assert.equal(hasNaturalOpening(opening), false);
  }
});
