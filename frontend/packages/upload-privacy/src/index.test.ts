import assert from 'node:assert/strict';
import { test } from 'node:test';
import { sanitizeUploadBytes } from './index.js';

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
test('cleanup preserves filenames and any provided folder path', async () => {
  for (const filename of ['photo.jpeg', 'private-customer.docx', 'private-customer', 'projects/voice-notes/recording.webm']) {
    const result = await sanitizeUploadBytes(new TextEncoder().encode('Content'), 'text/plain', filename);
    assert.equal(result.filename, filename);
  }
});

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
test('malformed files preserve their original bytes and still prepare an upload', async () => {
  const original = Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const before = original.slice();
  const prepared = await sanitizeUploadBytes(original, 'image/png', 'private-location.png');
  assert.equal(prepared.status, 'failed');
  assert.deepEqual(prepared.bytes, before);
  assert.deepEqual(original, before);
  assert.equal(prepared.filename, 'private-location.png');
});

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
test('Node Buffer input remains intact after successful and partially failed rewrites', async () => {
  const atom = (type: string, data: Buffer) => {
    const bytes = Buffer.alloc(8 + data.length);
    bytes.writeUInt32BE(bytes.length, 0);
    bytes.write(type, 4);
    data.copy(bytes, 8);
    return bytes;
  };
  const mp4 = Buffer.concat([
    atom('ftyp', Buffer.from('M4A \0\0\0\0')),
    atom('udta', Buffer.from('private-metadata')),
    atom('mdat', Buffer.from([1, 2, 3, 4])),
  ]);
  for (const malformed of [false, true]) {
    const original = Buffer.concat([mp4, malformed ? Buffer.from([0]) : Buffer.alloc(0)]);
    const before = Buffer.from(original);
    const prepared = await sanitizeUploadBytes(original, 'audio/mp4', 'private-person.m4a');
    assert.deepEqual(original, before);
    assert.equal(prepared.status, malformed ? 'unsupported' : 'sanitized');
    if (malformed) assert.deepEqual(prepared.bytes, before);
    else assert.ok(!Buffer.from(prepared.bytes).includes('private-metadata'));
  }
});

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
test('plain text is unchanged and never acquires filesystem metadata', async () => {
  const original = new TextEncoder().encode('Keep this document content exactly.');
  const prepared = await sanitizeUploadBytes(original, 'text/plain', 'personal-notes.txt');
  assert.equal(prepared.status, 'unsupported');
  assert.deepEqual(prepared.bytes, original);
  assert.equal(prepared.filename, 'personal-notes.txt');
});

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
test('a missing MIME type does not bypass cleanup for an identifiable PNG', async () => {
  const original = Uint8Array.from(Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5S8AAAAASUVORK5CYII=',
    'base64',
  ));
  const prepared = await sanitizeUploadBytes(original, '', 'private-image.bin');
  assert.equal(prepared.status, 'sanitized');
  assert.equal(prepared.mimeType, 'image/png');
  assert.equal(prepared.filename, 'private-image.bin');
  assert.ok(prepared.bytes.length);
});
