import { describe, expect, it } from 'vitest';
import type { PIIMatch } from '../piiDetectionService';
import { carryOverModelMatches } from '../piiModelCarryOver';

const match = (id: string, value: string, startIndex: number): PIIMatch => ({
  type: 'PERSON_NAME', match: value, startIndex, endIndex: startIndex + value.length, id, placeholder: '[PERSON_NAME_1]',
});
const text = 'Dear Thomas Berger, mail a@example.org';
const email = { ...match('pii-EMAIL-1', 'a@example.org', 25), type: 'EMAIL' as const };

describe('model highlight carry-over', () => {
  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
  it('keeps model highlights when another highlight is kept as original', () => {
    const thomas = match('pii-model-PERSON_NAME-a', 'Thomas', 5);
    const berger = match('pii-model-PERSON_NAME-b', 'Berger', 12);
    const result = carryOverModelMatches([thomas, berger, email], text, [], new Set(['pii-EMAIL-1']));
    expect(result.map(m => m.match)).toEqual(['Thomas', 'Berger']);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
  it('drops excluded, moved and basic-overlapping model highlights', () => {
    const excluded = match('pii-model-PERSON_NAME-a', 'Thomas', 5);
    const moved = match('pii-model-PERSON_NAME-b', 'Berger', 2);
    const overlapping = match('pii-model-PERSON_NAME-c', 'a@example', 25);
    const result = carryOverModelMatches([excluded, moved, overlapping], text, [email], new Set(['pii-model-PERSON_NAME-a']));
    expect(result).toEqual([email]);
  });
});
