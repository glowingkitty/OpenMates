// Invoked by upload-metadata-privacy.spec.ts in the isolated CI runner.
// localhost API sessions resolve the upload URL to port 8001. CI already runs
// an upload service there, so redirect only upload and transcription URLs to
// this probe's own port. Transcription responses are synthetic; no inference runs.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { join } from 'node:path';
import { once } from 'node:events';
import { transcribeUploadedAudio, uploadFile } from '../../../packages/openmates-cli/src/uploadService.ts';
import { prepareTuiMessage } from '../../../packages/openmates-cli/src/tuiAttachments.ts';

const [directory, marker] = process.argv.slice(2);
if (!directory || !marker) throw new Error('Fixture directory and metadata marker required');
const nativeFetch = globalThis.fetch;
const payloads = [];
const transcriptionPayloads = [];
const response = {
  embed_id: '00000000-0000-4000-8000-000000000001', filename: 'private-person.pdf',
  content_type: 'application/pdf', content_hash: 'test-content-hash',
  files: { original: { s3_key: 'test-object', width: 1, height: 1, size_bytes: 1, format: 'pdf' } },
  s3_base_url: 'https://example.invalid', aes_key: 'test-key', aes_nonce: 'test-nonce',
  vault_wrapped_aes_key: 'test-wrapped-key', malware_scan: 'clean', ai_detection: null,
  deduplicated: true, page_count: 1,
};
const server = createServer(async (request, reply) => {
  try {
    assert.equal(request.method, 'POST');
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const body = Buffer.concat(chunks);
    reply.writeHead(200, { 'content-type': 'application/json' });
    if (request.url === '/v1/apps/audio/skills/transcribe') {
      const payload = JSON.parse(body.toString());
      transcriptionPayloads.push(payload);
      reply.end(JSON.stringify({ data: { results: [{ id: response.embed_id, results: [{ transcript: 'hello' }] }] } }));
    } else {
      assert.equal(request.url, '/v1/upload/file');
      payloads.push(body);
      const filename = body.toString('latin1').match(/filename="([^"]+)"/)?.[1];
      reply.end(JSON.stringify({ ...response, filename: filename ?? response.filename }));
    }
  } catch (error) {
    reply.writeHead(500);
    reply.end(String(error));
  }
});

try {
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const address = server.address();
  assert.ok(address && typeof address !== 'string');
  const captureBaseUrl = `http://127.0.0.1:${address.port}`;
  globalThis.fetch = (input, init) => {
    const url = typeof input === 'string' || input instanceof URL ? String(input) : input.url;
    // Preserve FormData, headers, AbortSignal, and native HTTP serialization.
    // All unrelated requests retain their original destination.
    const capturePath = url === 'http://localhost:8001/v1/upload/file' ? '/v1/upload/file'
      : url === 'http://localhost:8000/v1/apps/audio/skills/transcribe' ? '/v1/apps/audio/skills/transcribe' : null;
    return nativeFetch(capturePath ? captureBaseUrl + capturePath : input, init);
  };
  const session = { apiUrl: 'http://localhost:8000', cookies: { auth_refresh_token: 'test-token' } };
  for (const extension of ['png', 'pdf', 'wav']) {
    const filePath = join(directory, `private-person.${extension}`);
    await uploadFile(filePath, session);
    const payload = payloads.at(-1);
    assert.ok(payload, `${extension} upload reached the local server`);
    assert.ok(payload.includes(`filename="private-person.${extension}"`), `${extension} source basename preserved`);
    assert.ok(!payload.includes(marker), `${extension} metadata marker removed from multipart body`);
  }

  const transcriptionFilename = join(directory, 'private-person.wav');
  const transcript = await transcribeUploadedAudio(
    { ...response, content_type: 'audio/wav' }, transcriptionFilename, session,
  );
  assert.equal(transcript.transcript, 'hello');
  assert.equal(transcriptionPayloads.length, 1);
  assert.equal(transcriptionPayloads[0].requests[0].filename, transcriptionFilename);

  const client = {
    hasSession: () => true,
    listMemories: async () => [],
    getSession: () => session,
  };
  const prepared = await prepareTuiMessage(client, `Read @${join(directory, 'private-person.pdf')}`);
  assert.equal(prepared.preparedEmbeds.length, 1);
  assert.equal(payloads.length, 4, 'TUI attachment invoked upload transport');
  assert.ok(payloads.at(-1).includes('filename="private-person.pdf"'), 'TUI retains the selected filename');
  assert.ok(!payloads.at(-1).includes(marker), 'TUI multipart omitted PDF metadata');

  await uploadFile(join(directory, 'broken-private.png'), session);
  assert.equal(payloads.length, 5, 'malformed image still uploaded after cleanup failure');
  assert.ok(payloads.at(-1).includes('filename="broken-private.png"'), 'fallback retains the selected filename');
  assert.ok(payloads.at(-1).includes(marker), 'failed cleanup retains original bytes');
  process.stdout.write('CLI/TUI multipart privacy probe passed\n');
} finally {
  globalThis.fetch = nativeFetch;
  server.close();
}
