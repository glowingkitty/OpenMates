import { describe, expect, it } from 'vitest';
import { aliasEnhancedPlaceholders, createPIIDisplayAliases } from '../piiDisplayAliases';

const first = { type: 'ADDRESS', original: 'Maple Avenue', placeholder: '[ADDRESS_1_0000000000000001]' };
const second = { type: 'ADDRESS', original: 'Birch Lane', placeholder: '[ADDRESS_1_0000000000000002]' };

describe('compact PII display aliases', () => {
  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('numbers distinct unique tokens in message order and reuses repeated token aliases', () => {
    const content = `${second.placeholder} ${first.placeholder} ${second.placeholder}`;
    const aliases = createPIIDisplayAliases(content, [first, second]);
    expect([...aliases]).toEqual([[second.placeholder, '[ADDRESS_1]'], [first.placeholder, '[ADDRESS_2]']]);
    expect(content).toContain(second.placeholder);
    expect(first.placeholder).toBe('[ADDRESS_1_0000000000000001]');
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('reserves literals, existing short mappings and configured labels', () => {
    const aliases = createPIIDisplayAliases(`[ADDRESS_1] ${first.placeholder} ${second.placeholder}`, [
      first, second, { type: 'ADDRESS', original: 'Existing Road', placeholder: '[ADDRESS_2]' },
    ], ['ADDRESS_3']);
    expect([...aliases.values()]).toEqual(['[ADDRESS_4]', '[ADDRESS_5]']);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('preserves custom/legacy tokens and configured replacements that resemble enhanced tokens', () => {
    const custom = { type: 'ADDRESS', original: 'Home', placeholder: '[MY_HOME]' };
    const legacy = { type: 'EMAIL', original: 'owner@example.test', placeholder: '[EMAIL_1_test]' };
    const source = [first, custom, legacy].map(mapping => mapping.placeholder).join(' ');
    expect([...createPIIDisplayAliases(source, [first, custom, legacy], [first.placeholder])]).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('handles existing send-collision UUID tokens without exposing their suffix', () => {
    const collided = { ...first, placeholder: '[ADDRESS_1_0000000000000001_1_00000000000040008000000000000001]' };
    expect(createPIIDisplayAliases(collided.placeholder, [collided]).get(collided.placeholder)).toBe('[ADDRESS_1]');
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,message-input.send.ownership
  it('uses only mappings present in this message and starts fresh for another message', () => {
    expect([...createPIIDisplayAliases(second.placeholder, [first, second])]).toEqual([[second.placeholder, '[ADDRESS_1]']]);
    expect([...createPIIDisplayAliases(first.original, [first, second])]).toEqual([[first.placeholder, '[ADDRESS_1]']]);
    expect([...createPIIDisplayAliases(second.placeholder, [])]).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('finds restored multiline originals inside structured messages without modifying their source', () => {
    const mapping = { ...first, original: 'Maple "House"\nBirch Lane' };
    const content = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: mapping.original }] }] };
    expect(createPIIDisplayAliases(content, [mapping]).get(mapping.placeholder)).toBe('[ADDRESS_1]');
    expect(content.content[0].content[0].text).toBe(mapping.original);
  });
});

describe('aliasEnhancedPlaceholders', () => {
  // contract-test: direct surface=gui.web assertions=chats.titles.first-message-fallback
  it('shows a chat summary with short placeholder labels, never the nonce', () => {
    expect(aliasEnhancedPlaceholders('Works as a sales lead at [PERSON_NAME_1_aa6c4a4339f34bee] with [PERSON_NAME_2_aa6c4a4339f34bef]'))
      .toBe('Works as a sales lead at [PERSON_NAME_1] with [PERSON_NAME_2]');
  });

  // contract-test: direct surface=gui.web assertions=chats.titles.first-message-fallback
  it('keeps text without enhanced placeholders unchanged', () => {
    expect(aliasEnhancedPlaceholders('Plan the garden beds [EMAIL_1_com]')).toBe('Plan the garden beds [EMAIL_1_com]');
  });
});
