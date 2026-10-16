import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { stripAudioMetadata } from './audio.js';

const encoder = new TextEncoder();
const str = (value: string) => encoder.encode(value);
const join = (...parts: Uint8Array[]): Uint8Array => {
  const result = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let offset = 0;
  for (const part of parts) { result.set(part, offset); offset += part.length; }
  return result;
};
const le32 = (value: number): Uint8Array => new Uint8Array([value & 255, (value >>> 8) & 255, (value >>> 16) & 255, (value >>> 24) & 255]);
const be32 = (value: number): Uint8Array => new Uint8Array([(value >>> 24) & 255, (value >>> 16) & 255, (value >>> 8) & 255, value & 255]);
const text = (bytes: Uint8Array): string => new TextDecoder().decode(bytes);

function wavChunk(id: string, body: Uint8Array): Uint8Array {
  return join(str(id), le32(body.length), body, body.length % 2 ? new Uint8Array(1) : new Uint8Array());
}
function atom(id: string, body: Uint8Array): Uint8Array { return join(be32(body.length + 8), str(id), body); }
function ebml(id: number[], body: Uint8Array): Uint8Array {
  if (body.length >= 127) throw new Error('test element too large');
  return join(new Uint8Array(id), new Uint8Array([0x80 | body.length]), body);
}

describe('stripAudioMetadata', () => {
  // contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
  it('removes WAV text chunks and preserves exact format and sample chunks', () => {
    const format = wavChunk('fmt ', new Uint8Array([1, 0, 1, 0, 0x40, 0x1f, 0, 0, 0x80, 0x3e, 0, 0, 2, 0, 16, 0]));
    const samples = wavChunk('data', new Uint8Array([1, 2, 3, 4, 5]));
    const info = wavChunk('LIST', join(str('INFO'), str('INAM'), str('private-name')));
    const body = join(str('WAVE'), format, info, samples);
    const source = join(str('RIFF'), le32(body.length), body);
    const result = stripAudioMetadata(source, 'audio/wav');
    assert.ok(result);
    assert.deepEqual(result.slice(12), join(format, samples));
    assert.equal(text(result).includes('private-name'), false);
    assert.ok(source.length > result.length);
  });

  // contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
  it('removes ID3v2, APEv2 and ID3v1 while preserving MP3 frame bytes', () => {
    const frame = new Uint8Array([0xff, 0xfb, 0x90, 0x64, 1, 2, 3, 4]);
    const id3 = join(str('ID3'), new Uint8Array([4, 0, 0, 0, 0, 0, 12]), str('private-name'));
    const ape = join(str('APETAGEX'), le32(2000), le32(32), le32(0), le32(0), le32(0), le32(0));
    const id3v1 = join(str('TAG'), str('private-name'), new Uint8Array(128 - 3 - 12));
    const result = stripAudioMetadata(join(id3, frame, ape, id3v1), 'audio/mpeg');
    assert.deepEqual(result, frame);
  });

  // contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
  it('removes ID3 from ADTS AAC and preserves its encoded frame', () => {
    const frame = new Uint8Array([0xff, 0xf1, 0x50, 0x80, 0x01, 0x1f, 0xfc, 5, 6]);
    assert.deepEqual(stripAudioMetadata(join(str('ID3'), new Uint8Array([4, 0, 0, 0, 0, 0, 0]), frame), 'audio/aac'), frame);
  });

  // contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
  it('accepts a clean MP3 frame unchanged', () => {
    const frame = new Uint8Array([0xff, 0xfb, 0x90, 0x64, 1, 2, 3, 4]);
    assert.equal(stripAudioMetadata(frame, 'audio/mpeg'), frame);
  });

  // contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
  it('accepts clean WAV, MP4 and WebM containers unchanged', () => {
    const format = wavChunk('fmt ', new Uint8Array([1, 0, 1, 0, 0x40, 0x1f, 0, 0, 0x80, 0x3e, 0, 0, 2, 0, 16, 0]));
    const samples = wavChunk('data', new Uint8Array([1, 2, 3, 4]));
    const wavBody = join(str('WAVE'), format, samples);
    const wav = join(str('RIFF'), le32(wavBody.length), wavBody);
    const mp4 = join(atom('ftyp', str('M4A ')), atom('mdat', new Uint8Array([1, 2, 3, 4])));
    const webm = join(ebml([0x1a, 0x45, 0xdf, 0xa3], ebml([0x42, 0x82], str('webm'))), ebml([0x18, 0x53, 0x80, 0x67], ebml([0x1f, 0x43, 0xb6, 0x75], ebml([0xa3], new Uint8Array([1, 2])))));
    assert.equal(stripAudioMetadata(wav, 'audio/wav'), wav);
    assert.equal(stripAudioMetadata(mp4, 'audio/mp4'), mp4);
    assert.equal(stripAudioMetadata(webm, 'audio/webm'), webm);
  });

  // contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
  it('replaces nested MP4 metadata with same-size free atoms without changing mdat or offsets', () => {
    const media = atom('mdat', new Uint8Array([9, 8, 7, 6]));
    const metadata = atom('udta', atom('meta', str('private-name')));
    const source = join(atom('ftyp', str('M4A ')), atom('moov', join(atom('trak', atom('mdia', atom('minf', atom('stbl', atom('stco', be32(1234)))))), metadata)), atom('free', str('hidden-name')), media);
    const result = stripAudioMetadata(source, 'audio/mp4');
    assert.ok(result);
    assert.equal(result.length, source.length);
    assert.deepEqual(result.slice(-media.length), media);
    assert.equal(text(result).includes('private-name'), false);
    assert.equal(text(result).includes('hidden-name'), false);
    assert.equal(text(result).includes('stco'), true);
    assert.equal(text(result).includes('free'), true);
  });

  // contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
  it('voids WebM metadata without moving audio or seek positions', () => {
    const title = ebml([0x7b, 0xa9], str('private-name'));
    const info = ebml([0x15, 0x49, 0xa9, 0x66], join(ebml([0x2a, 0xd7, 0xb1], new Uint8Array([0x0f, 0x42, 0x40])), title));
    const cluster = ebml([0x1f, 0x43, 0xb6, 0x75], ebml([0xa3], new Uint8Array([1, 2, 3, 4])));
    const crc = ebml([0xbf], new Uint8Array([1, 2, 3, 4]));
    const source = join(ebml([0x1a, 0x45, 0xdf, 0xa3], ebml([0x42, 0x82], str('webm'))), ebml([0x18, 0x53, 0x80, 0x67], join(crc, info, cluster)));
    const result = stripAudioMetadata(source, 'audio/webm');
    assert.ok(result);
    assert.equal(result.length, source.length);
    assert.deepEqual(result.slice(-cluster.length), cluster);
    assert.equal(text(result).includes('private-name'), false);
    assert.equal(result.includes(0xec), true); // Void
    assert.equal(result.includes(0xbf), false); // Invalidated CRC-32 replaced with Void
  });

  // contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
  it('clears OpusTags while preserving page layout, granule, audio packet and valid CRC', () => {
    const head = str('OpusHead');
    const tags = join(str('OpusTags'), le32(12), str('private-name'), le32(1), le32(19), str('ARTIST=private-name'));
    const audio = new Uint8Array([0xf8, 0x00, 0xab, 0xcd]);
    const payload = join(head, tags, audio);
    const page = join(str('OggS'), new Uint8Array([0, 2]), new Uint8Array([7, 0, 0, 0, 0, 0, 0, 0]), le32(1), le32(0), le32(0), new Uint8Array([3, head.length, tags.length, audio.length]), payload);
    const result = stripAudioMetadata(page, 'audio/ogg');
    assert.ok(result);
    assert.equal(result.length, page.length);
    assert.deepEqual(result.slice(-audio.length), audio);
    assert.deepEqual(result.slice(6, 22), page.slice(6, 22));
    assert.equal(text(result).includes('private-name'), false);
    assert.deepEqual(result.slice(26, 30), page.slice(26, 30));
    assert.equal(readOggCrc(result), readLe32(result, 22));
  });

  // contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
  it('anonymizes Vorbis comments without changing packet size or framing', () => {
    const head = join(new Uint8Array([1]), str('vorbis'), new Uint8Array([0]));
    const comments = join(new Uint8Array([3]), str('vorbis'), le32(12), str('private-name'), le32(1), le32(19), str('ARTIST=private-name'), new Uint8Array([1]));
    const audio = new Uint8Array([0, 9, 8, 7]);
    const page = join(str('OggS'), new Uint8Array([0, 2]), new Uint8Array(8), le32(2), le32(0), le32(0), new Uint8Array([3, head.length, comments.length, audio.length]), head, comments, audio);
    const result = stripAudioMetadata(page, 'audio/ogg');
    assert.ok(result);
    assert.deepEqual(result.slice(-audio.length), audio);
    assert.equal(result.length, page.length);
    assert.equal(text(result).includes('private-name'), false);
    assert.equal(result[result.length - audio.length - 1], 1);
    assert.equal(readOggCrc(result), readLe32(result, 22));
  });

  // contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
  it('returns undefined for malformed and unsupported data', () => {
    assert.equal(stripAudioMetadata(str('broken'), 'audio/wav'), undefined);
    assert.equal(stripAudioMetadata(join(str('ID3'), new Uint8Array([4, 0, 0, 127, 127, 127, 127])), 'audio/mpeg'), undefined);
    assert.equal(stripAudioMetadata(join(atom('ftyp', str('M4A ')), new Uint8Array([0, 0, 0, 100, 109, 111, 111, 118])), 'audio/mp4'), undefined);
    assert.equal(stripAudioMetadata(str('unknown'), 'audio/flac'), undefined);
  });
});

function readLe32(bytes: Uint8Array, offset: number): number {
  return (bytes[offset] | (bytes[offset + 1] << 8) | (bytes[offset + 2] << 16) | (bytes[offset + 3] << 24)) >>> 0;
}
function readOggCrc(bytes: Uint8Array): number {
  let crc = 0;
  for (let i = 0; i < bytes.length; i++) {
    const value = i >= 22 && i < 26 ? 0 : bytes[i];
    crc ^= value << 24;
    for (let bit = 0; bit < 8; bit++) crc = crc & 0x80000000 ? ((crc << 1) ^ 0x04c11db7) >>> 0 : (crc << 1) >>> 0;
  }
  return crc;
}
