// contract-test-file: tooling
import assert from 'node:assert/strict';
import test from 'node:test';

import { attachReviewedPublicMedia } from '../example_media_manifest.mjs';

const SOURCE_CHAT_ID = 'source-chat';
const HOST = 'openmates-public-examples.nbg1.your-objectstorage.com';

function variant(mediaType, name, mimeType, extension) {
  const sha256 = 'a'.repeat(64);
  return {
    variant: name,
    mime_type: mimeType,
    sha256,
    public_url: `https://${HOST}/reviewed-media/${mediaType}/${name}/sha256-${sha256}.${extension}`,
  };
}

function manifest(embedId, mediaType, variants) {
  return { reviewed: true, source_chat_id: SOURCE_CHAT_ID, embeds: [{ embed_id: embedId, media_type: mediaType, variants }] };
}

test('attaches reviewed application screenshot while preserving its source graph', () => {
  const source = {
    chat_id: SOURCE_CHAT_ID,
    messages: [{ id: 'message-1', role: 'assistant', content: 'Built app.' }],
    embeds: [{
      embed_id: 'app-embed', type: 'application', parent_embed_id: null,
      content: 'type: application\napp_id: code\nname: Recipe planner\nmodel: Gemini 3.1 Pro\nlatest_screenshot_url: "https://expired.example/private"\nfile_refs[1]{path,embed_id}:\n  src/App.svelte,child-1',
    }],
    sub_chats: [],
  };
  const approved = manifest('app-embed', 'application_preview', [variant('application_preview', 'preview', 'image/png', 'png')]);
  const result = attachReviewedPublicMedia(source, approved);
  assert.equal(result.chat_id, source.chat_id);
  assert.deepEqual(result.messages, source.messages);
  assert.match(result.embeds[0].content, /name: Recipe planner/);
  assert.match(result.embeds[0].content, /model: Gemini 3\.1 Pro/);
  assert.match(result.embeds[0].content, /src\/App.svelte,child-1/);
  assert.match(result.embeds[0].content, /latest_screenshot_url: "https:\/\/openmates-public-examples/);
  assert.doesNotMatch(result.embeds[0].content, /expired\.example/);
  assert.equal(source.embeds[0].content.includes('expired.example'), true);
});

test('binds generated media to a child embed and sets preview/full URLs', () => {
  const source = {
    chat_id: SOURCE_CHAT_ID, embeds: [],
    sub_chats: [{ chat_id: 'child-1', embeds: [{ embed_id: 'image-1', type: 'image', content: 'type: image\napp_id: images\nprompt: sunrise' }] }],
  };
  const approved = manifest('image-1', 'image', [
    variant('image', 'preview', 'image/webp', 'webp'),
    variant('image', 'full', 'image/webp', 'webp'),
  ]);
  const result = attachReviewedPublicMedia(source, approved);
  assert.match(result.sub_chats[0].embeds[0].content, /previewImageUrl: /);
  assert.match(result.sub_chats[0].embeds[0].content, /fullImageUrl: /);
  assert.match(result.sub_chats[0].embeds[0].content, /prompt: sunrise/);
});

test('merges reviewed media into JSON embed content without losing prompt or model', () => {
  const source = {
    chat_id: SOURCE_CHAT_ID,
    embeds: [{ embed_id: 'audio-1', content: JSON.stringify({
      type: 'audio', app_id: 'audio', prompt: 'Rain on leaves', model: 'sound-model',
      previewAudioUrl: 'https://expired.example/private',
    }) }],
  };
  const approved = manifest('audio-1', 'audio', [variant('audio', 'original', 'audio/mpeg', 'mp3')]);
  const result = attachReviewedPublicMedia(source, approved);
  const content = JSON.parse(result.embeds[0].content);
  assert.equal(content.prompt, 'Rain on leaves');
  assert.equal(content.model, 'sound-model');
  assert.match(content.previewAudioUrl, /openmates-public-examples/);
  assert.doesNotMatch(content.previewAudioUrl, /expired\.example/);
  assert.throws(() => attachReviewedPublicMedia({
    ...source,
    embeds: [{ ...source.embeds[0], content: JSON.stringify({ type: 'audio', app_id: 'audio', files: { original: { s3_key: 'private' } } }) }],
  }, approved), /Private media metadata/);
});

test('rejects unreviewed, wrong chat, unbound, or private host media', () => {
  const source = { chat_id: SOURCE_CHAT_ID, embeds: [{ embed_id: 'image-1', content: 'type: image\napp_id: images' }] };
  const approved = manifest('image-1', 'image', [variant('image', 'preview', 'image/webp', 'webp')]);
  assert.throws(() => attachReviewedPublicMedia(source, { ...approved, reviewed: false }), /reviewed/);
  assert.throws(() => attachReviewedPublicMedia(source, { ...approved, source_chat_id: 'other' }), /source chat/);
  assert.throws(() => attachReviewedPublicMedia(source, manifest('other', 'image', approved.embeds[0].variants)), /outside/);
  assert.throws(() => attachReviewedPublicMedia(source, {
    ...approved, embeds: [{ ...approved.embeds[0], variants: [{ ...approved.embeds[0].variants[0], public_url: 'https://private.example/file.webp' }] }],
  }), /immutable/);
  assert.throws(() => attachReviewedPublicMedia(source, {
    ...approved, embeds: [{ ...approved.embeds[0], variants: [{ ...approved.embeds[0].variants[0], public_url: `${approved.embeds[0].variants[0].public_url}?token=secret` }] }],
  }), /immutable/);
  assert.throws(() => attachReviewedPublicMedia(source, {
    ...approved, embeds: [{ ...approved.embeds[0], variants: [{ ...approved.embeds[0].variants[0], sha256: 'b'.repeat(64) }] }],
  }), /immutable/);
  assert.throws(() => attachReviewedPublicMedia(source, { ...approved, user_id: 'private-user' }), /unsupported fields/);
  assert.throws(() => attachReviewedPublicMedia({
    ...source, embeds: [{ ...source.embeds[0], content: `${source.embeds[0].content}\naes_key: private` }],
  }, approved), /Private media metadata/);
});
