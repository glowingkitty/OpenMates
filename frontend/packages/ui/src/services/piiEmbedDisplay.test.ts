import { describe, expect, it } from 'vitest';
import { displayPIIEmbedText, embedTextHasPIIDisplay } from './piiEmbedDisplay';
import type { PIIMapping } from '../types/chat';

const nonce = 'a7e44be046534152';
const mappings: PIIMapping[] = [
  { placeholder: `[PERSON_NAME_3_${nonce}]`, type: 'PERSON_NAME', original: 'Maria Weber' },
  { placeholder: `[PHONE_1_${nonce}]`, type: 'PHONE', original: '+49 170 1234567' },
  { placeholder: `[EMAIL_1_${nonce}]`, type: 'EMAIL', original: 'maria@example.org' },
  { placeholder: `[EMAIL_2_${nonce}]`, type: 'EMAIL', original: 'landlord@example.org' },
];

describe('displayPIIEmbedText', () => {
  // contract-test: supporting surface=gui.web assertions=chats.titles.first-message-fallback
  it('restores the long nonce form from the client mapping', () => {
    expect(displayPIIEmbedText(`Dear [PERSON_NAME_3_${nonce}]`, mappings, true)).toBe('Dear Maria Weber');
  });

  // contract-test: supporting surface=gui.web assertions=chats.titles.first-message-fallback
  it('restores shortened nonce forms that match exactly one mapping', () => {
    expect(displayPIIEmbedText('Call [PHONE_1_234] or [EMAIL_2_org]', mappings, true))
      .toBe('Call +49 170 1234567 or landlord@example.org');
  });

  // contract-test: supporting surface=gui.web assertions=chats.titles.first-message-fallback
  it('shows short labels, never the nonce, when not revealed or unmapped', () => {
    expect(displayPIIEmbedText(`[PERSON_NAME_3_${nonce}] [PHONE_1_234]`, mappings, false)).toBe('[PERSON_NAME_1] [PHONE_1]');
    expect(displayPIIEmbedText(`[PERSON_NAME_3_${nonce}]`, [], true)).toBe('[PERSON_NAME_1]');
    expect(displayPIIEmbedText('[PHONE_9_234]', mappings, true)).toBe('[PHONE_9_234]');
  });
});

describe('embedTextHasPIIDisplay', () => {
  // contract-test: supporting surface=gui.web assertions=chats.titles.first-message-fallback
  it('flags text with placeholders or mapped originals, not plain text', () => {
    expect(embedTextHasPIIDisplay(`<p>To [PERSON_NAME_3_${nonce}]</p>`, [])).toBe(true);
    expect(embedTextHasPIIDisplay('<p>Call [PHONE_1_234]</p>', mappings)).toBe(true);
    expect(embedTextHasPIIDisplay('<p>Dear Maria Weber</p>', mappings)).toBe(true);
    expect(embedTextHasPIIDisplay('<p>Heating repair by 30 November</p>', mappings)).toBe(false);
    expect(embedTextHasPIIDisplay('', mappings)).toBe(false);
  });
});
