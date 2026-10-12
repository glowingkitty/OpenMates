import assert from 'node:assert/strict';
import test from 'node:test';
import { validateLandingMetadata } from './compile-public-apps.mjs';

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
  assert.throws(() => validateLandingMetadata('events', { ...landing, capability: { type: 'app', id: 'events' } }, skills, focuses, artifacts), /reviewed app-level landing source evidence/);
  assert.doesNotThrow(() => validateLandingMetadata('events', {
    ...landing, capability: { type: 'app', id: 'events' },
    source_evidence: { request_excerpt: 'Find local music events this weekend', rationale: 'The request demonstrates event discovery through ordinary app guidance.' }
  }, skills, focuses, artifacts));
});
