/**
 * Chat settings usage-row regression tests.
 *
 * The Usage tab is local-first in this slice. These tests pin the deterministic
 * conversion from local assistant message metadata into visible rows and CSV/YAML
 * exports without adding backend calls or hiding unknown credit values.
 */

import { describe, expect, it } from 'vitest';
import type { Message } from '../../../types/chat';
import { buildChatUsageRows, totalKnownCredits, usageEntriesToChatUsageRows, usageRowsToCsv, usageRowsToYaml } from '../chatUsageRows';

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
  // contract-test: supporting surface=gui.web assertions=billing.usage.receipt-token-breakdown
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

  // contract-test: supporting surface=gui.web assertions=billing.usage.receipt-token-breakdown
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

  // contract-test: supporting surface=gui.web assertions=billing.usage.receipt-token-breakdown,audio-speak.billing.success-only
  it('maps audio app-skill usage entries to provider rows', () => {
    const rows = usageEntriesToChatUsageRows([
      {
        id: 'audio-speak-usage',
        type: 'skill_execution',
        source: 'chat',
        app_id: 'audio',
        skill_id: 'speak',
        model_used: 'elevenlabs/eleven_flash_v2_5',
        credits: 10,
        server_provider: 'ElevenLabs',
        server_region: 'US',
        chat_id: 'chat-1',
        message_id: 'message-1',
        created_at: 1_700_000_001,
      },
    ]);

    expect(rows).toEqual([
      {
        id: 'audio-speak-usage',
        label: 'audio | speak',
        provider: 'ElevenLabs / US',
        timestamp: 1_700_000_001,
        credits: 10,
        words: 0,
        iconName: 'audio',
        appId: 'audio',
        skillId: 'speak',
        inputTokens: null,
        outputTokens: null,
        llmUsageBreakdown: null,
      },
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=billing.usage.receipt-token-breakdown
  it('preserves an immutable versioned LLM receipt without repricing it', () => {
    const breakdown = {
      schema_version: 1 as const,
      input_tokens: 100,
      uncached_input_tokens: 60,
      cache_read_input_tokens: 30,
      cache_creation_input_tokens: 10,
      output_tokens: 5,
      usage_source: 'provider_reported',
      entries: [{
        model_id: 'example', inference_host: 'provider', pricing_version: 'v1',
        input_tokens: 100, uncached_input_tokens: 60, cache_read_input_tokens: 30,
        cache_creation_input_tokens: 10, cache_creation_5m_input_tokens: 10,
        cache_creation_1h_input_tokens: 0, output_tokens: 5,
        rates: { input: '100', cache_read: '1000', cache_write: '80', cache_write_1h: null, output: '20' },
        category_credits: { input: '0.6', cache_read: '0.03', cache_write: '0.125', cache_write_1h: '0', output: '0.25' },
        raw_credits: '1.005',
      }],
      raw_credits: '1.005', rounding_adjustment: '-0.005', credits_charged: 1,
    };
    const [row] = usageEntriesToChatUsageRows([{
      id: 'receipt-1', created_at: 1_700_000_001, credits: 1,
      llm_usage_breakdown: breakdown,
    }]);
    expect(row.llmUsageBreakdown).toBe(breakdown);
    expect(row.credits).toBe(1);

    const ordinaryBreakdown = {
      ...breakdown,
      input_tokens: 150,
      uncached_input_tokens: 100,
      cache_read_input_tokens: 50,
      cache_creation_input_tokens: null,
      entries: [{
        ...breakdown.entries[0],
        billing_mode: 'ordinary_input' as const,
        billed_input_tokens: 150,
        input_tokens: 150,
        uncached_input_tokens: 100,
        cache_read_input_tokens: 50,
        cache_creation_input_tokens: null,
        cache_creation_5m_input_tokens: null,
        cache_creation_1h_input_tokens: null,
        category_credits: { input: '1.5', cache_read: '0', cache_write: '0', cache_write_1h: '0', output: '0.25' },
        raw_credits: '1.75',
      }],
      raw_credits: '1.75', rounding_adjustment: '-0.75',
    };
    const [ordinaryRow] = usageEntriesToChatUsageRows([{
      id: 'ordinary-input', created_at: 1_700_000_002, credits: 1,
      llm_usage_breakdown: ordinaryBreakdown,
    }]);
    expect(ordinaryRow.llmUsageBreakdown?.entries[0]).toMatchObject({
      billing_mode: 'ordinary_input', billed_input_tokens: 150,
      uncached_input_tokens: 100, cache_read_input_tokens: 50,
      category_credits: { input: '1.5', cache_read: '0' },
    });
  });
});
