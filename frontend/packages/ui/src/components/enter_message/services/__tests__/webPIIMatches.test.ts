import { describe, expect, it, vi } from 'vitest';
import { mergeWebPIIMatches, modelPIIMatchId, type WebPIIEntity } from '../webPIIMatches';
import { detectPII } from '../piiDetectionService';

function entity(text: string, original: string, label = 'GIVEN_NAME'): WebPIIEntity {
  const start = text.indexOf(original);
  return { original, label, start, end: start + original.length, confidence: 0.99 };
}

describe('browser model PII span adaptation', () => {
  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('retains all basic categories and adds only uncovered semantic spans', () => {
    const text = 'Amina: anna@example.com; +1 202-555-0183; 4111111111111111; 123-45-6789; DE89370400440532013000; 192.0.2.42';
    const basic = detectPII(text);
    expect(basic.map(match => match.type)).toEqual(expect.arrayContaining(['EMAIL', 'PHONE', 'CREDIT_CARD', 'SSN', 'IPV4']));
    const hybrid = mergeWebPIIMatches(text, [entity(text, 'Amina'), entity(text, 'anna@example.com', 'EMAIL'), entity(text, '123-45-6789', 'GOVERNMENT_ID')]);
    expect(hybrid.filter(match => match.type !== 'PERSON_NAME')).toEqual(basic);
    expect(hybrid.find(match => match.type === 'PERSON_NAME')?.match).toBe('Amina');
    expect(mergeWebPIIMatches(text, [])).toEqual(basic);
    const bankOptions = { disabledCategories: new Set(['phone_numbers']) };
    const iban = 'DE89370400440532013000';
    expect(mergeWebPIIMatches(iban, [], bankOptions)).toEqual(detectPII(iban, bankOptions));
    expect(mergeWebPIIMatches(iban, [], bankOptions).map(match => match.type)).toEqual(['IBAN']);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('keeps basic email IDs and exclusions stable when model detections arrive', () => {
    const text = 'anna@example.com and bob@example.com';
    const basic = detectPII(text);
    const options = { excludedIds: new Set([basic[0].id]) };
    const expected = detectPII(text, options).filter(match => match.type === 'EMAIL');
    const hybrid = mergeWebPIIMatches(text, [entity(text, 'anna@example.com', 'EMAIL'), entity(text, 'anna', 'GIVEN_NAME'), entity(text, 'bob@example.com', 'EMAIL')], options);
    expect(hybrid).toEqual(expected);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('replaces partial regex phones with one complete validated model IBAN mapping', () => {
    // Same synthetic account-iban fixture/spans as the bounded Linux evaluation.
    const iban = ['DE89', '3704', '0044', '0532', '0130', '00'].join('');
    const text = `My bank account IBAN is ${iban}.`;
    const basic = detectPII(text);
    expect(basic.map(match => [match.type, match.startIndex, match.endIndex])).toEqual([
      ['PHONE', 26, 36], ['PHONE', 36, 46],
    ]);
    const model = entity(text, iban, 'BANK_ACCOUNT');
    const hybrid = mergeWebPIIMatches(text, [model]);
    expect(hybrid).toHaveLength(1);
    expect(hybrid[0]).toMatchObject({ type: 'BANK_ACCOUNT', match: iban, startIndex: 24, endIndex: 46, id: modelPIIMatchId('BANK_ACCOUNT', iban) });
    expect(hybrid[0].placeholder).toMatch(/^\[BANK_ACCOUNT_1_/);
    const positions = new Set(hybrid.flatMap(match => Array.from({ length: match.endIndex - match.startIndex }, (_, i) => match.startIndex + i)));
    expect(Array.from({ length: iban.length }, (_, i) => positions.has(model.start + i)).every(Boolean)).toBe(true);
    for (const match of hybrid) expect(text.slice(match.startIndex, match.endIndex)).toBe(match.match);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('does not let broader bank model coverage override a phone exclusion or disabled bank category', () => {
    const iban = ['DE89', '3704', '0044', '0532', '0130', '00'].join('');
    const text = `My bank account IBAN is ${iban}.`;
    const basic = detectPII(text);
    const model = entity(text, iban, 'BANK_ACCOUNT');
    const options = { excludedIds: new Set([basic[0].id]) };
    const excluded = mergeWebPIIMatches(text, [model], options);
    expect(excluded).toEqual(detectPII(text, options));
    expect(excluded.map(match => match.id)).toEqual([basic[1].id]);
    expect(mergeWebPIIMatches(text, [model], { disabledCategories: new Set(['iban_bank_account']) })).toEqual(basic);
    const ready = mergeWebPIIMatches(text, [model]);
    expect(mergeWebPIIMatches(text, [model], { excludedIds: new Set([ready[0].id]) })).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('keeps unaffected baseline IDs and rejects unvalidated bank expansions', () => {
    const iban = ['DE89', '3704', '0044', '0532', '0130', '00'].join('');
    const text = `anna@example.com account ${iban}.`;
    const basic = detectPII(text);
    const hybrid = mergeWebPIIMatches(text, [entity(text, iban, 'BANK_ACCOUNT')]);
    expect(hybrid.find(match => match.type === 'EMAIL')).toEqual(basic.find(match => match.type === 'EMAIL'));
    const invalid = iban.slice(0, -1) + '1';
    const invalidText = `My bank account IBAN is ${invalid}.`;
    expect(mergeWebPIIMatches(invalidText, [entity(invalidText, invalid, 'BANK_ACCOUNT')])).toEqual(detectPII(invalidText));
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('keeps configured identifiers and mandatory secret mappings intact under broader model spans', () => {
    const key = ['AKIA', 'ABCDEFGHIJKLMNOP'].join('');
    const text = `Token ${key} belongs to Amina`;
    const options = { personalDataEntries: [{ id: 'name', textToHide: 'Amina', replaceWith: 'MY_NAME' }] };
    expect(mergeWebPIIMatches(text, [entity(text, text, 'STREET_NAME')], options)).toEqual(detectPII(text, options));
  });
  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('uses UTF16 offsets after emoji and keeps encrypted placeholder shape', () => {
    const nonce = vi.spyOn(crypto, 'randomUUID').mockReturnValue('00000000-0000-4000-8000-000000000001');
    const text = '😀 Call Amina at 42 Maple Avenue';
    const result = mergeWebPIIMatches(text, [entity(text, 'Amina'), entity(text, '42 Maple Avenue', 'STREET_NAME')]);
    expect(result.map(m => [m.type, m.match, text.slice(m.startIndex, m.endIndex), m.placeholder])).toEqual([
      ['PERSON_NAME', 'Amina', 'Amina', expect.stringMatching(/^\[PERSON_NAME_1_[0-9a-f]{16}\]$/)], ['ADDRESS', '42 Maple Avenue', '42 Maple Avenue', expect.stringMatching(/^\[ADDRESS_1_[0-9a-f]{16}\]$/)],
    ]);
    expect(() => mergeWebPIIMatches(text, [{ ...entity(text, 'Amina'), start: 7 }])).toThrow('invalid character offsets');
    nonce.mockRestore();
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('protects explicitly configured private UUIDs, URLs and query values', () => {
    const uuid = '123e4567-e89b-42d3-a456-426614174000';
    const url = 'https://example.org/private-resource';
    const text = `${uuid} ${url} https://example.org/?owner=Amina [MY_NAME]`;
    const matches = mergeWebPIIMatches(text, [], { personalDataEntries: [
      { id: 'private-uuid', textToHide: uuid, replaceWith: 'MY_ID' },
      { id: 'private-url', textToHide: url, replaceWith: 'MY_URL' },
      { id: 'private-name', textToHide: 'Amina', replaceWith: 'MY_NAME' },
      { id: 'placeholder', textToHide: 'MY_NAME', replaceWith: 'PRIVATE' },
    ] });
    expect(matches.map(m => m.placeholder)).toEqual(['[MY_ID]', '[MY_URL]', '[MY_NAME]']);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('reserves secrets and configured values before model spans, even when restored', () => {
    const key = 'sk-proj-' + 'a'.repeat(30);
    const text = `${key} Amina`;
    const options = { personalDataEntries: [{ id: 'my-name', textToHide: 'Amina', replaceWith: 'MY_NAME' }] };
    const matches = mergeWebPIIMatches(text, [entity(text, key), entity(text, 'Amina')], options);
    expect(matches.map(m => m.placeholder)).toEqual([expect.stringContaining('[OPENAI_KEY_'), '[MY_NAME]']);
    const excluded = mergeWebPIIMatches(text, [entity(text, key), entity(text, 'Amina')], { ...options, excludedIds: new Set(matches.map(m => m.id)) });
    expect(excluded).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('redacts bracketed AWS keys and uppercase configured values before speculative placeholder syntax', () => {
    const key = ['AKIA', 'ABCDEFGHIJKLMNOP'].join('');
    const text = `[${key}] [PRIVATECODE] [EMAIL_1_secret] [PERSON_NAME_1_a0123456789bcdef]`;
    const matches = mergeWebPIIMatches(text, [], { personalDataEntries: [
      { id: 'private-code', textToHide: 'PRIVATECODE', replaceWith: 'MY_CODE' },
      { id: 'placeholder-like-private-code', textToHide: 'EMAIL_1_secret', replaceWith: 'PRIVATE_EMAIL_CODE' },
    ] });
    expect(matches.map(m => [m.type, m.match, m.placeholder])).toEqual([
      ['AWS_ACCESS_KEY', key, expect.stringContaining('[AWS_KEY_1_')],
      ['EMAIL', 'PRIVATECODE', '[MY_CODE]'],
      ['EMAIL', 'EMAIL_1_secret', '[PRIVATE_EMAIL_CODE]'],
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('preserves value exclusions across preview and canonical offsets and blocks overlaps', () => {
    const text = '**Amina** Okafor';
    const excludedIds = new Set([modelPIIMatchId('PERSON_NAME', 'Amina')]);
    expect(mergeWebPIIMatches(text, [entity(text, 'Amina'), entity(text, 'mina')], { excludedIds })).toEqual([]);
    expect(mergeWebPIIMatches('Amina', [entity('Amina', 'Amina')], { excludedIds })).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('honors mapped category toggles', () => {
    const text = 'Amina, 42 Maple Avenue, anna@example.com';
    const matches = mergeWebPIIMatches(text, [entity(text, 'Amina'), entity(text, '42 Maple Avenue', 'STREET_NAME'), entity(text, 'anna@example.com', 'EMAIL')], { disabledCategories: new Set(['names', 'addresses', 'email_addresses']) });
    expect(matches).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
  it('keeps URLs, placeholders and UUIDs intact, and ignores ORG/URL and version false positives', () => {
    const text = 'https://example.org/Amina [PERSON_NAME_1] 123e4567-e89b-42d3-a456-426614174000 version 3.14.159 OpenMates';
    expect(mergeWebPIIMatches(text, [entity(text, 'Amina'), entity(text, 'PERSON_NAME'), entity(text, '123e4567'), entity(text, '3.14.159', 'IP_ADDRESS'), entity(text, 'OpenMates', 'ORG')])).toEqual([]);
  });
});
