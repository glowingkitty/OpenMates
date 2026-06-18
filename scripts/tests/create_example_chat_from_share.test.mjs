import assert from 'node:assert/strict';
import test from 'node:test';

import {
  annotateChatWithUsage,
  sanitizeEmbedContent,
  sanitizeExampleMessageContent,
} from '../create-example-chat-from-share.mjs';

test('normalizes compact weather rain radar embeds for public example rendering', () => {
  const compactContent = `app_id: weather
skill_id: rain_radar
results[1]:
  - type: rain_radar
    provider: Deutscher Wetterdienst (DWD) via Bright Sky
    location_name: Berlin
    location_country: Germany
    location_country_code: DE
    location_admin1: State of Berlin
    location_latitude: 52.52437
    location_longitude: 13.41053
    location_timezone: Europe/Berlin
    coverage_status: available
    coverage_radius_km: 5
    summary_rain_expected: false
    summary_in_10_min: No rain visible near Berlin.
    summary_next_2_hours: No rain is visible near Berlin in the radar timeline.
    summary_peak_intensity: none
    summary_preview_frame_id: frame-1
    timeline[2]{frame_id,timestamp,kind,label,rain_at_location_mm_5min,max_intensity,rain_area_pct}:
      frame-0,"2026-06-14T19:35:00+02:00",forecast,+1 min,0,none,0
      frame-1,"2026-06-14T19:40:00+02:00",forecast,+6 min,0,none,0
status: finished`;

  const sanitized = sanitizeEmbedContent(compactContent);

  assert.match(sanitized, /^status: finished$/m);
  assert.match(sanitized, /^provider: Deutscher Wetterdienst \(DWD\) via Bright Sky$/m);
  assert.match(sanitized, /^location:\n  name: Berlin/m);
  assert.match(sanitized, /^summary:\n  rain_expected: false/m);
  assert.match(sanitized, /^  in_10_min: No rain visible near Berlin\.$/m);
  assert.match(sanitized, /^timeline\[2\]\{frame_id,timestamp,kind,label,rain_at_location_mm_5min,max_intensity,rain_area_pct\}:$/m);
});

test('removes standalone app-skill placeholder markers from example messages', () => {
  const sanitized = sanitizeExampleMessageContent(`Before

!

After!`);

  assert.equal(sanitized, 'Before\n\nAfter!');
});

test('continues to strip private encrypted storage fields', () => {
  const sanitized = sanitizeEmbedContent(`app_id: weather
skill_id: rain_radar
status: finished
s3_base_url: https://private.example
aes_key: secret
files:
  preview:
    s3_key: private/key.webp
summary:
  in_10_min: No rain`);

  assert.doesNotMatch(sanitized, /s3_base_url|aes_key|s3_key/);
  assert.match(sanitized, /^summary:\n  in_10_min: No rain$/m);
});

test('annotates assistant responses with summed source usage credits', () => {
  const chat = {
    chat_id: 'source-chat',
    messages: [
      { message_id: 'user-1', role: 'user', content: 'Search this', created_at: 1 },
      { message_id: 'assistant-1', role: 'assistant', content: 'Done', created_at: 2, user_message_id: 'user-1' },
      { message_id: 'user-2', role: 'user', content: 'No priced response', created_at: 3 },
      { message_id: 'assistant-2', role: 'assistant', content: 'Free', created_at: 4 },
    ],
    embeds: [],
    sub_chats: [
      {
        chat_id: 'source-sub-chat',
        messages: [
          { message_id: 'sub-user-1', role: 'user', content: 'Deep check', created_at: 5 },
          { message_id: 'sub-assistant-1', role: 'assistant', content: 'Sub done', created_at: 6 },
        ],
        embeds: [],
      },
    ],
  };

  const annotated = annotateChatWithUsage(chat, {
    chats: {
      'source-chat': {
        entries: [
          { message_id: 'user-1', credits: 17, app_id: 'ai', skill_id: 'ask' },
          { message_id: 'user-1', credits: 10, app_id: 'web', skill_id: 'search' },
          { message_id: 'user-2', credits: 0, app_id: 'ai', skill_id: 'ask' },
        ],
      },
      'source-sub-chat': {
        entries: [
          { message_id: 'sub-user-1', credits_charged: 4, app_id: 'ai', skill_id: 'ask' },
        ],
      },
    },
  });

  assert.equal(annotated.messages[1].user_message_id, 'user-1');
  assert.equal(annotated.messages[1].response_credits, 27);
  assert.equal(annotated.messages[3].user_message_id, 'user-2');
  assert.equal(annotated.messages[3].response_credits, undefined);
  assert.equal(annotated.sub_chats[0].messages[1].user_message_id, 'sub-user-1');
  assert.equal(annotated.sub_chats[0].messages[1].response_credits, 4);
});
