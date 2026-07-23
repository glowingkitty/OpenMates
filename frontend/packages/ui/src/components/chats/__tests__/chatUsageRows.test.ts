/**
 * Chat settings usage-row regression tests.
 *
 * The Usage tab is local-first in this slice. These tests pin the deterministic
 * conversion from local assistant message metadata into visible rows and CSV/YAML
 * exports without adding backend calls or hiding unknown credit values.
 */

import { describe, expect, it } from 'vitest';
import type { Message } from '../../../types/chat';
import { buildChatUsageRows, totalKnownCredits, usageRowsToCsv, usageRowsToYaml } from '../chatUsageRows';

function message(overrides: Partial<Message>): Message {
  return {
    message_id: crypto.randomUUID(),
    role: 'assistant',
    content: '',
    created_at: 1_700_000_000_000,
    ...overrides,
  } as Message;
}

describe('chat settings usage rows', () => {
  it('builds rows only for assistant messages and keeps unknown credits visible', () => {
    const rows = buildChatUsageRows([
      message({ role: 'user', content: 'Please research this.' }),
      message({ message_id: 'assistant-1', model_name: 'gpt-5.5', content: 'Research completed.', example_response_credits: 7 }),
      message({ message_id: 'assistant-2', model_name: undefined, content: 'Missing credit metadata.' }),
    ]);

    expect(rows).toEqual([
      {
        id: 'assistant-1',
        label: 'AI | Ask',
        provider: 'gpt-5.5',
        timestamp: 1_700_000_000_000,
        credits: 7,
        words: 2,
      },
      {
        id: 'assistant-2',
        label: 'AI | Ask',
        provider: 'Unknown provider',
        timestamp: 1_700_000_000_000,
        credits: null,
        words: 3,
      },
    ]);
    expect(totalKnownCredits(rows)).toBe(7);
  });

  it('exports deterministic CSV and YAML rows', () => {
    const rows = buildChatUsageRows([
      message({ message_id: 'assistant-1', model_name: 'Brave "Search"', content: 'One two', example_response_credits: 2 }),
      message({ message_id: 'assistant-2', content: '', example_response_credits: undefined }),
    ]);

    expect(usageRowsToCsv(rows)).toBe([
      'id,label,provider,timestamp,credits,words',
      '"assistant-1","AI | Ask","Brave ""Search""","1700000000000","2","2"',
      '"assistant-2","AI | Ask","Unknown provider","1700000000000","","0"',
    ].join('\n'));
    expect(usageRowsToYaml(rows)).toBe([
      '- id: assistant-1',
      '  label: AI | Ask',
      '  provider: Brave "Search"',
      '  timestamp: 1700000000000',
      '  credits: 2',
      '  words: 2',
      '- id: assistant-2',
      '  label: AI | Ask',
      '  provider: Unknown provider',
      '  timestamp: 1700000000000',
      '  credits: unknown',
      '  words: 0',
    ].join('\n'));
  });
});
