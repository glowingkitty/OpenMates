import { describe, expect, it } from 'vitest';
import { memoryResponseMappings } from '../memory/memoryResponseMappings';

const mapping = { placeholder: '[EMAIL_1]', original: 'jane.doe@example.org', type: 'EMAIL' };

describe('memoryResponseMappings', () => {
  // contract-test: supporting surface=gui.web assertions=app-memories.privacy.client-encrypted
  it('reads pii_mappings of a memory response', () => {
    const content = JSON.stringify({ type: 'app_settings_memories_response', user_message_id: 'm', action: 'included', pii_mappings: [mapping] });
    expect(memoryResponseMappings(content)).toEqual([mapping]);
  });
  // contract-test: supporting surface=gui.web assertions=app-memories.privacy.client-encrypted
  it('ignores other messages and malformed content', () => {
    expect(memoryResponseMappings(JSON.stringify({ type: 'other', pii_mappings: [mapping] }))).toEqual([]);
    expect(memoryResponseMappings('app_settings_memories_response {')).toEqual([]);
    expect(memoryResponseMappings(undefined)).toEqual([]);
  });
});
