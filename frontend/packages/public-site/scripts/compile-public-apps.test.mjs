import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { compilePublicApps, validateLandingMetadata } from './compile-public-apps.mjs';

// contract-test: supporting surface=gui.web assertions=marketing-landing.app-metadata-defaults
test('landing defaults require a real enabled tagged capability and localized caption', () => {
  const skills = new Set(['search']);
  const focuses = new Set(['research']);
  const artifacts = new Set(['document']);
  const landing = {
    order: 2,
    capability: { type: 'skill', id: 'search' },
    caption: { en: 'Find events', de: 'Finde Veranstaltungen' },
    example_chat_id: 'example-events'
  };
  assert.doesNotThrow(() => validateLandingMetadata('events', landing, skills, focuses, artifacts));
  assert.throws(() => validateLandingMetadata('events', { ...landing, capability: { type: 'skill', id: 'missing' } }, skills, focuses, artifacts), /Unavailable landing capability/);
  assert.throws(() => validateLandingMetadata('events', { ...landing, capability: { type: 'artifact', id: 'search' } }, skills, focuses, artifacts), /Unavailable landing capability/);
  assert.throws(() => validateLandingMetadata('events', { ...landing, caption: { en: 'Find events' } }, skills, focuses, artifacts), /de landing caption/);
  assert.throws(() => validateLandingMetadata('events', { ...landing, example_chat_id: '' }, skills, focuses, artifacts), /landing example/);
  assert.throws(() => validateLandingMetadata('events', { ...landing, capability: { type: 'app', id: 'events' } }, skills, focuses, artifacts), /Invalid landing capability/);
});

// contract-test: supporting surface=gui.web assertions=marketing-landing.app-metadata-defaults
test('unpublished examples stay out of the tour while published apps still require defaults', () => {
  const root = mkdtempSync(join(tmpdir(), 'public-landing-apps-'));
  const appRoot = join(root, 'backend/apps/diagrams');
  mkdirSync(appRoot, { recursive: true });
  const source = 'default_enabled: true\nicon_image: diagram.svg\nembed_types:\n  - id: html\n    category: direct\n';
  try {
    writeFileSync(join(appRoot, 'app.yml'), `${source}landing:\n  enabled: false\n`);
    assert.deepEqual(compilePublicApps(root), []);
    writeFileSync(join(appRoot, 'app.yml'), source);
    assert.throws(() => compilePublicApps(root), /Missing landing metadata for public app: diagrams/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// contract-test: supporting surface=gui.web assertions=marketing-landing.app-metadata-defaults
test('required-provider skills enter the public tour only with a configured source', () => {
  const root = mkdtempSync(join(tmpdir(), 'public-landing-providers-'));
  const appRoot = join(root, 'backend/apps/example');
  mkdirSync(appRoot, { recursive: true });
  const source = 'icon_image: search.svg\nskills:\n  - id: search\n    provider_required: true\n';
  const landing = 'landing:\n  order: 0\n  capability: {type: skill, id: search}\n  caption: {en: Search, de: Suchen}\n  example_chat_id: example-search\n';
  try {
    writeFileSync(join(appRoot, 'app.yml'), `${source}    providers: []\n${landing}`);
    assert.deepEqual(compilePublicApps(root), []);
    writeFileSync(join(appRoot, 'app.yml'), `${source}    providers: [OpenMates]\n${landing}`);
    assert.equal(compilePublicApps(root)[0].capability.id, 'search');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
