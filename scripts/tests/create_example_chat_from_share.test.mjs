import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

// Tooling contract: landing conversion must not silently publish an example
// without the real source conversation's follow-up suggestions.
test('landing conversion requires source follow-ups without rejecting legacy conversion', () => {
  const directory = mkdtempSync(path.join(tmpdir(), 'example-followups-'));
  const fixture = path.join(directory, 'chat.json');
  const chat = {
    chat_id: 'source-chat', title: 'Follow-up fixture',
    messages: [{ message_id: 'assistant-1', role: 'assistant', content: 'Hello.' }],
    embeds: [],
  };
  const run = (requireFollowUps = true) => spawnSync(process.execPath, [
    new URL('../create-example-chat-from-share.mjs', import.meta.url).pathname,
    '--from-json', fixture, '--slug', 'followup-validation-fixture', '--dry-run',
    ...(requireFollowUps ? ['--require-follow-ups'] : []),
  ], { encoding: 'utf8', env: { ...process.env, OPENMATES_API_KEY: '' } });
  try {
    for (const followUps of [undefined, [], [''], ['   '], ['Useful?', null]]) {
      writeFileSync(fixture, JSON.stringify({ ...chat, follow_up_suggestions: followUps }));
      const result = run();
      assert.equal(result.status, 1);
      assert.match(result.stderr, /source follow-up suggestions/i);
    }
    writeFileSync(fixture, JSON.stringify(chat));
    assert.equal(run(false).status, 0);
    writeFileSync(fixture, JSON.stringify({ ...chat, follow_up_suggestions: ['Can you explain more?'] }));
    const valid = run();
    assert.equal(valid.status, 0, valid.stderr);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

import {
  annotateChatWithUsage,
  formatTs,
  inlineEmbedsMapViewCodeEmbeds,
  removeInternalTaskEventMessages,
  sanitizeEmbedContent,
  sanitizeExampleMessageContent,
  normalizeLeadingModelSelection,
  attachReviewedPublicSpeech,
  withPromotedAppSkillUseMessages,
} from '../create-example-chat-from-share.mjs';

test('normalizes only a leading UI model selection while preserving typed prose and model provenance', () => {
  const prose = 'Could you summarize this PDF?\nPlease focus on the budget.';
  const chat = normalizeLeadingModelSelection({
    chat_id: 'source-chat',
    messages: [
      { message_id: 'user-1', role: 'user', content: `@ai-model:gemini-3.5-pro:google ${prose}` },
      { message_id: 'assistant-1', role: 'assistant', content: 'The budget is on page 2.', model_name: 'Gemini 3.5 Pro' },
    ],
    sub_chats: [],
    embeds: [],
  });

  assert.equal(chat.messages[0].content, prose);
  assert.equal(chat.messages[0].model_name, 'gemini-3.5-pro');
  assert.deepEqual(chat.messages[0].source_model_selection, { model_id: 'gemini-3.5-pro', provider: 'google' });
  assert.equal(chat.messages[1].model_name, 'Gemini 3.5 Pro');
  const rendered = formatTs(chat, {
    slug: 'model-selection-fixture', snake: 'model_selection_fixture', title: 'Model selection fixture',
    chatId: 'example-model-selection-fixture', summary: '', icon: 'file', category: 'general_knowledge',
    keywords: [], followUps: [], featured: false, order: 1, appSkillExamples: [],
    appFocusModeExamples: [], appSettingsMemoryExamples: [], contentEmbedExamples: [], activeFocusId: null,
  });
  assert.match(rendered, /Source user message user-1: selected @ai-model:gemini-3\.5-pro:google/);
  assert.match(rendered, /"role": "user",\n\s+"content": "example_chats\.model_selection_fixture\.message_1"[\s\S]*?"model_name": "gemini-3\.5-pro"/);
  assert.match(rendered, /"model_name": "Gemini 3\.5 Pro"/);
});

test('normalizes a providerless CLI model selector only when the real reply confirms its model', () => {
  const prose = 'I need an English-speaking GP appointment in Berlin next week.';
  const chat = normalizeLeadingModelSelection({
    chat_id: 'source-chat',
    messages: [
      { message_id: 'user-1', role: 'user', content: `@ai-model:gpt-5.4 ${prose}` },
      { message_id: 'assistant-1', role: 'assistant', user_message_id: 'user-1', model_name: 'GPT-5.4', content: 'Here are the appointments.' },
      { message_id: 'user-2', role: 'user', content: '@ai-model:gpt-5.4 Please try again.' },
      { message_id: 'assistant-2', role: 'assistant', user_message_id: 'user-2', model_name: 'Gemini 3.8 Flash', content: 'Trying again.' },
    ],
  });
  assert.equal(chat.messages[0].content, prose);
  assert.equal(chat.messages[0].model_name, 'gpt-5.4');
  assert.deepEqual(chat.messages[0].source_model_selection, { model_id: 'gpt-5.4', provider: null });
  assert.equal(chat.messages[1].model_name, 'GPT-5.4');
  assert.equal(chat.messages[2].content, '@ai-model:gpt-5.4 Please try again.');
  assert.equal(chat.messages[2].source_model_selection, undefined);
});

test('leaves app directives, malformed selectors, and non-leading model text intact', () => {
  const contents = [
    '@skill:web:search Find a source',
    '@app:fitness Find a class',
    '@best-model:best Find a source',
    '@ai-model:gemini-3.5-pro Find a source',
    '@ai-model:gemini-3.5-pro:google',
    '@ai-model:gemini-3.5-pro:google:extra Find a source',
    'Find a source @ai-model:gemini-3.5-pro:google',
  ];
  const chat = normalizeLeadingModelSelection({
    messages: [
      ...contents.map((content, index) => ({ message_id: `user-${index}`, role: 'user', content })),
      { role: 'user', content: '@ai-model:gemini-3.5-pro:google @skill:web:search Find a source' },
      { role: 'assistant', content: '@ai-model:gemini-3.5-pro:google An answer' },
    ],
  });
  assert.deepEqual(chat.messages.slice(0, contents.length).map((message) => message.content), contents);
  assert.equal(chat.messages[contents.length].content, '@skill:web:search Find a source');
  assert.equal(chat.messages.at(-1).content, '@ai-model:gemini-3.5-pro:google An answer');
});

test('enables model selection normalization only through the explicit import flag', () => {
  const directory = mkdtempSync(path.join(tmpdir(), 'example-model-selection-'));
  const fixture = path.join(directory, 'chat.json');
  writeFileSync(fixture, JSON.stringify({
    chat_id: 'source-chat', title: 'Model selection fixture',
    messages: [
      { message_id: 'user-1', role: 'user', content: '@ai-model:gemini-3.5-pro:google Find a source' },
      { message_id: 'assistant-1', role: 'assistant', content: 'Found one.' },
    ],
    embeds: [],
  }));
  const run = (enabled) => spawnSync(process.execPath, [
    new URL('../create-example-chat-from-share.mjs', import.meta.url).pathname,
    '--from-json', fixture, '--slug', 'model-selection-import-fixture', '--dry-run',
    ...(enabled ? ['--normalize-leading-model-selection'] : []),
  ], { encoding: 'utf8', env: { ...process.env, OPENMATES_API_KEY: '' } });
  try {
    const defaultRun = run(false);
    assert.equal(defaultRun.status, 0, defaultRun.stderr);
    assert.match(defaultRun.stdout, /normalized model selections: 0/);
    const enabledRun = run(true);
    assert.equal(enabledRun.status, 0, enabledRun.stderr);
    assert.match(enabledRun.stdout, /normalized model selections: 1/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test('requires reviewed content-addressed public speech fixtures', () => {
  const digest = 'a'.repeat(64);
  const chat = {
    chat_id: 'source-chat',
    messages: [{ message_id: 'assistant-1', role: 'assistant', content: 'Hello.' }],
    embeds: [],
  };
  const manifest = {
    reviewed: true,
    source_chat_id: 'source-chat',
    messages: [{
      assistant_message_id: 'assistant-1',
      segments: [{
        segment_id: 'segment-1',
        public_url: `https://openmates-public-examples.nbg1.your-objectstorage.com/assistant-speech/sha256-${digest}.mp3`,
        sha256: digest,
        duration_seconds: 1.2,
        waveform: [0.1, 0.5, 0.2],
      }],
    }],
  };

  assert.throws(() => attachReviewedPublicSpeech(chat, { ...manifest, reviewed: false }), /reviewed/i);
  const published = attachReviewedPublicSpeech(chat, manifest);
  assert.equal(published.public_speech['assistant-1'][0].public_url, manifest.messages[0].segments[0].public_url);
  assert.doesNotMatch(JSON.stringify(published.public_speech), /source_chat|vault|aes|private|provider|s3_key/i);
});

test('rejects mutable or non-S3 public speech URLs', () => {
  const chat = { chat_id: 'source-chat', messages: [{ message_id: 'assistant-1', role: 'assistant', content: 'Hello.' }], embeds: [] };
  const digest = 'a'.repeat(64);
  const manifest = (public_url, sha256 = digest) => ({
    reviewed: true,
    source_chat_id: 'source-chat',
    messages: [{ assistant_message_id: 'assistant-1', segments: [{ segment_id: 'segment-1', public_url, sha256, duration_seconds: 1 }] }],
  });
  const canonical = `https://openmates-public-examples.nbg1.your-objectstorage.com/assistant-speech/sha256-${digest}.mp3`;

  assert.throws(() => attachReviewedPublicSpeech(chat, manifest('https://example.com/audio.mp3')), /public example S3/i);
  assert.throws(() => attachReviewedPublicSpeech(chat, manifest(`${canonical}?token=secret`)), /public example S3/i);
  assert.throws(() => attachReviewedPublicSpeech(chat, manifest(canonical, 'b'.repeat(64))), /public example S3/i);
});

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

test('removes internal task event system messages from public examples', () => {
  const chat = removeInternalTaskEventMessages({
    chat_id: 'source-chat',
    messages: [
      { message_id: 'user-1', role: 'user', content: 'Create tasks' },
      { message_id: 'task-event-task-update-job-1', role: 'system', content: 'task-id created "Draft note" (todo)' },
      { message_id: 'system-json-1', role: 'system', content: '{"kept":true}' },
      { message_id: 'assistant-1', role: 'assistant', content: 'Done' },
    ],
    embeds: [],
    sub_chats: [
      {
        chat_id: 'sub-chat',
        messages: [
          { message_id: 'task-event-task-update-job-2', role: 'system', content: 'task-id created "Sub" (todo)' },
          { message_id: 'sub-assistant-1', role: 'assistant', content: 'Sub done' },
        ],
      },
    ],
  });

  assert.deepEqual(chat.messages.map((message) => message.message_id), ['user-1', 'system-json-1', 'assistant-1']);
  assert.deepEqual(chat.sub_chats[0].messages.map((message) => message.message_id), ['sub-assistant-1']);
});

test('inlines embeds_map_view code embeds as message-level map-view fences', () => {
  const chat = inlineEmbedsMapViewCodeEmbeds({
    chat_id: 'source-chat',
    messages: [
      {
        message_id: 'assistant-1',
        role: 'assistant',
        content: [
          'Before',
          '',
          '```json',
          '{"type":"code","embed_id":"map-code-1"}',
          '```',
          '',
          'After',
        ].join('\n'),
      },
    ],
    embeds: [
      {
        embed_id: 'map-code-1',
        type: 'code',
        content: 'type: code\nlanguage: embeds_map_view\ncode: "title: Places\\nembeds: place-a, place-b\\n"\nembed_ref: code-map\nstatus: finished',
      },
      {
        embed_id: 'place-a-id',
        type: 'event',
        content: 'embed_ref: place-a\ntitle: Place A',
      },
    ],
  });

  assert.match(chat.messages[0].content, /```embeds_map_view\ntitle: Places\nembeds: place-a, place-b\n```/);
  assert.doesNotMatch(chat.messages[0].content, /"type":"code"|Code snippet/);
  assert.deepEqual(chat.embeds.map((embed) => embed.embed_id), ['place-a-id']);
});

test('promotes parent app-skill embeds as markdown when child embeds are already visible', () => {
  const content = 'Routes: [08:27](embed:route-a) and [08:56](embed:route-b)';
  const chat = withPromotedAppSkillUseMessages({
    chat_id: 'source-chat',
    messages: [
      {
        message_id: 'assistant-1',
        role: 'assistant',
        content,
      },
    ],
    embeds: [
      {
        embed_id: 'parent-skill-use',
        type: 'app_skill_use',
        content: 'app_id: travel\nskill_id: search_connections\nstatus: finished\nembed_ids: child-a|child-b',
        embed_ids: ['child-a', 'child-b'],
      },
      {
        embed_id: 'child-a',
        type: 'connection',
        content: 'type: connection\nembed_ref: route-a',
        parent_embed_id: 'parent-skill-use',
      },
      {
        embed_id: 'child-b',
        type: 'connection',
        content: 'type: connection\nembed_ref: route-b',
        parent_embed_id: 'parent-skill-use',
      },
    ],
  });

  assert.equal(chat.messages[0].content, `[!](embed:parent-skill-use)\n\n${content}`);
});

test('promotes unreferenced parent app-skill embeds as markdown references', () => {
  const chat = withPromotedAppSkillUseMessages({
    chat_id: 'source-chat',
    messages: [
      {
        message_id: 'assistant-1',
        role: 'assistant',
        content: 'No visible result embeds yet.',
      },
    ],
    embeds: [
      {
        embed_id: 'parent-skill-use',
        type: 'app_skill_use',
        content: 'app_id: travel\nskill_id: search_connections\nstatus: finished',
      },
    ],
  });

  assert.equal(chat.messages[0].content, '[!](embed:parent-skill-use)\n\nNo visible result embeds yet.');
});

test('keeps code image-to-html app-skill promotion as JSON for audit compatibility', () => {
  const chat = withPromotedAppSkillUseMessages({
    chat_id: 'source-chat',
    messages: [
      {
        message_id: 'assistant-1',
        role: 'assistant',
        content: 'Generated the HTML.',
      },
    ],
    embeds: [
      {
        embed_id: 'parent-skill-use',
        type: 'app_skill_use',
        content: 'app_id: code\nskill_id: image_to_html\nstatus: finished',
      },
    ],
  });

  assert.match(chat.messages[0].content, /^```json\n\{"type":"app_skill_use","embed_id":"parent-skill-use"/);
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

test('strips nested screenshot storage metadata and preserves following public fields', () => {
  const sanitized = sanitizeEmbedContent(`type: document
title: Public document
screenshot_s3_keys:
  "1": chatfiles/private-owner/screenshots/page-1.png.bin
  "2": chatfiles/private-owner/screenshots/page-2.png.bin
s3_key: chatfiles/private-owner/document.pdf.bin
user_id: private-owner
page_count: 2
summary: Public summary`);

  assert.doesNotMatch(sanitized, /screenshot_s3_keys|chatfiles|s3_key|user_id|private-owner/);
  assert.match(sanitized, /^title: Public document$/m);
  assert.match(sanitized, /^page_count: 2$/m);
  assert.match(sanitized, /^summary: Public summary$/m);
});

test('strips private generated audio columns from app-skill result tables', () => {
  const sanitized = sanitizeEmbedContent(`app_id: audio
skill_id: speak
results[1]{id,status,text_preview,generation_type,provider,model,mime_type,duration_seconds,byte_length,audio_base64,files,s3_base_url,aes_key,aes_nonce,vault_wrapped_aes_key,credits_charged,error}:
  1,finished,"Hello, OpenMates",speech,ElevenLabs,eleven_flash_v2_5,audio/mpeg,1.2,1234,BASE64,{private},https://private.example,plain-key,nonce,wrapped,2,
status: finished`);

  assert.doesNotMatch(sanitized, /audio_base64|files|s3_base_url|aes_key|aes_nonce|vault_wrapped_aes_key/);
  assert.match(
    sanitized,
    /^results\[1\]\{id,status,text_preview,generation_type,provider,model,mime_type,duration_seconds,byte_length,credits_charged,error\}:$/m,
  );
  assert.match(
    sanitized,
    /^  1,finished,"Hello, OpenMates",speech,ElevenLabs,eleven_flash_v2_5,audio\/mpeg,1.2,1234,2,$/m,
  );
});

test('strips transient task persistence fields from static task embeds', () => {
  const sanitized = sanitizeEmbedContent(`type: task
parent_app_skill_type: app_skill_use
task_id: 00000000-0000-0000-0000-000000000000
short_id: null
title: Review transcript
status: todo
task_update_job_id: task-update-job-1
pending_client_persistence: true
embed_ref: review-transcript`);

  assert.doesNotMatch(sanitized, /task_id|short_id|task_update_job_id|pending_client_persistence/);
  assert.match(sanitized, /^title: Review transcript$/m);
  assert.match(sanitized, /^status: todo$/m);
});

test('annotates example chats with full usage entries and summed response credits', () => {
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
  assert.deepEqual(annotated.usage_entries.map((entry) => entry.id), ['source-chat-usage-1', 'source-chat-usage-2', 'source-chat-usage-3']);
  assert.equal(annotated.usage_entries[0].app_id, 'ai');
  assert.equal(annotated.usage_entries[0].credits, 17);
  assert.equal(annotated.sub_chats[0].messages[1].user_message_id, 'sub-user-1');
  assert.equal(annotated.sub_chats[0].messages[1].response_credits, 4);
  assert.deepEqual(annotated.sub_chats[0].usage_entries.map((entry) => entry.id), ['source-sub-chat-usage-1']);
});

test('serializes full usage entries into generated example chat data', () => {
  const chat = annotateChatWithUsage({
    chat_id: 'source-chat',
    title: 'Priced example',
    summary: 'Shows usage costs.',
    category: 'general_knowledge',
    messages: [
      { message_id: 'user-1', role: 'user', content: 'Forecast please', created_at: 1 },
      { message_id: 'assistant-1', role: 'assistant', content: 'Forecast ready', created_at: 2 },
    ],
    embeds: [],
  }, {
    entries: [
      {
        id: 'directus-usage-id',
        chat_id: 'source-chat',
        message_id: 'user-1',
        credits: 25,
        app_id: 'weather',
        skill_id: 'forecast',
        model_used: 'weather-forecast-v1',
        server_provider: 'DWD + Open-Meteo',
        server_region: 'DE',
        input_tokens: 10,
        output_tokens: 20,
        api_key_hash: 'private-api-key-hash',
        device_hash: 'private-device-hash',
        created_at: '2026-06-18T08:00:00Z',
      },
    ],
  });

  const source = formatTs(chat, {
    slug: 'priced-example',
    snake: 'priced_example',
    chatId: 'example-priced-example',
    title: 'Priced example',
    icon: 'cloud-sun',
    category: 'general_knowledge',
    keywords: [],
    followUps: [],
    featured: true,
    order: 1,
    appSkillExamples: [],
    appFocusModeExamples: [],
    appSettingsMemoryExamples: [],
    contentEmbedExamples: [],
    activeFocusId: null,
  });

  assert.match(source, /"user_message_id": "user-1"/);
  assert.match(source, /"response_credits": 25/);
  assert.match(source, /usage_entries: \[/);
  assert.match(source, /"id": "example-priced-example-usage-1"/);
  assert.match(source, /"chat_id": "example-priced-example"/);
  assert.match(source, /"message_id": "user-1"/);
  assert.match(source, /"server_provider": "DWD \+ Open-Meteo"/);
  assert.match(source, /"input_tokens": 10/);
  assert.doesNotMatch(source, /private-api-key-hash|private-device-hash|directus-usage-id/);
});

// Explicit public fixtures carry only reviewed fictional mapping sidecars.
// Conversion must preserve both supported locations without inventing mappings.
test('preserves explicit public PII mappings on messages and embeds', () => {
  const mappings = [
    { placeholder: '[EMAIL_1_com]', original: 'lena.hoffmann@example.com', type: 'EMAIL' },
    { placeholder: '[PHONE_1_147]', original: '+1 202-555-0147', type: 'PHONE' },
  ];
  const source = formatTs({
    chat_id: 'source-fictional-contacts',
    messages: [{ message_id: 'user-1', role: 'user', content: '[EMAIL_1_com] [PHONE_1_147]', pii_mappings: mappings }],
    embeds: [
      { embed_id: 'mail-1', type: 'mail', content: 'content: Contact [EMAIL_1_com] or [PHONE_1_147]', pii_mappings: mappings },
      { embed_id: 'mail-2', type: 'mail', content: 'content: No contact details' },
    ],
  }, {
    slug: 'fictional-contacts', snake: 'fictional_contacts', chatId: 'example-fictional-contacts',
    title: 'Fictional contacts', icon: 'mail', category: 'general_knowledge', keywords: [],
    followUps: [], featured: false, order: 1, appSkillExamples: [], appFocusModeExamples: [],
    appSettingsMemoryExamples: [], contentEmbedExamples: [],
  });
  const messages = JSON.parse(source.split('messages: ')[1].split(',\n  embeds:')[0]);
  const embeds = JSON.parse(source.split('embeds: ')[1].split(',\n  metadata:')[0]);
  assert.deepEqual(messages[0].pii_mappings, mappings);
  assert.deepEqual(embeds[0].pii_mappings, mappings);
  assert.equal(Object.hasOwn(embeds[1], 'pii_mappings'), false);
  assert.equal(embeds[0].content, 'content: Contact [EMAIL_1_com] or [PHONE_1_147]');
});
